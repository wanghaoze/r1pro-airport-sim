import json,copy
import numpy as np
import pytest
from r1pro_teleop.vla.data_three_table_single_tray import PROFILE,RULE_REVISION,FINAL_ORIENTATION_DEFINITION,source_validate,plan_action_segments,bc_input_contract,digest,final_axis_error,derive_grasp_confirmations,table_geometry_values
from r1pro_teleop.vla.data_single_tray import canonical_hash


def fixture(tmp_path,split='validation'):
    parent=dict(scene_id='parent',split=split,tables=[dict(table_id=x) for x in ('front_left','front_right','rear')]);p=tmp_path/'parent.json';p.write_text(json.dumps(parent))
    manifest=tmp_path/'manifest.json';manifest.write_text(json.dumps(dict(scenes=[dict(scene_id='parent',json='parent.json',split=split)])))
    registry=tmp_path/'registry.json';registry.write_text(json.dumps(dict(parent=split)))
    source=dict(schema='airport_three_table_single_tray_source/1',task_profile=PROFILE,source='simulation/program_generated',tray_count=1,table_count=3,fps=20,action_semantics='absolute_mobile19',state_semantics='measured_joint16_plus_base_origin_offset3',base_mode='planar_mobile_table_front',base_actuated=True,model_action_mask=[True]*19,variant_seed=1,parent_scene_id='parent',scene_id='parent_variant1',parent_scene_json=str(p),parent_scene_json_sha256=digest(p),parent_manifest=str(manifest),parent_manifest_sha256=digest(manifest),canonical_split_registry=str(registry),canonical_split_registry_sha256=digest(registry),parent_resource_split=split,parent_split=split,split='val' if split=='validation' else split,source_table='rear',target_table='front_left',route_goal_observation_policy='fixed_registered_rear_to_front_left_route',random_initial_pose=dict(xy=[.8,.1],yaw_rad=.42),grasp_requirement='bilateral_opposed_long_rims',contact_evidence_semantics='actual_mujoco_finger_tray_contacts_local',tray_dimensions=[.56,.43,.105],frames=40)
    source.update({k:'a'*64 for k in ('trace_sha256','scene_xml_sha256','scene_json_sha256','controller_sha256')})
    source.update(task_rule_revision=RULE_REVISION,final_orientation_definition=FINAL_ORIENTATION_DEFINITION)
    source.update(payload_support_object_order=['laptop','backpack','coat'],payload_support_evidence_semantics='actual_tray_contact_graph_registered_payload_entities')
    source.update(loaded_goal_policy='handover_left_motion_then_release',minimum_left_tray_motion_m=.03)
    source['loaded_bridge_profile']=dict(loaded_goal_policy=source['loaded_goal_policy'],minimum_left_tray_motion_m=.03)
    source['loaded_bridge_profile_sha256']=canonical_hash(source['loaded_bridge_profile'])
    source['grasp_confirmation_rule']=dict(schema='airport_existing_grasp_confirmation_rule/1',rule_id='recorded_controller_force_wait',controller_sha256=source['controller_sha256'],transition_journal_complete=True,stable_duration_s=.15,contact_n=.5,release_opening_min_m=.06)
    n=40;force=np.zeros((n,2));force[:17]=2;force[25:28,1]=2;force[28:31]=2;force[31:39,0]=2
    points=np.zeros((n,2,1,3));points[:,0,0,1]=.21;points[:,1,0,1]=-.21;normals=np.zeros_like(points);normals[:,:,0,1]=points[:,:,0,1]/.21;active=(force>0)[:,:,None]
    position=np.zeros((n,3));position[25:,1]=np.arange(15)*.01
    support=np.ones(n);support[9]=0;stages=np.zeros(n);stages[25:28]=1;stages[28:31]=2;stages[31:34]=3;stages[34:]=4
    loaded=np.zeros(n);loaded[25:]=1
    numeric=dict(payload_loaded=loaded,payload_mass=loaded*2,gripper_contact_force=force,support_contact=support,floor_contact=np.zeros(n),tray_clearance=np.ones(n)*.1,tray_goal_reached=np.arange(n)==39,tray_position=position,tray_long_axis_world=np.tile([1,0,0],(n,1)),robot_forward_world=np.tile([1,0,0],(n,1)),robot_left_world=np.tile([0,1,0],(n,1)),base_front_violation=np.zeros(n),push_stage=stages,gripper_tray_contact_points_local=points,gripper_tray_contact_normals_local=normals,gripper_tray_contact_active=active)
    table_counts=np.zeros((n,3));table_counts[:10,2]=support[:10];table_counts[10:,0]=support[10:]
    footprint=np.zeros((n,3),bool);footprint[:10,2]=True;footprint[10:,0]=True
    numeric.update(table_contact_counts=table_counts,tray_footprint_on_table=footprint)
    mask=np.zeros((n,2),bool);mask[2:17]=True;mask[27:31,1]=True;mask[30:39,0]=True
    numeric['gripper_grasp_confirmed']=mask;numeric['gripper_openings']=np.where(force>0,.03,.1)
    numeric['payload_supported_objects']=np.repeat(loaded.astype(bool)[:,None],3,axis=1)
    events=[]
    for label,a,b in [('pick_empty',0,10),('place_empty',10,20),('push_loaded',25,40)]:events +=[dict(event='action_start',action_label=label,frame=a),dict(event='action_complete',action_label=label,end_frame_exclusive=b,measured_endpoint_frame=b-1,verified=True)]
    events[3]['release_start_frame']=17
    for event,frame,sides,start in [('grasp_confirmed',2,['left','right'],0),('grasp_released',17,['left','right'],None),('grasp_confirmed',27,['right'],25),('grasp_confirmed',30,['left'],28),('grasp_released',31,['right'],None),('grasp_released',39,['left'],None)]:
        events.append(dict(schema='airport_actual_grasp_confirmation_event/1',event=event,frame=frame,sides=sides,confirmation_rule_id='recorded_controller_force_wait',stable_start_frame=start,after_existing_close_confirmation=True))
    result=dict(task_profile=PROFILE,task_completed=True,physics_success=True,training_eligible=True,actual_handover_verified=True)
    return source,events,result,numeric


