"""New three-table, mobile-base, opposed-rim task; never relabel old sources.

Pure qualification/planning only. Real source collection, replay, media and
official dataset export must still be verified before dataset_ready is true.
"""
import hashlib
import json
import math
from pathlib import Path
import numpy as np
from .data_single_tray import ACTION_VOCABULARY,canonical_hash

PROFILE='three_table_single_tray_action3_v1'
RULE_REVISION='20261006_loaded_handover_left_motion3cm_v3'
FINAL_ORIENTATION_DEFINITION='tray_long_axis_parallel_actual_horizontal_robot_forward_mod_pi'
TABLE_IDS=('front_left','front_right','rear')
LABELS=tuple(x['action_label'] for x in ACTION_VOCABULARY)
PAYLOAD_OBJECT_ORDER=('laptop','backpack','coat')


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source_validate(source):
    if source.get('run_scope')=='free_run_diagnostic' or source.get('run_kind')=='free_run_diagnostic' or source.get('free_run_diagnostic') is True:
        raise ValueError('free_run_diagnostic_never_training_source')
    if source.get('schema')!='airport_three_table_single_tray_source/1' or source.get('task_profile')!=PROFILE:
        raise ValueError('fresh_three_table_single_tray_source_required')
    if source.get('task_rule_revision')!=RULE_REVISION or source.get('final_orientation_definition')!=FINAL_ORIENTATION_DEFINITION:
        raise ValueError('fresh_robot_forward_axis_rule_required_not_old_left_goal')
    if source.get('source')!='simulation/program_generated' or source.get('tray_count')!=1 or source.get('table_count')!=3:
        raise ValueError('three_table_single_tray_simulation_required')
    if source.get('fps')!=20 or source.get('action_semantics')!='absolute_mobile19' or source.get('state_semantics')!='measured_joint16_plus_base_origin_offset3':raise ValueError('mobile19_record_contract_required')
    if source.get('base_mode')!='planar_mobile_table_front' or source.get('base_actuated') is not True or source.get('model_action_mask')!=[True]*19 or any(type(v) is not bool for v in source.get('model_action_mask',[])):
        raise ValueError('new_mobile_base_contract_required')
    if type(source.get('variant_seed')) is not int or not source.get('parent_scene_id') or not source.get('scene_id') or source['scene_id']==source['parent_scene_id']:raise ValueError('explicit_new_variant_identity_required')
    for key in ('trace_sha256','scene_xml_sha256','scene_json_sha256','controller_sha256','parent_scene_json_sha256','parent_manifest_sha256','canonical_split_registry_sha256'):
        value=source.get(key)
        if not isinstance(value,str) or len(value)!=64 or any(c not in '0123456789abcdef' for c in value):raise ValueError('source_hash_required:'+key)
    for path,sha in (('parent_scene_json','parent_scene_json_sha256'),('parent_manifest','parent_manifest_sha256'),('canonical_split_registry','canonical_split_registry_sha256')):
        if digest(source[path])!=source[sha]:raise ValueError('parent_source_changed:'+path)
    parent=json.loads(Path(source['parent_scene_json']).read_text());manifest=json.loads(Path(source['parent_manifest']).read_text())
    records=[r for r in manifest['scenes'] if r['scene_id']==source['parent_scene_id']]
    registry=json.loads(Path(source['canonical_split_registry']).read_text())
    registered=registry.get(source['parent_scene_id'])
    if len(records)!=1 or parent['scene_id']!=source['parent_scene_id'] or source.get('parent_split')!=registered or source.get('parent_resource_split')!=parent['split']:raise ValueError('parent_scene_registry_identity_mismatch')
    if (Path(source['parent_manifest']).parent/records[0]['json']).resolve()!=Path(source['parent_scene_json']).resolve():raise ValueError('parent_manifest_relative_source_changed')
    split={'validation':'val','val':'val','train':'train','test':'test'}.get(registered)
    if split is None or source.get('split')!=split:raise ValueError('variant_parent_split_leakage')
    if {t['table_id'] for t in parent.get('tables',[])}!=set(TABLE_IDS):raise ValueError('actual_original_three_tables_required')
    if source.get('source_table') not in TABLE_IDS or source.get('target_table') not in TABLE_IDS:raise ValueError('explicit_source_target_table_required')
    if source.get('route_goal_observation_policy')!='fixed_registered_rear_to_front_left_route' or (source['source_table'],source['target_table'])!=('rear','front_left'):
        raise ValueError('current_bc_requires_observable_fixed_rear_to_front_left_route')
    minimum=source.get('minimum_left_tray_motion_m');profile=source.get('loaded_bridge_profile',{})
    if source.get('loaded_goal_policy')!='handover_left_motion_then_release' or type(minimum) not in (float,int) or not np.isfinite(minimum) or minimum<.03 or profile.get('minimum_left_tray_motion_m')!=minimum or profile.get('loaded_goal_policy')!=source['loaded_goal_policy'] or source.get('loaded_bridge_profile_sha256')!=canonical_hash(profile):raise ValueError('actual_loaded_handover_left_motion_profile_required')
    pose=source.get('random_initial_pose',{});xy=np.asarray(pose.get('xy'),float)
    if xy.shape!=(2,) or not np.isfinite(xy).all() or type(pose.get('yaw_rad')) not in (float,int) or not np.isfinite(pose['yaw_rad']):raise ValueError('recorded_random_initial_pose_required')
    if source.get('grasp_requirement')!='bilateral_opposed_long_rims' or source.get('contact_evidence_semantics')!='actual_mujoco_finger_tray_contacts_local':raise ValueError('actual_opposed_long_rim_evidence_required')
    dims=np.asarray(source.get('tray_dimensions'),float)
    if dims.shape!=(3,) or not np.isfinite(dims).all() or min(dims)<=0 or dims[0]<=dims[1]:raise ValueError('long_axis_local_x_dimensions_required')
    return source


