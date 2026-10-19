"""Hash-bound orchestration recovery; optimizer/cache stay in the original run."""
from pathlib import Path
import json,os,time
from .training_cache import file_sha
from .training_pipeline import write_atomic,run_owned,unused_path,GPU_UUIDS
from .three_table_recovery import StageJournal,cache_proof,dataset_proof,milestone_proof,training_resources,reject_live_owned_children


def verify_external_training(options):
 old=Path(options['external_training_run']).resolve();new=Path(options['run_dir']).resolve();release=Path(options['training_release']).resolve();spec_path=Path(options['spec']);spec=json.loads(spec_path.read_text())
 if old==new or Path(spec['run_dir']).resolve()!=old or Path(spec['dataset_root']).resolve()!=(old/'datasets/train').resolve():raise ValueError('separate_orchestration_original_training_spec_required')
 required={str(spec_path),str(old/'data_cache/cache_manifest.json'),str(old/'acceleration_spec.json')}
 required.update(str(old/'datasets'/split/name) for split in ('train','val','test') for name in ('airport_training_manifest.json','whole_action_source_manifest.jsonl'))
 required.update(str(release/name) for name in ('scripts/train_pi05_accelerated.py','r1pro_teleop/vla/training_accelerated.py','r1pro_teleop/vla/training.py'))
 hashes=options['external_input_sha256']
 if not required.issubset(hashes):raise ValueError('complete_external_training_input_hash_binding_required')
 for path,digest in hashes.items():
  if file_sha(path)!=digest:raise ValueError('external_training_input_changed:'+path)
 milestone=Path(options['initial_milestone']);exit_path=Path(options['initial_train_exit']);m=json.loads(milestone.read_text());receipt=json.loads(exit_path.read_text());argv=receipt.get('argv',[])
 devices={row.split(',')[1].strip() for group in receipt.get('actual_own_gpu_rows',[]) for row in group}
 if milestone.resolve()!=(old/'milestone_000010.json').resolve() or file_sha(milestone)!=options['initial_milestone_sha256'] or file_sha(exit_path)!=options['initial_train_exit_sha256'] or m.get('actual_completed_updates')!=10 or m.get('checkpoint_step')!=9 or m.get('checkpoint_verified') is not True or receipt.get('returncode')!=0 or receipt.get('trainer_exited') is not True or devices!=set(GPU_UUIDS) or '--spec' not in argv or Path(argv[argv.index('--spec')+1]).resolve()!=spec_path.resolve() or '--stop-after' not in argv or argv[argv.index('--stop-after')+1]!='10':raise ValueError('actual_original_dual_gpu_checkpoint10_exit_required')
 if any(m.get('spec',{}).get(k)!=v for k,v in spec.items()):raise ValueError('original_checkpoint_training_spec_changed')
 return spec,dict(verified=True,external_training_run=str(old),training_release=str(release),initial_milestone_sha256=file_sha(milestone),initial_train_exit_sha256=file_sha(exit_path),initial_checkpoint_id=options['initial_checkpoint_id'],external_input_sha256=hashes,optimizer_policy='exact_original_optimizer_state_resume',new_optimizer_initialized=False,old_evaluation_directories_not_written=True)


def training_resume_command(options,updates):
 if updates<=10:raise ValueError('checkpoint10_is_reused_not_retrained')
 return [options['vla_python'],str(Path(options['training_release'])/'scripts/train_pi05_accelerated.py'),'--spec',options['spec'],'--parent-status',options['parent_status'],'--stop-after',str(updates),'--resume']


def successful_training_exit(paths,spec_path,updates):
 for path in paths:
  row=json.loads(Path(path).read_text());argv=row.get('argv',[]);devices={line.split(',')[1].strip() for group in row.get('actual_own_gpu_rows',[]) for line in group}
  if row.get('returncode')==0 and row.get('trainer_exited') is True and devices==set(GPU_UUIDS) and '--spec' in argv and Path(argv[argv.index('--spec')+1]).resolve()==Path(spec_path).resolve() and '--stop-after' in argv and argv[argv.index('--stop-after')+1]==str(updates):return dict(path=str(path),sha256=file_sha(path),actual_exit=row)
 return None


