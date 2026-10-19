"""Independent new-task data-to-BC supervisor. No old task runtime evaluation."""
from pathlib import Path
import json,os,time,subprocess
import numpy as np
import h5py
from .data_single_tray import PROFILE,canonical_hash,plan_action_segments,materialize_action_split
from .training_cache import file_sha
from .training_pipeline import write_atomic,run_owned,gpu_available,GPU_UUIDS,unused_path


def campaign_gate(path):
 path=Path(path)
 if not (path/'status.json').exists():return None
 status=json.loads((path/'status.json').read_text())
 if status.get('task_profile')!=PROFILE:raise ValueError('new_single_tray_campaign_required')
 if status.get('completed')!=status.get('selected') or not str(status.get('stage','')).startswith('physical_candidates_complete'):return None
 chosen={split:[] for split in ('train','val','test')}
 for row in status.get('results',[]):
  if row.get('task_completed') is not True or row.get('returncode')!=0:continue
  result_path=Path(row['result']);result=json.loads(result_path.read_text())
  if result.get('task_completed') is not True or result.get('physics_success') is not True or result.get('training_eligible') is not True:raise ValueError('campaign_success_not_actual_complete_source')
  if result['split']!=row['split'] or result['split'] not in chosen:raise ValueError('source_scene_split_changed')
  chosen[result['split']].append(str(result_path.parent))
 return dict(selected=status['selected'],successful_splits=chosen,ready=all(chosen.values()),campaign_status_sha256=file_sha(path/'status.json'))


def validate_run_metadata(scene,result,metadata,frames):
 if scene.get('schema')!='airport_single_tray_scene/1' or result.get('schema')!='airport_single_tray_result/1':raise ValueError('actual_single_tray_cli_schema_required')
 if canonical_hash(metadata.get('scene'))!=canonical_hash(scene):raise ValueError('trace_scene_identity_changed')
 if result.get('scene_id')!=scene.get('scene_id') or result.get('split')!=scene.get('split') or result.get('frames')!=frames:raise ValueError('result_scene_split_frame_identity_changed')
 if result.get('task_profile')!=PROFILE or metadata.get('task_profile')!=PROFILE or result.get('source')!='simulation/program_generated' or metadata.get('source')!='simulation/program_generated':raise ValueError('actual_new_task_source_required')
 profile=result.get('control_profile')
 if not isinstance(profile,dict) or not profile or canonical_hash(profile)!=canonical_hash(metadata.get('control_profile')):raise ValueError('result_trace_control_profile_disagreement')
 if metadata.get('scene_xml_sha256')!=scene.get('xml_sha256'):raise ValueError('result_trace_model_xml_identity_changed')
 if metadata.get('base_mode')!='fixed_front' or metadata.get('base_actuated') is not False or metadata.get('model_action_mask')!=[True]*16+[False]*3 or metadata.get('fps')!=20 or metadata.get('action_semantics')!='absolute_mobile19':raise ValueError('raw_fixed_base_action_contract_changed')
 return profile


