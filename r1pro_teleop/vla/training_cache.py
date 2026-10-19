"""Project-owned sequential CPU cache of official transformed training samples.

Keeps raw collections unchanged. RGB stays uint8; numeric model inputs use the
same FP32 projection as official training. No model weights are restored here.
"""
from pathlib import Path
import hashlib,json,itertools,os,tempfile
import numpy as np

SCHEMA='airport_pi05_training_cache/1'

def file_sha(path):
 h=hashlib.sha256()
 with Path(path).open('rb') as stream:
  while chunk:=stream.read(8*1024*1024):h.update(chunk)
 return h.hexdigest()

def flatten(tree,prefix=(),*,model_float32=False):
 result={}
 for key,value in tree.items():
  if not isinstance(key,str) or '/' in key:raise ValueError('unsupported_cache_tree_key')
  path=prefix+(key,)
  if isinstance(value,dict):result.update(flatten(value,path,model_float32=model_float32))
  else:
   array=np.asarray(value)
   if model_float32 and array.dtype.kind=='f':array=array.astype(np.float32)
   if array.dtype.kind not in 'bifu':raise ValueError('non_numeric_cache_leaf')
   result[path]=array
 return result

def unflatten(leaves):
 result={}
 for path,array in leaves.items():
  current=result
  for key in path[:-1]:current=current.setdefault(key,{})
  current[path[-1]]=array
 return result

def balanced_schedule(labels,batch_size,total_steps,seed,*,class_count=8):
 """Fixed eight-class distribution, with deterministic exact resume offsets."""
 labels=np.asarray(labels,dtype=np.int32)
 classes=np.unique(labels)
 if class_count not in (3,8):raise ValueError('unsupported_balanced_class_count')
 if not np.array_equal(classes,np.arange(class_count)):raise ValueError('all_eight_train_classes_required' if class_count==8 else 'all_three_train_classes_required')
 if type(batch_size) is not int or batch_size<1 or type(total_steps) is not int or total_steps<1:raise ValueError('invalid_schedule_budget')
 rng=np.random.default_rng(seed);members=[np.flatnonzero(labels==index) for index in range(class_count)]
 sampled_classes=rng.integers(0,class_count,size=(total_steps,batch_size))
 result=np.empty_like(sampled_classes,dtype=np.int64)
 for index,indices in enumerate(members):
  mask=sampled_classes==index;result[mask]=indices[rng.integers(0,len(indices),size=int(mask.sum()))]
 return result

class CachedDataset:
 def __init__(self,root,*,verify_hashes=True):
  self.root=Path(root);self.manifest=json.loads((self.root/'cache_manifest.json').read_text())
  if self.manifest.get('schema')!=SCHEMA or self.manifest.get('status')!='complete' or self.manifest.get('split')!='train':raise ValueError('training_cache_not_complete_train')
  self.leaves={}
  for leaf in self.manifest['leaves']:
   path=self.root/leaf['path']
   if verify_hashes and file_sha(path)!=leaf['sha256']:raise ValueError('training_cache_resource_changed')
   array=np.load(path,mmap_mode='r',allow_pickle=False)
   if list(array.shape)!=leaf['shape'] or str(array.dtype)!=leaf['dtype']:raise ValueError('training_cache_shape_or_dtype_changed')
   self.leaves[tuple(leaf['keys'])]=array
 def __len__(self):return self.manifest['frames']
 def __getitem__(self,index):
  if not 0<=index<len(self):raise IndexError(index)
  return unflatten({keys:np.array(array[index],copy=True) for keys,array in self.leaves.items()})