def long_rim_codes(points,normals,active,dimensions,*,reject_invalid=True):
    """Classify all actual finger/tray contacts, never trust supplied rim labels."""
    points=np.asarray(points,float);normals=np.asarray(normals,float);active=np.asarray(active)
    if points.ndim!=4 or points.shape[1]!=2 or points.shape[-1]!=3 or normals.shape!=points.shape or active.shape!=points.shape[:-1] or active.dtype!=np.bool_:raise ValueError('actual_contact_arrays_required')
    if not np.isfinite(points[active]).all() or not np.isfinite(normals[active]).all():raise ValueError('nonfinite_actual_contact')
    codes=np.zeros(active.shape[:2],np.int8);half=np.asarray(dimensions,float)/2
    for frame,side in np.ndindex(codes.shape):
        p=points[frame,side][active[frame,side]];n=normals[frame,side][active[frame,side]]
        if not len(p):continue
        # Wall or top lip on the long side; a short-side normal/corner is not
        # opposed-long-rim evidence. Both signs are legal, same-sign is not.
        invalid=np.any(abs(p[:,0])>=half[0]-.002) or np.any(abs(p[:,1])<half[1]-.025) or np.any(abs(n[:,0])>=np.maximum(abs(n[:,1]),abs(n[:,2])))
        signs=np.sign(p[:,1]).astype(np.int8)
        invalid=invalid or not np.all(signs==signs[0])
        if invalid:
            if reject_invalid:raise ValueError('short_or_ambiguous_rim_contact')
            codes[frame,side]=2;continue
        codes[frame,side]=signs[0]
    return codes


def final_axis_error(tray_long_axis,robot_forward):
    """Horizontal unoriented angle with one scalar IEEE-754/libm path.

    NumPy SIMD acos differs by one ULP between the recording and training
    environments. Fixed scalar multiply/add/sqrt/acos preserves exact plans
    without rounding annotations, changing tolerances, or mutating inputs.
    """
    a=np.asarray(tray_long_axis,float);b=np.asarray(robot_forward,float)
    if a.shape!=b.shape or a.ndim<1 or a.shape[-1]!=3 or not np.isfinite(a).all() or not np.isfinite(b).all():raise ValueError('actual_orientation_vectors_required')
    angles=[]
    for av,bv in zip(a.reshape(-1,3),b.reshape(-1,3)):
        ax,ay=float(av[0]),float(av[1]);bx,by=float(bv[0]),float(bv[1])
        na=math.sqrt(ax*ax+ay*ay);nb=math.sqrt(bx*bx+by*by)
        if na<1e-8 or nb<1e-8:raise ValueError('degenerate_actual_horizontal_orientation')
        cosine=(ax*bx+ay*by)/(na*nb)
        if not math.isfinite(cosine):raise ValueError('actual_orientation_vectors_required')
        angles.append(math.acos(min(1.,max(0.,abs(cosine)))))
    result=np.asarray(angles,dtype=np.float64).reshape(a.shape[:-1])
    return result[()] if result.ndim==0 else result


