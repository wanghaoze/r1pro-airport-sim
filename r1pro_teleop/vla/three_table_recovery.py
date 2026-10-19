"""Project-owned stage receipts; retries do not waive artifact qualification."""
from pathlib import Path
import json,os,time,subprocess,shutil,math
from .training_pipeline import write_atomic,unused_path,GPU_UUIDS,verify_owned
from .training_cache import file_sha

def process_fault(error):
 return isinstance(error,(OSError,TimeoutError)) or isinstance(error,RuntimeError) and str(error).startswith('owned_child_failed:')

def isolate_partial(path):
 path=Path(path)
 if path.exists():target=unused_path(path.with_name(path.name+'_partial_preserved'));path.rename(target);return str(target)
 return None

class StageJournal:
 def __init__(self,run,status_callback,max_attempts=3,backoff=(10,30,90)):
  if max_attempts!=3:raise ValueError('bounded_three_attempt_policy_required')
  self.run=Path(run);self.callback=status_callback;self.backoff=backoff;self.max_attempts=max_attempts
 def exit_proof(self,name,artifact):
  imported=self.run/'stage_imports'/(name+'.json')
  if imported.exists():
   proof=json.loads(imported.read_text());old=Path(proof['old_folder']);exit_path=Path(proof['old_exit_receipt']);receipt=json.loads(exit_path.read_text());argv=receipt.get('argv',[])
   if proof.get('schema')!='airport_verified_native_stage_import/1' or file_sha(exit_path)!=proof['old_exit_receipt_sha256'] or file_sha(old/'manifest.json')!=proof['old_manifest_sha256'] or receipt.get('returncode')!=0 or receipt.get('trainer_exited') is not True or '--output' not in argv or Path(argv[argv.index('--output')+1]).resolve()!=old.resolve() or Path(artifact).parent.resolve()!=old.resolve():raise ValueError('verified_native_stage_import_changed')
   return proof
  prefix='prepare_cache' if name=='cache' else 'render_'+name[7:] if name.startswith('native_') else name
  for path in self.run.glob(prefix+'*.exit.json'):
   receipt=json.loads(path.read_text())
   if receipt.get('returncode')==0 and receipt.get('trainer_exited') is True:
    return {'path':str(path),'sha256':file_sha(path),'pid':receipt['pid'],'returncode':0}
  return None
 def execute(self,name,operation,*,artifact=None,verify=None,prepare_retry=None):
  folder=self.run/'stage_receipts'/name;folder.mkdir(parents=True,exist_ok=True)
  reject_live_owned_children(self.run)
  previous=list(folder.glob('attempt_*.json'))
  for path in previous:
   old=json.loads(path.read_text())
   if old.get('status')=='started':old.update(status='orphaned_process_fault',last_error='supervisor_exited_before_stage_receipt_closed',heartbeat_unix=time.time());write_atomic(path,old)
  if any(json.loads(p.read_text()).get('status')=='qualification_or_contract_blocked' for p in previous):raise ValueError('sticky_stage_contract_block_requires_explicit_new_qualified_version:'+name)
  if artifact is not None and Path(artifact).exists() and verify is not None:
   evidence=verify();exit_evidence=self.exit_proof(name,artifact)
   if exit_evidence is None:raise ValueError('verified_artifact_missing_actual_successful_child_exit')
   receipt=dict(stage=name,status='reused_verified_artifact',artifact=str(artifact),verification=evidence,actual_child_exit=exit_evidence,heartbeat_unix=time.time())
   write_atomic(folder/'verified_artifact.json',receipt);self.callback('stage_verified_reuse',active_stage=name,stage_receipt=receipt);return None
  if len(previous)>=self.max_attempts:raise RuntimeError('ordinary_stage_process_fault_budget_exhausted:'+name)
  for attempt in range(len(previous)+1,self.max_attempts+1):
   path=unused_path(folder/f'attempt_{attempt:02d}.json');receipt=dict(stage=name,attempt=attempt,status='started',started_unix=time.time(),heartbeat_unix=time.time(),artifact=str(artifact) if artifact is not None else None)
   def pulse(progress):
    receipt.update(heartbeat_unix=time.time(),actual_progress=progress);write_atomic(path,receipt);self.callback('stage_running',active_stage=name,stage_attempt=attempt,stage_receipt=receipt)
   pulse({'operation_started':True})
   try:
    result=operation(pulse)
    evidence=verify() if verify is not None else {'child_operation_returned':True}
    receipt.update(status='verified_complete',heartbeat_unix=time.time(),exit_unix=time.time(),verification=evidence,child_receipt=result)
    write_atomic(path,receipt);self.callback('stage_verified_complete',active_stage=name,stage_receipt=receipt);return result
   except Exception as error:
    fault=process_fault(error);receipt.update(status='process_fault' if fault else 'qualification_or_contract_blocked',last_error=repr(error),heartbeat_unix=time.time(),exit_unix=time.time());write_atomic(path,receipt)
    self.callback(receipt['status'],active_stage=name,stage_receipt=receipt)
    if not fault or attempt==self.max_attempts:raise
    # Every subprocess has exited/reaped before operation raises. An identity
    # mismatch is ValueError and deliberately cannot enter this retry path.
    if prepare_retry is not None:receipt['preserved_partial']=prepare_retry();write_atomic(path,receipt)
    self.callback('process_fault_backoff',active_stage=name,stage_attempt=attempt,next_attempt=attempt+1,backoff_seconds=self.backoff[attempt-1],configuration_unchanged=True)
    time.sleep(self.backoff[attempt-1])

