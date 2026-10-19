"""Time-scheduled pure-policy diagnostic; no task completion or training labels."""
from pathlib import Path
import json,hashlib,time,traceback,os
import numpy as np
from ..vla.observations import render_model_observation

PROMPTS=('Pick up the tray','Place the tray','Flush tray to the left')
LABELS=('pick_empty','place_empty','push_loaded')


def stage_frames(stage_seconds,fps=20):
    if isinstance(stage_seconds,bool) or not np.isfinite(stage_seconds) or stage_seconds<=0 or fps!=20:raise ValueError('positive_three_stage_20hz_budget_required')
    frames=float(stage_seconds)*fps
    if not frames.is_integer():raise ValueError('stage_duration_must_be_whole_20hz_frames')
    return int(frames)


class RawReplyArchive:
    """Archive original numeric fields BEFORE existing policy validation."""
    def __init__(self,client,directory,frame):
        self.client=client;self.directory=Path(directory);self.directory.mkdir(parents=True,exist_ok=True);self.frame=frame;self.calls=0;self.replies=0
    def infer(self,observation):
        index=self.calls;self.calls+=1;state=np.asarray(observation['state']);start=dict(call=index,frame=int(self.frame()),prompt=observation['prompt'],state_sha256=hashlib.sha256(state.tobytes()).hexdigest(),image_shapes={k:list(np.asarray(v).shape) for k,v in observation.items() if k.startswith('image/')})
        with (self.directory/f'request_{index:06d}.npz').open('xb') as stream:np.savez(stream,request_state19=state.copy(),request_prompt=np.asarray(observation['prompt']))
        path=self.directory/f'raw_reply_{index:06d}.json';path.write_text(json.dumps(dict(start,status='request_started'),indent=2))
        try:reply=self.client.infer(observation)
        except Exception as error:path.write_text(json.dumps(dict(start,status='transport_failed',error=repr(error)),indent=2));raise
        fields={'request_state19':state.copy()};details={}
        for name in ('actions','raw_actions','model_action_mask'):
            if not isinstance(reply,dict) or name not in reply:continue
            value=np.asarray(reply[name]);details[name]=dict(shape=list(value.shape),dtype=str(value.dtype))
            if value.dtype.hasobject:details[name]['unsupported_object_value_repr']=repr(reply[name])
            else:fields[name]=value
        if fields:
            with (self.directory/f'raw_reply_{index:06d}.npz').open('xb') as stream:np.savez(stream,**fields)
        self.replies+=1;path.write_text(json.dumps(dict(start,status='reply_archived_before_validation',fields=details),indent=2));return reply


class ModelTrace:
    """Attach exact model row to original actual control-interval journal."""
    def __init__(self,trace):self.trace=trace;self.pending=None
    def __getattr__(self,name):return getattr(self.trace,name)
    def append(self,row):
        if self.pending is None:raise ValueError('actual_interval_missing_model_action_provenance')
        enriched=dict(row,**self.pending)
        if not np.array_equal(np.r_[row['action'],row['base_action']],self.pending['model_raw_action19']):raise ValueError('submitted_command_changed_from_raw_model_action')
        self.trace.append(enriched)