def plan(data):return plan_action_segments(*data,contact_n=.5,lifted_m=.04,final_yaw_tolerance_rad=.05)


def test_new_scope_full_windows_mobile19_parent_split_and_environment_exclusion(tmp_path):
    data=fixture(tmp_path);p=plan(data)
    assert [(s['start_frame'],s['end_frame']) for s in p['segments']]==[(0,10),(10,20),(25,40)]
    assert p['environment_excluded_frames']==list(range(20,25)) and not p['dataset_ready']
    assert p['segments'][1]['final_actual_yaw_error_rad']==0 and p['source']['parent_split']=='validation' and p['source']['split']=='val'
    assert [s['language_prompt'] for s in p['segments']]==['Pick up the tray','Place the tray','Flush tray to the left']
    c=bc_input_contract(p);assert c['base_actuated'] and c['model_action_mask']==[True]*19 and not c['dataset_ready']


@pytest.mark.parametrize('change',['old_scope','same_edge','short_edge','yaw','incomplete_push','no_right_motion','wrong_split','inactive_base','not_whole','hidden_target','one_hand_carry','place_wrong_table','push_wrong_table','push_footprint_outside'])
def test_nonqualifying_sources_do_not_become_new_expert_data(tmp_path,change):
    s,e,r,n=fixture(tmp_path)
    if change=='old_scope':s['task_profile']='single_tray_action3_v1'
    elif change=='same_edge':n['gripper_tray_contact_points_local'][:,1,0,1]=.21
    elif change=='short_edge':n['gripper_tray_contact_points_local'][9,0,0]=[.28,0,.07]
    elif change=='yaw':n['tray_long_axis_world'][19]=[0,1,0]
    elif change=='incomplete_push':n['push_stage'][31:34]=2
    elif change=='no_right_motion':n['tray_position'][25:28]=0
    elif change=='wrong_split':s['split']='train'
    elif change=='inactive_base':s['model_action_mask'][18]=False
    elif change=='hidden_target':s['target_table']='front_right'
    elif change=='one_hand_carry':n['gripper_contact_force'][12,0]=0
    elif change=='place_wrong_table':n['table_contact_counts'][19]=[0,0,1];n['tray_footprint_on_table'][19]=[False,False,True]
    elif change=='push_wrong_table':n['table_contact_counts'][30]=[0,0,1]
    elif change=='push_footprint_outside':n['tray_footprint_on_table'][30,0]=False
    else:r['task_completed']=False
    with pytest.raises(ValueError):plan((s,e,r,n))