def native_proof(folder,source):
 folder=Path(folder);m=json.loads((folder/'manifest.json').read_text());expected={'qpos','qvel','time','terminal_qpos','terminal_qvel','terminal_time'}
 errors=m.get('errors',{})
 if m.get('frames')!=source['frames'] or m.get('initial_restore_count')!=1 or set(errors)!=expected or any(type(v) not in (int,float) or not math.isfinite(v) or not 0<=v<=1e-7 for v in errors.values()):raise ValueError('native_full_replay_not_verified')
 # Both normalized and original replay must bind the actual physical bytes.
 hashes=m.get('source_sha256',{})
 for key,field in [('trace','trace_sha256'),('events','events_sha256'),('scene_xml','scene_xml_sha256'),('scene_json','scene_json_sha256'),('result','result_sha256')]:
  if hashes.get(key)!=source[field] or file_sha(source[key])!=source[field] or key not in m.get('source_files',{}) or Path(m['source_files'][key]).resolve()!=Path(source[key]).resolve() or file_sha(m['source_files'][key])!=source[field]:raise ValueError('native_source_identity_changed:'+key)
 shapes={'head_left':(1920,1536),'head_right':(1920,1536),'left_wrist':(1280,720),'right_wrist':(1280,720)};views=[]
 for camera,(w,h) in shapes.items():
  p=folder/(camera+'.mp4');header=json.loads(subprocess.check_output(['ffprobe','-v','error','-count_frames','-select_streams','v:0','-show_entries','stream=width,height,avg_frame_rate,nb_read_frames','-of','json',str(p)],text=True))['streams'][0]
  if int(header['width'])!=w or int(header['height'])!=h or header['avg_frame_rate']!='20/1' or int(header['nb_read_frames'])!=source['frames']:raise ValueError('native_frame_shape_rate_changed')
  views.append(dict(camera=camera,path=str(p),sha256=file_sha(p),header=header,manifest=str(folder/'manifest.json'),manifest_sha256=file_sha(folder/'manifest.json')))
 return {'verified':True,'videos':views,'manifest_sha256':file_sha(folder/'manifest.json')}

def dataset_proof(folder,split,records,*,repo_id=None):
 folder=Path(folder);p=folder/'airport_training_manifest.json';m=json.loads(p.read_text());expected={r['source']['scene_id'] for r in records if r['source']['split']==split}
 if m.get('dataset_ready') is not True or m.get('split')!=split or m.get('prompt_mode')!='three_table_single_tray_action3_v1' or m.get('repo_id')!=(repo_id or 'airport/three_table_single_tray_action3_'+split+'_v1') or set(m.get('complete_expected_scene_ids',[]))!=expected or {e['scene_id'] for e in m['episodes']}!=expected or any(e['split']!=split for e in m['episodes']):raise ValueError('frozen_split_dataset_identity_changed')
 for key in ('all_parquet_values_verified','training_video_encoding_verification','actual_training_rgb_derivation'):
  if m.get(key,{}).get('verified') is not True:raise ValueError('actual_dataset_audit_required:'+key)
 if file_sha(m['source_manifest'])!=m['source_manifest_sha256']:raise ValueError('dataset_source_manifest_changed')
 bound=[json.loads(x) for x in Path(m['source_manifest']).read_text().splitlines() if x.strip()]
 sources={r['source']['scene_id']:r['source']['trace_sha256'] for r in records if r['source']['split']==split}
 actual={r['scene_id']:r['trace_sha256'] for r in bound}
 if actual!=sources:raise ValueError('dataset_not_bound_to_frozen_sources')
 return {'verified':True,'training_manifest_sha256':file_sha(p),'source_manifest_sha256':m['source_manifest_sha256'],'scene_ids':sorted(expected)}

