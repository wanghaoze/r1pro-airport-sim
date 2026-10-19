"""Independent free-run diagnostic, never a formal evaluator or dataset source."""
from pathlib import Path
import argparse,json,os,sys,time,shutil,traceback
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


def execute(scene,output,policy,*,cfg,stage_seconds=200,execute_steps=5):
 from r1pro_teleop.single_tray_3table.free_run_runtime import FreeRunRuntime
 from r1pro_teleop.single_tray_3table.free_run import run_time_schedule,stage_frames
 from r1pro_teleop.single_tray_lab.three_table_scene import passenger_load_three_table
 from r1pro_teleop.airport_fsm.trace import Trace
 from r1pro_teleop.airport_fsm.contracts import atomic_json,sha256_file
 from r1pro_teleop.vla.data_three_table_single_tray import PROFILE,RULE_REVISION,FINAL_ORIENTATION_DEFINITION
 out=Path(output);out.mkdir(parents=True,exist_ok=False);runtime=None;trace=None
 result=dict(schema='airport_three_table_free_run_diagnostic/1',run_scope='free_run_diagnostic',run_kind='free_run_diagnostic',free_run_diagnostic=True,diagnostic_only=True,training_ready=False,counts_toward_task_rate=False,task_completed=False,physics_success=False,task_success_claimed=False,training_eligible=False,formal_evaluation_eligible=False,success_rate_eligible=False,checkpoint_id=policy.contract.checkpoint_id,scene_id=scene.get('scene_id'),split=scene.get('split'),frames=0,actual_inference_calls=0,inverse_solver_calls=None)
 try:
  archive=out/'scene';archive.mkdir();(archive/'scene.json').write_text(json.dumps(scene,indent=2));shutil.copyfile(scene['xml'],archive/'mobile.xml')
  if sha256_file(archive/'mobile.xml')!=scene['xml_sha256']:raise ValueError('free_run_scene_xml_identity_changed')
  if scene.get('task_rule_revision')!=RULE_REVISION:raise ValueError('free_run_rule_identity_changed')
  runtime=FreeRunRuntime(scene,cfg,render=True,diagnostic_directory=out/'diagnostics')
  meta=dict(limits=runtime.limits,scene=scene['legacy_spec'],scene_id=scene['scene_id'],scene_xml_sha256=scene['xml_sha256'],split=scene['split'],config=cfg.dump(),task_profile=PROFILE,task_rule_revision=RULE_REVISION,final_orientation_definition=FINAL_ORIENTATION_DEFINITION,checkpoint_id=policy.contract.checkpoint_id,run_scope='free_run_diagnostic',source='simulation/program_generated',controller_source='vla_generated_free_run_diagnostic',base_mode='planar_mobile_table_front',base_actuated=True,model_action_mask=[True]*19,fps=20,integration_state_spec=int(runtime.integration_spec),substeps_per_frame=runtime.sim.nstep,recorded_substep_controls_without_interpolation=not cfg.substep_control_enabled,physics_timestep_s=float(runtime.m.opt.timestep),base_origin_joint_state=runtime.sim.base_joint_state().tolist(),training_eligible=False,formal_evaluation_eligible=False,requested_stage_seconds=float(stage_seconds),planned_frames=3*stage_frames(stage_seconds),payload_event_frame=2*stage_frames(stage_seconds),run_kind='free_run_diagnostic',free_run_diagnostic=True,diagnostic_only=True,training_ready=False,counts_toward_task_rate=False,task_checks='diagnostic_only_never_early_task_stop',control_policy='raw_finite19_only_existing_engine_actuator_limits',state19_semantics='measured_arms16_plus_actual_planar_base_joint_offsets3_before_physics',action19_semantics='raw_model_servo_reference_arm14_full_opening2_planar_joint_offsets3',cmd19_semantics='unchanged_submitted_raw_model_servo_reference19_not_actuator_half_opening_units',effective_ctrl_semantics='diagnostic_only_engine_ctrlrange_clamp_never_written_back')
  meta['source_model_parameters']={name:getattr(runtime.m,name).copy().tolist() for name in ('actuator_forcerange','actuator_forcelimited','actuator_gainprm','actuator_biasprm','actuator_ctrlrange','actuator_ctrllimited','actuator_gear','cam_pos','cam_quat','cam_fovy','cam_ipd')}
  trace=Trace(out/'attempt',meta);trace.file.attrs['schema']='airport_fsm_raw/2';runtime.record_ctrl_substeps=True
  actual=run_time_schedule(runtime,policy,trace,out,stage_seconds=stage_seconds,execute_steps=execute_steps,environment_loader=lambda sim:passenger_load_three_table(sim,scene));result.update(actual)
 except Exception as error:
  result.update(failure_code=getattr(error,'code',type(error).__name__),failure_detail=str(error),recording_completed=False);(out/'exception.txt').write_text(traceback.format_exc())
 finally:
  if runtime:
   result.update(inverse_solver_calls=runtime.id_calls,frames=0 if trace is None else trace.count)
   if trace:trace.close(dict(qpos=runtime.d.qpos,qvel=runtime.d.qvel,time=float(runtime.d.time)))
   runtime.close_diagnostics();runtime.close()
  atomic_json(out/'result.json',result)
 return result