def test_actual_axis_is_unoriented_parallel_not_fixed_world_y():
    assert final_axis_error([1,0,0],[-1,0,0])==0
    assert final_axis_error([0,1,0],[1,0,0])==pytest.approx(np.pi/2)


def test_changed_parent_cannot_remap_split_or_relabel(tmp_path):
    s,_,_,_=fixture(tmp_path);source_validate(s)
    with open(s['parent_scene_json'],'w') as f:json.dump(dict(scene_id='parent',split='train'),f)
    with pytest.raises(ValueError,match='parent_source_changed'):source_validate(s)


def test_registered_split_wins_over_different_local_resource_split(tmp_path):
    s,_,_,_=fixture(tmp_path);p=s['parent_scene_json'];parent=json.loads(open(p).read());parent['split']='test';open(p,'w').write(json.dumps(parent));s['parent_scene_json_sha256']=digest(p);s['parent_resource_split']='test'
    assert source_validate(s)['split']=='val'
    s['split']='test'
    with pytest.raises(ValueError,match='split_leakage'):source_validate(s)


def test_initial_one_mm_gap_and_push_microgap_do_not_invent_wrong_table(tmp_path):
    s,e,r,n=fixture(tmp_path)
    n['support_contact'][0]=0;n['table_contact_counts'][0]=0
    n['tray_clearance'][0]=.001
    n['support_contact'][35]=0;n['table_contact_counts'][35]=0
    assert plan((s,e,r,n))['supervised_frames']==35
    # Raw gaps remain preserved; the source controller's continuous-substep
    # grace audit is still required by the downstream physical export gate.
    assert n['support_contact'][35]==0


def test_single_arm_prepare_stays_in_pick_before_real_opposed_lift(tmp_path):
    s,e,r,n=fixture(tmp_path)
    n['gripper_contact_force'][:4,1]=0;n['gripper_tray_contact_active'][:4,1]=False
    n['tray_clearance'][:4]=.001
    n['gripper_tray_contact_points_local'][:4,0,0]=[.1,.21,.07]
    n['tray_position'][:4,1]=[0,.005,.010,.015]
    next(x for x in e if x.get('event')=='grasp_confirmed' and x['frame']==2)['sides']=['left']
    e.append(dict(schema='airport_actual_grasp_confirmation_event/1',event='grasp_confirmed',frame=6,sides=['right'],confirmation_rule_id='recorded_controller_force_wait',stable_start_frame=4,after_existing_close_confirmation=True));n['gripper_grasp_confirmed'][2:6,1]=False
    p=plan((s,e,r,n))
    assert p['segments'][0]['start_frame']==0 and p['segments'][0]['end_frame']==10
    assert p['segments'][0]['language_prompt']=='Pick up the tray'
    n['gripper_contact_force'][9,1]=0
    with pytest.raises(ValueError,match='bilateral_lift'):plan((s,e,r,n))


def test_forward_axis_revision_rejects_old_left_goal_and_axis_record(tmp_path):
    s,e,r,n=fixture(tmp_path);p=plan((s,e,r,n))
    assert p['final_orientation_definition']==FINAL_ORIENTATION_DEFINITION
    old=copy.deepcopy(s);old['final_orientation_definition']='tray_long_axis_parallel_robot_left_unoriented'
    with pytest.raises(ValueError,match='forward_axis_rule'):plan((old,e,r,n))
    old=copy.deepcopy(s);old.pop('task_rule_revision')
    with pytest.raises(ValueError,match='forward_axis_rule'):source_validate(old)
    n['tray_long_axis_world'][19]=n['robot_left_world'][19]
    with pytest.raises(ValueError,match='alignment'):plan((s,e,r,n))
    p['segments'][1]['final_orientation_definition']='robot_left'
    with pytest.raises(ValueError,match='forward_axis_plan'):bc_input_contract(p)