def supervise_external_resume(options,*,recover=False):
 from .three_table_single_tray_pipeline import new_evaluation_gate,evaluation_command
 import fcntl
 run=Path(options['run_dir']);run.mkdir(parents=True,exist_ok=True);lock=(run/'pipeline.lock').open('a+');fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
 status_path=run/'pipeline_status.json'
 if status_path.exists() and not recover:raise ValueError('existing_orchestration_requires_explicit_recovery')
 status=dict(schema='airport_three_table_external_optimizer_resume/1',pid=os.getpid(),training_started=True,method='bc_lora',task_profile='three_table_single_tray_action3_v1',external_training_run=options['external_training_run'],actual_completed_updates=10)
 def stage(name,**fields):status.update(stage=name,heartbeat_unix=time.time(),**fields);write_atomic(status_path,status)
 stage('verifying_external_saved_checkpoint_and_cache')
 try:
  spec,proof=verify_external_training(options);old=Path(options['external_training_run']);training_release=Path(options['training_release']);release=Path(options['release'])
  reject_live_owned_children(run);reject_live_owned_children(old)
  binding=run/'external_training_binding.json'
  if binding.exists() and json.loads(binding.read_text())!=proof:raise ValueError('immutable_external_training_binding_changed')
  if not binding.exists():write_atomic(binding,proof)
  core=json.loads(Path(options['core_report']).read_text())
  if core.get('returncode')!=0:raise ValueError('new_evaluation_release_core_not_verified')
  initial_identity=milestone_proof(Path(options['initial_milestone']),spec,options)
  if initial_identity['actual_checkpoint_id']!=options['initial_checkpoint_id']:raise ValueError('original_checkpoint10_content_identity_changed')
  checks=run/'actual_reused_data_cache_proof.json'
  if not checks.exists():
   records=[json.loads(line) for line in (old/'source_records.jsonl').read_text().splitlines() if line.strip()]
   datasets={s:dataset_proof(old/'datasets'/s,s,records,repo_id='airport/three_table_single_tray_action3_'+s+'_v1') for s in ('train','val','test')}
   write_atomic(checks,dict(cache=cache_proof(old,spec),datasets=datasets,original_training_math_unchanged=True))
  journal=StageJournal(run,stage);env=dict(os.environ,OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1',WANDB_MODE='disabled');env.pop('JAX_PLATFORMS',None)
  model=dict(env,CUDA_VISIBLE_DEVICES=','.join(GPU_UUIDS),XLA_PYTHON_CLIENT_MEM_FRACTION='.55',NCCL_P2P_DISABLE='1',NCCL_SHM_DISABLE='1',NCCL_IB_DISABLE='1',NCCL_NET='Socket',NCCL_CUMEM_HOST_ENABLE='0',XLA_FLAGS='--xla_gpu_use_memcpy_local_p2p=false --xla_gpu_enable_nccl_user_buffers=false --xla_gpu_enable_command_buffer= --xla_gpu_enable_triton_gemm=false')
  for updates in (10,100,1000,10000,100000):
   verify_external_training(options)
   milestone=old/f'milestone_{updates:06d}.json'
   actual_exit=successful_training_exit(list(old.glob(f'train_to_{updates:06d}*.exit.json'))+list(run.glob(f'train_to_{updates:06d}*.exit.json')),options['spec'],updates)
   if not milestone.exists() or actual_exit is None:
    while True:
     resources=training_resources(project_root=training_release.parents[1])
     if resources['ready']:break
     stage('waiting_training_vram',next_completed_updates=updates,actual_resources=resources);time.sleep(30)
    command=training_resume_command(options,updates)
    def train(pulse):
     return run_owned(command,training_release,model,unused_path(run/f'train_to_{updates:06d}.log'),on_progress=pulse,on_started=lambda child:stage('initializing_exact_resumed_training_child',active_trainer_pid=child['pid'],next_completed_updates=updates,new_optimizer_initialized=False))
    journal.execute(f'train_{updates:06d}',train,verify=lambda:milestone_proof(milestone,spec,options))
    actual_exit=successful_training_exit(run.glob(f'train_to_{updates:06d}*.exit.json'),options['spec'],updates)
    if actual_exit is None:raise ValueError('actual_exact_resume_dual_gpu_exit_required')
   milestone_proof(milestone,spec,options);stage('actual_checkpoint_saved_evaluation_pending',actual_completed_updates=updates,actual_training_exit=actual_exit,checkpoint=str(milestone))
   completion=run/'evaluations'/f'step_{updates:06d}'/'completion_receipt.json'
   if not new_evaluation_gate(completion,milestone,updates):
    command=evaluation_command(options,milestone,completion.parent)
    if command is None:raise ValueError('new_scope_evaluator_required_for_saved_checkpoint_recovery')
    stage('evaluating_new_single_tray_checkpoint',actual_completed_updates=updates)
    journal.execute(f'eval_{updates:06d}',lambda pulse:run_owned(command,release,dict(env,CUDA_VISIBLE_DEVICES=''),unused_path(run/f'eval_{updates:06d}.log'),deadline_hours=72,on_progress=pulse),artifact=completion,verify=lambda:{'verified':new_evaluation_gate(completion,milestone,updates)})
    if not new_evaluation_gate(completion,milestone,updates):raise ValueError('evaluation_not_closed_cannot_resume_optimizer')
  stage('three_table_bc_training_and_new_scope_evaluations_complete',training_complete=True,actual_completed_updates=100000,completed_evaluation_updates=[10,100,1000,10000,100000])
 except BaseException as error:stage('failed_preserving_sources_and_checkpoints',error=repr(error));raise
