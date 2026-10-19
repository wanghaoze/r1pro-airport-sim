import mujoco
import numpy as np
import pytest
from types import SimpleNamespace
from r1pro_teleop.single_tray_3table.loaded_bridge import LoadedBridgeController,LoadedBridgeProfile
from r1pro_teleop.single_tray_lab.control import ControlProfile


def test_bridge_source_20mm_contract_is_explicit_and_does_not_relax_original_profile():
    with pytest.raises(ValueError):ControlProfile(max_penetration_m=.02,planning_gripper_preload_max_m=.02).validate()
    p=LoadedBridgeProfile(max_penetration_m=.02,source_collision_penetration_m=.02,planning_gripper_preload_max_m=.02)
    assert p.validate() is p
    with pytest.raises(ValueError,match='collision_contract_mismatch'):
        LoadedBridgeProfile(max_penetration_m=.01,source_collision_penetration_m=.02).validate()


def test_bound_controller_actual_contact_evidence_is_bounded_and_written_to_event_journal(tmp_path):
    import json
    journal=tmp_path/'actual_events.jsonl'
    def sink(row):
        with journal.open('a') as f:f.write(json.dumps(row)+'\n')
    r=runtime_fixture();c=LoadedBridgeController.bind(r,LoadedBridgeProfile(),passenger_loader=lambda sim:None,on_event=sink)
    contact=dict(entities=['robot_geom_47','passenger_backpack_collision'],distance_m=-.0003,penetration_m=.0003,normal_force_n=4.)
    obs=dict(base=c.base_origin.copy(),illegal_contacts=[],payload_floor_contacts=0,payload_mass_kg=0.,
        max_penetration=.0003,hard_max_penetration=.0003,soft_payload_max_penetration=0.,tray_bottom_z=.8,table_contacts=4,
        tray_corners=np.array([[.6,-.5,.8],[1.1,.02,.8]]),
        robot_payload_contacts=[contact])
    c.observation=lambda:obs
    for i in range(1000):
        r.d.time=i/10;c.phase='phase_'+str(i);c.guard()
    stats=c.robot_payload_contact_statistics()
    assert stats['guard_checks']==1000 and stats['guard_checks_with_contacts']==1000
    assert stats['contact_point_observations']==1000 and stats['penetration_peak_m']==.0003
    assert stats['normal_force_peak_n']==4. and stats['events_written']==32 and stats['event_limit_reached']
    assert len(journal.read_text().splitlines())==32
    assert all(json.loads(line)['scope']=='actual_live_guard_substeps_only_private_predictions_excluded' for line in journal.read_text().splitlines())
    # Copy returned to serializers cannot mutate the live accumulator.
    stats['guard_checks']=0
    assert c.robot_payload_contact_statistics()['guard_checks']==1000


def test_bound_controller_faulting_actual_contact_counts_but_private_observation_does_not(tmp_path):
    r=runtime_fixture();c=LoadedBridgeController.bind(r,LoadedBridgeProfile(),passenger_loader=lambda sim:None)
    c.event=lambda *a,**kw:None
    contact=dict(entities=['robot_geom_47','passenger_backpack_collision'],distance_m=-.004,penetration_m=.004,normal_force_n=8.)
    obs=dict(base=c.base_origin.copy(),illegal_contacts=[],payload_floor_contacts=0,payload_mass_kg=0.,
        max_penetration=.004,hard_max_penetration=.004,soft_payload_max_penetration=0.,tray_bottom_z=.8,table_contacts=4,
        tray_corners=np.array([[.6,-.5,.8],[1.1,.02,.8]]),
        robot_payload_contacts=[contact])
    c.observation=lambda:obs
    assert c._penetration_exceeds(obs)
    assert c.robot_payload_contact_statistics()['guard_checks']==0
    with pytest.raises(Exception,match='excess_penetration'):c.guard()
    stats=c.robot_payload_contact_statistics()
    assert stats['guard_checks']==1 and stats['penetration_peak_m']==.004 and c.p.max_penetration_m==.003