def build_source(case,work):
 case=Path(case);work=Path(work);work.mkdir(parents=True,exist_ok=False)
 scene_path=case/'scene/scene.json';scene=json.loads(scene_path.read_text());result_path=case/'result.json';result=json.loads(result_path.read_text());trace=case/'attempt/trace.h5';events_path=case/'attempt/events.jsonl'
 if result.get('task_completed') is not True or result.get('physics_success') is not True or result.get('training_eligible') is not True:raise ValueError('failed_task_cannot_be_source_export')
 if not scene.get('blender_assets_present'):raise ValueError('production_photo_scene_assets_not_present')
 if not isinstance(scene.get('scene_generator_sha256'),str) or len(scene['scene_generator_sha256'])!=64 or not isinstance(scene.get('passenger_layout'),dict):raise ValueError('new_scene_generator_and_passenger_layout_identity_required')
 with h5py.File(trace,'r') as file:
  metadata=json.loads(file.attrs['metadata_json']);frames=int(file.attrs['num_frames']);profile=validate_run_metadata(scene,result,metadata,frames)
  if len(file['qpos'])!=frames or file_sha(scene['xml'])!=metadata['scene_xml_sha256']:raise ValueError('actual_source_frame_or_xml_hash_changed')
  if file.attrs.get('schema')!='airport_single_tray_raw/2' or not np.all(file['transition_completed'][:]):raise ValueError('complete_raw2_transitions_required')
  for key in ('state19','action19','qpos','qvel','integration_state','ctrl_substeps','sim_time'):
   if not np.isfinite(file[key][:]).all():raise ValueError('nonfinite_source:'+key)
  numeric={key:file[key][:] for key in ('payload_loaded','payload_mass','gripper_contact_force','support_contact','floor_contact','tray_clearance','tray_goal_reached')}
 segments=work/'segments.json';segments.write_text(json.dumps(result['action_spans'],allow_nan=False))
 source=dict(schema='airport_single_tray_source/1',task_profile=PROFILE,source='simulation/program_generated',tray_count=1,scene_id=scene['scene_id'],split=scene['split'],frames=frames,fps=20,action_semantics='absolute_mobile19',state_semantics='measured_joint16_plus_base_origin_offset3',base_mode='fixed_front',base_actuated=False,model_action_mask=[True]*16+[False]*3,trace=str(trace),trace_sha256=file_sha(trace),scene_xml=scene['xml'],scene_xml_sha256=file_sha(scene['xml']),scene_json=str(scene_path),scene_json_sha256=file_sha(scene_path),result=str(result_path),result_sha256=file_sha(result_path),events=str(events_path),events_sha256=file_sha(events_path),segments=str(segments),segments_sha256=file_sha(segments),environment_manifest_sha256=canonical_hash(dict(asset_manifest=scene['blender_manifest_sha256'],photos=scene['reference_photos'],physics=scene['physics_options'],scene_generator_sha256=scene['scene_generator_sha256'],passenger_layout=scene['passenger_layout'])),controller_sha256=metadata['controller_sha256'],contact_n=profile['contact_n'],lifted_m=profile['minimum_lift_clearance'])
 if 'allowed_long_rim_contract' in metadata:
  from r1pro_teleop.single_tray_lab.grasp_contract import validate_long_rim_contract
  source['allowed_long_rim_contract']=json.loads(json.dumps(validate_long_rim_contract(metadata['allowed_long_rim_contract'])))
 from r1pro_teleop.single_tray_lab.contact_summary import audit_contact_peaks
 source['contact_gate_evidence']=audit_contact_peaks(result,trace)
 if source['contact_gate_evidence']['trace_sha256']!=source['trace_sha256']:raise ValueError('contact_gate_source_changed')
 events=[json.loads(line) for line in events_path.read_text().splitlines() if line.strip()]
 plan=plan_action_segments(source,events,result,numeric,contact_n=source['contact_n'],lifted_m=source['lifted_m'])
 from r1pro_teleop.single_tray_lab.withdrawal_audit import audit_place_withdrawal
 places=[row for row in plan['segments'] if row['action_label']=='place_empty']
 if len(places)!=1:raise ValueError('one_complete_place_withdrawal_endpoint_required')
 source['place_withdrawal_evidence']=audit_place_withdrawal(source,places[0])
 plan=plan_action_segments(source,events,result,numeric,contact_n=source['contact_n'],lifted_m=source['lifted_m'])
 return source,plan


def new_evaluation_gate(receipt_path,milestone_path,updates):
 receipt_path=Path(receipt_path)
 if not receipt_path.exists():return False
 value=json.loads(receipt_path.read_text())
 if (value.get('schema')!='airport_single_tray_evaluation_handoff/1' or value.get('task_profile')!=PROFILE or value.get('actual_completed_updates')!=updates or value.get('training_status_sha256')!=file_sha(milestone_path) or value.get('status')!='evaluation_completed_gpu_released' or value.get('training_resume_allowed') is not True or not value.get('new_single_tray_protocol_id')):raise ValueError('new_three_task_evaluation_receipt_not_bound_or_released')
 return True


