"""Fresh three-table opposed/mobile source -> BC; never the fixed-base pipeline."""
from pathlib import Path
import json,os,time,subprocess
from .data_three_table_single_tray import PROFILE
from .data_three_table_lerobot import build_source
from .training_cache import file_sha
from .training_pipeline import write_atomic,run_owned,gpu_available,GPU_UUIDS,unused_path

def campaign_gate(path,certified_catalog=None):
 path=Path(path)
 if certified_catalog and Path(certified_catalog).exists():
  from .data_three_table_single_tray import source_validate,bc_input_contract
  catalog=json.loads(Path(certified_catalog).read_text());chosen={s:[] for s in ('train','val','test')};proofs={}
  if catalog.get('schema')!='airport_three_table_certified_source_catalog/1':raise ValueError('certified_source_catalog_required')
  for row in catalog['records']:
   directory=Path(row['qualification_dir']);certificate=directory/'source_qualification_audit.json';c=json.loads(certificate.read_text());source=json.loads((directory/'source.json').read_text());plan=json.loads((directory/'plan.json').read_text())
   if file_sha(certificate)!=row['certificate_sha256'] or c.get('verified') is not True or c.get('schema')!='airport_three_table_source_requalification/1' or c['source_manifest_sha256']!=file_sha(directory/'source.json') or c['plan_sha256']!=file_sha(directory/'plan.json') or c['original_result_sha256']!=file_sha(source['result']) or c['original_trace_sha256']!=file_sha(source['trace']):raise ValueError('actual_certified_source_identity_changed')
   source_validate(source);bc_input_contract(plan)
   if source['split']!=row['split']:raise ValueError('certified_source_split_changed')
   original=str(Path(row['original_case']).resolve());chosen[row['split']].append(original);proofs[original]=str(directory)
  return dict(selected=len(catalog['records']),completed=len(catalog['records']),successful_splits=chosen,ready=all(chosen.values()),certified_source_proofs=proofs,certified_catalog_sha256=file_sha(certified_catalog))
 if not (path/'status.json').exists():return None
 status=json.loads((path/'status.json').read_text())
 if status.get('task_profile')!=PROFILE:raise ValueError('new_single_tray_campaign_required')
 chosen={split:[] for split in ('train','val','test')}
 for row in status.get('results',[]):
  if row.get('task_completed') is not True or row.get('returncode')!=0:continue
  result_path=Path(row['result']);result=json.loads(result_path.read_text())
  if result.get('task_completed') is not True or result.get('physics_success') is not True or result.get('training_eligible') is not True:raise ValueError('campaign_success_not_actual_complete_source')
  audit=result_path.parent/'source_qualification_audit.json'
  if not audit.is_file() or json.loads(audit.read_text()).get('verified') is not True:continue
  if result['split']!=row['split'] or result['split'] not in chosen:raise ValueError('source_scene_split_changed')
  chosen[result['split']].append(str(result_path.parent))
 return dict(selected=status['selected'],completed=status.get('completed',0),campaign_all_closed=status.get('completed')==status['selected'],successful_splits=chosen,ready=all(chosen.values()),campaign_status_sha256=file_sha(path/'status.json'))


def new_evaluation_gate(receipt_path,milestone_path,updates):
 receipt_path=Path(receipt_path)
 if not receipt_path.exists():return False
 value=json.loads(receipt_path.read_text())
 if (value.get('schema')!='airport_three_table_single_tray_evaluation_handoff/1' or value.get('task_profile')!=PROFILE or value.get('actual_completed_updates')!=updates or value.get('training_status_sha256')!=file_sha(milestone_path) or value.get('status')!='evaluation_completed_gpu_released' or value.get('training_resume_allowed') is not True or not value.get('new_three_table_single_tray_protocol_id')):raise ValueError('new_three_task_evaluation_receipt_not_bound_or_released')
 return True