def test_new_left_motion_origin_requires_actual_right_release_and_bilateral_confirmation():
    r=runtime_fixture();c=LoadedBridgeController.bind(r,LoadedBridgeProfile(
        loaded_goal_policy='handover_left_motion_then_release'),passenger_loader=lambda sim:None)
    c.event=lambda *a,**k:None;c.left_reference_captured=True
    c.right_motion_origin=np.array([.85,.05,.8])
    obs=dict(tray_position=np.array([.85,.16,.8]),gripper_contact_force={'left':30.,'right':9.})
    c.handover_verified=True;c._capture_actual_left_origin(obs)
    assert c.left_motion_origin is None
    obs['gripper_contact_force']['right']=0.;c.handover_verified=False;c._capture_actual_left_origin(obs)
    assert c.left_motion_origin is None
    c.handover_verified=True;c._capture_actual_left_origin(obs)
    np.testing.assert_array_equal(c.left_motion_origin,obs['tray_position'])
    obs['tray_position']=np.array([.85,.17,.8]);c._capture_actual_left_origin(obs)
    assert c.left_motion_origin[1]==.16  # origin is never reset per reference.


def test_new_left_three_cm_cannot_be_swallowed_by_old_five_cm_goal_tolerance():
    r=runtime_fixture();c=LoadedBridgeController.bind(r,LoadedBridgeProfile(
        loaded_goal_policy='handover_left_motion_then_release',position_tolerance_m=.05),passenger_loader=lambda sim:None)
    c.left_motion_origin=np.array([.85,.16,.8]);c.left_motion_axis=np.array([0.,1.,0.]);c.handover_verified=True
    c._on_table=lambda obs:obs['supported']
    obs=dict(tray_position=np.array([.85,.189,.8]),gripper_contact_force={'left':30.,'right':0.},supported=True)
    assert c.loaded_goal_remaining(obs)>.05 and not c.loaded_goal_reached(obs)
    obs['tray_position'][1]=.191
    assert c.loaded_goal_remaining(obs)==0 and c.loaded_goal_reached(obs)
    obs['supported']=False
    assert not c.loaded_goal_reached(obs)


def test_new_left_motion_profile_does_not_replace_historical_edge_default():
    assert LoadedBridgeProfile().loaded_goal_policy=='table_left_edge'
    with pytest.raises(ValueError,match='loaded_goal_policy'):LoadedBridgeProfile(loaded_goal_policy='fake').validate()


def runtime_fixture():
    m=mujoco.MjModel.from_xml_string('''<mujoco><worldbody><body name="base_link" pos=".1 .2 0"><joint name="bx" type="slide" axis="1 0 0"/><geom size=".1" mass="1"/></body><body name="tray" pos=".8 0 .8"><freejoint/><geom size=".1" mass="1"/></body><body name="table"><geom size=".2"/></body></worldbody><actuator><motor joint="bx"/></actuator></mujoco>''')
    d=mujoco.MjData(m);d.qpos[0]=.04;d.qvel[0]=.01;d.ctrl[0]=.03;mujoco.mj_forward(m,d)
    sim=SimpleNamespace(model=m,data=d,base_target=np.array([.04,.02,.03]),base_state=lambda:np.array([.14,.2,0.]))
    return SimpleNamespace(sim=sim,m=m,d=d,mj=mujoco,cfg=SimpleNamespace(fps=20,completion_collision_penetration_m=.003,rim_height_local_m=.082,rim_inset_m=.01),
        steps=688,integration_spec=mujoco.mjtState.mjSTATE_INTEGRATION,
        integration_size=mujoco.mj_stateSize(m,mujoco.mjtState.mjSTATE_INTEGRATION),trace=None)