def table_geometry_values(corners,tables):
    """Measured eight corners against immutable registered table boxes."""
    corners=np.asarray(corners,float)
    if corners.shape[-2:]!=(8,3) or not np.isfinite(corners).all():raise ValueError('actual_eight_tray_corners_required')
    excess=[];gap=[]
    for table_id in TABLE_IDS:
        rows=[t for t in tables if t['table_id']==table_id]
        if len(rows)!=1:raise ValueError('registered_table_geometry_required')
        t=rows[0];center=np.asarray(t['center_world'],float);dims=np.asarray(t['dimensions_m'],float);yaw=float(t['yaw_world'])
        if center.shape!=(3,) or dims.shape!=(3,) or not np.isfinite(np.r_[center,dims,yaw]).all() or np.any(dims<=0):raise ValueError('registered_table_geometry_required')
        c,s=np.cos(yaw),np.sin(yaw);rotation=np.array([[c,-s],[s,c]])
        local=(corners[...,:2]-center[:2])@rotation
        excess.append(np.max(abs(local)-dims[:2]/2,axis=(-2,-1)))
        gap.append(np.min(corners[...,2],axis=-1)-(center[2]+dims[2]))
    return np.stack(excess,axis=-1),np.stack(gap,axis=-1)


def source_supported_boundary_margin(source):
    rule=source.get('table_support_acceptance_rule',{})
    base=rule.get('existing_footprint_margin_m')
    if type(base) not in (float,int) or base not in (.005,.05):raise ValueError('recorded_authorized_total_boundary_margin_required')
    profile=source.get('loaded_bridge_profile')
    if base==.05 or profile is not None:
        if not isinstance(profile,dict) or source.get('loaded_bridge_profile_sha256')!=canonical_hash(profile) or rule.get('loaded_bridge_profile_sha256')!=canonical_hash(profile) or profile.get('supported_boundary_margin_m',.005)!=base or profile.get('push_transient_boundary_extra_m',0.)!=rule.get('extra_transient_footprint_margin_m'):raise ValueError('actual_loaded_profile_boundary_binding_required')
        if base==.05 and (profile.get('position_tolerance_m')!=.05 or rule.get('extra_transient_footprint_margin_m')!=0):raise ValueError('new_total_50mm_profile_not_stacked_margin_required')
    return base


def audit_table_support_acceptance(source,numeric,*,start_frame,end_frame,endpoint_frame):
    """Recompute explicit transient grace; its extra margin never applies at end.

    Guard rows are actual every-physics-substep observations retained in the
    bound trace, not interpolated from camera frames or accepted booleans.
    """
    rule=source.get('table_support_acceptance_rule',{});tables=source.get('table_support_geometry')
    parent=json.loads(Path(source['parent_scene_json']).read_text())
    if rule.get('schema')!='airport_recorded_table_support_acceptance/1' or rule.get('controller_sha256')!=source['controller_sha256'] or rule.get('trace_sha256')!=source['trace_sha256'] or rule.get('coverage')!='every_guarded_physics_substep' or canonical_hash(tables)!=canonical_hash(parent['tables']) or rule.get('table_geometry_sha256')!=canonical_hash(tables):raise ValueError('source_bound_table_support_rule_required')
    base=source_supported_boundary_margin(source);extra=rule.get('extra_transient_footprint_margin_m');grace=rule.get('grace_duration_s');cap=rule.get('gap_cap_m');dt=rule.get('physics_timestep_s');steps=rule.get('substeps_per_interval')
    if any(type(x) not in (int,float) or not np.isfinite(x) for x in (base,extra,grace,cap,dt)) or not 0<=extra<=.001 or not 0<grace<=.3 or not 0<cap<=.001 or dt<=0 or type(steps) is not int or steps<1 or not np.isclose(dt*steps,1/source['fps'],rtol=0,atol=1e-12):raise ValueError('declared_user_authorized_table_grace_required')
    n=source['frames'];corners=np.asarray(numeric.get('tray_corners_world'),float)
    if corners.shape!=(n,8,3):raise ValueError('actual_frame_eight_corners_required')
    frame_excess,frame_gap=table_geometry_values(corners,tables)
    strict=np.asarray(numeric['tray_footprint_on_table'])
    if strict.dtype!=np.bool_ or strict.shape!=(n,3) or not np.array_equal(strict,frame_excess<=0):raise ValueError('strict_zero_margin_footprint_not_actual_corners')
    ids=np.asarray(numeric.get('guard_frame_index'));time=np.asarray(numeric.get('guard_sim_time'),float);gc=np.asarray(numeric.get('guard_tray_corners_world'),float);counts=np.asarray(numeric.get('guard_table_contact_counts'));domain=np.asarray(numeric.get('guard_push_contact_domain'))
    length=len(time) if time.ndim==1 else -1
    if ids.shape!=(length,) or not np.issubdtype(ids.dtype,np.integer) or gc.shape!=(length,8,3) or counts.shape!=(length,3) or domain.shape!=(length,) or domain.dtype!=np.bool_ or not np.isfinite(time).all() or not np.isfinite(counts).all() or np.any(counts<0) or not np.all(counts==np.floor(counts)) or np.any(np.diff(ids)<0):raise ValueError('actual_guard_substep_journal_required')
    chosen=np.flatnonzero((ids>=start_frame)&(ids<end_frame));fi=ids[chosen]
    if not np.array_equal(np.bincount(fi-start_frame,minlength=end_frame-start_frame),np.full(end_frame-start_frame,steps)) or np.any(abs(np.diff(time[chosen])-dt)>1e-9):raise ValueError('complete_continuous_guard_substeps_required')
    excess,gap=table_geometry_values(gc[chosen],tables);target=TABLE_IDS.index(source['target_table'])
    # Domain comes from the actual bridge getter recorded in the bound raw
    # guard journal; rendered-frame stage labels can lag a substep transition.
    supported=(counts[chosen,target]>0)&(excess[:,target]<=base)
    missing_since=None;max_duration=0.;episodes=0
    for i in range(len(chosen)):
        if supported[i]:
            if missing_since is not None:max_duration=max(max_duration,float(time[chosen[i]]-missing_since))
            missing_since=None;continue
        if excess[i,target]>base+extra or abs(gap[i,target])>cap:raise ValueError('push_outside_declared_table_grace_geometry')
        if missing_since is None:missing_since=time[chosen[i]];episodes+=1
        duration=time[chosen[i]]-missing_since;max_duration=max(max_duration,float(duration))
        if duration>grace+1e-9:raise ValueError('push_declared_table_grace_exhausted')
    if missing_since is not None or frame_excess[endpoint_frame,target]>base or np.asarray(numeric['table_contact_counts'])[endpoint_frame,target]<=0:raise ValueError('actual_final_table_support_without_extra_grace_required')
    return dict(schema='airport_rederived_table_support_acceptance/1',qualification_scope='complete_flush_window',actual_live_guard_domain_rows=int(np.count_nonzero(domain[chosen])),microgap_outside_live_guard_domain_rows=int(np.count_nonzero(~supported & ~domain[chosen])),source_rule_sha256=canonical_hash(rule),guard_rows_verified=len(chosen),strict_zero_margin_footprint_all=bool(np.all(excess[:,target]<=0)),old_5mm_footprint_all=bool(np.all(excess[:,target]<=.005)),existing_margin_m=base,extra_transient_margin_m=extra,actual_boundary_excess_peak_m=float(excess[:,target].max()),actual_abs_gap_peak_m=float(abs(gap[:,target]).max()),grace_episodes=episodes,actual_grace_peak_duration_s=max_duration,final_extra_margin_used=False)