def evaluation_command(options,milestone,output):
 protocol=options.get('evaluation_protocol')
 driver=Path(options['release'])/'scripts/evaluate_three_table_single_tray_pi05_batch.py'
 if not protocol or not Path(protocol).is_file() or not driver.is_file():return None
 if options.get('evaluation_protocol_sha256') and file_sha(protocol)!=options['evaluation_protocol_sha256']:raise ValueError('new_scope_evaluation_protocol_changed')
 budget=options.get('evaluation_max_action_steps',3600)
 if type(budget) is not int or budget<=0:raise ValueError('positive_explicit_new_task_evaluation_budget_required')
 return [options['vla_python'],str(driver),'--spec',options['spec'],'--milestone',str(milestone),'--protocol',protocol,'--out',str(output),'--gpu-uuid',options.get('evaluation_gpu_uuid',GPU_UUIDS[1]),'--egl-device',str(options.get('evaluation_egl_device',0)),'--port',str(options.get('evaluation_port',8013)),'--model-python',options['vla_python'],'--sim-python',options['sim_python'],'--max-action-steps',str(budget),'--execute']


def supervise(options,*,recover=False):
 if options.get('external_training_run'):
  from .three_table_training_resume import supervise_external_resume
  return supervise_external_resume(options,recover=recover)
 run=Path(options['run_dir']);run.mkdir(parents=True,exist_ok=True);status_path=run/'pipeline_status.json'
 import fcntl
 lock=(run/'pipeline.lock').open('a+');fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
 previous=json.loads(status_path.read_text()) if status_path.exists() else None
 if previous and previous.get('task_profile')!=PROFILE:raise ValueError('cannot_resume_foreign_task_pipeline')
 if previous and not recover:raise ValueError('existing_pipeline_requires_explicit_recovery')
 if previous:write_atomic(unused_path(run/'pipeline_status_history.json'),previous)
 spec=json.loads(Path(options['spec']).read_text())
 if spec.get('prompt_mode')!=PROFILE or Path(spec['run_dir']).resolve()!=run.resolve() or Path(spec['dataset_root']).resolve()!=(run/'datasets/train').resolve():raise ValueError('new_three_task_spec_binding_required')
 data_only=options.get('data_only',False)
 if type(data_only) is not bool:raise ValueError('explicit_data_only_boolean_required')
 if not data_only and options.get('evaluation_policy')!='pause_at_milestone_until_new_three_table_runtime':raise ValueError('new_scope_milestone_evaluation_gate_required')
 acceleration=options.get('acceleration_spec',{}) if data_only else options['acceleration_spec'];acceleration_path=run/'acceleration_spec.json'
 if acceleration_path.exists() and json.loads(acceleration_path.read_text())!=acceleration:raise ValueError('acceleration_strategy_changed')
 if not acceleration_path.exists():write_atomic(acceleration_path,acceleration)
 status=dict(previous or {},schema='airport_three_table_single_tray_background_pipeline/1',pid=os.getpid(),task_profile=PROFILE,method='bc_lora_then_optional_verified_simulation_expert_flowdagger',dagger_executed=False,training_started=False,data_only=data_only,evaluation_status='pending_new_three_table_single_tray_runtime_validation')
 if data_only:status['method']='verified_simulation_teacher_dataset_only'
 def stage(name,**fields):status.update(stage=name,heartbeat_unix=time.time(),**fields);write_atomic(status_path,status)
 from .three_table_recovery import StageJournal,native_proof,dataset_proof,cache_proof,training_resources,reject_live_owned_children,preflight,isolate_partial,milestone_proof,import_native_stage
 reject_live_owned_children(run)
 binding={k:v for k,v in options.items() if k not in ('release','core_report')}
 binding['training_spec_sha256']=file_sha(options['spec'])
 binding_path=run/'recovery_options_binding.json'
 if binding_path.exists() and json.loads(binding_path.read_text())!=binding:raise ValueError('immutable_pipeline_options_changed')
 if not binding_path.exists():write_atomic(binding_path,binding)
 journal=StageJournal(run,stage)
 preflight_path=run/'training_preflight.json'
 if not data_only and not preflight_path.exists():
  stage('preflight_verified_parent_and_non_base_environments',training_started=False)
  try:write_atomic(preflight_path,preflight(options,run))
  except Exception as error:
   stage('preflight_contract_failed_preserving_sources_and_checkpoints',error=repr(error),training_started=False);raise
 release=Path(options['release']);env=dict(os.environ,OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1',WANDB_MODE='disabled');cpu=dict(env,CUDA_VISIBLE_DEVICES='',JAX_PLATFORMS='cpu');model=dict(env,CUDA_VISIBLE_DEVICES=','.join(GPU_UUIDS),XLA_PYTHON_CLIENT_MEM_FRACTION='.55',NCCL_P2P_DISABLE='1',NCCL_SHM_DISABLE='1',NCCL_IB_DISABLE='1',NCCL_NET='Socket',NCCL_CUMEM_HOST_ENABLE='0',XLA_FLAGS='--xla_gpu_use_memcpy_local_p2p=false --xla_gpu_enable_nccl_user_buffers=false --xla_gpu_enable_command_buffer= --xla_gpu_enable_triton_gemm=false');model.pop('JAX_PLATFORMS',None)
 try:
  if options.get('completed_dataset_run'):
   from .completed_dataset_import import import_completed_dataset
   stage('verifying_imported_completed_dataset',training_started=False)
   imported=import_completed_dataset(options,run,on_progress=lambda progress:stage('verifying_imported_completed_dataset',actual_import_progress=progress,training_started=False))
   records=imported['records'];proof=imported['selection'];selection=run/'frozen_source_selection.json'
   core=json.loads(Path(options['core_report']).read_text())
   if core.get('returncode')!=0:raise ValueError('new_release_core_not_verified')
   stage('imported_completed_dataset_verified',dataset_ready=True,completed_dataset_import=str(run/'completed_dataset_import.json'),imported_source_counts=imported['proof']['verified_source_counts'],training_started=False)
   if data_only:
    stage('data_only_exports_verified_no_training',dataset_ready=True,training_started=False,optimizer_initialized=False,cache_built=False,model_gpu_jobs_started=False,verified_splits=['train','val','test']);return
  else:
   selection=run/'frozen_source_selection.json'
   stage('waiting_for_data',training_started=False)
   while True:
    proof=json.loads(selection.read_text()) if selection.is_file() else campaign_gate(options['campaign'],options.get('certified_source_catalog'))
    closed=bool(proof and proof.get('completed')==proof.get('selected'))
    if proof and (proof['ready'] and (not data_only or proof.get('campaign_all_closed',True)) or closed):
     if not selection.exists():
      proof['frozen_file_sha256']={str(Path(case)/name):file_sha(Path(case)/name) for cases in proof['successful_splits'].values() for case in cases for name in ('result.json','attempt/trace.h5','scene/scene.json','source_qualification_audit.json')}
      for directory in proof.get('certified_source_proofs',{}).values():
       for name in ('source.json','plan.json','source_qualification_audit.json'):proof['frozen_file_sha256'][str(Path(directory)/name)]=file_sha(Path(directory)/name)
      write_atomic(selection,proof)
     for path,digest in proof.get('frozen_file_sha256',{}).items():
      if file_sha(path)!=digest:raise ValueError('frozen_first_batch_source_changed')
     break
    stage('waiting_for_data',training_started=False,source_gate=proof);time.sleep(30)
   core=json.loads(Path(options['core_report']).read_text())
   if core.get('returncode')!=0:raise ValueError('new_release_core_not_verified')
   stage('building_verified_new_task_media_and_datasets',source_gate=proof)
   records=[];case_errors=[]
   for split,cases in proof['successful_splits'].items():
    for number,case in enumerate(cases):
     try:
      proof_dir=Path(proof.get('certified_source_proofs',{}).get(case,run/'source_manifests'/split/f'case_{number:04d}'))
      if (proof_dir/'source.json').is_file() and (proof_dir/'plan.json').is_file():
       source=json.loads((proof_dir/'source.json').read_text());plan=json.loads((proof_dir/'plan.json').read_text())
       from .data_three_table_single_tray import source_validate,bc_input_contract
       source_validate(source);bc_input_contract(plan)
      else:
       if proof_dir.exists():proof_dir.rename(unused_path(proof_dir.with_name(proof_dir.name+'_partial_preserved')))
       source,plan=build_source(case,proof_dir)
      native=run/'native'/split/source['scene_id']
      imported=options.get('reusable_native_stages',{}).get(f'native_{split}_{number}')
      if imported:
       if file_sha(imported['exit_receipt'])!=imported['exit_receipt_sha256'] or file_sha(Path(imported['folder'])/'manifest.json')!=imported['manifest_sha256']:raise ValueError('native_stage_import_declaration_changed')
       import_native_stage(run,f'native_{split}_{number}',imported['folder'],imported['exit_receipt'],source);native=Path(imported['folder'])
      render_env=dict(env,CUDA_VISIBLE_DEVICES=GPU_UUIDS[0],MUJOCO_GL='egl',MUJOCO_EGL_DEVICE_ID='1');render_env.pop('JAX_PLATFORMS',None)
      if native.exists() and not (native/'manifest.json').exists():native.rename(unused_path(native.with_name(native.name+'_partial_preserved')))
      journal.execute(f'native_{split}_{number}',lambda pulse:run_owned([options['sim_python'],str(release/'scripts/render_three_table_single_tray.py'),'--case',case,'--output',str(native)],release,render_env,unused_path(run/f'render_{split}_{number}.log'),on_progress=pulse),artifact=native/'manifest.json',verify=lambda:native_proof(native,source),prepare_retry=lambda:isolate_partial(native))
      manifest=native/'manifest.json';replay=json.loads(manifest.read_text())
      if replay.get('frames')!=source['frames'] or any(value>1e-7 for value in replay['errors'].values()) or replay.get('initial_restore_count')!=1:raise ValueError('native_full_replay_not_verified')
      views=[]
      for camera in ('head_left','head_right','left_wrist','right_wrist'):
       path=native/(camera+'.mp4');header=json.loads(subprocess.check_output(['ffprobe','-v','error','-select_streams','v:0','-show_entries','stream=width,height,avg_frame_rate,nb_frames','-of','json',str(path)],text=True))['streams'][0];views.append(dict(camera=camera,path=str(path),sha256=file_sha(path),header=header,manifest=str(manifest),manifest_sha256=file_sha(manifest)))
      records.append(dict(source=source,plan=plan,native_videos=views))
     except Exception as error:
      case_errors.append(dict(case=case,split=split,error=repr(error)));stage('case_artifact_blocked_preserving_other_cases',case_errors=case_errors,training_started=False)
   present={r['source']['split'] for r in records};missing=[split for split in ('train','val','test') if split not in present]
   media_selection=dict(schema='airport_verified_three_table_media_selection/1',physical_source_selection_sha256=file_sha(selection),verified_source_count=len(records),verified_scene_ids=[r['source']['scene_id'] for r in records],verified_split_counts={split:sum(r['source']['split']==split for r in records) for split in ('train','val','test')},failed_excluded_media_cases=case_errors,missing_splits=missing,records=records,master_physical_selection_unchanged=True,failed_sources_excluded_from_training=True)
   media_path=run/'verified_media_selection.json'
   if media_path.exists() and json.loads(media_path.read_text())!=media_selection:raise ValueError('immutable_verified_media_batch_changed_requires_new_data_version')
   if not media_path.exists():write_atomic(media_path,media_selection)
   if case_errors:
    write_atomic(run/'failed_media_cases.json',dict(failed_media_cases=case_errors,verified_media_cases=[r['source']['scene_id'] for r in records],training_started=False))
    write_atomic(run/'verified_partial_source_records.json',records)
   records_path=run/'source_records.jsonl';records_path.write_text(''.join(json.dumps(row,allow_nan=False)+'\n' for row in records))
   for split in ('train','val','test'):
    if split not in present:continue
    version=options.get('data_version','v1')
    if version not in ('v1','v2'):raise ValueError('explicit_supported_dataset_version_required')
    repo_id='airport/three_table_single_tray_action3_'+split+'_'+version
    dataset=run/'datasets'/split;published=dataset/'airport_training_manifest.json'
    if published.exists():dataset_proof(dataset,split,records,repo_id=repo_id);continue
    if dataset.exists():dataset.rename(unused_path(dataset.with_name(dataset.name+'_partial_preserved')))
    journal.execute('export_'+split,lambda pulse:run_owned([options['vla_python'],str(release/'scripts/export_three_table_single_tray_actions.py'),'--records',str(records_path),'--destination',str(dataset),'--repo-id',repo_id,'--split',split],release,cpu,unused_path(run/f'export_{split}.log'),on_progress=pulse),artifact=published,verify=lambda:dataset_proof(dataset,split,records,repo_id=repo_id),prepare_retry=lambda:isolate_partial(dataset))
   if missing:
    stage('waiting_missing_qualified_media_split',source_campaign_closed=closed,case_errors=case_errors,missing_qualified_media_splits=missing,verified_cases=len(records),verified_export_splits=sorted(present),verified_media_selection_sha256=file_sha(media_path),training_started=False,no_failed_case_silently_dropped=True);return
   if data_only:
    stage('data_only_exports_verified_no_training',dataset_ready=True,dataset_version=version,training_started=False,optimizer_initialized=False,cache_built=False,model_gpu_jobs_started=False,verified_splits=['train','val','test'],source_selection_sha256=file_sha(selection));return
  protocol_path=options.get('evaluation_protocol')
  if protocol_path and not Path(protocol_path).exists():
   from ..single_tray_3table.evaluation_protocol import prepare_from_source
   prepare_from_source(next(r['source'] for r in records if r['source']['split']=='train'),protocol_path,selected=options.get('evaluation_selected',3),max_action_steps=options.get('evaluation_max_action_steps',3600))
  stage('preparing_cpu_train_cache')
  cache=run/'data_cache'
  if cache.exists() and not (cache/'cache_manifest.json').exists():cache.rename(unused_path(cache.with_name('data_cache_partial_preserved')))
  journal.execute('cache',lambda pulse:run_owned([options['vla_python'],str(release/'scripts/train_pi05_accelerated.py'),'--spec',options['spec'],'--parent-status',options['parent_status'],'--prepare-cache'],release,cpu,unused_path(run/'prepare_cache.log'),on_progress=pulse),artifact=cache/'cache_manifest.json',verify=lambda:cache_proof(run,spec),prepare_retry=lambda:isolate_partial(cache))
  from .three_table_recovery import training_resource_admission
  admission=training_resource_admission(options,run)
  for updates in (10,100,1000,10000,100000):
   milestone=run/f'milestone_{updates:06d}.json'
   saved=False
   if milestone.exists():
    value=json.loads(milestone.read_text())
    if value.get('schema')!='airport_pi05_training_milestone/1' or value.get('prompt_mode')!=PROFILE or value.get('checkpoint_verified') is not True or value.get('actual_completed_updates')!=updates or value.get('checkpoint_step')!=updates-1 or any(value.get('spec',{}).get(k)!=v for k,v in spec.items()):raise ValueError('saved_milestone_identity_changed')
    milestone_proof(milestone,spec,options)
    exits=[]
    for file in run.glob(f'train_to_{updates:06d}*.exit.json'):
     exit_value=json.loads(file.read_text());seen_exit={row.split(',')[1].strip() for group in exit_value.get('actual_own_gpu_rows',[]) for row in group}
     if exit_value.get('returncode')==0 and exit_value.get('trainer_exited') is True and seen_exit==set(GPU_UUIDS):exits.append(exit_value)
    saved=bool(exits)
   if not saved:
    while True:
     resources=training_resources(min_free_mib=admission['minimum_training_free_mib'],project_root=release.parents[1])
     if resources['ready']:break
     stage('waiting_training_vram',next_completed_updates=updates,actual_resources=resources);time.sleep(30)
   stage('starting_training_child' if not saved else 'reusing_saved_milestone',training_started=bool(status.get('training_started')),next_completed_updates=updates)
   argv=[options['vla_python'],str(release/'scripts/train_pi05_accelerated.py'),'--spec',options['spec'],'--parent-status',options['parent_status'],'--stop-after',str(updates)]
   checkpoint_root=run/'checkpoints'/spec['name']/'training'
   if updates>10 or (checkpoint_root.exists() and any(p.name.isdigit() for p in checkpoint_root.iterdir())):argv.append('--resume')
   receipt=None
   if not saved:
    def train_attempt(pulse):
     baseline=status.get('actual_completed_updates',0)
     def update_progress(progress):
      pulse(progress)
      advanced=progress.get('actual_training_status')=='training' and (progress.get('actual_completed_updates') or 0)>baseline
      stage('training_new_three_action_model' if advanced else 'initializing_training_child',training_started=bool(status.get('training_started') or advanced),gradient_updates_started_this_child=advanced,active_trainer_pid=progress['pid'],actual_training_progress=progress)
     command=list(argv)
     if checkpoint_root.exists() and any(p.name.isdigit() for p in checkpoint_root.iterdir()) and '--resume' not in command:command.append('--resume')
     return run_owned(command,release,model,unused_path(run/f'train_to_{updates:06d}.log'),on_progress=update_progress,on_started=lambda child:stage('initializing_training_child',training_started=bool(status.get('training_started')),gradient_updates_started_this_child=False,active_trainer_pid=child['pid'],actual_child_identity=child))
    receipt=journal.execute(f'train_{updates:06d}',train_attempt,verify=lambda:milestone_proof(milestone,spec,options))
   seen={row.split(',')[1].strip() for group in (receipt['actual_own_gpu_rows'] if receipt else []) for row in group}
   if receipt is not None and seen!=set(GPU_UUIDS):raise ValueError('dual_gpu_training_not_proven')
   stage('actual_checkpoint_saved_evaluation_pending',training_started=True,actual_completed_updates=updates,evaluation_status='pending_new_three_table_single_tray_runtime_validation')
   milestone=run/f'milestone_{updates:06d}.json';evaluation_receipt=run/'evaluations'/f'step_{updates:06d}'/'completion_receipt.json'
   while not new_evaluation_gate(evaluation_receipt,milestone,updates):
    command=evaluation_command(options,milestone,evaluation_receipt.parent)
    if command is not None:
     stage('evaluating_new_single_tray_checkpoint',actual_completed_updates=updates,evaluation_status='running_new_scope_only')
     eval_env=dict(env,CUDA_VISIBLE_DEVICES='');eval_env.pop('JAX_PLATFORMS',None)
     journal.execute(f'eval_{updates:06d}',lambda pulse:run_owned(command,release,eval_env,unused_path(run/f'eval_{updates:06d}.log'),deadline_hours=72,on_progress=pulse),artifact=evaluation_receipt,verify=lambda:{'verified':new_evaluation_gate(evaluation_receipt,milestone,updates)})
     if not new_evaluation_gate(evaluation_receipt,milestone,updates):raise ValueError('new_scope_evaluator_returned_without_closed_receipt')
    else:
     stage('blocked_evaluation_waiting_new_three_action_runtime',actual_completed_updates=updates,evaluation_receipt=str(evaluation_receipt),training_gpu_process_exited=True);time.sleep(30)
  stage('three_table_bc_training_and_new_scope_evaluations_complete',actual_completed_updates=100000,training_complete=True,evaluation_status='all_milestone_new_scope_evaluations_verified_gpu_released',completed_evaluation_updates=[10,100,1000,10000,100000])
 except BaseException as error:stage('failed_preserving_sources_and_checkpoints',error=repr(error));raise