def cache_proof(run,spec):
 from .training_cache import CachedDataset,validate_cache_spec
 from .training import TrainingSpec
 data=CachedDataset(Path(run)/'data_cache',verify_hashes=True);m=data.manifest
 validate_cache_spec(TrainingSpec(**spec),m)
 if m.get('prompt_mode')!=spec['prompt_mode'] or m.get('dataset_repo_id',m.get('repo_id'))!=spec['dataset_repo_id']:raise ValueError('cache_model_dataset_binding_changed')
 return {'verified':True,'cache_manifest_sha256':file_sha(Path(run)/'data_cache/cache_manifest.json'),'samples':len(data)}

def training_resources(min_free_mib=72000,*,owned_compute_pids=(),project_root=None):
 rows=subprocess.check_output(['nvidia-smi','--query-gpu=uuid,memory.free','--format=csv,noheader,nounits'],text=True)
 free={x.split(',')[0].strip():int(x.split(',')[1]) for x in rows.splitlines()}
 compute=subprocess.check_output(['nvidia-smi','--query-compute-apps=pid,gpu_uuid,used_memory','--format=csv,noheader,nounits'],text=True)
 actual=[dict(pid=int(x.split(',')[0]),gpu_uuid=x.split(',')[1].strip(),used_mib=x.split(',')[2].strip()) for x in compute.splitlines() if x.strip()]
 owned=set(owned_compute_pids)
 if project_root is not None:
  base=str(Path(project_root).resolve())+'/'
  for row in actual:
   try:argv=(Path('/proc')/str(row['pid'])/'cmdline').read_bytes().decode().split('\0')
   except (OSError,UnicodeError):continue
   if any(a.startswith(base) and Path(a).name.startswith(('train_pi05','serve_pi05','evaluate_three_table')) for a in argv):owned.add(row['pid'])
 blocked=[r for r in actual if r['pid'] in owned and r['gpu_uuid'] in GPU_UUIDS]
 return {'ready':all(free.get(u,0)>=min_free_mib for u in GPU_UUIDS) and not blocked,'minimum_free_mib':min_free_mib,'actual_free_mib':free,'actual_compute':actual,'active_owned_compute':blocked,'unrelated_processes_not_signaled':True}

def training_resource_admission(options,run):
 threshold=options.get('minimum_training_free_mib',72000)
 if type(threshold) is not int or threshold<=0:raise ValueError('positive_explicit_training_vram_admission_required')
 evidence=options.get('training_resource_admission_evidence')
 if threshold!=72000:
  if not isinstance(evidence,dict) or not evidence.get('path') or not evidence.get('sha256'):raise ValueError('changed_training_admission_requires_recorded_evidence')
  if file_sha(evidence['path'])!=evidence['sha256']:raise ValueError('training_resource_admission_evidence_changed')
 proof=dict(schema='airport_training_resource_admission/1',minimum_training_free_mib=threshold,
            historical_default_minimum_free_mib=72000,evidence=evidence,
            batch_and_acceleration_strategy_unchanged=True,unrelated_services_not_stopped=True)
 target=Path(run)/'training_resource_admission.json'
 if target.exists() and json.loads(target.read_text())!=proof:raise ValueError('immutable_training_resource_admission_changed')
 if not target.exists():write_atomic(target,proof)
 return proof

def reject_live_owned_children(run):
 for path in Path(run).glob('*.startup.json'):
  row=json.loads(path.read_text());pid=row.get('pid');proc=Path('/proc')/str(pid)
  if not proc.exists():continue
  try:actual=[x.decode() for x in (proc/'cmdline').read_bytes().rstrip(b'\0').split(b'\0')];cwd=proc.joinpath('cwd').resolve(strict=True)
  except (FileNotFoundError,ProcessLookupError):continue
  if actual==row.get('argv') and str(cwd)==str(Path(row['cwd']).resolve()):raise ValueError('healthy_owned_stage_child_still_running_wait_before_recovery:'+str(pid))
  # A reused PID is not owned and must not be signaled or adopted.