def test_bind_real_mujoco_bookkeeping_cannot_reset_or_rebuild_simulation(monkeypatch):
    from r1pro_teleop.airport_recording import AirportSimulation
    monkeypatch.setattr(AirportSimulation,'__init__',lambda *a,**k:pytest.fail('new model prohibited'))
    r=runtime_fixture();q=r.d.qpos.copy();v=r.d.qvel.copy();ctrl=r.d.ctrl.copy();target=r.sim.base_target.copy()
    c=LoadedBridgeController.bind(r,LoadedBridgeProfile(),passenger_loader=lambda sim:None)
    assert c.sim is r.sim and c.d is r.d and c.m is r.m
    assert c.frames==688
    np.testing.assert_array_equal(r.d.qpos,q);np.testing.assert_array_equal(r.d.qvel,v)
    np.testing.assert_array_equal(r.d.ctrl,ctrl);np.testing.assert_array_equal(r.sim.base_target,target)
    np.testing.assert_array_equal(c.base_origin,[.14,.2,0.])


def test_bridge_tick_uses_original_journal_and_restores_guard_on_failed_substep():
    r=runtime_fixture();c=LoadedBridgeController.bind(r,LoadedBridgeProfile(),passenger_loader=lambda sim:None)
    calls=[];original=lambda:calls.append('original');r.guard=original
    c.guard=lambda:calls.append('bridge')
    c.observation=lambda:{'actual':True}
    def tick():
        r.guard();calls.append(r.sim.base_target.copy());raise RuntimeError('physical failure')
    r.tick=tick
    with pytest.raises(RuntimeError,match='physical failure'):c.tick()
    assert r.guard is original and calls[:2]==['original','bridge']
    np.testing.assert_array_equal(calls[2],[.04,.02,.03])


def test_bridge_event_uses_actual_parent_journal_even_when_parent_returns_none():
    r=runtime_fixture();c=LoadedBridgeController.bind(r,LoadedBridgeProfile(),passenger_loader=lambda sim:None)
    receipts=[];r.trace=SimpleNamespace(event=lambda name,**details:receipts.append((name,details)))
    row=c.event('private_reference',actual=True)
    assert row is c.events[-1]
    assert row['frame']==688 and row['payload_loaded'] is False
    assert receipts==[('private_reference',{k:v for k,v in row.items() if k not in ('event','frame')})]

def test_actual_old_grasp_goal_height_and_opposed_long_rim_material_points():
    from r1pro_teleop.airport_fsm.runtime import Runtime
    from r1pro_teleop.airport_fsm.contracts import Config
    r=runtime_fixture();r.cfg=Config(rim_height_local_m=.075,rim_pitch_deg=-35.,rim_inset_m=.01)
    r.g=SimpleNamespace(sizes=np.array([[.56,.43,.105]]))
    r.grasp_goals=lambda *a,**k:Runtime.grasp_goals(r,*a,**k)
    r.observation=lambda:{'tray_pose':np.array([[.8,0,.8,1,0,0,0]])}
    c=LoadedBridgeController.__new__(LoadedBridgeController);c.runtime=r;c.sim=r.sim
    goals=c._grasp_goals()
    np.testing.assert_allclose(goals['left'][0],[.8,.205,.875])
    np.testing.assert_allclose(goals['right'][0],[.8,-.205,.875])
    np.testing.assert_allclose(goals['left'][1].T@goals['left'][1],np.eye(3),atol=1e-12)


def test_loaded_edge_target_recomputed_for_forward_tray_not_empty_place_reference():
    from r1pro_teleop.single_tray_3table.loaded_bridge import derive_bridge_profile
    r=runtime_fixture();r.g=SimpleNamespace(tables={'table':{'center_world':[.85,0,0],'yaw_world':np.pi/2,'dimensions_m':[1.2,.6,.8]}},sizes=np.array([[.56,.43,.105]]))
    p=derive_bridge_profile(r,{'target_table':'table','payloads':[]},ControlProfile())
    assert p.loaded_goal_position[1]+.28==pytest.approx(.575)
    c=LoadedBridgeController.__new__(LoadedBridgeController);c.p=p
    corners=np.array([[x,y,z] for x in (-.28,.28) for y in (-.215,.215) for z in (0,.105)])+[.85,0,.8]
    obs={'tray_corners':corners,'table_contacts':4}
    assert c.loaded_goal_remaining(obs)==pytest.approx(.36)
    obs['tray_corners']=corners+[0,.36,0]
    assert c.loaded_goal_reached(obs)