def derive_grasp_confirmations(source,events,numeric,*,contact_n):
    """Audit recorded existing confirmation/release transitions, no new gate.

    The source observer must declare its existing rule and complete transition
    journal. A phase name or an arbitrary per-frame bool is not a confirmation.
    The exporter must rederive this mask from bound raw events/force/jaw state.
    """
    frames=source['frames'];rule=source.get('grasp_confirmation_rule',{})
    if rule.get('schema')!='airport_existing_grasp_confirmation_rule/1' or not rule.get('rule_id') or rule.get('controller_sha256')!=source['controller_sha256'] or rule.get('transition_journal_complete') is not True:raise ValueError('recorded_existing_grasp_confirmation_rule_required')
    seconds=rule.get('stable_duration_s');release_mode=rule.get('release_evidence_mode','existing_measured_opening_minimum')
    release_open=rule.get('release_opening_min_m') if release_mode=='existing_measured_opening_minimum' else rule.get('existing_open_command_m')
    if release_mode not in ('existing_measured_opening_minimum','existing_low_force_commanded_open') or type(seconds) not in (float,int) or not np.isfinite(seconds) or seconds<=0 or rule.get('contact_n')!=contact_n or type(release_open) not in (float,int) or not np.isfinite(release_open) or not 0<release_open<=.1:raise ValueError('existing_confirmation_rule_parameters_required')
    force=np.asarray(numeric['gripper_contact_force'],float);jaw=np.asarray(numeric['gripper_openings'],float)
    # Actual measured jaws may overshoot the command range. Mechanical state
    # guards belong to the bound controller, not an invented annotation gate.
    if force.shape!=(frames,2) or jaw.shape!=(frames,2) or not np.isfinite(force).all() or not np.isfinite(jaw).all():raise ValueError('actual_force_and_jaw_state_required')
    command=None
    if release_mode=='existing_low_force_commanded_open':
        submitted=rule.get('command_evidence_mode')=='actual_submitted_actuator_opening'
        command=np.asarray(numeric.get('gripper_effective_command_openings' if submitted else 'gripper_command_openings'))
        if command.shape!=(frames,2) or not np.issubdtype(command.dtype,np.floating) or not np.isfinite(command).all() or np.any(command<0) or np.any(command>np.asarray(.1,dtype=command.dtype)):raise ValueError('actual_recorded_gripper_commands_required')
        if submitted:
            evidence=rule.get('command_actuator_evidence',{});controls=np.asarray(numeric.get('gripper_control_substeps'))
            if evidence.get('schema')!='airport_actual_gripper_actuator_command/1' or evidence.get('scene_xml_sha256')!=source['scene_xml_sha256'] or evidence.get('actuator_names')!=['left_gripper_target','right_gripper_target'] or evidence.get('opening_multiplier')!=2 or controls.ndim!=3 or controls.shape[0]!=frames or controls.shape[2]!=2 or not np.issubdtype(controls.dtype,np.floating) or not np.isfinite(controls).all():raise ValueError('actual_gripper_control_journal_required')
            proof=dict(shape=list(controls.shape),dtype=str(controls.dtype),sha256=hashlib.sha256(np.ascontiguousarray(controls).tobytes()).hexdigest())
            limits=np.asarray(evidence.get('ctrlranges'),float)
            if evidence.get('raw_control_journal_sha256')!=canonical_hash(proof) or limits.shape!=(2,2) or not np.isfinite(limits).all() or np.any(limits[:,0]>=limits[:,1]):raise ValueError('actual_submitted_command_projection_not_verified')
            if evidence.get('control_range_semantics')=='mujoco_ctrllimited_internal_clamp':
                if evidence.get('actuator_ctrllimited')!=[True,True] or evidence.get('raw_trace_sha256')!=source['trace_sha256']:raise ValueError('actual_ctrllimited_source_binding_required')
                effective=np.clip(controls[:,0,:],limits[:,0],limits[:,1])*2
            else:
                if np.any(controls<limits[:,0]) or np.any(controls>limits[:,1]):raise ValueError('actual_submitted_command_projection_not_verified')
                effective=controls[:,0,:]*2
            if not np.array_equal(command,effective):raise ValueError('actual_submitted_command_projection_not_verified')
        release_open=np.asarray(release_open,dtype=command.dtype).item()
    transitions={};confirmed_at={};count=max(1,int(np.ceil(seconds*source['fps']-1e-9)))
    for event in events:
        if event.get('event') not in ('grasp_confirmed','grasp_released'):continue
        frame=event.get('frame');sides=event.get('sides')
        if event.get('schema')!='airport_actual_grasp_confirmation_event/1' or event.get('confirmation_rule_id')!=rule['rule_id'] or type(frame) is not int or not 0<=frame<frames or not isinstance(sides,list) or not sides or len(set(sides))!=len(sides) or not set(sides)<={'left','right'}:raise ValueError('actual_confirmation_event_required')
        for side in sides:
            column=0 if side=='left' else 1
            if (frame,column) in transitions:raise ValueError('ambiguous_grasp_confirmation_transition')
            if event['event']=='grasp_confirmed':
                start=event.get('stable_start_frame')
                if type(start) is not int or not 0<=start<=frame or frame-start+1<count or not np.all(force[start:frame+1,column]>contact_n) or event.get('after_existing_close_confirmation') is not True:raise ValueError('existing_stable_force_confirmation_not_observed')
                confirmed_at[column]=frame
            else:
                if force[frame,column]>contact_n:raise ValueError('actual_release_force_and_open_jaw_required')
                if release_mode=='existing_measured_opening_minimum':
                    if jaw[frame,column]<release_open:raise ValueError('actual_release_force_and_open_jaw_required')
                else:
                    start=event.get('release_command_start_frame')
                    if type(start) is not int or not 0<start<=frame or event.get('after_existing_release_verification') is not True or command[frame,column]<release_open:raise ValueError('actual_existing_open_command_release_required')
                    if submitted:
                        before=confirmed_at.get(column)
                        if before is None or not np.any(command[before:frame,column]<release_open):raise ValueError('actual_existing_open_command_release_required')
                    elif command[start-1,column]>=release_open or command[frame,column]<=command[start-1,column]:raise ValueError('actual_existing_open_command_release_required')
            transitions[(frame,column)]=event['event']=='grasp_confirmed'
    result=np.zeros((frames,2),bool);state=np.zeros(2,bool)
    for frame in range(frames):
        for column in range(2):
            if (frame,column) in transitions:state[column]=transitions[(frame,column)]
        result[frame]=state
    actual=np.asarray(numeric.get('gripper_grasp_confirmed'))
    if actual.shape!=(frames,2) or actual.dtype!=np.bool_ or not np.array_equal(actual,result):raise ValueError('grasp_confirmation_mask_not_rederived_from_actual_events')
    return result


