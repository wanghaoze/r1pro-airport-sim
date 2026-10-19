"""Independent three-action records for the new single-tray simulation task.

This profile cannot reinterpret historical three-tray demonstrations. Actual
controller events, payload physics, measured endpoints and scene identities
must be supplied before an action becomes a supervised example.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import numpy as np

PROFILE='single_tray_action3_v1'
ACTION_VOCABULARY=(
 {'action_label':'pick_empty','base_skill':'pick_empty','language_prompt':'Pick up the tray'},
 {'action_label':'place_empty','base_skill':'place_empty','language_prompt':'Place the tray'},
 {'action_label':'push_loaded','base_skill':'push_loaded','language_prompt':'Flush tray to the left'},
)
LABELS=tuple(row['action_label'] for row in ACTION_VOCABULARY)


def canonical_hash(value):
 return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def validate_source_identity(source):
 if source.get('schema')!='airport_single_tray_source/1' or source.get('task_profile')!=PROFILE:
  raise ValueError('new_single_tray_source_required_not_legacy_relabeling')
 if source.get('source')!='simulation/program_generated' or source.get('tray_count')!=1:
  raise ValueError('single_tray_simulation_provenance_required')
 if source.get('split') not in ('train','val','test') or not source.get('scene_id'):
  raise ValueError('explicit_scene_split_required')
 for name in ('trace_sha256','scene_xml_sha256','scene_json_sha256','environment_manifest_sha256','controller_sha256'):
  value=source.get(name)
  if not isinstance(value,str) or len(value)!=64 or any(c not in '0123456789abcdef' for c in value):raise ValueError('source_identity_hash_required:'+name)
 if source.get('fps')!=20 or source.get('action_semantics')!='absolute_mobile19' or source.get('state_semantics')!='measured_joint16_plus_base_origin_offset3':
  raise ValueError('single_tray_mobile19_contract_changed')
 if 'allowed_long_rim_contract' in source:
  import h5py
  from r1pro_teleop.single_tray_lab.grasp_contract import validate_long_rim_contract
  validate_long_rim_contract(source['allowed_long_rim_contract'])
  with h5py.File(source['trace'],'r') as f:actual=json.loads(f.attrs['metadata_json']).get('allowed_long_rim_contract')
  if canonical_hash(actual)!=canonical_hash(source['allowed_long_rim_contract']):raise ValueError('source_long_rim_permission_not_declared_by_actual_trace')
 if 'contact_gate_evidence' in source:
  from r1pro_teleop.single_tray_lab.contact_summary import audit_contact_peaks
  actual=audit_contact_peaks(json.loads(Path(source['result']).read_text()),source['trace'])
  if actual['trace_sha256']!=source['trace_sha256'] or canonical_hash(actual)!=canonical_hash(source['contact_gate_evidence']):raise ValueError('contact_gate_source_evidence_changed')
 if 'place_withdrawal_evidence' in source:
  from r1pro_teleop.single_tray_lab.withdrawal_audit import audit_place_withdrawal
  actual=audit_place_withdrawal(source,source['place_withdrawal_evidence']['source_action_span'])
  if canonical_hash(actual)!=canonical_hash(source['place_withdrawal_evidence']):raise ValueError('place_withdrawal_source_evidence_changed')
 return source


def plan_action_segments(source,events,result,numeric,*,contact_n,lifted_m):
 """Only measured completed action windows are trainable; all gaps stay explicit.

 action_start: action_label/frame. action_complete additionally supplies
 end_frame_exclusive and measured_endpoint_frame. The endpoint must be a real
 recorded observation within the window, not an invented/padded final state.
 """
 validate_source_identity(source)
 frames=source['frames']
 if type(frames) is not int or frames<1 or contact_n<=0 or lifted_m<=0:raise ValueError('invalid_source_frames_or_physical_thresholds')
 arrays={k:np.asarray(v) for k,v in numeric.items()}
 required={'payload_loaded':(frames,), 'payload_mass':(frames,), 'gripper_contact_force':(frames,2),
           'support_contact':(frames,), 'floor_contact':(frames,), 'tray_clearance':(frames,), 'tray_goal_reached':(frames,)}
 for key,shape in required.items():
  if key not in arrays or arrays[key].shape!=shape or not np.isfinite(arrays[key]).all():raise ValueError('recorded_numeric_evidence_missing_or_invalid:'+key)
 if not np.isin(arrays['payload_loaded'],[0,1]).all() or (arrays['payload_mass']<0).any():raise ValueError('invalid_payload_physics_evidence')
 segments=[];pending=None
 for event in events:
  if event.get('event') not in ('action_start','action_complete'):continue
  label=event.get('action_label')
  if label not in LABELS:raise ValueError('unknown_new_task_action')
  if event['event']=='action_start':
   if pending is not None:raise ValueError('overlapping_or_unfinished_single_tray_action')
   pending=(label,event['frame'],event)
   continue
  if pending is None or pending[0]!=label:raise ValueError('action_completion_without_matching_start')
  _,a,start=pending;b=event.get('end_frame_exclusive');endpoint=event.get('measured_endpoint_frame')
  if any(type(v) is not int for v in (a,b,endpoint)) or not 0<=a<=endpoint<b<=frames:raise ValueError('invalid_actual_action_halfopen_interval')
  loaded=arrays['payload_loaded'][a:b];mass=arrays['payload_mass'][a:b];forces=arrays['gripper_contact_force'][endpoint]
  if event.get('verified') is not True:raise ValueError('action_complete_without_verified_controller_guard')
  if label in ('pick_empty','place_empty') and (loaded.any() or (mass>0).any()):raise ValueError('empty_action_contains_loaded_payload')
  if label=='pick_empty' and not (np.all(forces>contact_n) and arrays['support_contact'][endpoint]==0 and arrays['floor_contact'][endpoint]==0 and arrays['tray_clearance'][endpoint]>=lifted_m):raise ValueError('pick_endpoint_not_measured_supported_lift')
  if label=='place_empty' and not (np.all(forces<=contact_n) and arrays['support_contact'][endpoint]>0 and arrays['floor_contact'][endpoint]==0):raise ValueError('place_endpoint_not_supported_bilateral_release')
  if label=='push_loaded' and not (loaded.all() and np.all(mass>0) and bool(arrays['tray_goal_reached'][endpoint]) and arrays['support_contact'][endpoint]>0 and arrays['floor_contact'][endpoint]==0 and np.all(forces<=contact_n)):raise ValueError('loaded_push_payload_or_final_guard_invalid')
  vocabulary=ACTION_VOCABULARY[LABELS.index(label)]
  segments.append(dict(schema='airport_single_tray_action_segment/1',task_profile=PROFILE,**vocabulary,task_index=LABELS.index(label),start_frame=a,end_frame=b,measured_endpoint_frame=endpoint,split=source['split'],scene_id=source['scene_id'],source=dict(source),source_start_event=start,source_complete_event=event,source_event_sha256=canonical_hash([start,event]),training_eligible=True))
  pending=None
 if pending is not None:raise ValueError('unfinished_action_cannot_be_training_example')
 if tuple(row['action_label'] for row in segments)!=LABELS or result.get('task_completed') is not True or result.get('physics_success') is not True:raise ValueError('three_action_complete_task_required')
 mask=np.zeros(frames,dtype=bool)
 for row in segments:
  a,b=row['start_frame'],row['end_frame']
  if mask[a:b].any():raise ValueError('action_windows_overlap')
  mask[a:b]=True
 gaps=[];start=None
 for index,covered in enumerate(np.r_[mask,True]):
  if not covered and start is None:start=index
  if covered and start is not None:gaps.append(dict(start_frame=start,end_frame=index,training_eligible=False,reason='environment_load_or_settle_not_robot_demonstration'));start=None
 return dict(schema='airport_single_tray_action_plan/1',task_profile=PROFILE,action_vocabulary=list(ACTION_VOCABULARY),source=dict(source),segments=segments,inventory=gaps,source_frames=frames,supervised_frames=int(mask.sum()),excluded_frames=int((~mask).sum()),dataset_ready=False)

def materialize_action_split(records,destination,repo_id,*,split,dataset_class=None,_contract=None):
 """Export new source-only continuous action windows using the official schema.

 records contain source/plan/native_videos. Plan guards are recomputed from the
 bound trace; saved plan flags alone do not make a source eligible. Publication
 remains nonready unless real LeRobot, encoding, source arrays and RGB audits
 all complete. No training or GPU model is started here.
 """
 import h5py
 from fractions import Fraction
 from . import data_task_lerobot as shared
 from .data_lerobot import MODEL_CAMERAS,CameraFrameReader,STATE_SEMANTICS,TRAINING_VIDEO_ENCODING,project_dataset_class
 from r1pro_teleop.airport_fsm.contracts import NAMES,BASE_NAMES
 contract=_contract or {}
 validate_source=contract.get('source_validate',validate_source_identity)
 qualify_plan=contract.get('plan_action_segments',plan_action_segments)
 read_arrays=contract.get('read_arrays',read_fixed_base_arrays)
 audit_arrays=contract.get('audit_dataset',audit_fixed_base_dataset)
 profile=contract.get('profile',PROFILE)
 numeric_keys=contract.get('numeric_keys',('payload_loaded','payload_mass','gripper_contact_force','support_contact','floor_contact','tray_clearance','tray_goal_reached'))
 destination=Path(destination).resolve()
 if destination.exists():raise ValueError('refuse_existing_single_tray_dataset')
 if split not in ('train','val','test') or not records:raise ValueError('explicit_nonempty_dataset_split_required')
 if len({row['source']['scene_id'] for row in records})!=len(records):raise ValueError('duplicate_single_tray_scene_source')
 vocabulary={row['action_label']:dict(row,task_index=index) for index,row in enumerate(ACTION_VOCABULARY)}
 verified=[]
 for record in records:
  source=validate_source(record['source'])
  if source['split']!=split:raise ValueError('single_tray_scene_split_leakage')
  if not contract and 'place_withdrawal_evidence' not in source:raise ValueError('actual_place_withdrawal_fk_evidence_required_for_export')
  for field,hashfield in [('trace','trace_sha256'),('scene_xml','scene_xml_sha256'),('scene_json','scene_json_sha256'),('result','result_sha256'),('events','events_sha256')]:
   if shared.digest(source[field])!=source[hashfield]:raise ValueError('new_task_source_changed:'+field)
  with h5py.File(source['trace'],'r') as file:
   numeric={key:file[key][:] for key in numeric_keys}
  events=[json.loads(line) for line in Path(source['events']).read_text().splitlines() if line.strip()]
  result=json.loads(Path(source['result']).read_text())
  plan=qualify_plan(source,events,result,numeric,contact_n=source['contact_n'],lifted_m=source['lifted_m'])
  if canonical_hash(plan)!=canonical_hash(record['plan']):raise ValueError('saved_action_plan_changed_or_not_actual_trace_guard')
  views={row['camera']:row for row in record['native_videos']}
  if set(views)!=set(shared.NATIVE_CAMERAS) or len(record['native_videos'])!=4:raise ValueError('new_task_full_native_four_views_required')
  for ref in views.values():
   if shared.digest(ref['path'])!=ref['sha256'] or Fraction(ref['header']['avg_frame_rate'])!=20 or int(ref['header']['nb_frames'])!=source['frames']:raise ValueError('new_task_native_source_contract_changed')
  verified.append((source,plan,views))
 official=dataset_class is None
 if official:dataset_class=project_dataset_class()
 features={'observation.state':dict(dtype='float32',shape=(19,),names=NAMES+BASE_NAMES),'action':dict(dtype='float32',shape=(19,),names=NAMES+BASE_NAMES)}
 features.update({'observation.images.'+camera:dict(dtype='video',shape=(3,224,224),names=['channels','height','width']) for camera in MODEL_CAMERAS})
 dataset=dataset_class.create(repo_id=repo_id,fps=20,root=destination,robot_type='r1pro_mujoco_sim_mobile19',features=features,use_videos=True,image_writer_threads=4,video_backend='pyav')
 for row in vocabulary.values():
  dataset.meta.add_task(row['language_prompt'])
  if dataset.meta.get_task_index(row['language_prompt'])!=row['task_index']:raise ValueError('three_goal_task_index_changed')
 reader=CameraFrameReader();episodes=[];source_rows=[];projections={};trace_hash_cache={}
 try:
  for source,plan,views in verified:
   task=dict(source,native_videos=list(views.values()))
   shared.preserve_full_task(task,destination.parent/(destination.name+'_full_tasks')/source['scene_id'])
   spans=[dict(row,segment_id=canonical_hash(dict(trace_sha256=source['trace_sha256'],action_label=row['action_label'],start=row['start_frame'],end=row['end_frame']))[:24]) for row in plan['segments']]
   windows={camera:[dict(segment_id=row['segment_id'],start_frame=row['start_frame'],end_frame=row['end_frame'],path=destination/'native_action_clips'/row['action_label']/source['scene_id']/row['segment_id']/(camera+'.mkv')) for row in spans] for camera in shared.NATIVE_CAMERAS}
   clips=shared.cut_case_native_windows(views,windows,expected_source_frames=source['frames'],workers=4)
   for row in spans:
    a,b=row['start_frame'],row['end_frame'];states,actions,columns=read_arrays(source,row)
    native={camera:clips[camera][row['segment_id']] for camera in shared.NATIVE_CAMERAS}
    refs={camera:dict(path=native[camera]['path'],sha256=native[camera]['sha256'],start_frame=0,end_frame=b-a,verified=True) for camera in MODEL_CAMERAS};rgbhash={camera:hashlib.sha256() for camera in MODEL_CAMERAS}
    for offset in range(b-a):
     images=reader.read(refs,offset);frame={'observation.state':states[offset],'action':actions[offset],'task':row['language_prompt']}
     for camera in MODEL_CAMERAS:rgbhash[camera].update(np.ascontiguousarray(images[camera]).tobytes());frame['observation.images.'+camera]=images[camera]
     dataset.add_frame(frame)
    dataset.save_episode();episode=dict(row,episode_index=len(episodes),source_trace=source['trace'],source_trace_sha256=source['trace_sha256'],source_start_frame=a,source_end_frame=b,frames=b-a,fps=20,action_semantics='absolute_mobile19',state_semantics=STATE_SEMANTICS,base_qpos_indices=columns,skill=row['action_label'],base_skill=row['action_label'],phase='whole_action',operation_index=row['task_index'],native_action_clips=native,preencode_training_rgb_sha256={camera:sha.hexdigest() for camera,sha in rgbhash.items()},base_state_origin_policy=contract.get('base_state_origin_policy','fixed_front_explicit_zero_base_offsets'))
    if contract:episode.update(parent_scene_id=source['parent_scene_id'],parent_split=source['parent_split'],parent_resource_split=source['parent_resource_split'],route_goal_observation_policy=source['route_goal_observation_policy'])
    episodes.append(episode);source_rows.append(dict(row,trace=source['trace'],trace_sha256=source['trace_sha256'],scene_xml_sha256=source['scene_xml_sha256'],scene_json_sha256=source['scene_json_sha256'],base_qpos_indices=columns,source_segment_id=row['segment_id'],fps=20,state_semantics=STATE_SEMANTICS,action_semantics='absolute_mobile19'))
   shared.update_action_video_index(destination,episodes,dataset)
  if hasattr(dataset,'stop_image_writer'):dataset.stop_image_writer()
  encoding=shared.validate_task_training_encoding(destination,len(episodes)*3) if official else dict(verified=False,reason='diagnostic_fixture')
  arrays=audit_arrays(destination,episodes,vocabulary,repo_id=repo_id) if official else dict(verified=False,reason='diagnostic_fixture')
  rgb=shared.audit_training_rgb_derivation(destination,episodes,dataset) if official else dict(verified=False,reason='diagnostic_fixture')
  manifest_path=destination/'whole_action_source_manifest.jsonl';manifest_path.write_text(''.join(json.dumps(row,sort_keys=True,allow_nan=False)+'\n' for row in source_rows))
  manifest=dict(schema='airport_pi05_training/1',task_profile=PROFILE,prompt_mode=PROFILE,language_profile=PROFILE,base_mode='fixed_front',base_actuated=False,model_action_mask=[True]*16+[False]*3,repo_id=repo_id,split=split,fps=20,action_semantics='absolute_mobile19',state_semantics=STATE_SEMANTICS,controller_source='program_generated',environment_source='simulation',human_demonstration=False,action_vocabulary=list(vocabulary.values()),episodes=episodes,source_manifest=str(manifest_path),source_manifest_sha256=shared.digest(manifest_path),all_parquet_values_verified=arrays,training_video_encoding=dict(TRAINING_VIDEO_ENCODING),training_video_encoding_verification=encoding,actual_training_rgb_derivation=rgb,complete_expected_scene_ids=sorted(row['source']['scene_id'] for row in records),counts=dict(supervised_frames=sum(e['frames'] for e in episodes),unique_full_task_frames=sum(row['source']['frames'] for row in records)),dataset_ready=official and all(audit.get('verified') is True for audit in (encoding,arrays,rgb)),training_started=False,normalization_split='train_only' if split=='train' else 'excluded_from_optimization')
  if contract:
   manifest.update(task_profile=profile,prompt_mode=profile,language_profile=profile,**contract['manifest_fields'])
  (destination/'airport_training_manifest.json').write_text(json.dumps(manifest,indent=2,allow_nan=False));return manifest
 finally:reader.close()


def read_fixed_base_arrays(source,span):
 import h5py
 from .data import digest
 if digest(source['trace'])!=source['trace_sha256']:raise ValueError('fixed_base_trace_changed')
 a,b=span['start_frame'],span['end_frame']
 with h5py.File(source['trace'],'r') as file:
  metadata=json.loads(file.attrs['metadata_json'])
  if file.attrs.get('schema')!='airport_single_tray_raw/2' or metadata.get('base_mode')!='fixed_front' or metadata.get('base_actuated') is not False or metadata.get('model_action_mask')!=[True]*16+[False]*3:raise ValueError('explicit_fixed_base_contract_required')
  state=file['state19'][a:b];action=file['action19'][a:b]
  if state.shape!=(b-a,19) or action.shape!=(b-a,19) or not np.isfinite(state).all() or not np.isfinite(action).all():raise ValueError('invalid_fixed_base_19_arrays')
  if not np.array_equal(state[:,:16],file['state'][a:b]) or not np.array_equal(action[:,:16],file['action'][a:b]) or np.any(state[:,16:]!=0) or np.any(action[:,16:]!=0):raise ValueError('fixed_base_19_projection_changed')
 return state.astype(np.float32),action.astype(np.float32),None


def audit_fixed_base_dataset(destination,episodes,vocabulary,*,repo_id,_read_arrays=None):
 import pyarrow.parquet as pq
 from lerobot.common.datasets.lerobot_dataset import LeRobotDataset
 destination=Path(destination);info=json.loads((destination/'meta/info.json').read_text());tasks=[json.loads(line) for line in (destination/'meta/tasks.jsonl').read_text().splitlines()]
 if tasks!=[dict(task_index=row['task_index'],task=row['language_prompt']) for row in vocabulary.values()]:raise ValueError('fixed_three_tasks_changed')
 loaded=LeRobotDataset(repo_id=repo_id,root=destination,video_backend='pyav',delta_timestamps={'action':[i/20 for i in range(20)]});offset=0
 for episode in episodes:
  path=destination/info['data_path'].format(episode_chunk=episode['episode_index']//info.get('chunks_size',1000),episode_index=episode['episode_index']);table=pq.read_table(path)
  state,action,_=(_read_arrays or read_fixed_base_arrays)(dict(trace=episode['source_trace'],trace_sha256=episode['source_trace_sha256']),dict(start_frame=episode['source_start_frame'],end_frame=episode['source_end_frame']))
  if not np.array_equal(state,np.asarray(table['observation.state'].to_pylist(),dtype=np.float32)) or not np.array_equal(action,np.asarray(table['action'].to_pylist(),dtype=np.float32)):raise ValueError('fixed_base_parquet_source_mismatch')
  for local in (0,len(action)-1):
   sample=loaded[offset+local];indices=np.minimum(np.arange(local,local+20),len(action)-1)
   if not np.array_equal(sample['action'].numpy(),action[indices]) or not np.array_equal(sample['action_is_pad'].numpy(),np.arange(local,local+20)>=len(action)):raise ValueError('fixed_base_actual_horizon_mismatch')
   for camera in ('head_left','left_wrist','right_wrist'):
    if tuple(sample['observation.images.'+camera].shape)!=(3,224,224):raise ValueError('fixed_base_model_rgb_shape_changed')
  offset+=len(action)
 return dict(verified=True,actual_h20_verified=True,all_numeric_source_values_equal=True,frames=offset,episodes=len(episodes),base_actuated=False)