def validate_cache_source(spec,manifest,*,diagnostic_fixture=False):
 if manifest.get('split')!='train' or any(e.get('split')!='train' for e in manifest.get('episodes',[])):raise ValueError('cache_cannot_include_holdout')
 if manifest.get('repo_id')!=spec.dataset_repo_id:raise ValueError('cache_source_repo_changed')
 if manifest.get('prompt_mode')!=spec.prompt_mode or spec.prompt_mode not in ('task_complete_action8_v1','single_tray_action3_v1','three_table_single_tray_action3_v1'):raise ValueError('cache_language_mode_changed')
 if not manifest.get('all_parquet_values_verified',{}).get('verified'):raise ValueError('unverified_parquet_cache_source')
 if file_sha(manifest['source_manifest'])!=manifest['source_manifest_sha256']:raise ValueError('cache_source_manifest_changed')
 if spec.prompt_mode in ('single_tray_action3_v1','three_table_single_tray_action3_v1'):
  from .data_single_tray import ACTION_VOCABULARY
  if spec.prompt_mode=='single_tray_action3_v1':
   if manifest.get('base_mode')!='fixed_front' or manifest.get('base_actuated') is not False or manifest.get('model_action_mask')!=[True]*16+[False]*3:raise ValueError('single_tray_fixed_base_mask_required')
  else:
   validate_three_table_metadata(manifest)
   if manifest.get('task_profile')!=spec.prompt_mode or any(e.get('parent_split')!='train' or not e.get('parent_scene_id') for e in manifest.get('episodes',[])):raise ValueError('canonical_parent_train_split_required')
   if manifest.get('new_task_source_guard_audit',{}).get('verified') is not True:raise ValueError('actual_three_table_complete_source_guards_required')
   if not diagnostic_fixture:
    from .data_three_table_single_tray import source_validate
    sources={}
    for line in Path(manifest['source_manifest']).read_text().splitlines():
     if not line.strip():continue
     row=json.loads(line);source=row['source'];key=source['scene_id']
     if key not in sources:source_validate(source);sources[key]=source
    if set(sources)!={e['scene_id'] for e in manifest.get('episodes',[])}:raise ValueError('actual_three_table_source_population_changed')
  vocabulary=manifest.get('action_vocabulary',[])
  expected=[dict(row,task_index=i) for i,row in enumerate(ACTION_VOCABULARY)]
  if vocabulary!=expected:raise ValueError('single_tray_exact_three_tasks_required')
  ids=manifest.get('complete_expected_scene_ids',[]);actual={e['scene_id'] for e in manifest.get('episodes',[])}
  if not diagnostic_fixture and (manifest.get('dataset_ready') is not True or not ids or len(ids)!=len(set(ids)) or set(ids)!=actual):raise ValueError('full_declared_single_tray_train_dataset_required')
 else:
  if not diagnostic_fixture and (manifest.get('dataset_ready') is not True or len(manifest.get('complete_expected_scene_ids',[]))!=149):raise ValueError('full_149_train_dataset_required')

def validate_cache_spec(spec,manifest):
 for key,attribute in [('prompt_mode','prompt_mode'),('action_horizon','action_horizon'),('batch_size','batch_size'),('total_steps','num_train_steps'),('seed','seed'),('repo_id','dataset_repo_id')]:
  if manifest.get(key)!=getattr(spec,attribute):raise ValueError('cache_spec_changed:'+key)
 if spec.prompt_mode=='single_tray_action3_v1' and (manifest.get('base_mode')!='fixed_front' or manifest.get('base_actuated') is not False or manifest.get('model_action_mask')!=[True]*16+[False]*3):raise ValueError('cached_fixed_base_semantics_changed')
 if spec.prompt_mode=='three_table_single_tray_action3_v1':validate_three_table_metadata(manifest)
 if Path(manifest['dataset_root']).resolve()!=Path(spec.dataset_root).resolve():raise ValueError('cache_dataset_root_changed')

def validate_three_table_metadata(manifest):
 from .data_three_table_single_tray import RULE_REVISION,FINAL_ORIENTATION_DEFINITION
 if manifest.get('task_rule_revision')!=RULE_REVISION or manifest.get('final_orientation_definition')!=FINAL_ORIENTATION_DEFINITION:raise ValueError('fresh_three_table_forward_axis_metadata_required')
 mask=manifest.get('model_action_mask')
 if manifest.get('base_mode')!='planar_mobile_table_front' or manifest.get('base_actuated') is not True or not isinstance(mask,list) or len(mask)!=19 or any(type(x) is not bool or not x for x in mask):raise ValueError('three_table_mobile19_all_actuated_required')
 if manifest.get('route_goal_observation_policy')!='fixed_registered_rear_to_front_left_route':raise ValueError('observable_fixed_registered_route_required')