def preflight(options,run):
 p=Path(options['parent_status']);parent=json.loads(p.read_text());cp=Path(parent['checkpoint'])
 if parent.get('checkpoint_verified') is not True or not (parent.get('checkpoint_saved') is True or parent.get('status')=='checkpoint_saved') or not (cp/'params').is_dir() or not (cp/'train_state').is_dir():raise ValueError('verified_parent_checkpoint_required')
 free=shutil.disk_usage(run).free
 if free<100*1024**3:raise ValueError('insufficient_project_disk_for_verified_recipe')
 environments=[]
 for key in ('sim_python','vla_python'):
  result=json.loads(subprocess.check_output([options[key],'-c','import sys,json;print(json.dumps({"prefix":sys.prefix,"executable":sys.executable}))'],text=True))
  if Path(result['prefix']).name=='base' or 'envs' not in Path(result['prefix']).parts:raise ValueError('non_base_conda_required')
  environments.append(result)
 env=dict(os.environ,CUDA_VISIBLE_DEVICES='',JAX_PLATFORMS='cpu')
 identity=json.loads(subprocess.check_output([options['vla_python'],str(Path(options['release'])/'scripts/serve_pi05_airport.py'),'--training-status',str(p),'--identity-only'],env=env,text=True,timeout=240))
 return dict(verified=True,actual_verified_parent_checkpoint_id=identity['checkpoint_id'],parent_status_sha256=file_sha(p),parent_checkpoint=str(cp),free_disk_bytes=free,environments=environments,optimizer_policy='new_optimizer_weights_only_parent',oom_policy='same_verified_configuration_only_no_silent_batch_or_data_change')


def milestone_proof(path,spec,options):
 p=Path(path);m=json.loads(p.read_text());updates=m.get('actual_completed_updates')
 if m.get('schema')!='airport_pi05_training_milestone/1' or m.get('checkpoint_verified') is not True or type(updates) is not int or m.get('checkpoint_step')!=updates-1 or any(m.get('spec',{}).get(k)!=v for k,v in spec.items()):raise ValueError('actual_saved_milestone_contract_required')
 identity=json.loads(subprocess.check_output([options['vla_python'],str(Path(options['release'])/'scripts/serve_pi05_airport.py'),'--training-status',str(p),'--identity-only'],env=dict(os.environ,CUDA_VISIBLE_DEVICES='',JAX_PLATFORMS='cpu'),text=True,timeout=240))
 return {'verified':True,'milestone_sha256':file_sha(p),'actual_checkpoint_id':identity['checkpoint_id'],'actual_completed_updates':updates,'model_restored':False,'identity_only_not_model_inference':True}


def import_native_stage(run,name,old_folder,old_exit,source):
 run=Path(run);old=Path(old_folder);exit_path=Path(old_exit);receipt=json.loads(exit_path.read_text());argv=receipt.get('argv',[])
 if receipt.get('returncode')!=0 or receipt.get('trainer_exited') is not True or '--output' not in argv or Path(argv[argv.index('--output')+1]).resolve()!=old.resolve():raise ValueError('actual_old_native_successful_exit_and_output_binding_required')
 evidence=native_proof(old,source);proof=dict(schema='airport_verified_native_stage_import/1',old_folder=str(old.resolve()),old_exit_receipt=str(exit_path.resolve()),old_exit_receipt_sha256=file_sha(exit_path),old_manifest_sha256=file_sha(old/'manifest.json'),source_trace_sha256=source['trace_sha256'],source_sha256={key:source[field] for key,field in [('trace','trace_sha256'),('events','events_sha256'),('scene_xml','scene_xml_sha256'),('scene_json','scene_json_sha256'),('result','result_sha256')]},camera_videos=evidence['videos'],new_process_spawned=False,old_exit_not_copied_as_new_exit=True)
 path=run/'stage_imports'/(name+'.json')
 if path.exists() and json.loads(path.read_text())!=proof:raise ValueError('native_stage_import_binding_changed')
 write_atomic(path,proof);return proof