def main():
 from r1pro_teleop.airport_fsm.contracts import Config
 from r1pro_teleop.single_tray_3table.learned import ThreeTablePolicy
 from r1pro_teleop.vla.policy import PolicyContract
 from r1pro_teleop.vla.data_three_table_single_tray import PROFILE
 p=argparse.ArgumentParser()
 for name in ('scene','config','output','checkpoint-id','gpu-uuid'):p.add_argument('--'+name,required=True)
 p.add_argument('--host',default='127.0.0.1');p.add_argument('--port',type=int,default=8015);p.add_argument('--action-horizon',type=int,default=20);p.add_argument('--execute-steps',type=int,default=5);p.add_argument('--stage-seconds',type=float,default=200);p.add_argument('--egl-device',type=int,default=1);a=p.parse_args()
 from r1pro_teleop.single_tray_3table.free_run import stage_frames
 stage_frames(a.stage_seconds)
 os.environ['MUJOCO_GL']='egl';os.environ['MUJOCO_EGL_DEVICE_ID']=str(a.egl_device);os.environ['CUDA_VISIBLE_DEVICES']=a.gpu_uuid
 # Root's outer supervisor owns model startup/resource exclusion. This child
 # does not start a model, trainer, teacher or planner.
 scene=json.loads(Path(a.scene).read_text())
 try:
  policy=ThreeTablePolicy.from_websocket(a.host,a.port,PolicyContract(a.checkpoint_id,action_horizon=a.action_horizon,action_width=19,prompt_mode=PROFILE));cfg=Config.load(a.config)
 except Exception as error:
  from r1pro_teleop.airport_fsm.contracts import atomic_json
  out=Path(a.output);out.mkdir(parents=True,exist_ok=False);archive=out/'scene';archive.mkdir();(archive/'scene.json').write_text(json.dumps(scene,indent=2));shutil.copyfile(scene['xml'],archive/'mobile.xml')
  result=dict(schema='airport_three_table_free_run_diagnostic/1',run_kind='free_run_diagnostic',run_scope='free_run_diagnostic',task_completed=False,physics_success=False,training_eligible=False,formal_evaluation_eligible=False,success_rate_eligible=False,task_success_claimed=False,frames=0,actual_inference_calls=0,recording_completed=False,diagnostic_duration_completed=False,checkpoint_id=a.checkpoint_id,inverse_solver_calls=None,failure_code=type(error).__name__,failure_detail=str(error),zero_frame_evidence={'native_video_possible':False,'reason':'initialization_failed_before_model_execution'})
  result.update(free_run_diagnostic=True,diagnostic_only=True,training_ready=False,counts_toward_task_rate=False)
  atomic_json(out/'result.json',result);print(json.dumps(result));return 2
 result=execute(scene,a.output,policy,cfg=cfg,stage_seconds=a.stage_seconds,execute_steps=a.execute_steps)
 print(json.dumps(result));return 0 if result.get('recording_completed') else 2
if __name__=='__main__':raise SystemExit(main())