def test_parallel_axis_tracks_measured_robot_heading_with_pi_equivalence(tmp_path):
    s,e,r,n=fixture(tmp_path)
    n['robot_forward_world'][19]=[0,-1,0];n['tray_long_axis_world'][19]=[0,1,0]
    assert plan((s,e,r,n))['segments'][1]['final_actual_yaw_error_rad']==0


def test_horizontal_yaw_is_not_tilt_and_vertical_projection_fails_closed():
    assert final_axis_error([.9,0,.4],[1,0,.1])==0
    with pytest.raises(ValueError,match='horizontal'):final_axis_error([0,0,1],[1,0,0])


def test_preparation_short_bump_retained_but_actual_confirmed_short_grasp_rejected(tmp_path):
    s,e,r,n=fixture(tmp_path);n['gripper_contact_force'][:2,1]=0
    n['gripper_tray_contact_active'][:2,1]=False;n['tray_clearance'][:2]=.001
    n['gripper_tray_contact_points_local'][0,0,0]=[.28,0,.07]
    n['gripper_grasp_confirmed'][0]=False
    next(x for x in e if x.get('event')=='grasp_confirmed' and x['frame']==2)['sides']=['left']
    e.append(dict(schema='airport_actual_grasp_confirmation_event/1',event='grasp_confirmed',frame=4,sides=['right'],confirmation_rule_id='recorded_controller_force_wait',stable_start_frame=2,after_existing_close_confirmation=True));n['gripper_grasp_confirmed'][2:4,1]=False
    assert plan((s,e,r,n))['segments'][0]['start_frame']==0
    n['gripper_tray_contact_points_local'][2,0,0]=[.28,0,.07]
    with pytest.raises(ValueError,match='confirmed_short'):plan((s,e,r,n))


def test_confirmation_bool_without_matching_actual_event_or_force_is_rejected(tmp_path):
    s,e,r,n=fixture(tmp_path);assert np.array_equal(derive_grasp_confirmations(s,e,n,contact_n=.5),n['gripper_grasp_confirmed'])
    n['gripper_grasp_confirmed'][0,0]=True
    with pytest.raises(ValueError,match='not_rederived'):derive_grasp_confirmations(s,e,n,contact_n=.5)
    n['gripper_grasp_confirmed'][0,0]=False;n['gripper_contact_force'][1,0]=0
    with pytest.raises(ValueError,match='not_observed'):derive_grasp_confirmations(s,e,n,contact_n=.5)


def test_missing_confirmations_cannot_make_force_only_lift_an_expert(tmp_path):
    s,e,r,n=fixture(tmp_path);e=[x for x in e if x.get('schema')!='airport_actual_grasp_confirmation_event/1'];n['gripper_grasp_confirmed'][:]=False
    with pytest.raises(ValueError,match='bilateral_lift'):plan((s,e,r,n))


def test_stage1_left_acquisition_contacts_do_not_erase_proven_right_only_push(tmp_path):
    s,e,r,n=fixture(tmp_path)
    n['gripper_contact_force'][27,0]=2;n['gripper_tray_contact_active'][27,0]=True
    assert plan((s,e,r,n))['segments'][2]['training_eligible']
    # Moving only with both hands before the handover cannot prove right-push.
    n['tray_position'][25:27]=0
    with pytest.raises(ValueError,match='right_and_left_push_motion'):plan((s,e,r,n))


