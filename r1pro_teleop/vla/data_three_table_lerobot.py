"""Actual raw-source/mobile19 export for the new three-table opposed-rim task."""
import json,math
from pathlib import Path
import numpy as np
from .data_three_table_single_tray import PROFILE,RULE_REVISION,FINAL_ORIENTATION_DEFINITION,source_validate,plan_action_segments,bc_input_contract
from .data_single_tray import canonical_hash,materialize_action_split,audit_fixed_base_dataset
from .training_cache import file_sha
NUMERIC_KEYS=('payload_loaded','payload_mass','payload_supported_objects','gripper_contact_force','gripper_grasp_confirmed','gripper_openings','gripper_command_openings','support_contact','floor_contact','tray_clearance','tray_goal_reached','tray_position','tray_long_axis_world','robot_forward_world','robot_left_world','base_front_violation','push_stage','gripper_tray_contact_points_local','gripper_tray_contact_normals_local','gripper_tray_contact_active','table_contact_counts','tray_footprint_on_table')
GUARD_NUMERIC_KEYS=('tray_corners_world','guard_frame_index','guard_sim_time','guard_tray_corners_world','guard_table_contact_counts','guard_push_contact_domain')
RAW_SCHEMAS=('airport_three_table_single_tray_raw/2','airport_single_tray_raw/2')

def reject_free_run_source(value):
 if value.get('run_scope')=='free_run_diagnostic' or value.get('run_kind')=='free_run_diagnostic' or value.get('free_run_diagnostic') is True:raise ValueError('free_run_diagnostic_is_never_training_source')

def qualify(source,events,result,numeric,*,contact_n,lifted_m):
 if source.get('table_support_acceptance_rule') is not None and any(k not in numeric for k in GUARD_NUMERIC_KEYS):
  import h5py
  if file_sha(source['trace'])!=source['trace_sha256']:raise ValueError('guard_journal_source_trace_changed')
  with h5py.File(source['trace'],'r') as f:numeric=dict(numeric,**{k:f[k][:] for k in GUARD_NUMERIC_KEYS})
 if source.get('grasp_confirmation_rule',{}).get('command_evidence_mode')=='actual_submitted_actuator_opening':
  from .gripper_command_evidence import derive_submitted_gripper_evidence
  actual,evidence,audit=derive_submitted_gripper_evidence(source)
  if evidence!=source['grasp_confirmation_rule']['command_actuator_evidence']:raise ValueError('actual_actuator_command_evidence_changed')
  numeric=dict(numeric,**actual)
 if source.get('qualification_repair',{}).get('table_contact_projection'):
  from .table_contact_projection import derive_table_contacts
  record=source['qualification_repair']['table_contact_projection'];actual,receipt=derive_table_contacts(source,record['arrays'])
  if receipt!=record:raise ValueError('contact_projection_requalification_changed')
  numeric=dict(numeric,**actual)
 if source.get('qualification_repair') is not None:
  from .action_event_projection import project_action_events
  events,audit=project_action_events(events,result)
  if 'action_event_projection' in source['qualification_repair'] and source['qualification_repair']['action_event_projection']!=audit:raise ValueError('action_event_projection_changed')
 return plan_action_segments(source,events,result,numeric,contact_n=contact_n,lifted_m=lifted_m,final_yaw_tolerance_rad=source['final_yaw_tolerance_rad'])