def test_acquire_executes_real_parent_smooth_opening_api_with_injected_mujoco_ticks():
    r=runtime_fixture();r.sim.target=np.zeros(16);r.sim.target[[7,15]]=.1
    c=LoadedBridgeController.bind(r,LoadedBridgeProfile(),passenger_loader=lambda sim:None)
    c.action='push_loaded'
    c._grasp_goals=lambda:{'right':(np.array([.8,-.205,.882]),np.eye(3))}
    c.move=lambda *a,**k:None
    jaw=[];times=[]
    def tick():
        # Exercise the original _opening reference updater and real MuJoCo
        # integration. Contact verification is explicitly injected, not a
        # claim about the mechanical gripper fixture.
        jaw.append(float(r.sim.target[15]));mujoco.mj_step(r.m,r.d);c.frames+=1;times.append(r.d.time)
        return {'gripper_contact_force':{'right':1.,'left':0.}}
    c.tick=tick
    result=c.acquire(('right',),prefix='right_')
    assert c.holding_sides=={'right'} and result['gripper_contact_force']['right']==1.
    assert len(jaw)==50
    np.testing.assert_allclose(np.diff([.1]+jaw),-.002,atol=1e-12)
    assert times[-1]>times[0] and c.events[-1]['event']=='grasp_contact_verified'


def test_outward_release_exercises_real_branch_math_and_actual_long_rim_direction():
    from dataclasses import replace
    r=runtime_fixture();r.sim.target=np.zeros(16);r.sim.target[15]=.02;r.sim.state=lambda:r.sim.target.copy()
    p=replace(LoadedBridgeProfile(),push_command_reference=True,push_right_outward_release=True)
    c=LoadedBridgeController.bind(r,p,passenger_loader=lambda sim:None)
    c.action='push_loaded';c.holding_sides={'left','right'};c.handover_verified=True
    c.rim_outward_local={'right':np.array([0.,-1.,0.])}
    c.push_anchor=('right',np.zeros(3),np.zeros(3),np.eye(3));c.push_last_reference_position=np.zeros(3)
    c.observation=lambda:{'gripper_contact_force':{'left':1.,'right':0.}}
    references=[]
    def move(goals,*,openings,**kwargs):
        references.append(goals['right'][0].copy());r.sim.target[15]=openings['right']
        mujoco.mj_step(r.m,r.d)
    c.move=move
    c.release(('right',),predicate=lambda o:o['gripper_contact_force']['left']>.5)
    assert c.holding_sides=={'left'} and r.sim.target[15]==pytest.approx(.1)
    assert len(references)>=40
    assert all(p[0]==0. and p[1]<0. and p[2]==0. for p in references)
    assert any(e['event']=='right_outward_open_complete' for e in c.events)

def boundary_fixture(extra=.001):
    from dataclasses import replace
    r=runtime_fixture();p=replace(LoadedBridgeProfile(),push_table_contact_grace_frames=6,push_transient_boundary_extra_m=extra)
    c=LoadedBridgeController.bind(r,p,passenger_loader=lambda sim:None)
    c.action='push_loaded';c.phase='left_push'
    corners=np.array([[x,y,.8] for x in (.544975,.9) for y in (-.2,.2)])
    return c,{'tray_corners':corners,'tray_bottom_z':.8,'table_contacts':0}


def test_authorized_micro_boundary_uses_original_finite_support_timer_and_recovers():
    c,obs=boundary_fixture();c.d.time=1.
    assert c._observe_push_table_support(obs) is None
    c.d.time=1.298
    assert c._observe_push_table_support(obs) is None
    assert not c.strict_push_footprint_gate_passed
    assert c.observed_boundary_extra_peak_m==pytest.approx(.000025)
    assert not c._on_table(obs)  # No final-support predicate relaxation.
    restored={**obs,'tray_corners':obs['tray_corners']+[.0001,0,0],'table_contacts':4}
    c.d.time=1.3
    assert c._observe_push_table_support(restored) is None
    assert c.boundary_grace_recoveries==1 and c._push_table_missing_since is None
    assert c.boundary_grace_max_duration_s==pytest.approx(.3)
    assert c._on_table(restored)


