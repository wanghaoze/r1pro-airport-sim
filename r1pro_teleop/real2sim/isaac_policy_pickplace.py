"""Pure learned-policy room controller and measured Pick/Place observer.

Privileged tray/contact state is used only for task gates, never policy inputs.
No IK, inverse dynamics, teacher or pose reset. The robot filter is mandatory and these runs are excluded from pure model success.
"""
import json
import os
from pathlib import Path
import time
import traceback
from threading import Event
import numpy as np
from .isaac_mobile import mobile_targets
from .robot_action_filter import load_limits, contract_id, bound_actions, filter_command


class FilePolicyClient:
    def __init__(self,directory,room_id,checkpoint_id,horizon=20,timeout_seconds=300,wall_deadline=None):
        self.directory=Path(directory);self.room=room_id;self.sequence=0;self.timeout_seconds=timeout_seconds;self.wall_deadline=wall_deadline
        self.closed=Event()
        metadata=json.loads((self.directory/'ready.json').read_text())
        if metadata.get('checkpoint_id')!=checkpoint_id or metadata.get('horizon')!=horizon:raise ValueError('policy_checkpoint_identity_mismatch')

    def close(self):
        # Cancel this room's file wait only; preserve requests and service ownership.
        self.closed.set()

    def check_cancelled(self):
        if (self.directory.parent/'stop_requested').exists():raise InterruptedError('policy_stopped_by_user')
        if self.closed.is_set():raise InterruptedError('policy_client_closed')

    def infer(self,sample):
        self.check_cancelled()
        if set(sample)!= {'state','prompt','image/head_left','image/left_wrist','image/right_wrist'}:raise ValueError('privileged_policy_input_rejected')
        stem=f'room{self.room:03d}_{self.sequence:06d}';self.sequence+=1
        request=self.directory/(stem+'.request.npz');temporary=request.with_suffix('.tmp')
        with temporary.open('wb') as stream:np.savez(stream,**sample)
        temporary.replace(request);reply=self.directory/(stem+'.reply.npz');error=self.directory/(stem+'.error.json');deadline=time.monotonic()+self.timeout_seconds
        while not reply.exists():
            self.check_cancelled()
            if self.wall_deadline and time.time()>=self.wall_deadline:raise TimeoutError('evaluation_wall_time_limit')
            if error.exists():raise RuntimeError(json.loads(error.read_text())['error'])
            if time.monotonic()>deadline:raise TimeoutError('policy_inference_response_timeout')
            self.closed.wait(.01)
        self.check_cancelled()
        with np.load(reply,allow_pickle=False) as values:return {'actions':values['actions'].copy()}


def measured_pick(obs,initial_bottom):
    return bool(np.all(obs['finger_force'][0]>.5) and np.prod(obs['long_edge_sign'][0])==-1
        and obs['table_force'][0]<=.01 and obs['tray_pose'][0,2]-initial_bottom>=.02)


class PlaceObserver:
    def __init__(self,obs,table):
        self.height=float(table['center_world'][2]+table['dimensions_m'][2]);self.previous=obs['tray_pose'][0,:3].copy()
        self.released=False;self.release_gap=None;self.stable=0

    def update(self,obs):
        gap=float(obs['tray_pose'][0,2]-self.height)
        if not self.released and np.any(obs['finger_force'][0]<=.5):
            self.released=True;self.release_gap=gap
            if gap>.02:raise ValueError('policy_release_above_authorized_2cm')
        speed=float(np.linalg.norm(obs['tray_pose'][0,:3]-self.previous)*20);self.previous=obs['tray_pose'][0,:3].copy()
        self.stable=self.stable+1 if obs['table_force'][0]>.01 and speed<.01 and np.all(obs['finger_force'][0]<=.5) else 0
        return bool(self.released and self.stable>=10 and obs['boundary_ok'][0] and obs['axis_error_rad'][0]<=np.deg2rad(15))


def validate_actions(actions,model,horizon=20):
    actions=np.asarray(actions)
    if actions.shape!=(horizon,19) or not np.isfinite(actions).all():raise ValueError('invalid_policy_action_chunk')
    for action_index,action in enumerate(actions):
        for name,target in mobile_targets(action).items():
            joint=model.joint(name).id
            if not model.jnt_limited[joint] or not model.jnt_range[joint,0]<=target<=model.jnt_range[joint,1]:
                raise ValueError('policy_action_outside_mechanical_joint_range:'+name+'; chunk_step='+str(action_index)+'; target_rad_or_m='+str(float(target))+'; lower='+str(float(model.jnt_range[joint,0]))+'; upper='+str(float(model.jnt_range[joint,1])))
    return actions