def build_source(case,work,*,repair_submitted_commands=False,contact_projection_cache=None):
 import h5py
 case=Path(case);work=Path(work);result_path=case/'result.json';scene_path=case/'scene/scene.json';trace=case/'attempt/trace.h5';events_path=case/'attempt/events.jsonl'
 result=json.loads(result_path.read_text());scene=json.loads(scene_path.read_text())
 reject_free_run_source(result)
 if result.get('task_profile')!=PROFILE or any(result.get(k) is not True for k in ('task_completed','physics_success')) or (result.get('training_eligible') is not True and not repair_submitted_commands):raise ValueError('actual_new_three_table_complete_source_required')
 if repair_submitted_commands:
  prior=json.loads((case/'source_qualification_audit.json').read_text())
  if result.get('training_eligible') is not False or prior.get('verified') is not False or prior.get('error')!='actual_recorded_gripper_commands_required':raise ValueError('only_recorded_command_annotation_failure_can_be_requalified')
 if scene.get('task_rule_revision')!=RULE_REVISION or scene.get('final_orientation_definition')!=FINAL_ORIENTATION_DEFINITION or result.get('task_rule_revision')!=RULE_REVISION or result.get('final_orientation_definition')!=FINAL_ORIENTATION_DEFINITION:raise ValueError('fresh_forward_axis_scene_result_rule_required')
 if scene.get('schema')!='airport_three_table_single_tray_scene/1' or scene.get('task_profile')!=PROFILE:raise ValueError('fresh_three_table_scene_required')
 with h5py.File(trace,'r') as f:
  metadata=json.loads(f.attrs['metadata_json']);reject_free_run_source(metadata);frames=int(f.attrs['num_frames'])
  if f.attrs.get('schema') not in RAW_SCHEMAS or metadata.get('task_profile')!=PROFILE or canonical_hash(metadata.get('scene'))!=canonical_hash(scene):raise ValueError('actual_raw_three_table_scene_identity_required')
  if result.get('frames')!=frames or result.get('scene_id')!=scene['scene_id'] or result.get('split')!=scene['split']:raise ValueError('raw_result_identity_changed')
  if metadata.get('task_rule_revision')!=RULE_REVISION or metadata.get('final_orientation_definition')!=FINAL_ORIENTATION_DEFINITION:raise ValueError('fresh_forward_axis_raw_rule_required')
  if metadata.get('base_mode')!='planar_mobile_table_front' or metadata.get('base_actuated') is not True or metadata.get('model_action_mask')!=[True]*19 or metadata.get('fps')!=20:raise ValueError('actual_mobile19_raw_contract_required')
  if metadata.get('scene_xml_sha256')!=scene['xml_sha256'] or file_sha(scene['xml'])!=scene['xml_sha256']:raise ValueError('raw_model_source_changed')
  if metadata.get('contact_evidence_semantics')!='actual_mujoco_finger_tray_contacts_local':raise ValueError('actual_contact_source_semantics_required')
  if not np.all(f['transition_completed'][:]) or frames<1:raise ValueError('all_actual_transitions_required')
  for key in ('qpos','qvel','integration_state','ctrl_substeps','sim_time','state19','action19'):
   if len(f[key])!=frames or not np.isfinite(f[key][:]).all():raise ValueError('incomplete_or_nonfinite_actual_raw:'+key)
  numeric={k:f[k][:] for k in NUMERIC_KEYS}
  if metadata.get('table_support_acceptance_rule') is not None:numeric.update({k:f[k][:] for k in GUARD_NUMERIC_KEYS})
  limits=metadata['qualification_limits']
  if canonical_hash(result.get('qualification_limits'))!=canonical_hash(limits):raise ValueError('result_raw_qualification_limits_changed')
 origin=scene['initial_tray_pose'];source=dict(schema='airport_three_table_single_tray_source/1',task_profile=PROFILE,task_rule_revision=RULE_REVISION,final_orientation_definition=FINAL_ORIENTATION_DEFINITION,source='simulation/program_generated',tray_count=1,table_count=3,frames=frames,fps=20,action_semantics='absolute_mobile19',state_semantics='measured_joint16_plus_base_origin_offset3',base_mode='planar_mobile_table_front',base_actuated=True,model_action_mask=[True]*19,scene_id=scene['scene_id'],variant_seed=int(scene['seed']),split=scene['split'],random_initial_pose=dict(xy=origin['position_world'][:2],yaw_rad=origin['yaw_world']),grasp_requirement='bilateral_opposed_long_rims',contact_evidence_semantics=metadata['contact_evidence_semantics'],tray_dimensions=scene['tray']['size'],trace=str(trace),trace_sha256=file_sha(trace),scene_xml=scene['xml'],scene_xml_sha256=scene['xml_sha256'],scene_json=str(scene_path),scene_json_sha256=file_sha(scene_path),result=str(result_path),result_sha256=file_sha(result_path),events=str(events_path),events_sha256=file_sha(events_path),controller_sha256=metadata['controller_sha256'],grasp_confirmation_rule=metadata['grasp_confirmation_rule'],contact_n=float(limits['contact_n']),lifted_m=float(limits['lifted_m']),final_yaw_tolerance_rad=float(limits['final_yaw_tolerance_rad']))
 for key in ('parent_scene_id','parent_scene_json','parent_scene_json_sha256','parent_manifest','parent_manifest_sha256','parent_split','parent_resource_split','canonical_split_registry','canonical_split_registry_sha256','source_table','target_table','route_goal_observation_policy'):source[key]=scene[key]
 source['loaded_goal_policy']=metadata['loaded_bridge_profile']['loaded_goal_policy']
 source['minimum_left_tray_motion_m']=metadata['loaded_bridge_profile']['minimum_left_tray_motion_m']
 for key in ('payload_support_object_order','payload_support_evidence_semantics','loaded_bridge_profile','loaded_bridge_profile_sha256'):
  if key in metadata:source[key]=metadata[key]
 if metadata.get('table_support_acceptance_rule') is not None:
  source['table_support_geometry']=scene['tables']
  source['table_support_acceptance_rule']=dict(metadata['table_support_acceptance_rule'],trace_sha256=source['trace_sha256'],bound_to_original_physical_trace_sha256=metadata['original_trace_sha256'])
 if metadata.get('numeric_derivation')=='live_same_runtime_pre_action_observer':
  from ..single_tray_3table.observer import audit_observed_lineage
  source['original_physical_lineage_audit']=audit_observed_lineage(trace)
 if repair_submitted_commands or result.get('training_eligible') is True:
  from .gripper_command_evidence import derive_submitted_gripper_evidence
  extra,evidence,command_audit=derive_submitted_gripper_evidence(source);numeric.update(extra)
  source['grasp_confirmation_rule']=dict(source['grasp_confirmation_rule'],command_evidence_mode='actual_submitted_actuator_opening',command_actuator_evidence=evidence)
  source['qualification_repair']=dict(schema='airport_actual_command_qualification_repair/1',original_result_sha256=file_sha(result_path),original_qualification_sha256=file_sha(case/'source_qualification_audit.json') if repair_submitted_commands else None,original_raw_events_unchanged=True,command_audit=command_audit)
 source_validate(source);read_mobile_arrays(source,dict(start_frame=0,end_frame=frames))
 events=[json.loads(line) for line in events_path.read_text().splitlines() if line.strip()]
 if source.get('qualification_repair') is not None:
  from .action_event_projection import project_action_events
  _,projection=project_action_events(events,result);source['qualification_repair']['action_event_projection']=projection
  if metadata.get('table_contact_semantics')=='actual_mujoco_tray_table_contacts_without_force_cutoff_matching_loaded_bridge':
   source['qualification_repair']['actual_table_contacts_recorded_without_force_cutoff']=True
  else:
   from .table_contact_projection import derive_table_contacts
   work.parent.mkdir(parents=True,exist_ok=True)
   projection_path=Path(contact_projection_cache)/(work.name+'_table_contacts.npz') if contact_projection_cache is not None else work.parent/(work.name+'_table_contacts.npz')
   if contact_projection_cache is not None and not projection_path.with_suffix('.json').exists():raise ValueError('required_continuous_contact_projection_not_closed_yet')
   actual,contact_receipt=derive_table_contacts(source,projection_path);numeric.update(actual);source['qualification_repair']['table_contact_projection']=contact_receipt
 plan=qualify(source,events,result,numeric,contact_n=source['contact_n'],lifted_m=source['lifted_m']);bc_input_contract(plan)
 work.mkdir(parents=True,exist_ok=False);segments=work/'segments.json';segments.write_text(json.dumps(result['action_spans'],allow_nan=False));source.update(segments=str(segments),segments_sha256=file_sha(segments))
 plan=qualify(source,events,result,numeric,contact_n=source['contact_n'],lifted_m=source['lifted_m'])
 if repair_submitted_commands:(work/'source_qualification_audit.json').write_text(json.dumps(dict(schema='airport_three_table_source_requalification/1',verified=True,original_case=str(case.resolve()),original_result_sha256=file_sha(result_path),original_trace_sha256=source['trace_sha256'],source_manifest=str((work/'source.json').resolve()),source_canonical_sha256=canonical_hash(source),original_result_training_eligible=False,original_result_unchanged=True,physical_task_completed=True,source_qualification_only_not_control_improvement=True),indent=2))
 (work/'source.json').write_text(json.dumps(source,indent=2,allow_nan=False));(work/'plan.json').write_text(json.dumps(plan,indent=2,allow_nan=False))
 if repair_submitted_commands:
  certificate=json.loads((work/'source_qualification_audit.json').read_text());certificate.update(source_manifest_sha256=file_sha(work/'source.json'),plan_sha256=file_sha(work/'plan.json'));(work/'source_qualification_audit.json').write_text(json.dumps(certificate,indent=2))
 return source,plan