def plan_action_segments(source,events,result,numeric,*,contact_n,lifted_m,final_yaw_tolerance_rad):
    source_validate(source);frames=source.get('frames')
    if type(frames) is not int or frames<1 or not np.isfinite([contact_n,lifted_m,final_yaw_tolerance_rad]).all() or min(contact_n,lifted_m,final_yaw_tolerance_rad)<=0:raise ValueError('finite_actual_physical_thresholds_required')
    arrays={k:np.asarray(v) for k,v in numeric.items()}
    required={'payload_loaded':(frames,),'payload_mass':(frames,),'gripper_contact_force':(frames,2),'support_contact':(frames,),'floor_contact':(frames,),'tray_clearance':(frames,),'tray_goal_reached':(frames,),'tray_position':(frames,3),'tray_long_axis_world':(frames,3),'robot_forward_world':(frames,3),'robot_left_world':(frames,3),'base_front_violation':(frames,),'push_stage':(frames,)}
    required.update(table_contact_counts=(frames,3),tray_footprint_on_table=(frames,3))
    required['gripper_grasp_confirmed']=(frames,2)
    required['gripper_openings']=(frames,2)
    required['payload_supported_objects']=(frames,3)
    for key,shape in required.items():
        if key not in arrays or arrays[key].shape!=shape or not np.isfinite(arrays[key]).all():raise ValueError('actual_numeric_evidence_required:'+key)
    if arrays['base_front_violation'].any() or not np.isin(arrays['payload_loaded'],[0,1]).all() or np.any(arrays['payload_mass']<0):raise ValueError('actual_task_guard_violation')
    if source.get('payload_support_object_order')!=list(PAYLOAD_OBJECT_ORDER) or source.get('payload_support_evidence_semantics')!='actual_tray_contact_graph_registered_payload_entities' or arrays['payload_supported_objects'].dtype!=np.bool_:raise ValueError('actual_all_three_payload_support_evidence_required')
    if arrays['gripper_grasp_confirmed'].dtype!=np.bool_:raise ValueError('actual_grasp_confirmation_mask_required')
    derive_grasp_confirmations(source,events,numeric,contact_n=contact_n)
    table_counts=arrays['table_contact_counts'];footprint=arrays['tray_footprint_on_table']
    if footprint.dtype!=np.bool_ or np.any(table_counts<0) or not np.all(table_counts==np.floor(table_counts)) or not np.array_equal(table_counts.sum(axis=1),arrays['support_contact']):raise ValueError('actual_table_contact_and_footprint_evidence_required')
    declared_table_rule=source.get('table_support_acceptance_rule') is not None
    if declared_table_rule:
        excess,_=table_geometry_values(arrays.get('tray_corners_world'),source.get('table_support_geometry',[]))
        source_supported_boundary_margin(source)
        footprint=excess<=.005  # Empty source/place gates are unchanged; 50mm is Push-only.
    source_table=TABLE_IDS.index(source['source_table']);target_table=TABLE_IDS.index(source['target_table'])
    active=np.asarray(arrays['gripper_tray_contact_active'])
    if active.ndim!=3 or active.shape[:2]!=(frames,2) or active.dtype!=np.bool_:raise ValueError('actual_contact_frame_mask_required')
    # Incidental, non-gripping contact is preserved in source; only actual
    # force-qualified grasps are classified as arm/rim assignments here.
    active=active&(arrays['gripper_contact_force']>contact_n)[:,:,None]
    # Preserve incidental short-side collisions in source. They do not become
    # a stable short-rim grasp unless actual controller confirmation supports
    # that classification. Export must rederive this mask from its recorded
    # confirmation events and actual force/jaw state, never a phase label.
    codes=long_rim_codes(arrays['gripper_tray_contact_points_local'],arrays['gripper_tray_contact_normals_local'],active,source['tray_dimensions'],reject_invalid=False)
    confirmed=arrays['gripper_grasp_confirmed']&(arrays['gripper_contact_force']>contact_n)
    if np.any(confirmed&(~np.isin(codes,(-1,1)))):raise ValueError('confirmed_short_or_unobserved_rim_grasp_forbidden')
    if codes.shape!=(frames,2):raise ValueError('contact_frame_alignment_required')
    yaw=final_axis_error(arrays['tray_long_axis_world'],arrays['robot_forward_world']);segments=[];pending=None
    for event in events:
        if event.get('event') not in ('action_start','action_complete'):continue
        label=event.get('action_label')
        if label not in LABELS:raise ValueError('unknown_new_task_action')
        if event['event']=='action_start':
            if pending is not None:raise ValueError('overlapping_action_windows')
            pending=(label,event);continue
        if pending is None or pending[0]!=label:raise ValueError('unmatched_action_completion')
        start=pending[1];a=start.get('frame');b=event.get('end_frame_exclusive');endpoint=event.get('measured_endpoint_frame')
        if any(type(v) is not int for v in (a,b,endpoint)) or not 0<=a<=endpoint<b<=frames or event.get('verified') is not True:raise ValueError('actual_halfopen_completed_action_required')
        force=arrays['gripper_contact_force'];released=np.all(force[endpoint]<=contact_n);loaded=arrays['payload_loaded'][a:b];table_audit=None
        if label in ('pick_empty','place_empty'):
            if loaded.any() or arrays['payload_mass'][a:b].any():raise ValueError('empty_action_contains_payload')
            if label=='pick_empty':
                lift=(arrays['support_contact'][a:b]==0)&(arrays['tray_clearance'][a:b]>=lifted_m);lift[endpoint-a]=True
                if not arrays['gripper_grasp_confirmed'][a:b][lift].all() or not np.all(force[a:b][lift]>contact_n) or np.any(np.prod(codes[a:b][lift],axis=1)!=-1):raise ValueError('actual_opposed_bilateral_lift_required')
            else:
                both=np.all(force[a:b]>contact_n,axis=1)
                if not both.any() or np.any(np.prod(codes[a:b][both],axis=1)!=-1):raise ValueError('actual_opposed_grasp_required')
        if label=='pick_empty' and not (np.all(force[endpoint]>contact_n) and arrays['support_contact'][endpoint]==0 and arrays['floor_contact'][endpoint]==0 and arrays['tray_clearance'][endpoint]>=lifted_m):raise ValueError('actual_pick_lift_required')
        if label=='pick_empty' and not (np.any(table_counts[a:endpoint,source_table]>0) and footprint[a,source_table]):raise ValueError('actual_pick_source_table_required')
        if label=='place_empty':
            release_start=event.get('release_start_frame')
            if type(release_start) is not int or not a<release_start<=endpoint or not arrays['gripper_grasp_confirmed'][a:release_start].all() or not np.all(force[a:release_start]>contact_n):raise ValueError('bilateral_opposed_carry_until_actual_release_required')
            if not (released and table_counts[endpoint,target_table]>0 and footprint[endpoint,target_table] and arrays['floor_contact'][endpoint]==0 and yaw[endpoint]<=final_yaw_tolerance_rad):raise ValueError('actual_place_target_table_support_release_alignment_required')
        if label=='push_loaded':
            stages=arrays['push_stage'][a:b];order=[int(x) for i,x in enumerate(stages) if x and (i==0 or x!=stages[i-1])]
            if order!=[1,2,3,4] or result.get('actual_handover_verified') is not True:raise ValueError('whole_ordered_push_handover_window_required')
            f=force[a:b];position=arrays['tray_position'][a:b];left=arrays['robot_left_world'][a:b]
            right=np.flatnonzero(stages==1);bilateral=np.flatnonzero(stages==2);release=np.flatnonzero(stages==3);last=np.flatnonzero(stages==4)
            # Stage1 also includes left approach/close before the actual stable
            # handover callback. Preserve those contacts, but prove right-push
            # only using its measured right-only interval, never both-hand drag.
            right_only=right[(f[right,1]>contact_n)&(f[right,0]<=contact_n)]
            if not (len(right_only)>=2 and np.all(f[right,1]>contact_n) and len(bilateral)>=3 and np.all(f[bilateral]>contact_n) and np.all(f[release,0]>contact_n) and np.any(f[release,1]<=contact_n) and np.any((f[last,0]>contact_n)&(f[last,1]<=contact_n))):raise ValueError('actual_handover_contact_order_required')
            right_motion=float((position[right_only[-1]]-position[right_only[0]])@left[right_only[0]])
            if right_motion<=0:raise ValueError('actual_right_and_left_push_motion_required')
            driven=last[(f[last,0]>contact_n)&(f[last,1]<=contact_n)]
            if len(driven)<2:raise ValueError('actual_left_driven_tray_motion_required')
            left_motion=float((position[driven[-1]]-position[last[0]])@left[last[0]])
            if left_motion<source['minimum_left_tray_motion_m']:raise ValueError('actual_left_tray_motion_below_declared_minimum')
            if not (loaded.all() and np.all(arrays['payload_mass'][a:b]>0) and arrays['payload_supported_objects'][endpoint].all() and released and arrays['tray_goal_reached'][endpoint] and arrays['support_contact'][endpoint]>0 and arrays['floor_contact'][endpoint]==0):raise ValueError('actual_loaded_push_final_guard_required')
            supported=arrays['support_contact'][a:b]>0
            if declared_table_rule:
                table_audit=audit_table_support_acceptance(source,numeric,start_frame=a,end_frame=b,endpoint_frame=endpoint)
            elif not footprint[a:b,target_table].all():raise ValueError('whole_push_target_table_geometry_required')
            if np.any(table_counts[a:b,target_table][supported]<=0):raise ValueError('whole_push_target_table_geometry_required')
            if table_audit is not None:table_audit.update(actual_right_tray_motion_m=right_motion,actual_left_tray_motion_m=left_motion,minimum_left_tray_motion_m=source['minimum_left_tray_motion_m'],goal_reference='actual_left_phase_origin_tray_motion_not_tcp_or_table_edge')
        segments.append(dict(schema='airport_three_table_single_tray_action_segment/1',task_profile=PROFILE,task_rule_revision=RULE_REVISION,final_orientation_definition=FINAL_ORIENTATION_DEFINITION,**ACTION_VOCABULARY[LABELS.index(label)],task_index=LABELS.index(label),start_frame=a,end_frame=b,measured_endpoint_frame=endpoint,final_actual_yaw_error_rad=float(yaw[endpoint]) if label=='place_empty' else None,parent_scene_id=source['parent_scene_id'],split=source['split'],scene_id=source['scene_id'],source=dict(source),source_event_sha256=canonical_hash([start,event]),training_eligible=True))
        if table_audit is not None:segments[-1]['table_support_acceptance_audit']=table_audit
        pending=None
    eligible=result.get('training_eligible') is True
    if not eligible and result.get('training_eligible') is False and source.get('qualification_repair'):
        repair=source['qualification_repair'];original=Path(source.get('result',''));prior=original.parent/'source_qualification_audit.json'
        if repair.get('schema')!='airport_actual_command_qualification_repair/1' or repair.get('original_raw_events_unchanged') is not True or not original.is_file() or digest(original)!=repair.get('original_result_sha256') or digest(original)!=source.get('result_sha256') or json.loads(original.read_text())!=result or not prior.is_file() or digest(prior)!=repair.get('original_qualification_sha256'):
            raise ValueError('additive_annotation_repair_original_identity_required')
        previous=json.loads(prior.read_text());audit=repair.get('command_audit',{})
        if previous.get('verified') is not False or previous.get('error')!='actual_recorded_gripper_commands_required' or audit.get('verified') is not True or audit.get('source_trace_sha256')!=source['trace_sha256'] or audit.get('raw_commands_and_actions_unchanged') is not True or source['grasp_confirmation_rule'].get('command_evidence_mode')!='actual_submitted_actuator_opening' or audit.get('evidence')!=source['grasp_confirmation_rule'].get('command_actuator_evidence'):
            raise ValueError('additive_actual_command_repair_proof_required')
        eligible=True
    if pending is not None or tuple(s['action_label'] for s in segments)!=LABELS or result.get('task_profile')!=PROFILE or any(result.get(k) is not True for k in ('task_completed','physics_success')) or not eligible:raise ValueError('fresh_scope_whole_completed_task_required')
    mask=np.zeros(frames,bool)
    for row in segments:
        a,b=row['start_frame'],row['end_frame']
        if mask[a:b].any():raise ValueError('overlapping_action_windows')
        mask[a:b]=True
    return dict(schema='airport_three_table_single_tray_action_plan/1',task_profile=PROFILE,task_rule_revision=RULE_REVISION,final_orientation_definition=FINAL_ORIENTATION_DEFINITION,action_vocabulary=list(ACTION_VOCABULARY),source=dict(source),segments=segments,environment_excluded_frames=np.flatnonzero(~mask).tolist(),source_frames=frames,supervised_frames=int(mask.sum()),dataset_ready=False)


def bc_input_contract(plan):
    if plan.get('schema')!='airport_three_table_single_tray_action_plan/1' or plan.get('task_profile')!=PROFILE or tuple(x.get('action_label') for x in plan.get('segments',[]))!=LABELS:raise ValueError('fresh_whole_three_action_plan_required')
    if plan.get('task_rule_revision')!=RULE_REVISION or plan.get('final_orientation_definition')!=FINAL_ORIENTATION_DEFINITION or any(s.get('task_rule_revision')!=RULE_REVISION or s.get('final_orientation_definition')!=FINAL_ORIENTATION_DEFINITION for s in plan['segments']):raise ValueError('bc_requires_fresh_forward_axis_plan')
    source_validate(plan['source'])
    return dict(prompt_mode=PROFILE,task_profile=PROFILE,task_rule_revision=RULE_REVISION,final_orientation_definition=FINAL_ORIENTATION_DEFINITION,action_width=19,action_semantics='absolute_mobile19',base_mode='planar_mobile_table_front',base_actuated=True,model_action_mask=[True]*19,environment_phase_excluded=True,requires_official_dataset_and_native_four_camera_audits=True,dataset_ready=False)