def grace_fixture(tmp_path):
    s,e,r,n=fixture(tmp_path)
    tables=[dict(table_id=key,center_world=[x,y,0],dimensions_m=[1.2,.6,.8],yaw_world=np.pi/2) for key,x,y in [('front_left',.85,0),('front_right',.85,-1.2),('rear',-1.08,0)]]
    parent=json.loads(open(s['parent_scene_json']).read());parent['tables']=tables
    open(s['parent_scene_json'],'w').write(json.dumps(parent));s['parent_scene_json_sha256']=digest(s['parent_scene_json'])
    s['table_support_geometry']=tables
    s['loaded_bridge_profile'].update(supported_boundary_margin_m=.005,push_transient_boundary_extra_m=.001)
    s['loaded_bridge_profile_sha256']=canonical_hash(s['loaded_bridge_profile'])
    s['table_support_acceptance_rule']=dict(schema='airport_recorded_table_support_acceptance/1',controller_sha256=s['controller_sha256'],trace_sha256=s['trace_sha256'],coverage='every_guarded_physics_substep',table_geometry_sha256=canonical_hash(tables),existing_footprint_margin_m=.005,extra_transient_footprint_margin_m=.001,grace_duration_s=.3,gap_cap_m=.001,physics_timestep_s=.002,substeps_per_interval=25)
    s['table_support_acceptance_rule']['loaded_bridge_profile_sha256']=s['loaded_bridge_profile_sha256']
    box=np.array([[x,y,z] for x in [-.215,.215] for y in [-.28,.28] for z in [0,.105]])
    corners=np.tile(box+[.85,0,.8],(40,1,1));corners[:10,:,0]-=1.93
    # A real corner exceeds the original 5 mm allowance by 24.6 micrometres.
    corners[30,:,0]+=.3-.215+.0050246
    n['tray_corners_world']=corners;n['tray_footprint_on_table']=table_geometry_values(corners,tables)[0]<=0
    n['guard_frame_index']=np.repeat(np.arange(25,40),25)
    n['guard_sim_time']=np.arange(375)*.002+1.252
    n['guard_tray_corners_world']=np.repeat(corners[25:],25,axis=0)
    n['guard_table_contact_counts']=np.repeat(n['table_contact_counts'][25:],25,axis=0)
    n['guard_push_contact_domain']=np.ones(375,bool)
    return s,e,r,n


def test_recorded_extra_one_mm_grace_preserves_strict_failure_and_final_original_gate(tmp_path):
    p=plan(grace_fixture(tmp_path));audit=p['segments'][2]['table_support_acceptance_audit']
    assert not audit['strict_zero_margin_footprint_all'] and audit['extra_transient_margin_m']==.001
    assert audit['actual_boundary_excess_peak_m']==pytest.approx(.0050246)
    assert audit['guard_rows_verified']==375 and audit['grace_episodes']==1
    assert audit['actual_grace_peak_duration_s']==pytest.approx(.05)
    assert audit['final_extra_margin_used'] is False


@pytest.mark.parametrize('change',['over_limit','long_duration','gap','missing_substep','wrong_binding','fake_strict','final_extra'])
def test_table_grace_cannot_hide_unbounded_or_unbound_geometry(tmp_path,change):
    s,e,r,n=grace_fixture(tmp_path)
    if change=='over_limit':n['guard_tray_corners_world'][125:150,:,0]+=.001
    elif change=='long_duration':n['guard_tray_corners_world'][:176,:,0]=n['guard_tray_corners_world'][125,:,0]
    elif change=='gap':n['guard_tray_corners_world'][125:150,:,2]+=.0011
    elif change=='missing_substep':
        for key in ('guard_frame_index','guard_sim_time','guard_tray_corners_world','guard_table_contact_counts','guard_push_contact_domain'):n[key]=np.delete(n[key],0,axis=0)
    elif change=='wrong_binding':s['table_support_acceptance_rule']['trace_sha256']='b'*64
    elif change=='fake_strict':n['tray_footprint_on_table'][30,0]=True
    elif change=='final_extra':
        n['tray_corners_world'][39]=n['tray_corners_world'][30];n['guard_tray_corners_world'][-25:]=n['tray_corners_world'][30]
        n['tray_footprint_on_table']=table_geometry_values(n['tray_corners_world'],s['table_support_geometry'])[0]<=0
    with pytest.raises(ValueError):plan((s,e,r,n))


def test_complete_flush_microgap_preserves_actual_false_live_domain(tmp_path):
    s,e,r,n=grace_fixture(tmp_path)
    n['guard_push_contact_domain'][125:150]=False
    audit=plan((s,e,r,n))['segments'][2]['table_support_acceptance_audit']
    assert audit['qualification_scope']=='complete_flush_window'
    assert audit['microgap_outside_live_guard_domain_rows']==25
    assert not n['guard_push_contact_domain'][125:150].any()