def evaluation_command(options,milestone,output):
 protocol=options.get('evaluation_protocol')
 driver=Path(options['release'])/'scripts/evaluate_single_tray_pi05_batch.py'
 if not protocol or not Path(protocol).is_file() or not driver.is_file():return None
 if options.get('evaluation_protocol_sha256') and file_sha(protocol)!=options['evaluation_protocol_sha256']:raise ValueError('new_scope_evaluation_protocol_changed')
 budget=options.get('evaluation_max_action_steps',3600)
 if type(budget) is not int or budget<=0:raise ValueError('positive_explicit_new_task_evaluation_budget_required')
 return [options['vla_python'],str(driver),'--spec',options['spec'],'--milestone',str(milestone),'--protocol',protocol,'--out',str(output),'--gpu-uuid',GPU_UUIDS[0],'--egl-device','1','--port',str(options.get('evaluation_port',8013)),'--model-python',options['vla_python'],'--sim-python',options['sim_python'],'--max-action-steps',str(budget),'--execute']


def supervise(options):
 run=Path(options['run_dir']);run.mkdir(parents=True,exist_ok=True);status_path=run/'pipeline_status.json'
 import fcntl
 lock=(run/'pipeline.lock').open('a+');fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
 if status_path.exists():raise ValueError('new_pipeline_directory_required_preserve_previous_attempt')
 spec=json.loads(Path(options['spec']).read_text())
 if spec.get('prompt_mode')!=PROFILE or Path(spec['run_dir']).resolve()!=run.resolve() or Path(spec['dataset_root']).resolve()!=(run/'datasets/train').resolve():raise ValueError('new_three_task_spec_binding_required')
 if options.get('evaluation_policy')!='pause_at_milestone_until_new_three_action_runtime':raise ValueError('new_scope_milestone_evaluation_gate_required')
 acceleration=options['acceleration_spec'];acceleration_path=run/'acceleration_spec.json'
 if acceleration_path.exists() and json.loads(acceleration_path.read_text())!=acceleration:raise ValueError('acceleration_strategy_changed')
 if not acceleration_path.exists():write_atomic(acceleration_path,acceleration)
 status=dict(schema='airport_single_tray_background_pipeline/1',pid=os.getpid(),task_profile=PROFILE,method='bc_lora_then_optional_verified_simulation_expert_flowdagger',dagger_executed=False,training_started=False,evaluation_status='pending_new_single_tray_learned_runtime_validation')
 def stage(name,**fields):status.update(stage=name,**fields);write_atomic(status_path,status)
 release=Path(options['release']);env=dict(os.environ,OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1',WANDB_MODE='disabled');cpu=dict(env,CUDA_VISIBLE_DEVICES='',JAX_PLATFORMS='cpu');model=dict(env,CUDA_VISIBLE_DEVICES=','.join(GPU_UUIDS),XLA_PYTHON_CLIENT_MEM_FRACTION='.55',NCCL_P2P_DISABLE='1',NCCL_SHM_DISABLE='1',NCCL_IB_DISABLE='1',NCCL_NET='Socket',NCCL_CUMEM_HOST_ENABLE='0',XLA_FLAGS='--xla_gpu_use_memcpy_local_p2p=false --xla_gpu_enable_nccl_user_buffers=false --xla_gpu_enable_command_buffer= --xla_gpu_enable_triton_gemm=false');model.pop('JAX_PLATFORMS',None)
 try:
  stage('waiting_complete_new_campaign')
  while True:
   proof=campaign_gate(options['campaign'])
   if proof and proof['ready']:break
   stage('blocked_data_missing_complete_successful_splits' if proof else 'waiting_complete_new_campaign',source_gate=proof);time.sleep(30)
  core=json.loads(Path(options['core_report']).read_text())
  if core.get('returncode')!=0:raise ValueError('new_release_core_not_verified')
  stage('building_verified_new_task_media_and_datasets',source_gate=proof)
  records=[]
  for split,cases in proof['successful_splits'].items():
   for number,case in enumerate(cases):
    source,plan=build_source(case,run/'source_manifests'/split/f'case_{number:04d}');native=run/'native'/split/source['scene_id']
    render_env=dict(env,CUDA_VISIBLE_DEVICES=GPU_UUIDS[0],MUJOCO_GL='egl',MUJOCO_EGL_DEVICE_ID='1');render_env.pop('JAX_PLATFORMS',None)
    run_owned([options['sim_python'],str(release/'scripts/render_single_tray_lab.py'),'--case',case,'--output',str(native)],release,render_env,unused_path(run/f'render_{split}_{number}.log'))
    manifest=native/'manifest.json';replay=json.loads(manifest.read_text())
    if replay.get('frames')!=source['frames'] or any(value>1e-7 for value in replay['errors'].values()) or replay.get('initial_restore_count')!=1:raise ValueError('native_full_replay_not_verified')
    views=[]
    for camera in ('head_left','head_right','left_wrist','right_wrist'):
     path=native/(camera+'.mp4');header=json.loads(subprocess.check_output(['ffprobe','-v','error','-select_streams','v:0','-show_entries','stream=width,height,avg_frame_rate,nb_frames','-of','json',str(path)],text=True))['streams'][0];views.append(dict(camera=camera,path=str(path),sha256=file_sha(path),header=header,manifest=str(manifest),manifest_sha256=file_sha(manifest)))
    records.append(dict(source=source,plan=plan,native_videos=views))
  records_path=run/'source_records.jsonl';records_path.write_text(''.join(json.dumps(row,allow_nan=False)+'\n' for row in records))
  for split in ('train','val','test'):
   run_owned([options['vla_python'],str(release/'scripts/export_single_tray_actions.py'),'--records',str(records_path),'--destination',str(run/'datasets'/split),'--repo-id','airport/single_tray_action3_'+split+'_v1','--split',split],release,cpu,run/f'export_{split}.log')
  stage('preparing_cpu_train_cache')
  run_owned([options['vla_python'],str(release/'scripts/train_pi05_accelerated.py'),'--spec',options['spec'],'--parent-status',options['parent_status'],'--prepare-cache'],release,cpu,run/'prepare_cache.log')
  for updates in (10,100,1000,10000,100000):
   while not gpu_available():stage('waiting_exclusive_training_gpus',next_completed_updates=updates);time.sleep(30)
   stage('training_new_three_action_model',training_started=True,next_completed_updates=updates)
   argv=[options['vla_python'],str(release/'scripts/train_pi05_accelerated.py'),'--spec',options['spec'],'--parent-status',options['parent_status'],'--stop-after',str(updates)]
   if updates>10:argv.append('--resume')
   receipt=run_owned(argv,release,model,run/f'train_to_{updates:06d}.log');seen={row.split(',')[1].strip() for group in receipt['actual_own_gpu_rows'] for row in group}
   if seen!=set(GPU_UUIDS):raise ValueError('dual_gpu_training_not_proven')
   stage('actual_checkpoint_saved_evaluation_pending',actual_completed_updates=updates,evaluation_status='pending_new_single_tray_learned_runtime_validation')
   milestone=run/f'milestone_{updates:06d}.json';evaluation_receipt=run/'evaluations'/f'step_{updates:06d}'/'completion_receipt.json'
   while not new_evaluation_gate(evaluation_receipt,milestone,updates):
    command=evaluation_command(options,milestone,evaluation_receipt.parent)
    if command is not None:
     stage('evaluating_new_single_tray_checkpoint',actual_completed_updates=updates,evaluation_status='running_new_scope_only')
     eval_env=dict(env,CUDA_VISIBLE_DEVICES='');eval_env.pop('JAX_PLATFORMS',None)
     run_owned(command,release,eval_env,run/f'eval_{updates:06d}.log',deadline_hours=72)
     if not new_evaluation_gate(evaluation_receipt,milestone,updates):raise ValueError('new_scope_evaluator_returned_without_closed_receipt')
    else:
     stage('blocked_evaluation_waiting_new_three_action_runtime',actual_completed_updates=updates,evaluation_receipt=str(evaluation_receipt),training_gpu_process_exited=True);time.sleep(30)
  stage('bc_training_and_new_scope_evaluations_complete',actual_completed_updates=100000,training_complete=True,evaluation_status='all_milestone_new_scope_evaluations_verified_gpu_released',completed_evaluation_updates=[10,100,1000,10000,100000])
 except BaseException as error:stage('failed_preserving_sources_and_checkpoints',error=repr(error));raise

