"""Pure learned-policy room controller and measured Pick/Place observer.

Privileged tray/contact state is used only for task gates, never policy inputs.
No IK, inverse dynamics, teacher, pose reset or action clipping is available.
"""
import json
import os
from pathlib import Path
import time
import traceback
import numpy as np
from .isaac_mobile import mobile_targets


class FilePolicyClient:
    def __init__(self,directory,room_id,checkpoint_id):
        self.directory=Path(directory);self.room=room_id;self.sequence=0
        metadata=json.loads((self.directory/'ready.json').read_text())
        if metadata.get('checkpoint_id')!=checkpoint_id or metadata.get('horizon')!=20:raise ValueError('policy_checkpoint_identity_mismatch')

    def infer(self,sample):
        if set(sample)!= {'state','prompt','image/head_left','image/left_wrist','image/right_wrist'}:raise ValueError('privileged_policy_input_rejected')
        stem=f'room{self.room:03d}_{self.sequence:06d}';self.sequence+=1
        request=self.directory/(stem+'.request.npz');temporary=request.with_suffix('.tmp')
        with temporary.open('wb') as stream:np.savez(stream,**sample)
        temporary.replace(request);reply=self.directory/(stem+'.reply.npz');error=self.directory/(stem+'.error.json');deadline=time.monotonic()+300
        while not reply.exists():
            if error.exists():raise RuntimeError(json.loads(error.read_text())['error'])
            if time.monotonic()>deadline:raise TimeoutError('policy_inference_response_timeout')
            time.sleep(.01)
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


def validate_actions(actions,model):
    actions=np.asarray(actions)
    if actions.shape!=(20,19) or not np.isfinite(actions).all():raise ValueError('invalid_policy_action_chunk')
    for action in actions:
        for name,target in mobile_targets(action).items():
            joint=model.joint(name).id
            if not model.jnt_limited[joint] or not model.jnt_range[joint,0]<=target<=model.jnt_range[joint,1]:
                raise ValueError('policy_action_outside_mechanical_joint_range:'+name)
    return actions


def run_policy_room(runtime,case):
    from r1pro_teleop.vla.policy import Pi05Policy,PolicyContract
    r=runtime;cfg=case['policy'];error=None;spans=[];raw_chunks=[];submitted=[];executed=0;source='model_failure'
    try:
        policy=Pi05Policy(FilePolicyClient(cfg['directory'],r.room_id,cfg['checkpoint_id']),PolicyContract(cfg['checkpoint_id'],action_horizon=20))
        first=r.observation();base_reference=first['state'][16:].copy();bottom=float(first['tray_pose'][0,2])
        table=min(r.tables,key=lambda t:np.linalg.norm(np.asarray(t['center_world'])[:2]-first['tray_pose'][0,:2]))
        r.context=table;r.manipulating=True
        if not r.observation()['front_region_ok']:raise ValueError('policy_initial_station_not_table_front')
        r.write('policy_contract.json',dict(checkpoint_id=cfg['checkpoint_id'],base_reference=base_reference.tolist(),
            base_reference_source='episode_initial_measured_feedback',model_action_mask=[True]*16+[False]*3,
            fixed_base_command=r.fixed_episode_base_command.tolist(),teacher_fallback=False,policy_inputs=['state19','3_native_rgb','prompt'],
            policy_horizon=20,execution_horizon=5,frames_per_action=cfg['frames_per_action'],parent_split=case['parent_split'],held_out_generalization=False,task_table=table))
        for prompt in ('Pick up the tray','Place the tray'):
            start=r.frames;gate=PlaceObserver(r.observation(),table) if prompt=='Place the tray' else None;passed=False
            if gate:r.write('place_initial_state.json',dict(frame=r.frames,state=r.observation()['state'].tolist(),source='preceding_model_pick_physical_continuation',reset_between_pick_and_place=False,model_executed=True))
            while r.frames-start<cfg['frames_per_action']:
                obs=r.observation();state=obs['state'].copy();state[16:]-=base_reference
                actions=policy.infer(obs['policy_images'],state,prompt);raw_chunks.append(actions.copy());validate_actions(actions,r.model)
                r.event('model_chunk',prompt=prompt,chunk_index=len(raw_chunks)-1,raw_action=actions.tolist(),policy_input_frame=r.frames)
                for raw in actions[:min(5,cfg['frames_per_action']-(r.frames-start))]:
                    command=raw.astype(float).copy();command[16:]=r.fixed_episode_base_command
                    submitted.append(command.copy());obs=r.tick(command);executed+=1
                    passed=measured_pick(obs,bottom) if gate is None else gate.update(obs)
                    if passed:break
                r.write('policy_progress.json',dict(stage='native_policy',action=prompt,completed=r.frames-start,total=cfg['frames_per_action'],heartbeat_unix=time.time(),executed_model_frames=executed))
                if passed:break
            spans.append(dict(prompt=prompt,start=start,end=r.frames,frames=r.frames-start,passed=passed,stable_support_frames=gate.stable if gate else None,release_gap_m=gate.release_gap if gate else None))
            if not passed:raise ValueError('policy_action_budget_exhausted:'+prompt)
    except BaseException as exc:
        error=dict(type=type(exc).__name__,message=str(exc),traceback=traceback.format_exc())
        if isinstance(exc,(TimeoutError,FileNotFoundError,ConnectionError)) or 'inference_failed' in str(exc):source='infrastructure_failure'
        r.write('failure.json',error)
    finally:
        # A physics guard can raise after the actuator step. Those real frames
        # still count as model execution, even though that attempt failed.
        executed=r.frames
        np.savez_compressed(r.output/'model_actions.npz',raw_chunks=np.asarray(raw_chunks),submitted=np.asarray(submitted),executed_frames=executed)
        r.worker_result=dict(schema='isaac_policy_room/1',scope='training_scene_native_closed_loop_diagnostic',model_executed=executed>0,
            teacher_collection=False,teacher_fallback=False,training_eligible=False,passed=error is None and len(spans)==2,
            actions=spans,error=error,failure_category=source if error else None,frames=r.frames,executed_model_frames=executed,room_id=r.room_id,
            original_room_id=case.get('original_room_id',r.room_id),parent_split=case['parent_split'],worker_completed=True)
        r.write('worker_result.json',r.worker_result);r.worker_done()
    return r.worker_result