def audit_cache_official(source,repo_id,episodes,transform,leaves,schedule):
 from lerobot.common.datasets.lerobot_dataset import LeRobotDataset
 loaded=LeRobotDataset(repo_id,root=source,video_backend='pyav',delta_timestamps={'action':[i/20 for i in range(20)]})
 checks=[];offset=0
 for episode in episodes:
  for local_index in sorted(set((0,episode['frames']//2,episode['frames']-1))):
   index=offset+local_index;raw=loaded[index];raw['prompt']=episode['language_prompt'];expected=flatten(transform(raw),model_float32=True)
   if set(expected)!=set(leaves):raise ValueError('official_cache_tree_mismatch')
   for keys,array in expected.items():
    if array.dtype!=leaves[keys].dtype or not np.array_equal(array,leaves[keys][index]):raise ValueError('official_transformed_cache_value_changed:'+str(keys))
   mask=np.arange(local_index,local_index+20)>=episode['frames']
   if not np.array_equal(np.asarray(raw['action_is_pad']),mask):raise ValueError('official_cache_terminal_padding_changed')
   checks.append(dict(episode_index=episode['episode_index'],source_frame=episode['source_start_frame']+local_index,all_official_transformed_leaves_exact=True))
  offset+=episode['frames']
 import time
 indices=schedule[0];prompts={};offset=0
 for episode in episodes:
  for index in indices:
   if offset<=index<offset+episode['frames']:prompts[int(index)]=episode['language_prompt']
  offset+=episode['frames']
 start=time.monotonic()
 for index in indices:
  raw=loaded[int(index)];raw['prompt']=prompts[int(index)];transform(raw)
 official_seconds=time.monotonic()-start
 start=time.monotonic()
 for index in indices:unflatten({keys:np.array(array[int(index)],copy=True) for keys,array in leaves.items()})
 cache_seconds=time.monotonic()-start
 return dict(verified=True,samples=checks,official_float_RGB_rounding_exact=True,state_conditioned_tokenization_exact=True,float_comparison='FP32_model_input_same_as_JAX_x64_disabled_transfer',action_H20_and_terminal_mask_exact=True,same_batch_indices=[int(i) for i in indices],benchmark=dict(official_random_seek_transform_seconds=official_seconds,cache_memmap_seconds=cache_seconds,batch_size=len(indices),warm_compile_included=False,model_math_measured=False))

def build_cache(spec,destination,*,diagnostic_fixture=False):
 """One sequential decode per whole action/camera; official transforms unchanged."""
 import pyarrow.parquet as pq
 from .training import register_openpi_config
 from .data_task_lerobot import decoded_rgb,MODEL_CAMERAS
 spec.validate();destination=Path(destination)
 if destination.exists():raise ValueError('refuse_existing_training_cache')
 source=Path(spec.dataset_root);training_path=source/'airport_training_manifest.json'
 manifest=json.loads(training_path.read_text())
 validate_cache_source(spec,manifest,diagnostic_fixture=diagnostic_fixture)
 config=register_openpi_config(spec)
 from openpi.training import data_loader
 data_config=config.data.create(config.assets_dirs,config.model)
 norm_path=config.assets_dirs/spec.dataset_repo_id/'norm_stats.json'
 norm_sha256=file_sha(norm_path)
 class Empty:
  def __len__(self):return 0
  def __getitem__(self,index):raise IndexError(index)
 transform=data_loader.transform_dataset(Empty(),data_config)._transform
 info=json.loads((source/'meta/info.json').read_text());episodes=manifest['episodes'];total=sum(e['frames'] for e in episodes)
 destination.mkdir(parents=True);leaves={};descriptors=[];offset=0;task_indices=np.empty(total,dtype=np.int32)
 def persist(stage,**extra):
  record=dict(schema=SCHEMA,status=stage,split='train',frames=total,written_frames=offset,model_restored=False,training_started=False,**extra)
  tmp=destination/'status.json.tmp';tmp.write_text(json.dumps(record,indent=2));tmp.replace(destination/'status.json')
 persist('building')
 for episode in episodes:
  n=episode['frames'];index=episode['episode_index'];chunk=index//info.get('chunks_size',1000)
  table=pq.read_table(source/info['data_path'].format(episode_chunk=chunk,episode_index=index))
  state=np.asarray(table['observation.state'].to_pylist(),dtype=np.float32);actions=np.asarray(table['action'].to_pylist(),dtype=np.float32)
  if spec.prompt_mode=='single_tray_action3_v1' and (np.any(state[:,16:]!=0) or np.any(actions[:,16:]!=0)):raise ValueError('fixed_base_cache_tail_nonzero')
  videos={camera:iter(decoded_rgb(source/info['video_path'].format(episode_chunk=chunk,episode_index=index,video_key='observation.images.'+camera))) for camera in MODEL_CAMERAS}
  for frame in range(n):
   sample={'observation.state':state[frame],'action':actions[np.minimum(np.arange(frame,frame+spec.action_horizon),n-1)],'prompt':episode['language_prompt']}
   for camera,iterator in videos.items():
    image=next(iterator,None)
    if image is None:raise ValueError('cache_training_video_missing_frame')
    sample['observation.images.'+camera]=image.astype(np.float32)/255
   transformed=flatten(transform(sample),model_float32=True)
   if not leaves:
    for number,(keys,array) in enumerate(sorted(transformed.items())):
     path=destination/f'leaf_{number:02d}.npy'
     leaves[keys]=np.lib.format.open_memmap(path,mode='w+',dtype=array.dtype,shape=(total,*array.shape))
     descriptors.append(dict(keys=list(keys),path=path.name,dtype=str(array.dtype),shape=[total,*array.shape]))
   if set(transformed)!=set(leaves):raise ValueError('official_transform_cache_structure_changed')
   for keys,array in transformed.items():
    if array.shape!=leaves[keys].shape[1:] or array.dtype!=leaves[keys].dtype:raise ValueError('official_transform_cache_leaf_changed')
    leaves[keys][offset]=array
   task_indices[offset]=episode['task_index'];offset+=1
  if any(next(iterator,None) is not None for iterator in videos.values()):raise ValueError('cache_training_video_has_extra_frames')
  persist('building',completed_episode=index)
 for array in leaves.values():array.flush()
 np.save(destination/'task_indices.npy',task_indices,allow_pickle=False)
 schedule=(np.random.default_rng(spec.seed).integers(0,total,size=(spec.num_train_steps,spec.batch_size),dtype=np.int64) if diagnostic_fixture else balanced_schedule(task_indices,spec.batch_size,spec.num_train_steps,spec.seed,class_count=3 if spec.prompt_mode in ('single_tray_action3_v1','three_table_single_tray_action3_v1') else 8))
 np.save(destination/'sample_schedule.npy',schedule,allow_pickle=False)
 audit=audit_cache_official(source,spec.dataset_repo_id,episodes,transform,leaves,schedule)
 for descriptor in descriptors:descriptor['sha256']=file_sha(destination/descriptor['path'])
 record=dict(schema=SCHEMA,status='complete',split='train',repo_id=spec.dataset_repo_id,official_transformed_sample_audit=audit,frames=total,episodes=len(episodes),scene_count=len({e['scene_id'] for e in episodes}),production_ready=not diagnostic_fixture,prompt_mode=spec.prompt_mode,dataset_root=str(source),dataset_training_manifest_sha256=file_sha(training_path),dataset_source_manifest_sha256=manifest['source_manifest_sha256'],normalization_path=str(norm_path),normalization_sha256=norm_sha256,action_horizon=spec.action_horizon,batch_size=spec.batch_size,total_steps=spec.num_train_steps,seed=spec.seed,leaves=descriptors,task_indices_sha256=file_sha(destination/'task_indices.npy'),sample_schedule_sha256=file_sha(destination/'sample_schedule.npy'),sampling='diagnostic_fixture_uniform_only' if diagnostic_fixture else ('uniform_three_classes_then_uniform_real_frames' if spec.prompt_mode in ('single_tray_action3_v1','three_table_single_tray_action3_v1') else 'uniform_eight_classes_then_uniform_real_frames'),raw_source_unchanged=True,numeric_cache_precision='official_float32',rgb_cache_precision='uint8',transforms='official_repack_AirportInputs_Normalize_model_transforms',model_restored=False,training_started=False)
 if spec.prompt_mode=='single_tray_action3_v1':record.update(base_mode='fixed_front',base_actuated=False,model_action_mask=[True]*16+[False]*3)
 if spec.prompt_mode=='three_table_single_tray_action3_v1':record.update(task_rule_revision=manifest['task_rule_revision'],final_orientation_definition=manifest['final_orientation_definition'],base_mode='planar_mobile_table_front',base_actuated=True,model_action_mask=[True]*19,route_goal_observation_policy=manifest['route_goal_observation_policy'])
 tmp=destination/'cache_manifest.json.tmp';tmp.write_text(json.dumps(record,indent=2));tmp.replace(destination/'cache_manifest.json');persist('complete')
 return record


def normalization_input_binding(spec,manifest,info,directory,*,diagnostic_fixture=False):
    """Bind normalization to the exact train bytes and math-relevant options."""
    root=Path(spec.dataset_root).resolve();parquets=[]
    for episode in manifest['episodes']:
        index=episode['episode_index'];chunk=index//info.get('chunks_size',1000)
        path=(root/info['data_path'].format(episode_chunk=chunk,episode_index=index)).resolve()
        if not path.is_relative_to(root):raise ValueError('train_norm_parquet_outside_dataset')
        parquets.append(dict(episode_index=index,frames=episode['frames'],path=str(path),sha256=file_sha(path)))
    return dict(schema='airport_train_only_normalization_input/1',split='train',holdout_used=False,
        source='all_whole_action_numeric_rows',diagnostic_fixture=diagnostic_fixture,
        spec=dict(dataset_root=str(root),dataset_repo_id=spec.dataset_repo_id,prompt_mode=spec.prompt_mode,
            action_horizon=spec.action_horizon,normalization_policy=spec.normalization_policy),
        algorithm='official_RunningStats_FP32_state_actions_declared_horizon_terminal_clipped_pad',
        output=str((Path(directory)/'norm_stats.json').resolve()),
        train_manifest_sha256=file_sha(root/'airport_training_manifest.json'),
        source_manifest=str(Path(manifest['source_manifest']).resolve()),source_manifest_sha256=file_sha(manifest['source_manifest']),
        info_sha256=file_sha(root/'meta/info.json'),parquet_inventory=parquets)


def verify_train_normalization(directory,binding):
    directory=Path(directory);norm=directory/'norm_stats.json';proof=directory/'norm_provenance.json';checksum=directory/'norm_provenance.sha256'
    if not proof.is_file() or not checksum.is_file():raise ValueError('refuse_existing_uncertified_train_normalization')
    if file_sha(proof)!=checksum.read_text().strip():raise ValueError('train_norm_provenance_certificate_changed')
    record=json.loads(proof.read_text())
    if record.get('schema')!='airport_train_only_normalization_provenance/1' or record.get('verified') is not True or record.get('input_binding')!=binding:
        raise ValueError('train_norm_source_or_configuration_changed')
    if not norm.is_file() or file_sha(norm)!=record.get('normalization_sha256'):
        raise ValueError('train_norm_bytes_changed')
    return dict(path=str(norm),sha256=record['normalization_sha256'],split='train',source='all_whole_action_numeric_rows',
        holdout_used=False,provenance=str(proof),provenance_sha256=file_sha(proof),safely_reused=True)


def _write_norm_provenance(directory,binding):
    directory=Path(directory);proof=directory/'norm_provenance.json';checksum=directory/'norm_provenance.sha256'
    if proof.exists() or checksum.exists():raise ValueError('refuse_existing_train_norm_certificate')
    record=dict(schema='airport_train_only_normalization_provenance/1',verified=True,input_binding=binding,
        normalization_sha256=file_sha(directory/'norm_stats.json'),split='train',holdout_used=False,
        source='all_whole_action_numeric_rows',model_restored=False,training_started=False)
    temp=proof.with_suffix('.json.tmp');temp.write_text(json.dumps(record,indent=2));os.replace(temp,proof)
    temp=checksum.with_suffix('.sha256.tmp');temp.write_text(file_sha(proof)+'\n');os.replace(temp,checksum)


def compute_train_only_norm(spec,*,diagnostic_fixture=False):
    """Numeric whole-action rows only; no holdout or image decode in normalization."""
    import sys
    import pyarrow.parquet as pq
    sys.path.insert(0,str(Path(spec.openpi_root)/'src'))
    from openpi.shared import normalize
    from .training import build_openpi_config
    spec.validate();root=Path(spec.dataset_root);manifest=json.loads((root/'airport_training_manifest.json').read_text())
    if manifest.get('split')!='train' or not manifest.get('all_parquet_values_verified',{}).get('verified'):raise ValueError('only_verified_train_norm')
    validate_cache_source(spec,manifest,diagnostic_fixture=diagnostic_fixture)
    if not diagnostic_fixture and manifest.get('dataset_ready') is not True:raise ValueError('only_complete_train_norm')
    info=json.loads((root/'meta/info.json').read_text());config=build_openpi_config(spec);directory=config.assets_dirs/spec.dataset_repo_id
    binding=normalization_input_binding(spec,manifest,info,directory,diagnostic_fixture=diagnostic_fixture)
    if (directory/'norm_stats.json').exists():return verify_train_normalization(directory,binding)
    if (directory/'norm_provenance.json').exists() or (directory/'norm_provenance.sha256').exists():
        raise ValueError('train_norm_certificate_without_original_norm')
    stats={key:normalize.RunningStats() for key in ('state','actions')}
    for episode in manifest['episodes']:
        index=episode['episode_index'];chunk=index//info.get('chunks_size',1000)
        table=pq.read_table(root/info['data_path'].format(episode_chunk=chunk,episode_index=index))
        state=np.asarray(table['observation.state'].to_pylist(),dtype=np.float32)
        actions=np.asarray(table['action'].to_pylist(),dtype=np.float32)
        if spec.prompt_mode=='single_tray_action3_v1' and (not np.isfinite(state).all() or not np.isfinite(actions).all() or np.any(state[:,16:]!=0) or np.any(actions[:,16:]!=0)):raise ValueError('fixed_base_norm_tail_must_remain_zero')
        stats['state'].update(state)
        indices=np.minimum(np.arange(len(actions))[:,None]+np.arange(spec.action_horizon)[None,:],len(actions)-1)
        stats['actions'].update(actions[indices].reshape(-1,19))
    if normalization_input_binding(spec,manifest,info,directory,diagnostic_fixture=diagnostic_fixture)!=binding:
        raise ValueError('train_norm_source_changed_during_computation')
    if (directory/'norm_stats.json').exists():raise ValueError('refuse_existing_new_train_normalization')
    # Official serialization stays unchanged. Publish with an atomic no-clobber
    # hard link, so even concurrent preparers cannot overwrite existing stats.
    directory.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='norm_staging_',dir=directory) as staging:
        normalize.save(Path(staging),{key:value.get_statistics() for key,value in stats.items()})
        os.link(Path(staging)/'norm_stats.json',directory/'norm_stats.json')
    _write_norm_provenance(directory,binding)
    return dict(verify_train_normalization(directory,binding),safely_reused=False)