def test_existing_command_release_does_not_invent_measured_opening_minimum(tmp_path):
    s,e,r,n=fixture(tmp_path)
    rule=s['grasp_confirmation_rule'];rule.pop('release_opening_min_m');rule.update(release_evidence_mode='existing_low_force_commanded_open',existing_open_command_m=.08)
    n['gripper_command_openings']=np.where(n['gripper_contact_force']>0,0.,.08).astype(np.float32)
    n['gripper_openings'][n['gripper_contact_force']==0]=.035
    n['gripper_openings'][17]=.10102053  # Real servo overshoot is not a new annotation gate.
    n['gripper_command_openings'][17]=np.float32(.1)
    for event in e:
        if event.get('event')=='grasp_released':event.update(release_command_start_frame=event['frame'],after_existing_release_verification=True)
    assert plan((s,e,r,n))['supervised_frames']==35
    n['gripper_command_openings'][17]=0
    with pytest.raises(ValueError,match='open_command_release'):plan((s,e,r,n))


def test_submitted_controls_prove_release_without_clipping_or_relabeling_raw_reference(tmp_path):
    import hashlib
    s,e,r,n=fixture(tmp_path);rule=s['grasp_confirmation_rule']
    rule.pop('release_opening_min_m');rule.update(release_evidence_mode='existing_low_force_commanded_open',existing_open_command_m=.1,command_evidence_mode='actual_submitted_actuator_opening')
    raw=np.where(n['gripper_contact_force']>0,0.,.10000127544604663)
    n['gripper_command_openings']=raw.copy()
    ctrl=np.repeat(np.where(n['gripper_contact_force']>0,0.,.0500006377696991)[:,None,:],25,axis=1)
    n['gripper_control_substeps']=ctrl;n['gripper_effective_command_openings']=np.clip(ctrl[:,0,:],.002,.05)*2
    proof=dict(shape=list(ctrl.shape),dtype=str(ctrl.dtype),sha256=hashlib.sha256(ctrl.tobytes()).hexdigest())
    rule['command_actuator_evidence']=dict(schema='airport_actual_gripper_actuator_command/1',scene_xml_sha256=s['scene_xml_sha256'],actuator_names=['left_gripper_target','right_gripper_target'],opening_multiplier=2,ctrlranges=[[.002,.05],[.002,.05]],raw_control_journal_sha256=canonical_hash(proof),control_range_semantics='mujoco_ctrllimited_internal_clamp',actuator_ctrllimited=[True,True],raw_trace_sha256=s['trace_sha256'])
    for event in e:
        if event.get('event')=='grasp_released':event.update(release_command_start_frame=event['frame'],after_existing_release_verification=True)
    assert plan((s,e,r,n))['supervised_frames']==35
    np.testing.assert_array_equal(n['gripper_command_openings'],raw)
    r['training_eligible']=False
    original=tmp_path/'result.json';original.write_text(json.dumps(r))
    prior=tmp_path/'source_qualification_audit.json';prior.write_text(json.dumps(dict(verified=False,error='actual_recorded_gripper_commands_required')))
    s.update(result=str(original),result_sha256=digest(original))
    s['qualification_repair']=dict(schema='airport_actual_command_qualification_repair/1',original_raw_events_unchanged=True,original_result_sha256=digest(original),original_qualification_sha256=digest(prior),command_audit=dict(verified=True,source_trace_sha256=s['trace_sha256'],raw_commands_and_actions_unchanged=True,evidence=rule['command_actuator_evidence']))
    assert plan((s,e,r,n))['supervised_frames']==35
    assert json.loads(original.read_text())['training_eligible'] is False
    s['qualification_repair']['original_qualification_sha256']='b'*64
    with pytest.raises(ValueError,match='repair_original_identity'):plan((s,e,r,n))
    s['qualification_repair']['original_qualification_sha256']=digest(prior)
    n['gripper_effective_command_openings'][17,0]=.09
    with pytest.raises(ValueError,match='projection_not_verified'):plan((s,e,r,n))