def test_boundary_extra_cannot_exceed_one_mm_gap_cap_or_point_three_seconds():
    c,obs=boundary_fixture();c.d.time=1.
    assert c._observe_push_table_support(obs) is None
    c.d.time=1.302
    assert c._observe_push_table_support(obs).code=='single_tray_push_table_contact_grace_exhausted'
    c,obs=boundary_fixture();obs['tray_corners'][0,0]=.5439
    assert c._observe_push_table_support(obs).code=='single_tray_push_missing_support_outside_grace_geometry'
    c,obs=boundary_fixture();obs['tray_bottom_z']=.80101
    assert c._observe_push_table_support(obs).code=='single_tray_push_missing_support_outside_grace_geometry'


def test_default_preserves_old_boundary_and_final_goal_does_not_accept_extended_margin():
    c,obs=boundary_fixture(extra=0.)
    assert c._observe_push_table_support(obs).code=='single_tray_push_missing_support_outside_grace_geometry'
    c,obs=boundary_fixture();obs['table_contacts']=4
    obs['tray_corners'][:,1]+=.575-.2
    assert not c.loaded_goal_reached(obs)
    with pytest.raises(ValueError,match='0_to_1mm'):
        LoadedBridgeProfile(push_transient_boundary_extra_m=.00101).validate()
    with pytest.raises(ValueError,match='finite_support_grace'):
        LoadedBridgeProfile(push_transient_boundary_extra_m=.001).validate()

def test_scene_boundary_profile_is_explicit_and_old_scene_defaults_zero():
    from dataclasses import replace
    from r1pro_teleop.single_tray_3table.loaded_bridge import derive_bridge_profile
    r=runtime_fixture();r.g=SimpleNamespace(tables={'table':{'center_world':[.85,0,0],'yaw_world':np.pi/2,'dimensions_m':[1.2,.6,.8]}},sizes=np.array([[.56,.43,.105]]))
    scene={'target_table':'table','payloads':[]}
    reference=replace(ControlProfile(),push_table_contact_grace_frames=6)
    old=derive_bridge_profile(r,scene,reference)
    assert old.push_transient_boundary_extra_m==0.
    declared={**scene,'loaded_push_target':{'transient_boundary_extra_m':.001,'existing_boundary_numeric_margin_m':.005,
        'transient_support_grace_s':.3,'transient_lowest_corner_gap_m':.001,'final_boundary_extra_m':0.}}
    new=derive_bridge_profile(r,declared,reference)
    assert new.push_transient_boundary_extra_m==.001
    assert new.max_penetration_m==old.max_penetration_m and new.loaded_goal_position==old.loaded_goal_position
    assert new.push_table_contact_grace_frames==old.push_table_contact_grace_frames==6
    declared['loaded_push_target']['final_boundary_extra_m']=.001
    with pytest.raises(ValueError,match='final_boundary'):derive_bridge_profile(r,declared,reference)

def test_selected_five_cm_boundary_needs_real_contact_and_does_not_add_five_cm_to_old_margin():
    from dataclasses import replace
    c,obs=boundary_fixture(extra=0.)
    c.p=replace(c.p,supported_boundary_margin_m=.05)
    obs['tray_corners'][:,0]-=.04  # total overhang45.025mm, inside selected50
    obs['table_contacts']=4
    assert c._on_table(obs)
    c.d.time=1.
    assert c._observe_push_table_support(obs) is None and c._push_table_missing_since is None
    obs['table_contacts']=0
    assert not c._on_table(obs)
    assert c._observe_push_table_support(obs) is None
    c.d.time=1.302
    assert c._observe_push_table_support(obs).code=='single_tray_push_table_contact_grace_exhausted'
    obs['table_contacts']=4;obs['tray_corners'][:,0]-=.0051
    assert not c._on_table(obs)  # total50.125mm cannot pass.
    with pytest.raises(ValueError,match='total_cannot_exceed'):
        replace(c.p,push_transient_boundary_extra_m=.001).validate()