def clip_diagnostic_actions(actions,model,horizon=20):
    values=np.asarray(actions,dtype=np.float64).copy()
    if values.shape!=(horizon,19) or not np.isfinite(values).all():raise ValueError('invalid_policy_action_chunk')
    changes=[]
    for side,offset in [('left',0),('right',8)]:
        for k in range(8):
            names=[f'{side}_arm_joint{k+1}'] if k<7 else [f'{side}_gripper_finger_joint{j}' for j in (1,2)]
            ranges=[model.jnt_range[model.joint(n).id] for n in names]
            factor=1 if k<7 else 2
            low=max(float(x[0]) for x in ranges)*factor;high=min(float(x[1]) for x in ranges)*factor
            before=values[:,offset+k].copy();values[:,offset+k]=np.clip(before,low,high)
            for step in np.flatnonzero(before!=values[:,offset+k]):
                changes.append(dict(chunk_step=int(step),channel=offset+k,joint=names[0],original=float(before[step]),applied=float(values[step,offset+k]),lower=low,upper=high))
    return values,changes


class AsyncChunkBuffer:
    """One outstanding request; consume only time-aligned, unexpired predictions."""
    def __init__(self,policy,horizon,cancel_pending=None):
        from concurrent.futures import ThreadPoolExecutor
        self.policy=policy;self.horizon=horizon;self.pool=ThreadPoolExecutor(max_workers=1)
        self.pending=None;self.current=None;self.origin=0;self.prompt=None;self.request_frame=0
        self.cancel_pending=cancel_pending
    def get(self,images,state,prompt,frame):
        if self.prompt!=prompt:
            if self.pending is not None:self.pending.result();self.pending=None
            self.current=None;self.prompt=prompt
        if self.pending is not None and (self.pending.done() or self.current is None or frame-self.origin>=self.horizon):
            self.current=self.pending.result();self.origin=self.request_frame;self.pending=None
        if self.current is None or frame-self.origin>=self.horizon:
            self.current=self.policy.infer(images,state,prompt);self.origin=frame
        elif self.pending is None:
            self.request_frame=frame
            self.pending=self.pool.submit(self.policy.infer,{k:v.copy() for k,v in images.items()},state.copy(),prompt)
        return self.current.copy(),frame-self.origin,self.origin
    def close(self):
        if self.cancel_pending:self.cancel_pending()
        self.pool.shutdown(wait=True,cancel_futures=True)


def robot_limit_command(command,previous,measured,model,limits,observation_age):
    return filter_command(command,previous,measured,model,limits,observation_age)



