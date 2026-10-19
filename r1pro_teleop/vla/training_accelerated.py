"""Exact-optimizer milestone JAX training with sequentially prebuilt CPU cache."""
from pathlib import Path
import dataclasses,functools,json,os,time
import numpy as np
from .training_cache import CachedDataset,file_sha,validate_cache_spec
from concurrent.futures import ThreadPoolExecutor
from collections import deque

MILESTONES=(10,100,1000,10000,100000)

def milestone_target(completed,budget=100000):
 if type(completed) is not int or not 0<=completed<=budget:raise ValueError('invalid_completed_updates')
 return next((step for step in MILESTONES if completed<step<=budget),budget)

class CacheLoader:
 def __init__(self,data_config):self._config=data_config
 def data_config(self):return self._config

def batch_at(dataset,schedule,step):
 import jax
 samples=[dataset[int(index)] for index in schedule[step]]
 return jax.tree.map(lambda *values:np.stack(values),*samples)


def preserve_checkpoint(step):
 return step+1 in MILESTONES

class PrefetchedCacheBatches:
 def __init__(self,dataset,schedule,start,end,*,depth=2,producer=batch_at):
  if depth<1:raise ValueError('prefetch_depth_must_be_positive')
  self.pool=ThreadPoolExecutor(max_workers=1);self.pending={};self.next_step=start;self.end=end;self.dataset=dataset;self.schedule=schedule;self.producer=producer;self.depth=depth
  self._fill()
 def _fill(self):
  while len(self.pending)<self.depth and self.next_step<self.end:
   step=self.next_step;self.pending[step]=self.pool.submit(self.producer,self.dataset,self.schedule,step);self.next_step+=1
 def get(self,step):
  if step not in self.pending:raise ValueError('prefetch_request_outside_ordered_schedule')
  value=self.pending.pop(step).result();self._fill();return value
 def close(self):self.pool.shutdown(wait=True,cancel_futures=True)

def project_checkpoint_manager(config,official_checkpoints,*,resume):
 """Public Orbax retention: all evaluation points, plus latest two periodic saves."""
 from etils import epath
 directory=epath.Path(config.checkpoint_dir).resolve()
 if directory.exists() and not resume:raise FileExistsError('new_training_checkpoint_directory_already_exists')
 if not directory.exists() and resume:raise ValueError('cannot_resume_missing_own_checkpoint_directory')
 directory.mkdir(parents=True,exist_ok=True);ocp=official_checkpoints.ocp
 manager=ocp.CheckpointManager(directory,item_handlers={'assets':official_checkpoints.CallbackHandler(),'train_state':ocp.PyTreeCheckpointHandler(),'params':ocp.PyTreeCheckpointHandler()},options=ocp.CheckpointManagerOptions(max_to_keep=2,should_keep_fn=preserve_checkpoint,create=False,async_options=ocp.AsyncOptions(timeout_secs=7200)))
 if resume and not manager.all_steps():manager.close();raise ValueError('no_saved_optimizer_checkpoint_to_resume')
 return manager,resume


class DurationTelemetry:
 def __init__(self):
  self.recent=deque(maxlen=32);self.count=0;self.sum=0.;self.first=None;self.warm_min=None;self.warm_max=None
 def update(self,duration):
  duration=float(duration)
  if not np.isfinite(duration) or duration<0:raise ValueError('invalid_actual_update_duration')
  self.count+=1;self.sum+=duration;self.recent.append(duration)
  if self.first is None:self.first=duration
  else:
   self.warm_min=duration if self.warm_min is None else min(self.warm_min,duration)
   self.warm_max=duration if self.warm_max is None else max(self.warm_max,duration)
  return self.summary()
 def summary(self):
  return dict(update_count=self.count,first_update_including_compile_seconds=self.first,last32_update_seconds=list(self.recent),warm_count=max(0,self.count-1),warm_mean_seconds=None if self.count<2 else (self.sum-self.first)/(self.count-1),warm_min_seconds=self.warm_min,warm_max_seconds=self.warm_max)

