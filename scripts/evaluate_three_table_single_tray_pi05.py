"""Pure model mobile19 evaluation of one new three-table scene."""
from pathlib import Path
import argparse,json,sys,time,traceback,shutil,hashlib
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

class InferenceAuditClient:
 """Append request/transport outcome evidence without changing model values."""
 def __init__(self,client,path,step):self.client=client;self.path=Path(path);self.step=step;self.count=0
 def write(self,row):
  with self.path.open('a',encoding='utf-8') as stream:stream.write(json.dumps(row,allow_nan=False)+'\n')
 def infer(self,observation):
  call=self.count;self.count+=1
  self.write(dict(event='inference_request_started',call=call,step=int(self.step()),prompt=observation.get('prompt'),
   state_sha256=hashlib.sha256(np.asarray(observation.get('state')).tobytes()).hexdigest(),
   rgb_shapes={k:list(np.asarray(v).shape) for k,v in observation.items() if k.startswith('image/')},
   physical_execution_claimed=False))
  try:reply=self.client.infer(observation)
  except Exception as error:
   self.write(dict(event='inference_transport_failed',call=call,error=repr(error),physical_execution_claimed=False));raise
  self.write(dict(event='inference_reply_received',call=call,physical_execution_claimed=False))
  return reply

def source_push_reference_profile(scene,cfg):
 """Validate the declared reference using its actual three-table source cap.

 This restores the existing 20mm source contract; it neither changes cfg nor
 executes any teacher motion. Historical lab references retain their validator.
 """
 from r1pro_teleop.single_tray_lab.control import ControlProfile
 from r1pro_teleop.single_tray_3table.loaded_bridge import LoadedBridgeProfile
 values=dict(scene['control_profile']);cap=values.get('max_penetration_m',.003)
 if cap<=.01:return ControlProfile(**values).validate()
 if cap!=cfg.completion_collision_penetration_m:
  raise ValueError('learned_reference_source_collision_contract_mismatch')
 values['source_collision_penetration_m']=cap
 values['planning_gripper_preload_max_m']=max(values.get('planning_gripper_preload_max_m',.003),cap)
 return LoadedBridgeProfile(**values).validate()
def evaluate(scene,output,policy,*,cfg,push_reference_scene,execute_steps=5,max_action_steps=6000,actuator_saturation=False,reference_rate_limit=False):
 from r1pro_teleop.single_tray_3table.control import ThreeTableRuntime
 from r1pro_teleop.single_tray_3table.learned import LearnedThreeTable
 from r1pro_teleop.airport_fsm.trace import Trace
 from r1pro_teleop.airport_fsm.contracts import atomic_json,sha256_file
 from r1pro_teleop.single_tray_lab.control import ControlProfile
 from r1pro_teleop.vla.data_three_table_single_tray import PROFILE,RULE_REVISION,FINAL_ORIENTATION_DEFINITION
 output=Path(output);output.mkdir(parents=True,exist_ok=False)
 started=time.monotonic();result=dict(schema='airport_three_table_single_tray_learned_evaluation/1',task_profile=PROFILE,task_rule_revision=RULE_REVISION,scene_id=scene.get('scene_id'),split=scene.get('split'),checkpoint_id=policy.contract.checkpoint_id,task_completed=False,physics_success=False,training_eligible=False,inverse_solver_calls=None,teacher_fallback_calls=0,physical_episode_started=False,execute_steps=execute_steps,max_action_steps=max_action_steps,environment_phase_excluded=True)
 learner=None;r=None;trace=None;initial_time=None;original_client=None
 try:
  archive=output/'scene';archive.mkdir()
  (archive/'scene.json').write_text(json.dumps(scene,indent=2));shutil.copyfile(scene['xml'],archive/'mobile.xml')
  if sha256_file(archive/'mobile.xml')!=scene['xml_sha256']:raise ValueError('three_table_scene_xml_identity_changed')
  if scene.get('task_rule_revision')!=RULE_REVISION:raise ValueError('three_table_scene_rule_mismatch')
  r=ThreeTableRuntime(scene,cfg,render=True);r.record_ctrl_substeps=True;initial_time=float(r.d.time)
  meta=dict(limits=r.limits,scene=scene['legacy_spec'],scene_id=scene['scene_id'],scene_xml_sha256=scene['xml_sha256'],split=scene['split'],config=cfg.dump(),task_profile=PROFILE,task_rule_revision=RULE_REVISION,final_orientation_definition=FINAL_ORIENTATION_DEFINITION,checkpoint_id=policy.contract.checkpoint_id,base_mode='planar_mobile_table_front',base_actuated=True,model_action_mask=[True]*19,fps=20,source='simulation/program_generated',controller_source='vla_generated',integration_state_spec=int(r.integration_spec),substeps_per_frame=r.sim.nstep,recorded_substep_controls_without_interpolation=not cfg.substep_control_enabled,physics_timestep_s=float(r.m.opt.timestep),base_origin_joint_state=r.sim.base_joint_state().tolist())
  trace=Trace(output/'attempt',meta);trace.file.attrs['schema']='airport_fsm_raw/2';r.trace=trace
  result['physical_episode_started']=True
  if hasattr(policy,'client'):
   original_client=policy.client;policy.client=InferenceAuditClient(original_client,output/'inference_calls.jsonl',lambda:r.steps)
  learner=LearnedThreeTable(r,scene,policy,output=output/'policy_decisions',push_reference_profile=source_push_reference_profile(push_reference_scene,cfg),execute_steps=execute_steps,max_action_steps=max_action_steps,actuator_saturation=actuator_saturation,reference_rate_limit=reference_rate_limit)
  result.update(learner.run())
 except Exception as e:result.update(failure_code=getattr(e,'code',type(e).__name__),failure_detail=str(e));(output/'exception.txt').write_text(traceback.format_exc())
 finally:
  result.update(frames=0 if trace is None else trace.count,sim_seconds=None if r is None else float(r.d.time),wall_seconds=time.monotonic()-started,inverse_solver_calls=None if r is None else int(r.id_calls),action_spans=[] if learner is None else learner.spans)
  result['physical_episode_started']=bool(r is not None and initial_time is not None and float(r.d.time)>initial_time)
  result['zero_frame_evidence']=dict(status='no_physical_video_frames' if result['frames']==0 else 'recorded_trace_available',native_video_possible=result['frames']>0,reason=result.get('failure_detail'))
  if result['task_completed'] and (r is None or r.id_calls!=0 or not result['physical_episode_started']):
   result.update(task_completed=False,physics_success=False,failure_code='learned_controller_identity_not_verified')
  try:
   if trace is not None:trace.close(dict(qpos=r.d.qpos,qvel=r.d.qvel,time=float(r.d.time)))
   if r is not None:r.sim.close()
  except Exception as cleanup:result['cleanup_error']=repr(cleanup)
  if original_client is not None:
   result['actual_inference_calls']=policy.client.count;policy.client=original_client
  atomic_json(output/'result.json',result)
 return result