def run_policy_room(runtime,case):
    from r1pro_teleop.vla.policy import Pi05Policy,PolicyContract
    r=runtime;cfg=case['policy'];error=None;spans=[];raw_chunks=[];submitted=[];executed=0;source='model_failure';pipeline=None
    try:
        horizon=cfg.get('action_horizon',20)
        if type(horizon)!=int or not 1<=horizon<=40:raise ValueError('invalid_registered_policy_horizon')
        client=FilePolicyClient(cfg['directory'],case.get('original_room_id',r.room_id),cfg['checkpoint_id'],horizon,cfg.get('inference_timeout_seconds',300),cfg.get('wall_deadline'))
        policy=Pi05Policy(client,PolicyContract(cfg['checkpoint_id'],action_horizon=horizon))
        pipeline=AsyncChunkBuffer(policy,horizon,cancel_pending=client.close) if cfg.get('runtime_profile')=='realtime' else None
        limits=cfg.get('robot_action_limits') or load_limits();filter_id=contract_id(limits)
        previous_command=np.asarray(r.command,dtype=float).copy();previous_command[16:]=r.fixed_episode_base_command
        from .policy_start_diagnostic import policy_base_reference
        first=r.observation();base_reference=policy_base_reference(first['state'],case.get('prepared_pick_start'),limits);bottom=float(first['tray_pose'][0,2])
        table=min(r.tables,key=lambda t:np.linalg.norm(np.asarray(t['center_world'])[:2]-first['tray_pose'][0,:2]))
        r.context=table;r.manipulating=True
        if not r.observation()['front_region_ok']:raise ValueError('policy_initial_station_not_table_front')
        r.write('policy_contract.json',dict(checkpoint_id=cfg['checkpoint_id'],base_reference=base_reference.tolist(),
            diagnostic_start='prepared_pick_pose' if 'prepared_pick_start' in case else 'native_initial',
            full_task_success_eligible=False,raw_action_semantics='pre_rate_filter_after_service_bounds',
            base_reference_source='source_episode_initial_feedback_aligned_to_runtime' if 'prepared_pick_start' in case else 'episode_initial_measured_feedback',
            policy_initial_base_state=(first['state'][16:]-base_reference).tolist(),model_action_mask=[True]*16+[False]*3,
            fixed_base_command=r.fixed_episode_base_command.tolist(),teacher_fallback=False,policy_inputs=['state19','3_native_rgb','prompt'],
            action_filter_contract=filter_id,action_safety_mode='robot_limits',requested_action_safety_mode=cfg.get('action_safety_mode'),
            policy_horizon=horizon,execution_horizon=min(5,horizon),frames_per_action=cfg['frames_per_action'],parent_split=case['parent_split'],held_out_generalization=False,task_table=table))
        for prompt in ('Pick up the tray','Place the tray'):
            start=r.frames;gate=PlaceObserver(r.observation(),table) if prompt=='Place the tray' else None;passed=False
            if gate:r.write('place_initial_state.json',dict(frame=r.frames,state=r.observation()['state'].tolist(),source='preceding_model_pick_physical_continuation',reset_between_pick_and_place=False,model_executed=True))
            while r.frames-start<cfg['frames_per_action']:
                if (Path(cfg['directory']).parent/'stop_requested').exists():raise InterruptedError('policy_stopped_by_user')
                if cfg.get('max_simulation_frames') is not None and r.frames>=cfg['max_simulation_frames']:raise ValueError('simulation_time_budget_reached')
                if cfg.get('wall_deadline') and time.time()>=cfg['wall_deadline']:raise TimeoutError('evaluation_wall_time_limit')
                obs=r.observation();state=obs['state'].copy();state[16:]-=base_reference
                offset=0;origin=r.frames
                if pipeline:actions,offset,origin=pipeline.get(obs['policy_images'],state,prompt,r.frames)
                else:actions=policy.infer(obs['policy_images'],state,prompt)
                raw_chunks.append(actions.copy())
                actions=bound_actions(actions,limits,horizon)
                actions,corrections=clip_diagnostic_actions(actions,r.model,horizon)
                r.event('explicit_limit_diagnostic',chunk_index=len(raw_chunks)-1,corrections=corrections,pure_model_success_eligible=False)
                r.event('model_chunk',prompt=prompt,chunk_index=len(raw_chunks)-1,raw_action=raw_chunks[-1].tolist(),applied_chunk=actions.tolist(),policy_input_frame=origin,consumed_chunk_offset=offset)
                for raw in actions[offset:offset+min(5,cfg['frames_per_action']-(r.frames-start),max(0,(cfg.get('max_simulation_frames') or 200000)-r.frames))]:
                    if (Path(cfg['directory']).parent/'stop_requested').exists():raise InterruptedError('policy_stopped_by_user')
                    command=raw.astype(float).copy();command[16:]=r.fixed_episode_base_command
                    feedback=r.observation()
                    measured_at=feedback.get('measured_wall_time',float('nan'))
                    age=time.time()-measured_at
                    filtered=robot_limit_command(command,previous_command,feedback['state'],r.model,limits,age)
                    validate_actions(filtered[None],r.model,1)
                    r.event('robot_action_filter',raw=command.tolist(),applied=filtered.tolist(),feedback=feedback['state'].tolist(),limits=limits,contract=filter_id,observation_age=age)
                    previous_command=filtered.copy()
                    submitted.append(filtered.copy());obs=r.tick(filtered,raw_command=command);executed+=1
                    passed=measured_pick(obs,bottom) if gate is None else gate.update(obs)
                    if passed:break
                r.write('policy_progress.json',dict(stage='native_policy',action=prompt,completed=r.frames-start,total=cfg['frames_per_action'],heartbeat_unix=time.time(),executed_model_frames=executed))
                if passed:break
            spans.append(dict(prompt=prompt,start=start,end=r.frames,frames=r.frames-start,passed=passed,stable_support_frames=gate.stable if gate else None,release_gap_m=gate.release_gap if gate else None))
            if not passed:
                if (Path(cfg['directory']).parent/'stop_requested').exists():raise InterruptedError('policy_stopped_by_user')
                if cfg.get('max_simulation_frames') is not None and r.frames>=cfg['max_simulation_frames']:raise ValueError('simulation_time_budget_reached')
                raise ValueError('policy_action_budget_exhausted:'+prompt)
    except BaseException as exc:
        error=dict(type=type(exc).__name__,message=str(exc),traceback=traceback.format_exc())
        if isinstance(exc,(TimeoutError,FileNotFoundError,ConnectionError)) or 'inference_failed' in str(exc):source='infrastructure_failure'
        if isinstance(exc,InterruptedError):source='user_cancelled'
        r.write('failure.json',error)
    finally:
        if pipeline:pipeline.close()
        # A physics guard can raise after the actuator step. Those real frames
        # still count as model execution, even though that attempt failed.
        executed=r.frames
        np.savez_compressed(r.output/'model_actions.npz',raw_chunks=np.asarray(raw_chunks),submitted=np.asarray(submitted),executed_frames=executed)
        r.worker_result=dict(schema='isaac_policy_room/1',scope='training_scene_native_closed_loop_diagnostic',model_executed=executed>0,
            action_safety_mode='robot_limits',pure_model_success_eligible=False,teacher_collection=False,teacher_fallback=False,training_eligible=False,passed=error is None and len(spans)==2,
            actions=spans,error=error,failure_category=source if error else None,frames=r.frames,executed_model_frames=executed,room_id=r.room_id,
            original_room_id=case.get('original_room_id',r.room_id),parent_split=case['parent_split'],worker_completed=True)
        r.write('worker_result.json',r.worker_result);r.worker_done()
    return r.worker_result