def read_mobile_arrays(source,span):
 import h5py,mujoco
 if file_sha(source['trace'])!=source['trace_sha256']:raise ValueError('actual_mobile_raw_changed')
 a,b=span['start_frame'],span['end_frame']
 with h5py.File(source['trace'],'r') as f:
  meta=json.loads(f.attrs['metadata_json']);scene=meta['scene'];xml=source.get('scene_xml',scene['xml'])
  if f.attrs.get('schema') not in RAW_SCHEMAS or meta.get('task_profile')!=PROFILE or meta.get('base_mode')!='planar_mobile_table_front' or meta.get('base_actuated') is not True or meta.get('model_action_mask')!=[True]*19:raise ValueError('actual_three_table_mobile_raw_required')
  if meta.get('task_rule_revision')!=RULE_REVISION or meta.get('final_orientation_definition')!=FINAL_ORIENTATION_DEFINITION:raise ValueError('fresh_forward_axis_mobile_raw_required')
  if file_sha(xml)!=meta['scene_xml_sha256']:raise ValueError('mobile_projection_xml_changed')
  model=mujoco.MjModel.from_xml_path(str(xml));columns=[int(model.jnt_qposadr[model.joint('agent_base_'+axis).id]) for axis in ('x','y','yaw')]
  state=np.asarray(f['state19'][a:b]);action=np.asarray(f['action19'][a:b]);state16=f['state16' if 'state16' in f else 'state'][a:b];action16=f['action16' if 'action16' in f else 'action'][a:b]
  if state.shape!=(b-a,19) or action.shape!=(b-a,19) or not np.isfinite(state).all() or not np.isfinite(action).all():raise ValueError('invalid_mobile_19_arrays')
  expected=f['qpos'][a:b][:,columns]-f['qpos'][0,columns]
  if not np.array_equal(state[:,:16],state16) or not np.array_equal(action[:,:16],action16) or not np.array_equal(state[:,16:],expected.astype(state.dtype)) or not np.array_equal(action[:,16:],f['base_action'][a:b].astype(action.dtype)):raise ValueError('actual_mobile_19_projection_changed')
 return state.astype(np.float32),action.astype(np.float32),columns