def main():
 from r1pro_teleop.airport_fsm.contracts import Config
 from r1pro_teleop.single_tray_3table.learned import ThreeTablePolicy
 from r1pro_teleop.vla.policy import PolicyContract
 from r1pro_teleop.vla.data_three_table_single_tray import PROFILE
 p=argparse.ArgumentParser();
 for k in ('scene','config','push-reference-scene','output','checkpoint-id'):p.add_argument('--'+k,required=True)
 p.add_argument('--host',default='127.0.0.1');p.add_argument('--port',type=int,default=8013);p.add_argument('--action-horizon',type=int,default=20);p.add_argument('--execute-steps',type=int,default=5);p.add_argument('--max-action-steps',type=int,default=6000);p.add_argument('--actuator-saturation',action='store_true');p.add_argument('--reference-rate-limit',action='store_true');a=p.parse_args()
 scene=json.loads(Path(a.scene).read_text())
 try:policy=ThreeTablePolicy.from_websocket(a.host,a.port,PolicyContract(a.checkpoint_id,action_horizon=a.action_horizon,action_width=19,prompt_mode=PROFILE))
 except Exception as exc:
  record_policy_startup_failure(scene,a.output,a.checkpoint_id,exc);return 2
 result=evaluate(scene,a.output,policy,cfg=Config.load(a.config),push_reference_scene=json.loads(Path(a.push_reference_scene).read_text()),execute_steps=a.execute_steps,max_action_steps=a.max_action_steps,actuator_saturation=a.actuator_saturation,reference_rate_limit=a.reference_rate_limit)
 return 0 if result['task_completed'] else 2

def record_policy_startup_failure(scene,output,requested_checkpoint_id,error):
 """Unavailable/incorrect model identity is infrastructure evidence, not a task trial."""
 from r1pro_teleop.airport_fsm.contracts import atomic_json
 from r1pro_teleop.vla.data_three_table_single_tray import PROFILE,RULE_REVISION
 output=Path(output);output.mkdir(parents=True,exist_ok=False)
 archive=output/'scene';archive.mkdir();(archive/'scene.json').write_text(json.dumps(scene,indent=2))
 shutil.copyfile(scene['xml'],archive/'mobile.xml')
 result=dict(schema='airport_three_table_single_tray_learned_evaluation/1',task_profile=PROFILE,
  task_rule_revision=RULE_REVISION,scene_id=scene.get('scene_id'),split=scene.get('split'),
  checkpoint_id=requested_checkpoint_id,checkpoint_identity_verified=False,physical_episode_started=False,
  task_completed=False,physics_success=False,training_eligible=False,frames=0,
  inverse_solver_calls=None,teacher_fallback_calls=0,failure_code='policy_startup_failed',failure_detail=repr(error),
  failure_category='infrastructure',action_spans=[],
  zero_frame_evidence=dict(status='no_physical_video_frames',native_video_possible=False,reason=repr(error)))
 (output/'exception.txt').write_text(traceback.format_exc());atomic_json(output/'result.json',result)
 (output/'inference_calls.jsonl').write_text(json.dumps(dict(event='policy_startup_failed',error=repr(error),inference_executed=False,physical_execution_claimed=False))+'\n')
 return result
if __name__=='__main__':raise SystemExit(main())