def run_time_schedule(runtime,policy,trace,output,*,stage_seconds=200,execute_steps=5,environment_loader=None):
    n=stage_frames(stage_seconds);budget=3*n;out=Path(output);decisions=out/'policy_decisions';decisions.mkdir(parents=True,exist_ok=True)
    if type(execute_steps) is not int or not 1<=execute_steps<=policy.contract.action_horizon:raise ValueError('execute_steps_outside_model_horizon')
    proxy=ModelTrace(trace);runtime.trace=proxy;original=policy.client;archive=RawReplyArchive(original,decisions,lambda:trace.count);policy.client=archive
    start=float(runtime.d.time);phase=None;decision=0;environment_count=0;wall=time.monotonic();last_progress_wall=wall
    def progress(stage):
        target=out/'progress.json';temporary=out/'progress.json.tmp'
        value=dict(pid=os.getpid(),stage=stage,heartbeat_unix=time.time(),frames=trace.count,actual_runtime_ticks=runtime.steps,sim_seconds=float(runtime.d.time)-start,current_text_stage=phase,current_prompt=None if phase is None else PROMPTS[phase],actual_inference_calls=archive.calls,diagnostic_only=True,training_eligible=False)
        temporary.write_text(json.dumps(value,indent=2));temporary.replace(target)
    progress('initializing_time_schedule')
    result=dict(schema='airport_three_table_free_run_diagnostic/1',run_scope='free_run_diagnostic',run_kind='free_run_diagnostic',free_run_diagnostic=True,diagnostic_only=True,training_ready=False,counts_toward_task_rate=False,source='simulation/program_generated',controller_source='vla_generated',checkpoint_id=policy.contract.checkpoint_id,task_success_claimed=False,task_completed=False,physics_success=False,training_eligible=False,formal_evaluation_eligible=False,success_rate_eligible=False,requested_stage_seconds=float(stage_seconds),requested_total_sim_seconds=3*float(stage_seconds),fps=20,total_requested_frames=budget,expected_prompts=list(PROMPTS),teacher_fallback_calls=0,control_policy='raw_finite_mobile19_only_existing_engine_actuator_limits',environment_load_extra_ticks=0)
    try:
        while trace.count<budget:
            frame=trace.count;current=min(frame//n,2)
            if current!=phase:
                phase=current;runtime.phase='free_run_'+LABELS[phase];trace.event('free_run_text_stage_start',action_label=LABELS[phase],prompt=PROMPTS[phase],time_schedule_frame=frame)
                if phase==2:
                    if environment_loader is None:raise ValueError('actual_payload_environment_loader_required')
                    steps=runtime.steps;sim_time=float(runtime.d.time);journal=environment_loader(runtime.sim)
                    if runtime.steps!=steps or float(runtime.d.time)!=sim_time:raise ValueError('passenger_load_added_unrequested_control_ticks')
                    runtime.passenger_loaded=True
                    trace.event('passenger_payload_initialized',environment_evidence=journal,environment_only=True,training_eligible=False);environment_count+=1
            state=np.r_[runtime.sim.state(),runtime.sim.base_joint_state()]
            images={name:render_model_observation(runtime.sim,name,getattr(runtime.cfg,'vla_model_render_max_dim',0)) for name in policy.contract.camera_names}
            call=archive.calls;actions=np.asarray(policy.infer(images,state,PROMPTS[phase]),dtype=np.float32)
            if actions.shape!=(policy.contract.action_horizon,19) or not np.isfinite(actions).all():raise ValueError('invalid_or_nonfinite_model_chunk')
            used=min(execute_steps,budget-frame,n*(phase+1)-frame)
            with (decisions/f'chunk_{decision:06d}.npz').open('xb') as stream:np.savez(stream,state19=state,model_actions=actions,used_rows=np.arange(used,dtype=np.int32))
            (decisions/f'chunk_{decision:06d}.json').write_text(json.dumps(dict(decision=decision,raw_reply_call=call,frame=frame,prompt=PROMPTS[phase],used_rows=used,model_shape=list(actions.shape),model_dtype=str(actions.dtype)),indent=2))
            for index in range(used):
                raw=actions[index].copy();before_state19=np.r_[runtime.sim.state(),runtime.sim.base_joint_state()].copy();proxy.pending=dict(state19=before_state19,action19=raw.copy(),cmd19=raw.copy(),model_raw_action19=raw,model_decision_index=np.int32(decision),model_row_index=np.int32(index),model_text_stage=np.int32(phase))
                runtime.apply_model_target(raw);runtime.tick();proxy.pending=None
                if trace.count%100==0 or time.monotonic()-last_progress_wall>=5:
                    progress('recording_free_run_actual_controls');last_progress_wall=time.monotonic()
            decision+=1
        result.update(recording_completed=True,requested_diagnostic_duration_completed=trace.count==budget and abs(float(runtime.d.time)-start-budget/20)<1e-8,diagnostic_duration_completed=budget==12000 and float(runtime.d.time)-start>=600-1e-8,full_600_sim_seconds_completed=budget==12000 and float(runtime.d.time)-start>=600-1e-8)
    except Exception as error:
        result.update(recording_completed=False,failure_code=getattr(error,'code',type(error).__name__),failure_detail=str(error));(out/'exception.txt').write_text(traceback.format_exc())
    finally:
        progress('recording_closed_full_requested_duration' if result.get('recording_completed') else 'recording_stopped_preserving_actual_prefix')
        policy.client=original
        result.update(frames=trace.count,actual_runtime_ticks=runtime.steps,sim_seconds=float(runtime.d.time)-start,wall_seconds=time.monotonic()-wall,actual_inference_calls=archive.calls,actual_model_replies=archive.replies,inverse_solver_calls=runtime.id_calls,environment_event_count=environment_count,actual_ctrl_substep_recording=True)
    return result