def test_new_edge_zero_reserve_and_five_cm_tolerance_are_bound_from_scene_only():
    from dataclasses import replace
    from r1pro_teleop.single_tray_3table.loaded_bridge import derive_bridge_profile
    r=runtime_fixture();r.g=SimpleNamespace(tables={'table':{'center_world':[.85,0,0],'yaw_world':np.pi/2,'dimensions_m':[1.2,.6,.8]}},sizes=np.array([[.56,.43,.105]]))
    old={'target_table':'table','payloads':[]}
    source=replace(ControlProfile(),push_table_contact_grace_frames=6)
    oldp=derive_bridge_profile(r,old,source)
    new={**old,'loaded_push_target':{'table_edge_margin_m':0.,'supported_boundary_margin_m':.05,'goal_edge_tolerance_m':.05,'transient_boundary_extra_m':0.}}
    p=derive_bridge_profile(r,new,source)
    assert oldp.supported_boundary_margin_m==.005 and oldp.position_tolerance_m==.03
    assert oldp.loaded_goal_position[1]+.28==pytest.approx(.575)
    assert p.loaded_goal_position[1]+.28==pytest.approx(.6)
    assert p.supported_boundary_margin_m==.05 and p.position_tolerance_m==.05
    assert not p.push_axis_feedback_enabled and p.max_penetration_m==oldp.max_penetration_m
    c=LoadedBridgeController.__new__(LoadedBridgeController);c.p=p
    corners=np.array([[x,y,.8] for x in (.51,1.1) for y in (.14,.55)])
    obs={'tray_corners':corners,'table_contacts':4}
    assert c.loaded_goal_reached(obs)  # actualedge .55 is exactly5cm from .6
    obs['tray_corners'][:,1]-=.001
    assert not c.loaded_goal_reached(obs)  # .549 is51mm from genuine tableedge.

def test_explicit_base_five_cm_preserves_old_default_yaw_gate_and_actual_front(monkeypatch):
    from dataclasses import replace
    from r1pro_teleop.single_tray_lab.control import SingleTrayController
    r=runtime_fixture();r.m.body_pos[r.m.body('table').id]=[.85,0,0];r.m.body_quat[r.m.body('table').id]=[np.sqrt(.5),0,0,np.sqrt(.5)];mujoco.mj_forward(r.m,r.d)
    r.manifest={'target_table':'table'};r.g=SimpleNamespace(tables={'table':{'dimensions_m':[1.2,.6,.8]}})
    c=LoadedBridgeController.bind(r,replace(LoadedBridgeProfile(),base_drift_m=.05),passenger_loader=lambda sim:None)
    c.action='push_loaded'
    # Exercise real inherited base predicate with an injected finite contact
    # observation; all contact/task acceptance remains separately covered.
    obs={'base':np.array([.18,.2,.003]),'hard_max_penetration':0.,'soft_payload_max_penetration':0.,'illegal_contacts':[],
        'payload_floor_contacts':0,'payload_mass_kg':2.05,'max_penetration':0.,'tray_corners':np.array([[.6,0,.8],[1.1,.3,.8]]),'tray_bottom_z':.8,'table_contacts':4}
    c.observation=lambda:obs
    r.sim.base_state=lambda:obs['base'].copy()
    c.guard();assert not c.strict_base_5mm_gate_passed
    assert c.statistics()['observed_base_drift_peak_m']==pytest.approx(.04)
    obs['base']=np.array([.1901,.2,.003])
    with pytest.raises(Exception,match='fixed_base_drift'):c.guard()
    obs['base']=np.array([.18,.2,.0101])
    with pytest.raises(Exception,match='fixed_base_drift'):c.guard()
    # Remain within selected5cm of a station near long-edge end yet move
    # outside table front. This cannot be accepted as passive drift.
    c.base_origin=np.array([.14,.58,0.]);obs['base']=np.array([.14,.62,0.])
    with pytest.raises(Exception,match='outside_target_table_front'):c.guard()
    assert LoadedBridgeProfile().base_drift_m==.005
    with pytest.raises(ValueError,match='up_to_5cm'):replace(c.p,base_drift_m=.0501).validate()