def fifty_mm_fixture(tmp_path):
    s,e,r,n=grace_fixture(tmp_path)
    profile=dict(s['loaded_bridge_profile'],supported_boundary_margin_m=.05,position_tolerance_m=.05,push_transient_boundary_extra_m=0.)
    s['loaded_bridge_profile']=profile;s['loaded_bridge_profile_sha256']=canonical_hash(profile)
    s['table_support_acceptance_rule'].update(existing_footprint_margin_m=.05,extra_transient_footprint_margin_m=0.,loaded_bridge_profile_sha256=canonical_hash(profile))
    # Supported throughout, including >.3s outside old5mm: never missing contact.
    n['tray_corners_world'][25:,:,0]=n['tray_corners_world'][25,:,0]+.125
    n['tray_corners_world'][39,:,1]+=.28  # Real left edge .56, target .60: 4cm error.
    n['guard_tray_corners_world']=np.repeat(n['tray_corners_world'][25:],25,axis=0)
    n['tray_footprint_on_table']=table_geometry_values(n['tray_corners_world'],s['table_support_geometry'])[0]<=0
    return s,e,r,n


def test_source_bound_total_50mm_supported_boundary_is_not_missing_contact(tmp_path):
    p=plan(fifty_mm_fixture(tmp_path));audit=p['segments'][2]['table_support_acceptance_audit']
    assert audit['existing_margin_m']==.05 and audit['extra_transient_margin_m']==0
    assert not audit['strict_zero_margin_footprint_all'] and not audit['old_5mm_footprint_all']
    assert audit['grace_episodes']==0 and audit['actual_grace_peak_duration_s']==0
    assert audit['actual_boundary_excess_peak_m']==pytest.approx(.04)
    assert audit['actual_left_tray_motion_m']==pytest.approx(.04)
    assert audit['goal_reference']=='actual_left_phase_origin_tray_motion_not_tcp_or_table_edge'


@pytest.mark.parametrize('change',['stacked_extra','profile_hash','over_total','missing_object','wrong_object_order','no_contact_long','short_left_motion'])
def test_new_50mm_rule_is_bound_total_and_requires_all_payloads_and_true_edge(tmp_path,change):
    s,e,r,n=fifty_mm_fixture(tmp_path)
    if change=='stacked_extra':s['table_support_acceptance_rule']['extra_transient_footprint_margin_m']=.001
    elif change=='profile_hash':s['loaded_bridge_profile']['supported_boundary_margin_m']=.06
    elif change=='over_total':
        n['guard_tray_corners_world'][:,:,0]+=.011
    elif change=='missing_object':n['payload_supported_objects'][39,2]=False
    elif change=='wrong_object_order':s['payload_support_object_order']=['coat','backpack','laptop']
    elif change=='short_left_motion':n['tray_position'][34:39,1]=np.arange(5)*.005
    else:n['guard_table_contact_counts'][:176]=0
    with pytest.raises(ValueError):plan((s,e,r,n))

def test_axis_error_uses_scalar_libm_for_actual_one_ulp_case_and_preserves_inputs(monkeypatch):
    import math
    cosine=float.fromhex('0x1.fffffee2fab12p-1')
    y=math.sqrt((1.-cosine)*(1.+cosine))
    tray=np.array([[cosine,y,.3],[-cosine,-y,-.7]],dtype=np.float64)
    forward=np.array([[1.,0.,.2],[1.,0.,-.4]],dtype=np.float64)
    original_tray=tray.copy();original_forward=forward.copy()
    monkeypatch.setattr(np,'arccos',lambda *a:pytest.fail('NumPy SIMD acos must not define the annotation'))
    result=final_axis_error(tray,forward)
    expected=math.acos(cosine)
    assert expected.hex()==float(.0002576073785863697).hex()
    assert [v.hex() for v in result]==[expected.hex(),expected.hex()]
    assert result.shape==(2,) and result.dtype==np.float64
    np.testing.assert_array_equal(tray,original_tray);np.testing.assert_array_equal(forward,original_forward)
    assert final_axis_error(tray[0],forward[0]).hex()==result[0].hex()


def test_axis_error_batch_shape_matches_scalar_path_at_near_parallel_and_opposed():
    import math
    angles=[0.,1e-6,.001,.3,math.pi/2,math.pi-.1,math.pi]
    tray=np.array([[math.cos(a),math.sin(a),.4] for a in angles]).reshape(1,7,3)
    forward=np.broadcast_to([1.,0.,-.2],tray.shape).copy()
    batch=final_axis_error(tray,forward)
    assert batch.shape==(1,7)
    assert [v.hex() for v in batch.flat]==[final_axis_error(a,b).hex() for a,b in zip(tray.reshape(-1,3),forward.reshape(-1,3))]