def vision_parameter_filter(path,value):
 return tuple(str(key) for key in path[:2])==('PaliGemma','img')


def train_to_milestone(spec,*,parent_status,stop_after,resume=False,diagnostic_smoke=False):
 """Return only after official checkpoint manager finishes and can release GPUs."""
 import jax
 from .training import register_openpi_config,_load_script,project_jax_cache_dir
 from .training_preview import host_replicated_key,OFFICIAL_TRAIN_SHA256
 run=Path(spec.run_dir);cache_root=run/'data_cache';load_started=time.monotonic();cache=CachedDataset(cache_root);cache_load_seconds=time.monotonic()-load_started;validate_cache_spec(spec,cache.manifest)
 if not diagnostic_smoke and cache.manifest.get('production_ready') is not True:raise ValueError('diagnostic_cache_cannot_train_production_model')
 if not resume and any((run/'checkpoints').rglob('train_state')):raise ValueError('initialization_cannot_overwrite_previous_optimizer')
 if stop_after not in MILESTONES and not diagnostic_smoke:raise ValueError('unknown_evaluation_milestone')
 if not 0<stop_after<=spec.num_train_steps:raise ValueError('invalid_milestone_budget')
 config=register_openpi_config(spec)
 from openpi.training import checkpoints,sharding
 from openpi.models import model
 acceleration_path=run/'acceleration_spec.json'
 acceleration=json.loads(acceleration_path.read_text())
 if acceleration.get('schema')!='airport_pi05_acceleration/1' or type(acceleration.get('freeze_visual_encoder')) is not bool:raise ValueError('explicit_acceleration_strategy_required')
 if acceleration.get('attention_backend','legacy_xla')!='legacy_xla':raise ValueError('unverified_attention_backend_cannot_train')
 if acceleration['freeze_visual_encoder']:
  from flax import nnx
  config=dataclasses.replace(config,freeze_filter=nnx.Any(config.freeze_filter,vision_parameter_filter))
 config=dataclasses.replace(config,resume=resume,keep_period=1)
 script=_load_script(spec.openpi_root,'train.py')
 if file_sha(Path(spec.openpi_root)/'scripts/train.py')!=OFFICIAL_TRAIN_SHA256:raise ValueError('official_train_source_identity_changed')
 if jax.device_count()!=2 or spec.fsdp_devices!=1:raise ValueError('two_device_dp_mesh_required')
 # Parent validation includes actual content identity via the serving verifier;
 # parent is a weights-only initializer, never an optimizer resume source.
 import importlib.util
 server_path=Path(__file__).resolve().parents[2]/'scripts/serve_pi05_airport.py'
 module_spec=importlib.util.spec_from_file_location('airport_verify_initializer',server_path)
 verifier=importlib.util.module_from_spec(module_spec);module_spec.loader.exec_module(verifier)
 verified=verifier.verify_training_checkpoint(parent_status)
 parent_identity=verified[2]
 parent_json=json.loads(Path(parent_status).read_text())
 if Path(spec.base_params).resolve()!=(Path(parent_json['checkpoint'])/'params').resolve():raise ValueError('initializer_params_do_not_match_verified_parent')
 if parent_json['spec'].get('lora')!=spec.lora or parent_json['spec'].get('action_horizon')!=spec.action_horizon:raise ValueError('initializer_model_semantics_changed')
 schedule=np.load(cache_root/'sample_schedule.npy',mmap_mode='r')
 if file_sha(cache_root/'sample_schedule.npy')!=cache.manifest['sample_schedule_sha256'] or schedule.shape!=(spec.num_train_steps,spec.batch_size):raise ValueError('exact_resume_schedule_changed')
 manifest_path=Path(spec.dataset_root)/'airport_training_manifest.json'
 if file_sha(cache.manifest['normalization_path'])!=cache.manifest['normalization_sha256']:raise ValueError('cache_normalization_changed')
 if file_sha(manifest_path)!=cache.manifest['dataset_training_manifest_sha256']:raise ValueError('cached_dataset_manifest_changed')
 status=dict(schema='airport_pi05_training_diagnostic/1' if diagnostic_smoke else 'airport_pi05_training_milestone/1',method='bc_lora',status='initializing',model='pi05',fps=20,action_semantics='absolute_mobile19',source='simulation/program_generated',prompt_mode=spec.prompt_mode,spec=dataclasses.asdict(spec),planned_total_steps=spec.num_train_steps,training_steps=0,actual_completed_updates=0,checkpoint_verified=False,cache_manifest=str(cache_root/'cache_manifest.json'),cache_manifest_sha256=file_sha(cache_root/'cache_manifest.json'),dataset_training_manifest_sha256=file_sha(manifest_path),dataset_source_manifest_sha256=cache.manifest['dataset_source_manifest_sha256'],parent_initializer_status=str(Path(parent_status).resolve()),parent_initializer_status_sha256=file_sha(parent_status),parent_initializer_checkpoint_id=parent_identity['checkpoint_id'],parent_prompt_mode=parent_json.get('prompt_mode',parent_json['spec'].get('prompt_mode','legacy')),initialization='verified_parent_weights_only_new_optimizer' if not resume else 'same_run_exact_optimizer_and_step_resume',rng_verification_receipts=[],precision=dict(frozen_weights='bfloat16',trainable_lora_optimizer='float32',model_compute='bfloat16',cache_rgb='uint8',cache_numeric='float32'),model_math='official_openpi_train_step',sampling=cache.manifest['sampling'],prefetch_depth=2,checkpoint_retention='all_evaluation_milestones_plus_latest_two_periodic',acceleration_spec=str(acceleration_path),acceleration_spec_sha256=file_sha(acceleration_path),freeze_visual_encoder=acceleration['freeze_visual_encoder'])
 if spec.prompt_mode=='single_tray_action3_v1':status.update(base_mode='fixed_front',base_actuated=False,model_action_mask=[True]*16+[False]*3,evaluation_status='pending_new_single_tray_learned_runtime_validation')
 if spec.prompt_mode=='three_table_single_tray_action3_v1':status.update(task_profile=spec.prompt_mode,task_rule_revision=cache.manifest['task_rule_revision'],final_orientation_definition=cache.manifest['final_orientation_definition'],base_mode='planar_mobile_table_front',base_actuated=True,model_action_mask=[True]*19,route_goal_observation_policy=cache.manifest['route_goal_observation_policy'],evaluation_status='pending_new_three_table_single_tray_runtime_validation')
 status_path=run/'training_status.json'
 def persist():
  tmp=status_path.with_suffix('.json.tmp');tmp.write_text(json.dumps(status,indent=2,default=str));tmp.replace(status_path)
 persist()
 try:
  mesh=sharding.make_mesh(1);replicated=jax.sharding.NamedSharding(mesh,jax.sharding.PartitionSpec());data_sharding=jax.sharding.NamedSharding(mesh,jax.sharding.PartitionSpec(sharding.DATA_AXIS))
  train_rng,init_rng=jax.random.split(jax.random.key(spec.seed))
  train_rng=host_replicated_key(jax,train_rng,replicated,status['rng_verification_receipts'],persist)
  init_rng=host_replicated_key(jax,init_rng,replicated,status['rng_verification_receipts'],persist)
  cache_dir=project_jax_cache_dir(spec);cache_dir.mkdir(parents=True,exist_ok=True);jax.config.update('jax_compilation_cache_dir',str(cache_dir))
  manager,resuming=project_checkpoint_manager(config,checkpoints,resume=resume)
  data_config=config.data.create(config.assets_dirs,config.model);loader=CacheLoader(data_config)
  state,state_sharding=script.init_train_state(config,init_rng,mesh,resume=resuming)
  if resuming:state=checkpoints.restore_state(manager,state,loader)
  jax.block_until_ready(state);start=int(state.step)
  if start>stop_after:raise ValueError('saved_optimizer_state_ahead_of_requested_milestone')
  if start==stop_after:
   if not resume:raise ValueError('completed_checkpoint_requires_explicit_optimizer_restore')
   checkpoint=config.checkpoint_dir/str(stop_after-1);norm=checkpoint/'assets'/spec.dataset_repo_id/'norm_stats.json';milestone=run/f'milestone_{stop_after:06d}.json'
   if not (checkpoint/'params').is_dir() or not (checkpoint/'train_state').is_dir() or not norm.is_file():raise ValueError('restored_completed_checkpoint_not_fully_saved')
   receipt=dict(schema='airport_optimizer_checkpoint_exit_finalization/1',pid=os.getpid(),restored_optimizer_step=start,actual_new_gradient_updates=0,checkpoint=str(checkpoint),checkpoint_step=start-1,optimizer_state_restore_verified=True,original_exit_code_not_fabricated=True,actual_devices=[str(device) for device in jax.devices()],cache_manifest_sha256=file_sha(cache_root/'cache_manifest.json'),norm_sha256=file_sha(norm))
   if milestone.exists():
    original=json.loads(milestone.read_text())
    if original.get('actual_completed_updates')!=start or original.get('checkpoint_step')!=start-1 or any(original.get('spec',{}).get(k)!=v for k,v in dataclasses.asdict(spec).items()):raise ValueError('immutable_completed_milestone_changed')
    receipt['original_milestone_sha256']=file_sha(milestone);status.update(original)
   else:
    status.update(status='diagnostic_checkpoint' if diagnostic_smoke else 'milestone_checkpoint',actual_completed_updates=start,training_steps=start,checkpoint=str(checkpoint),checkpoint_step=start-1,checkpoint_saved=True,checkpoint_verified=True,normalization=str(norm),norm_sha256=file_sha(norm),optimizer_state_checkpoint=True,exact_resume_schedule=True,training_complete=start==spec.num_train_steps,reconstructed_from_actual_optimizer_checkpoint=True)
    milestone.write_text(json.dumps(status,indent=2,default=str))
   status['checkpoint_exit_finalization']=receipt;persist();(run/f'checkpoint_exit_finalization_{start:06d}_{os.getpid()}.json').write_text(json.dumps(receipt,indent=2));manager.close();return status
  if resume and start not in MILESTONES and start%1000!=0 and not diagnostic_smoke:raise ValueError('resume_requires_saved_milestone_or_periodic_point')
  def adapter_digest(current):
   import hashlib
   sha=hashlib.sha256()
   for leaf in jax.tree.leaves(current.params.filter(config.trainable_filter)):
    array=np.asarray(jax.device_get(leaf));sha.update(array.tobytes())
   return sha.hexdigest()
  before_adapter_sha=adapter_digest(state)
  def vision_digest(current):
   import hashlib
   sha=hashlib.sha256()
   for leaf in jax.tree.leaves(current.params.filter(vision_parameter_filter)):sha.update(np.asarray(jax.device_get(leaf)).tobytes())
   return sha.hexdigest()
  vision_before=vision_digest(state) if acceleration['freeze_visual_encoder'] else None
  dtype_inventory={}
  for leaf in jax.tree.leaves(state.params):
   dtype_inventory[str(leaf.dtype)]=dtype_inventory.get(str(leaf.dtype),0)+int(np.prod(leaf.shape))
  status['actual_parameter_dtype_element_counts']=dtype_inventory
  status['actual_trainable_dtype_element_counts']={}
  for leaf in jax.tree.leaves(state.params.filter(config.trainable_filter)):
   counts=status['actual_trainable_dtype_element_counts'];counts[str(leaf.dtype)]=counts.get(str(leaf.dtype),0)+int(np.prod(leaf.shape))
  vision_elements=sum(int(np.prod(leaf.shape)) for leaf in jax.tree.leaves(state.params.filter(vision_parameter_filter)))
  status['actual_vision_parameter_elements']=vision_elements
  if acceleration['freeze_visual_encoder'] and vision_elements!=414803696:raise ValueError('visual_freeze_scope_does_not_match_verified_architecture')
  update=jax.jit(functools.partial(script.train_step,config),in_shardings=(replicated,state_sharding,data_sharding),out_shardings=(state_sharding,replicated),donate_argnums=(1,))
  status.update(status='training',actual_completed_updates=start,training_steps=start,actual_devices=[str(device) for device in jax.devices()],pid=os.getpid(),cache_hash_and_load_seconds=cache_load_seconds);persist()
  started=time.monotonic();telemetry=DurationTelemetry();prefetch=PrefetchedCacheBatches(cache,schedule,start,stop_after)
  for step in range(start,stop_after):
   update_started=time.monotonic();host=prefetch.get(step);batch=(model.Observation.from_dict(host),host['actions']);batch=jax.device_put(batch,data_sharding)
   with sharding.set_mesh(mesh):state,info=update(train_rng,state,batch)
   metrics={key:float(value) for key,value in jax.device_get(info).items()}
   if not all(np.isfinite(value) for value in metrics.values()):raise ValueError('nonfinite_actual_train_metrics')
   duration=time.monotonic()-update_started;duration_summary=telemetry.update(duration)
   status.update(actual_completed_updates=step+1,training_steps=step+1,last_metrics=metrics,elapsed_training_seconds=time.monotonic()-started,seconds_per_update=(time.monotonic()-started)/(step+1-start),actual_update_seconds=duration,duration_telemetry=duration_summary);persist()
   if (step+1)%1000==0 and step+1<stop_after:
    free_bytes=__import__('shutil').disk_usage(run).free
    if free_bytes<32*1024**3:raise RuntimeError('insufficient_disk_for_durable_checkpoint')
    checkpoints.save_state(manager,state,loader,step);manager.wait_until_finished()
    snapshot=dict(status,status='periodic_checkpoint',checkpoint=str(config.checkpoint_dir/str(step)),checkpoint_step=step,checkpoint_saved=True,checkpoint_verified=True,optimizer_state_checkpoint=True,retention='all_evaluation_milestones_plus_latest_two_periodic')
    (run/f'periodic_{step+1:06d}.json').write_text(json.dumps(snapshot,indent=2,default=str))
   print(json.dumps(dict(step=step,completed_updates=step+1,metrics=metrics,seconds_per_update=status['seconds_per_update'])),flush=True)
  prefetch.close()
  after_adapter_sha=adapter_digest(state)
  if before_adapter_sha==after_adapter_sha:raise ValueError('real_trainable_adapter_parameters_did_not_update')
  if acceleration['freeze_visual_encoder']:
   vision_after=vision_digest(state)
   if vision_before!=vision_after:raise ValueError('frozen_visual_parameters_changed')
   status['frozen_vision_parameter_sha256']=dict(before=vision_before,after=vision_after,unchanged=True)
  status['actual_trainable_parameter_change']=dict(before_sha256=before_adapter_sha,after_sha256=after_adapter_sha,changed=True)
  checkpoints.save_state(manager,state,loader,stop_after-1);manager.wait_until_finished()
  checkpoint=config.checkpoint_dir/str(stop_after-1)
  if not (checkpoint/'params').is_dir() or not (checkpoint/'train_state').is_dir():raise ValueError('official_checkpoint_not_fully_saved')
  norm=checkpoint/'assets'/spec.dataset_repo_id/'norm_stats.json'
  status.update(status='diagnostic_checkpoint' if diagnostic_smoke else 'milestone_checkpoint',checkpoint=str(checkpoint),checkpoint_step=stop_after-1,checkpoint_saved=True,checkpoint_verified=True,normalization=str(norm),norm_sha256=file_sha(norm),optimizer_state_checkpoint=True,exact_resume_schedule=True,training_complete=stop_after==spec.num_train_steps)
  persist();(run/f'milestone_{stop_after:06d}.json').write_text(json.dumps(status,indent=2,default=str));manager.close()
  return status
 except BaseException as error:
  if 'prefetch' in locals():prefetch.close()
  if 'manager' in locals():manager.close()
  status.update(status='failed',error=repr(error),checkpoint_verified=False);persist();raise