def audit_mobile_dataset(destination,episodes,vocabulary,*,repo_id):
 audit=audit_fixed_base_dataset(destination,episodes,vocabulary,repo_id=repo_id,_read_arrays=read_mobile_arrays);audit.update(base_actuated=True,base_projection='compiled_agent_joint_qpos_minus_source_initial_origin');return audit

def materialize(records,destination,repo_id,*,split,dataset_class=None):
 for r in records:source_validate(r['source']);bc_input_contract(r['plan'])
 contract=dict(profile=PROFILE,source_validate=source_validate,plan_action_segments=qualify,read_arrays=read_mobile_arrays,audit_dataset=audit_mobile_dataset,numeric_keys=NUMERIC_KEYS,base_state_origin_policy='source_initial_agent_joint_origin_not_segment_start',manifest_fields=dict(task_rule_revision=RULE_REVISION,final_orientation_definition=FINAL_ORIENTATION_DEFINITION,base_mode='planar_mobile_table_front',base_actuated=True,model_action_mask=[True]*19,route_goal_observation_policy='fixed_registered_rear_to_front_left_route',new_task_source_guard_audit=dict(verified=True,qualified_complete_sources=len(records),actual_opposed_contact_geometry=True,actual_place_yaw_and_handover_verified=True)))
 return materialize_action_split(records,destination,repo_id,split=split,dataset_class=dataset_class,_contract=contract)

