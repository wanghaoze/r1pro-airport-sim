from dataclasses import replace
import numpy as np
import pytest
from r1pro_teleop.single_tray_lab.control import ControlProfile,SingleTrayController,long_front_goals
from r1pro_teleop.airport_fsm.contracts import Fault


def test_two_hands_share_front_long_edge_and_jaws_cross_wall():
    profile=ControlProfile();R=np.array([[0,-1,0],[1,0,0],[0,0,1.]])
    center=np.array([.85,-.24,.801]);goals=long_front_goals(center,R,profile)
    local={side:R.T@(point-center) for side,(point,_) in goals.items()}
    assert local['left'][1]==pytest.approx(.205) and local['right'][1]==pytest.approx(.205)
    assert local['left'][0]>0 and local['right'][0]<0
    for _,tool in goals.values():
        assert abs(tool[:,1]@np.array([-1,0,0]))==pytest.approx(1);assert np.linalg.det(tool)==pytest.approx(1)
    with pytest.raises(Fault,match='long_rim_not_facing'):long_front_goals(center,np.eye(3),profile)


def test_measured_midwall_goals_align_pad_to_real_taper_and_stay_on_long_rim():
    profile=ControlProfile(grasp_mode='wall_mid_taper',rim_height=.07,grasp_half_separation=.20)
    R=np.array([[0,-1,0],[1,0,0],[0,0,1.]])
    center=np.array([.85,-.24,.801]);goals=long_front_goals(center,R,profile)
    for side,(point,tool) in goals.items():
        pad=point+.00811*tool[:,2];local=R.T@(pad-center)
        outer=.19753+(local[2]-.008)*(.01747/.097)
        inner=.18753+(local[2]-.012)*(.01747/.093)
        assert local[1]==pytest.approx((outer+inner)/2)
        assert point[2]==pytest.approx(.871)
        assert local[0]==pytest.approx(.20 if side=='left' else -.20)
        assert tool[0,2]<0 and np.linalg.det(tool)==pytest.approx(1)
        np.testing.assert_allclose(tool.T@tool,np.eye(3),atol=1e-12)


def test_loaded_left_end_goal_allows_inside_table_forward_offset_but_not_wrong_left_coordinate():
    c=fake_handover();goal=np.array([.79,.295,.801])
    corners=np.array([[.575,.015,.801],[1.005,.015,.801],[.575,.575,.906],[1.005,.575,.906]])
    obs=dict(tray_position=goal,tray_corners=corners,table_contacts=4)
    assert c.loaded_goal_reached(obs)
    assert not c.loaded_goal_reached(dict(obs,tray_position=goal+np.array([0,-.031,0]),tray_corners=corners+[0,-.031,0]))
    assert not c.loaded_goal_reached(dict(obs,table_contacts=0))
    outside=corners.copy();outside[:,0]-=.04
    assert not c.loaded_goal_reached(dict(obs,tray_corners=outside))


def test_profile_rejects_side_access_nonfinite_and_invalid_budgets():
    for profile in (replace(ControlProfile(),fps=30),replace(ControlProfile(),push_step_m=float('nan')),
                    replace(ControlProfile(),stable_contact_frames=True),replace(ControlProfile(),front_normal=(0,0,1)),
                    replace(ControlProfile(),max_penetration_m=.0101,planning_gripper_preload_max_m=.02)):
        with pytest.raises(ValueError):profile.validate()


def fake_handover():
    controller=SingleTrayController.__new__(SingleTrayController);controller.p=ControlProfile()
    controller.holding_sides={'right'};controller.handover_verified=False;controller.action='push_loaded';controller.frames=0
    class Sim:
        target=np.zeros(16)
        def tcp(self,side):return np.array([.645,0,.90]),np.eye(3)
    controller.sim=Sim();controller.events=[]
    controller.event=lambda name,**kw:controller.events.append(name)
    controller.hold=lambda frames,predicate=None:dict(gripper_contact_force={'left':2.,'right':3.})
    controller.acquire=lambda sides,**kw:controller.holding_sides.update(sides)
    controller.move=lambda *a,**kw:None
    controller.tick=lambda:dict(gripper_contact_force={'left':2.,'right':3.})
    return controller


def test_handover_contact_precedes_every_right_open_command():
    c=fake_handover();releases=[]
    def release(sides,**kwargs):
        assert c.handover_verified and c.sim.target[15]==0
        assert c.events[-1]=='left_handover_contact_verified'
        assert kwargs['predicate']({'gripper_contact_force':{'left':2.}})
        releases.append(sides);c.holding_sides.difference_update(sides)
    c.release=release;c._handover()
    assert releases==[('right',)]
    assert c.events.index('left_handover_contact_verified')<c.events.index('right_released_after_left_contact')
    assert c.holding_sides=={'left'}


def test_right_release_without_left_verification_and_loss_during_open_rejected():
    c=fake_handover()
    with pytest.raises(Fault,match='right_release_before_left_contact'):c.release(('right',))
    assert c.sim.target[15]==0
    c.handover_verified=True;c.tick=lambda:dict(gripper_contact_force={'left':0.})
    with pytest.raises(Fault,match='handover_left_contact_lost'):
        c.release(('right',),predicate=lambda o:o['gripper_contact_force']['left']>.5)
    assert 'right' in c.holding_sides


def test_failed_left_acquire_never_releases_right():
    c=fake_handover()
    def failure(*a,**kw):raise Fault('single_tray_missing_grasp_contact')
    c.acquire=failure;c.release=lambda *a,**kw:pytest.fail('Right must stay closed')
    with pytest.raises(Fault):c._handover()
    assert not c.handover_verified


@pytest.fixture
def actual_controller(tmp_path):
    from r1pro_teleop.single_tray_lab.scene import generate_scene,LabSceneConfig
    scene=generate_scene(tmp_path/'scene',LabSceneConfig(cloth_enabled=False))
    rows=[];controller=SingleTrayController.from_scene(scene,on_frame=rows.append)
    yield controller,scene,rows
    controller.close()


def test_actual_mujoco_raw2_tick_preserves_pre_action_state_and_controls(actual_controller):
    c,scene,rows=actual_controller
    start=c.d.qpos.copy();t=float(c.d.time)
    c.tick();row=rows[0]
    np.testing.assert_array_equal(row['qpos'],start)
    assert row['state19'].shape==row['action19'].shape==(19,)
    assert row['sim_time']==t and c.d.time==pytest.approx(t+1/20)
    assert row['executed_substeps']==c.sim.nstep and row['transition_completed']
    assert row['ctrl_substeps'].shape==(c.sim.nstep,c.m.nu)
    np.testing.assert_array_equal(row['ctrl_substeps'],np.tile(row['ctrl_substeps'][0],(c.sim.nstep,1)))
    assert not row['training_segment'] and not row['payload_loaded']
    assert c.p.table_half_sizes_xy==pytest.approx((.3,.6))


def test_actual_action_endpoint_tick_emits_complete_event_with_live_identity(actual_controller):
    c,_,rows=actual_controller;c.action='pick_empty';c.phase='stabilize';c.loaded=False
    c._finish_action(0)
    assert c.frames==1 and len(rows)==1 and rows[0]['transition_completed']
    action=c.actions[0];event=c.events[-1]
    assert event['event']=='action_complete' and event['action_label']==action['action_label']=='pick_empty'
    assert event['payload_loaded']==action['payload_loaded']==False
    assert event['measured_endpoint_frame']==action['measured_endpoint_frame']==0
    assert event['end_frame_exclusive']==action['end_frame_exclusive']==1
    assert event['verified'] is True


def test_passenger_callback_cannot_modify_live_tray(actual_controller):
    c,_,_=actual_controller
    def malicious(sim):sim.data.qpos[c._protected_qpos[0]]+=.01;return {}
    c.passenger_loader=malicious
    with pytest.raises(Fault,match='environment_modified_robot_or_tray'):c.passenger_load()
    assert not c.loaded


def test_loaded_push_requires_actual_positive_mass_and_support():
    c=fake_handover();c.loaded=False
    c.observation=lambda:dict(payload_mass_kg=2.,payload_support_contacts=1)
    with pytest.raises(Fault,match='push_requires_real_load'):c.push_loaded()
    c.loaded=True;c.observation=lambda:dict(payload_mass_kg=0.,payload_support_contacts=1)
    with pytest.raises(Fault,match='push_requires_real_load'):c.push_loaded()




def test_real_multistart_joint_goal_is_pose_accurate_collision_safe_and_private(tmp_path):
    from r1pro_teleop.single_tray_lab.scene import generate_scene,LabSceneConfig
    scene=generate_scene(tmp_path/'aligned_scene',LabSceneConfig(robot_x=.15,robot_y=-.24))
    c=SingleTrayController.from_scene(scene);c.p=replace(c.p,grasp_half_separation=.20)
    try:
        qpos=c.d.qpos.copy();qvel=c.d.qvel.copy();ctrl=c.d.ctrl.copy();target=c.sim.target.copy();stamp=float(c.d.time)
        goals={s:(p+np.array([0,0,c.p.approach_clearance]),R) for s,(p,R) in c._grasp_goals().items()}
        planned=c.plan_joint_goal(goals)
        np.testing.assert_array_equal(c.d.qpos,qpos);np.testing.assert_array_equal(c.d.qvel,qvel)
        np.testing.assert_array_equal(c.d.ctrl,ctrl);np.testing.assert_array_equal(c.sim.target,target)
        assert float(c.d.time)==stamp and c.frames==0
        assert c._joint_path_clear(target,planned)
        import mujoco
        shadow=mujoco.MjData(c.m);shadow.qpos[:]=qpos
        for side,offset in (('left',0),('right',8)):
            cols=[c.m.jnt_qposadr[j] for j in c.sim.arms[side]];shadow.qpos[cols]=planned[offset:offset+7]
        mujoco.mj_forward(c.m,shadow)
        for side,(position,rotation) in goals.items():
            assert np.linalg.norm(shadow.site(side+'_tcp').xpos-position)<.002
        assert planned[1]>0 and planned[9]<0  # no former lower-limit adduction stall
    finally:c.close()


def test_unsafe_private_path_never_submits_a_robot_command(actual_controller,monkeypatch):
    c,_,_=actual_controller;before=c.sim.target.copy()
    goals=c._grasp_goals()
    monkeypatch.setattr(c,'_ik_candidates',lambda side,*a,**kw:[(0.,np.zeros(7),0.,0.)])
    monkeypatch.setattr(c,'_joint_path_clear',lambda *a:False)
    monkeypatch.setattr(c,'tick',lambda:pytest.fail('Unsafe plan must not reach live physics'))
    with pytest.raises(Fault,match='private_joint_path_collision'):c.move(goals)
    np.testing.assert_array_equal(c.sim.target,before)


def test_quintic_reference_finishes_path_and_keeps_free_arm_fixed():
    c=fake_handover();c.p=ControlProfile(max_stage_steps=200);c.sim.target=np.zeros(16);submitted=[]
    target=np.zeros(16);target[0]=.3
    c.plan_joint_goal=lambda _:target.copy()
    c.sim.tcp=lambda side:(np.array([0.,0.,1.]),np.eye(3))
    c.tick=lambda:(submitted.append(c.sim.target.copy()) or dict(gripper_contact_force={'left':2.,'right':3.}))
    SingleTrayController.move(c,{'left':(np.array([0.,0.,1.]),np.eye(3))})
    commands=np.stack(submitted)
    assert len(commands)==25
    np.testing.assert_allclose(commands[-1],target)
    assert np.max(np.abs(np.diff(np.r_[0.,commands[:,0]])))*20<=.45+1e-8
    np.testing.assert_array_equal(commands[:,8:],np.zeros((25,8)))


def test_measured_endpoint_stops_reference_before_unnecessary_target_motion():
    c=fake_handover();c.p=ControlProfile(max_stage_steps=200);c.sim.target=np.zeros(16);submitted=[]
    target=np.zeros(16);target[0]=.3;c.plan_joint_goal=lambda _:target.copy()
    c.sim.tcp=lambda side:(np.array([0.,0.,1.]),np.eye(3))
    def tick():
        submitted.append(c.sim.target.copy())
        return dict(gripper_contact_force={'left':2.,'right':3.},endpoint=len(submitted)==4)
    c.tick=tick
    SingleTrayController.move(c,{'left':(np.array([0.,0.,1.]),np.eye(3))},
        predicate=lambda o:min(o['gripper_contact_force'].values())>.5,
        finish_predicate=lambda o:o['endpoint'])
    assert len(submitted)==4 and 0<c.sim.target[0]<target[0]
    np.testing.assert_array_equal(c.sim.target,submitted[-1])


def test_endpoint_does_not_override_lost_contact():
    c=fake_handover();c.sim.target=np.zeros(16);c.plan_joint_goal=lambda _:np.zeros(16)
    c.tick=lambda:dict(gripper_contact_force={'left':0.,'right':3.},endpoint=True)
    with pytest.raises(Fault,match='contact_lost'):
        SingleTrayController.move(c,{'left':(np.zeros(3),np.eye(3))},
            predicate=lambda o:o['gripper_contact_force']['left']>.5,
            finish_predicate=lambda o:o['endpoint'])


def test_place_release_requires_lowest_corner_height_and_complete_table_footprint():
    c=fake_handover()
    corners=np.array([[.60,-.5,.814],[1.10,-.5,.814],[.60,.1,.9],[1.10,.1,.9]])
    obs=dict(tray_corners=corners,tray_bottom_z=.814,table_contacts=0)
    assert c._place_release_ready(obs)  # real drop permitted without prior support
    assert not c._place_release_ready(dict(obs,tray_bottom_z=.821))
    assert not c._place_release_ready(dict(obs,tray_bottom_z=.796))
    outside=corners.copy();outside[0,0]=.549
    assert not c._place_release_ready(dict(obs,tray_corners=outside))
    nonfinite=corners.copy();nonfinite[0,2]=float('nan')
    assert not c._place_release_ready(dict(obs,tray_corners=nonfinite))
    with pytest.raises(ValueError,match='2 cm'):replace(c.p,place_release_clearance_m=.021).validate()


def test_place_near_table_releases_before_support_but_requires_actual_final_settle():
    c=fake_handover();c.loaded=False;c.holding_sides={'left','right'}
    obs=dict(tray_corners=np.array([[.6,-.5,.814],[1.1,-.5,.814],[.6,.1,.9],[1.1,.1,.9]]),
        tray_bottom_z=.814,table_contacts=0,gripper_contact_force={'left':3.,'right':3.},gripper_openings=[.02,.02])
    c.observation=lambda:obs
    c._held_move=lambda *a,**kw:pytest.fail('Already at safe release height; do not command further lowering')
    c.release=lambda sides: c.events.append('real_open_command')
    final=dict(obs,table_contacts=2,gripper_contact_force={'left':0.,'right':0.},gripper_openings=[.08,.08])
    c.hold=lambda *a,**kw:final
    c._finish_action=lambda start:c.events.append('completed_after_settle')
    c.place_empty()
    assert c.events.index('real_open_command')<c.events.index('completed_after_settle')
    c.hold=lambda *a,**kw:dict(final,table_contacts=0)
    with pytest.raises(Fault,match='empty_place_not_released'):c.place_empty()


def test_pick_margin_stops_above_acceptance_but_stabilization_retains_four_cm_gate():
    c=fake_handover();c.loaded=False;initial=dict(tray_bottom_z=.8,table_contacts=2,
        tray_position=np.array([.85,-.24,.8]),gripper_contact_force={'left':30.,'right':30.})
    c.observation=lambda:initial
    accepted=dict(initial,tray_bottom_z=.8451,table_contacts=0)
    def held(position,sides,*,finish_predicate):
        assert not finish_predicate(dict(accepted,tray_bottom_z=.8401))
        assert finish_predicate(accepted)
    c._held_move=held;c._finish_action=lambda start:pytest.fail('Below 4 cm cannot complete pick')
    c.tick=lambda:dict(accepted,tray_bottom_z=.8399)
    with pytest.raises(Fault,match='empty_lift_not_stable'):c.pick_empty()
    c.tick=lambda:dict(accepted,gripper_contact_force={'left':0.,'right':30.})
    with pytest.raises(Fault,match='contact_lost'):c.pick_empty()


def test_empty_place_surviving_hand_continues_and_lost_hand_reference_is_frozen():
    c=fake_handover();c.action='place_empty';c.p=ControlProfile(max_stage_steps=200)
    c.holding_sides={'left','right'};c.sim.target=np.zeros(16);commands=[];events=[]
    c.event=lambda name,**details:events.append(dict(event=name,**details))
    target=np.zeros(16);target[0]=target[8]=.3;c.plan_joint_goal=lambda _:target.copy()
    c.sim.tcp=lambda side:(np.array([0.,0.,1.]),np.eye(3))
    c.tick=lambda:(commands.append(c.sim.target.copy()) or dict(
        gripper_contact_force={'left':15.,'right':0.},tray_bottom_z=.83))
    goals={s:(np.array([0.,0.,1.]),np.eye(3)) for s in ('left','right')}
    SingleTrayController.move(c,goals,predicate=lambda o:min(o['gripper_contact_force'].values())>.5,
        allow_one_hand_recovery=True)
    commands=np.stack(commands)
    assert len(commands)==25 and c.holding_sides=={'left'}
    np.testing.assert_array_equal(commands[:,8],np.full(25,commands[0,8]))
    assert commands[-1,0]==pytest.approx(.3)
    recovery=[e for e in events if e['event']=='empty_place_one_hand_recovery']
    assert len(recovery)==1 and recovery[0]['lost_sides']==['right']
    assert recovery[0]['lowest_corner_gap_m']==pytest.approx(.03)
    np.testing.assert_array_equal(recovery[0]['frozen_arm_references']['right'],commands[0,8:15])
    c.tick=lambda:dict(gripper_contact_force={'left':0.,'right':0.},tray_bottom_z=.83)
    with pytest.raises(Fault,match='contact_lost'):
        SingleTrayController.move(c,goals,predicate=lambda o:False,allow_one_hand_recovery=True)
    c.action='push_loaded'
    with pytest.raises(ValueError,match='empty place'):
        SingleTrayController.move(c,goals,allow_one_hand_recovery=True)


def test_actual_command_fk_capture_does_not_modify_live_state(actual_controller):
    c,_,_=actual_controller;before=(c.d.qpos.copy(),c.d.qvel.copy(),c.d.ctrl.copy(),float(c.d.time),c.sim.target.copy())
    obs=c.observation();c._capture_held_tools(('left','right'),obs)
    np.testing.assert_array_equal(c.d.qpos,before[0]);np.testing.assert_array_equal(c.d.qvel,before[1])
    np.testing.assert_array_equal(c.d.ctrl,before[2]);assert c.d.time==before[3]
    np.testing.assert_array_equal(c.sim.target,before[4])
    for side in ('left','right'):
        offset,R=c.held_relative_tools[side]
        np.testing.assert_allclose(obs['tray_position']+obs['tray_rotation']@offset,c.sim.tcp(side)[0],atol=1e-6)
        assert np.linalg.det(R)==pytest.approx(1)


def test_pose_follow_uses_actual_rotation_and_bounds_each_joint_reference():
    c=fake_handover();c.action='pick_empty';c.p=replace(c.p,follow_tray_pose=True);c.sim.target=np.zeros(16)
    c.holding_sides={'left','right'};planned=[];commands=[]
    R=np.array([[0,-1,0],[1,0,0],[0,0,1.]])
    c.held_relative_tools={s:(np.array([.1,0,0]),np.eye(3)) for s in ('left','right')}
    obs=dict(tray_position=np.array([.8,-.24,.8]),tray_rotation=R,gripper_contact_force={'left':3.,'right':3.})
    c.observation=lambda:obs
    def plan(goals,**kwargs):
        assert kwargs['reference_step_rad']==pytest.approx(.45/20)
        planned.append(goals);return np.ones(16)
    c.plan_joint_goal=plan
    def tick():c.frames+=1;commands.append(c.sim.target.copy());return obs
    c.tick=tick
    c._held_pose_follow_move(np.array([.8,-.24,1.]),('left','right'),finish_predicate=lambda o:c.frames==3)
    for step,goals in enumerate(planned):
        for position,rotation in goals.values():
            np.testing.assert_array_equal(rotation,R)
            np.testing.assert_allclose(position,[.8,-.14,.8+.0025*(step+1)])
    assert len(commands)==3
    np.testing.assert_allclose(np.diff(np.vstack([np.zeros(16),commands]),axis=0)[:,[0,8]],.45/20)
    np.testing.assert_array_equal(np.array(commands)[:,[7,15]],np.zeros((3,2)))
    assert c.private_held_translation is None
    c.observation=lambda:dict(obs,gripper_contact_force={'left':0.,'right':0.})
    with pytest.raises(Fault,match='contact_lost'):
        c._held_pose_follow_move(obs['tray_position'],('left','right'),finish_predicate=lambda o:True)


def test_soft_payload_domain_is_registered_flex_only_and_keeps_hard_three_mm(actual_controller):
    c,_,_=actual_controller
    tray=next(iter(c.tray));table=next(iter(c.tables));robot=next(iter(c.robot));payload=next(iter(c.payload))
    for other in (tray,table,payload):
        assert c._is_soft_payload_pair('payload_flex',other)
        assert c._is_soft_payload_pair(other,'payload_flex')
    for other in (robot,0,'unknown_flex'):
        assert not c._is_soft_payload_pair('payload_flex',other)
    assert not c._is_soft_payload_pair(tray,payload)
    soft=dict(max_penetration=.00325,hard_max_penetration=.001,soft_payload_max_penetration=.00325)
    assert not c._penetration_exceeds(soft)
    assert c._penetration_exceeds(dict(soft,hard_max_penetration=.003001))
    assert c._penetration_exceeds(dict(soft,soft_payload_max_penetration=.005001))
    assert c._penetration_exceeds(dict(max_penetration=.00325))  # no untyped soft fallback
    with pytest.raises(ValueError):replace(c.p,soft_payload_penetration_m=float('nan')).validate()


def test_private_compliance_prediction_applies_only_new_reference_increment(actual_controller,monkeypatch):
    c,_,_=actual_controller;live_q=c.d.qpos.copy()
    start=c.sim.state().astype(float);c.sim.target=start.copy();c.sim.target[0]+=.05
    end=c.sim.target.copy();end[0]+=.02;observed=[]
    jid=int(c.sim.arms['left'][0]);qindex=int(c.m.jnt_qposadr[jid])
    def contacts(shadow):
        observed.append(float(shadow.qpos[qindex]))
        return dict(illegal_contacts=[],max_penetration=0.,hard_max_penetration=0.,soft_payload_max_penetration=0.)
    monkeypatch.setattr(c,'_contacts',contacts)
    c.private_incremental_command_prediction=True
    assert c._joint_path_clear(start,end,samples=3)
    assert observed[-1]==pytest.approx(start[0]+.02)
    np.testing.assert_array_equal(c.d.qpos,live_q)
    np.testing.assert_array_equal(c.sim.target,end-np.r_[.02,np.zeros(15)])
    c.private_incremental_command_prediction=False;observed.clear()
    assert c._joint_path_clear(start,end,samples=3)
    assert observed[-1]==pytest.approx(end[0])


def test_feedback_checks_exact_speed_limited_reference_not_full_ik_endpoint(actual_controller,monkeypatch):
    c,_,_=actual_controller;before=c.sim.target.copy();checked=[]
    candidate=before[:7].astype(float)+.2
    monkeypatch.setattr(c,'_ik_candidates',lambda *a,**kw:[(1.,candidate,0.,0.)])
    monkeypatch.setattr(c,'_joint_path_clear',lambda start,end:(checked.append(end.copy()) or True))
    c.private_incremental_command_prediction=True
    planned=c.plan_joint_goal({'left':c.sim.tcp('left')},reference_step_rad=.45/20)
    np.testing.assert_allclose(planned[:7]-before[:7],np.full(7,.45/20),atol=1e-8)
    np.testing.assert_array_equal(planned[8:],before[8:])
    np.testing.assert_array_equal(checked[0],planned)
    np.testing.assert_array_equal(c.sim.target,before)


def test_private_held_finger_preload_does_not_relax_actual_or_other_pairs(actual_controller):
    c,_,_=actual_controller;c.holding_sides={'left','right'}
    finger=next(b for b in c.robot if c.m.body(b).name.startswith('left_gripper_finger'))
    arm=next(b for b in c.robot if c.m.body(b).name.startswith('left_arm'))
    tray=next(iter(c.tray));table=next(iter(c.tables))
    assert c._is_held_finger_pair(finger,tray)
    assert not c._is_held_finger_pair(arm,tray)
    assert not c._is_held_finger_pair(finger,table)
    c.holding_sides={'right'};assert not c._is_held_finger_pair(finger,tray)
    contacts=dict(max_penetration=.006,hard_max_penetration=.006,
        non_preload_hard_max_penetration=.001,held_finger_tray_max_penetration=.006,soft_payload_max_penetration=0.)
    assert c._penetration_exceeds(contacts)  # actual substep hard gate always 3 mm
    assert not c._penetration_exceeds(contacts,planning_preload=True)
    assert c._penetration_exceeds(dict(contacts,held_finger_tray_max_penetration=.010001),planning_preload=True)
    assert c._penetration_exceeds(dict(contacts,non_preload_hard_max_penetration=.003001),planning_preload=True)


def test_scene_restores_complete_declared_control_profile_before_any_action(actual_controller,tmp_path):
    from dataclasses import asdict
    from r1pro_teleop.airport_fsm.contracts import json_default
    import json,copy
    c,scene,_=actual_controller
    profile=replace(c.p,soft_payload_penetration_m=.01,follow_tray_pose=True,grasp_half_separation=.20,
        lift_stop_margin_m=.008,place_release_clearance_m=.018)
    declared=copy.deepcopy(scene);declared['control_profile']=asdict(profile)
    saved=tmp_path/'declared_scene.json';saved.write_text(json.dumps(declared,default=json_default))
    declared=json.loads(saved.read_text());restored=ControlProfile.from_scene(declared)
    assert restored.soft_payload_penetration_m==.01 and restored.follow_tray_pose is True
    assert restored.grasp_half_separation==.20 and restored.lift_stop_margin_m==.008
    assert restored.place_release_clearance_m==.018
    before=c.d.qpos.copy();c.p=restored
    c._ik_candidates=lambda *a,**kw:pytest.fail('Runtime tick must not invoke teacher IK from provenance flags')
    c._held_pose_follow_move=lambda *a,**kw:pytest.fail('Runtime tick must not execute teacher pose-follow primitive')
    c.tick()  # learned runtime tick does not invoke teacher IK
    assert c.frames==1 and restored.follow_tray_pose
    bad=copy.deepcopy(declared);bad['control_profile']['loaded_goal_position'][1]+=.1
    with pytest.raises(ValueError,match='geometry mismatch'):ControlProfile.from_scene(bad)
    bad=copy.deepcopy(declared);bad['control_profile']['payload_bodies']=['unregistered']
    with pytest.raises(ValueError,match='identity mismatch'):ControlProfile.from_scene(bad)
    bad=copy.deepcopy(declared);bad['control_profile'].pop('follow_tray_pose')
    with pytest.raises(ValueError,match='complete known'):ControlProfile.from_scene(bad)
    bad=copy.deepcopy(declared);bad['control_profile']['soft_payload_penetration_m']=.02
    with pytest.raises(ValueError):ControlProfile.from_scene(bad)


def test_held_private_residual_tolerance_does_not_relax_free_grasp(actual_controller,monkeypatch):
    from scipy.spatial.transform import Rotation
    from types import SimpleNamespace
    import r1pro_teleop.single_tray_lab.control as module
    c,_,_=actual_controller;before=c.d.qpos.copy();p,R=c.sim.tcp('left')
    target=p+np.array([.006,0,0]);rotation=Rotation.from_rotvec([.04,0,0]).as_matrix()@R
    original=c.sim.target[:7].copy()
    monkeypatch.setattr(module,'least_squares',lambda *a,**kw:SimpleNamespace(x=original.copy()))
    assert c._ik_candidates('left',target,rotation,warm_only=True)==[]
    c.private_incremental_command_prediction=True;c.holding_sides={'left'}
    approximate=c._ik_candidates('left',target,rotation,warm_only=True)
    assert len(approximate)==1 and approximate[0][2]==pytest.approx(.006,abs=1e-7)
    assert approximate[0][3]==pytest.approx(.04)
    c.holding_sides=set()
    assert c._ik_candidates('left',target,rotation,warm_only=True)==[]
    np.testing.assert_array_equal(c.d.qpos,before)


def test_push_reference_preserves_commanded_height_despite_measured_lag():
    c=fake_handover();c.loaded=True;c.action='push_loaded'
    origin=np.array([.85,-.24,.8]);tcp=np.array([.6464,-.44,.871]);R=np.eye(3)
    c.push_anchor=('right',origin,tcp,R);goals=[]
    obs=dict(tray_position=origin.copy(),gripper_contact_force={'right':40.})
    c.observation=lambda:obs
    def move(g,**kw):
        assert c.private_incremental_command_prediction
        assert kw['finish_on_reference_submitted'] is True
        assert kw['predicate'](obs)
        np.testing.assert_allclose(c.private_held_translation,[0,.012,0])
        goals.append(g);return obs
    c.move=move
    c._push_reference_move(origin+np.array([0,.012,0]),'right')
    obs['tray_position']=origin+np.array([0,.001,0])
    c._push_reference_move(origin+np.array([0,.024,0]),'right')
    for i,g in enumerate(goals):
        np.testing.assert_allclose(g['right'][0],tcp+np.array([0,.012*(i+1),0]))
        assert g['right'][0][2]==.871
    assert c.private_incremental_command_prediction is False and c.private_held_translation is None
    with pytest.raises(Fault,match='holder_mismatch'):c._push_reference_move(origin,'left')


def test_push_accumulates_reference_until_explicit_lead_cap_when_tray_is_stuck():
    c=fake_handover();c.loaded=True;c.p=replace(c.p,push_command_reference=True)
    obs=dict(payload_mass_kg=2.,payload_support_contacts=1,tray_position=np.array([.85,-.24,.8]),
        tray_corners=np.array([[.635,-.52,.8],[1.065,.04,.905]]))
    c.observation=lambda:obs;c.sim.tcp=lambda side:(np.array([.6464,-.44,.871]),np.eye(3))
    c.base_origin=np.array([.15,-.24,0]);c.endpoint_reachable=lambda *a:True
    c._on_table=lambda o:True;c._capture_push_reference=lambda side:obs['tray_position'].copy()
    commands=[]
    class StopProbe(Exception):pass
    def move(position,side):
        assert side=='right';commands.append(position.copy())
        if len(commands)==5:raise StopProbe()
    c._push_reference_move=move
    with pytest.raises(StopProbe):c.push_loaded()
    np.testing.assert_allclose(np.array(commands)[:,1]-obs['tray_position'][1],[.012,.024,.036,.04,.04])
    np.testing.assert_array_equal(np.array(commands)[:,[0,2]],np.tile(obs['tray_position'][[0,2]],(5,1)))
    assert not c.handover_verified


def test_push_force_reference_ramp_is_not_reported_as_actual_pose_or_action_completion():
    c=fake_handover();c.p=replace(c.p,push_command_reference=True,max_stage_steps=100)
    c.action='push_loaded';c.sim.target=np.zeros(16);events=[];commands=[]
    target=np.zeros(16);target[8]=.3;c.plan_joint_goal=lambda _:target.copy()
    c.sim.tcp=lambda side:(np.array([0.,0.,1.]),np.eye(3))
    c.event=lambda name,**details:events.append(dict(event=name,**details))
    c.tick=lambda:(commands.append(c.sim.target.copy()) or dict(gripper_contact_force={'right':40.}))
    SingleTrayController.move(c,{'right':(np.array([0.,.04,1.]),np.eye(3))},minimum_seconds=.25,
        predicate=lambda o:o['gripper_contact_force']['right']>.5,finish_on_reference_submitted=True)
    assert len(commands)==25  # actual rate-limited .3 rad trajectory, no instantaneous command
    np.testing.assert_array_equal(commands[-1],target)
    assert events[-1]['event']=='push_reference_ramp_submitted'
    assert events[-1]['position_errors_m']==[.04] and events[-1]['strict_6mm_passed'] is False
    assert not any(e['event']=='action_complete' for e in events)
    c.action='place_empty'
    with pytest.raises(ValueError,match='explicit loaded push'):
        SingleTrayController.move(c,{},finish_on_reference_submitted=True)


def test_live_guard_peaks_exclude_private_geometry_and_remain_monotonic(actual_controller,monkeypatch):
    c,_,_=actual_controller;c.p=replace(c.p,max_penetration_m=.005,soft_payload_penetration_m=.01)
    obs=c.observation();obs.update(max_penetration=.008,hard_max_penetration=.0035,soft_payload_max_penetration=.008)
    monkeypatch.setattr(c,'observation',lambda:obs)
    c.guard()
    assert c.observed_hard_penetration_peak_m==.0035 and c.observed_soft_payload_penetration_peak_m==.008
    assert c.guarded_substeps==1
    obs.update(max_penetration=.002,hard_max_penetration=.002,soft_payload_max_penetration=.001)
    c.guard();assert c.observed_hard_penetration_peak_m==.0035
    assert c.guarded_substeps==2
    contacts=dict(illegal_contacts=[],max_penetration=.009,hard_max_penetration=.009,
        non_preload_hard_max_penetration=0.,held_finger_tray_max_penetration=.009,soft_payload_max_penetration=0.)
    monkeypatch.setattr(c,'_contacts',lambda d:contacts);c.private_allow_held_preload=True
    assert c._joint_path_clear(c.sim.state(),c.sim.target,samples=3)
    assert c.observed_hard_penetration_peak_m==.0035 and c.observed_soft_payload_penetration_peak_m==.008
    assert c.guarded_substeps==2
    obs.update(max_penetration=.006,hard_max_penetration=.006,soft_payload_max_penetration=0.)
    with pytest.raises(Fault,match='excess_penetration'):c.guard()
    assert c.guarded_substeps==3 and c.observed_hard_penetration_peak_m==.006


def test_explicit_place_recipe_dispatch_keeps_selected_limits_and_requests_withdrawal(monkeypatch):
    import r1pro_teleop.single_tray_lab.placement_recipe as module
    c=fake_handover();c.loaded=False;c.holding_sides={'left','right'}
    c.p=replace(c.p,place_inboard_slow_recipe=True)
    before=c.p;called=[]
    def recipe(controller,settings):
        assert controller is c and settings.withdraw is True
        assert controller.p.max_penetration_m==.003  # no implicit approximate acceptance
        called.append(settings);return 'actual-recipe-result'
    monkeypatch.setattr(module,'place_empty_recipe',recipe)
    assert c.place_empty()=='actual-recipe-result' and len(called)==1 and c.p is before
    with pytest.raises(ValueError):replace(c.p,place_inboard_slow_recipe=1).validate()


def test_push_vertical_relief_changes_only_declared_anchor_not_live_robot_or_tray(actual_controller,monkeypatch):
    c,_,_=actual_controller;c.loaded=True;c.holding_sides={'right'}
    c.p=replace(c.p,push_command_reference=True,push_vertical_relief_m=.005)
    obs=c.observation();obs.update(payload_mass_kg=2.,gripper_contact_force={'left':0.,'right':40.})
    monkeypatch.setattr(c,'observation',lambda:obs)
    before=(c.d.qpos.copy(),c.d.qvel.copy(),c.sim.target.copy(),float(c.d.time))
    tcp=c.sim.tcp('right')[0].copy();origin=c._capture_push_reference('right')
    np.testing.assert_allclose(c.push_anchor[2],tcp+[0,0,.005],atol=1e-7)
    np.testing.assert_array_equal(origin,obs['tray_position'])
    np.testing.assert_array_equal(c.d.qpos,before[0]);np.testing.assert_array_equal(c.d.qvel,before[1])
    np.testing.assert_array_equal(c.sim.target,before[2]);assert c.d.time==before[3]
    event=c.events[-1]
    assert event['vertical_reference_relief_m']==.005
    np.testing.assert_allclose(event['commanded_tcp_position'],tcp,atol=1e-7)
    np.testing.assert_allclose(event['push_tcp_anchor_position'],tcp+[0,0,.005],atol=1e-7)
    with pytest.raises(ValueError):replace(c.p,push_vertical_relief_m=.011).validate()


@pytest.mark.parametrize('phase',['right_push','left_push','vla_push_loaded'])
def test_contact_grace_is_bounded_by_actual_time_geometry_and_requires_final_support(actual_controller,monkeypatch,phase):
    c,_,_=actual_controller;c.p=replace(c.p,push_table_contact_grace_frames=6)
    c.action='push_loaded';c.phase=phase
    corners=np.array([[.635,-.52,.800005],[1.065,-.52,.800005],[.635,.04,.905],[1.065,.04,.905]])
    obs=c.observation();obs.update(tray_position=np.array([.85,-.24,.800005]),tray_corners=corners,
        tray_bottom_z=.800005,table_contacts=0,payload_mass_kg=2.)
    monkeypatch.setattr(c,'observation',lambda:obs)
    c.d.time=1.;c.guard()
    assert c._push_table_supported(obs) and c.strict_continuous_push_table_contact_gate is False
    assert not c.loaded_goal_reached(dict(obs,tray_position=np.array([.85,.295,.800005])))
    c.d.time=1.298;c.guard()  # frames unchanged: real physics time determines grace
    c.d.time=1.302
    with pytest.raises(Fault,match='grace_exhausted'):c.guard()
    assert c.push_table_contact_max_absent_duration_s==pytest.approx(.302)
    obs['table_contacts']=4;c.d.time=1.304;c.guard()
    assert c._push_table_missing_since is None and c.push_table_contact_grace_recoveries==1
    assert c.strict_continuous_push_table_contact_gate is False
    obs['table_contacts']=0;obs['tray_bottom_z']=.80101;c.d.time=1.306
    with pytest.raises(Fault,match='grace_geometry'):c.guard()


def test_contact_grace_does_not_cover_other_phases_or_outside_table(actual_controller,monkeypatch):
    c,_,_=actual_controller;c.p=replace(c.p,push_table_contact_grace_frames=6)
    obs=c.observation();obs.update(table_contacts=0,tray_bottom_z=.800005,payload_mass_kg=2.)
    c.action='environment';c.phase='passenger_settle'
    assert c._observe_push_table_support(obs) is None and c._push_table_missing_since is None
    c.action='push_loaded';c.phase='right_approach'
    assert c._observe_push_table_support(obs) is None and not c._push_table_supported(obs)
    c.phase='right_push';outside=np.asarray(obs['tray_corners']).copy();outside[0,0]=.544
    obs['tray_corners']=outside;monkeypatch.setattr(c,'observation',lambda:obs)
    with pytest.raises(Fault,match='grace_geometry'):c.guard()
    for p in (replace(c.p,push_table_contact_grace_frames=7),replace(c.p,push_table_contact_grace_frames=True),
              replace(c.p,push_table_contact_grace_gap_m=.0011)):
        with pytest.raises(ValueError):p.validate()


def test_default_zero_grace_records_strict_failure_without_new_runtime_gate(actual_controller,monkeypatch):
    c,_,_=actual_controller;c.action='push_loaded';c.phase='vla_push_loaded'
    obs=c.observation();obs.update(table_contacts=0,tray_bottom_z=.82,payload_mass_kg=2.)
    monkeypatch.setattr(c,'observation',lambda:obs);c.guard()
    assert c.strict_continuous_push_table_contact_gate is False and not c._push_table_supported(obs)


def test_actual_rotated_corner_edge_completes_without_nominal_centre_false_negative():
    from itertools import product
    c=fake_handover();angle=np.deg2rad(70);R=np.array([[np.cos(angle),-np.sin(angle),0],[np.sin(angle),np.cos(angle),0],[0,0,1]])
    centre=np.array([.85,.245,.801]);corners=centre+np.array(list(product((-.28,.28),(-.215,.215),(0,.105))))@R.T
    obs=dict(tray_position=centre,tray_corners=corners,table_contacts=4)
    assert abs(centre[1]-c.p.loaded_goal_position[1])>.03  # old centre gate would reject
    assert c.loaded_goal_reached(obs)
    assert c.loaded_goal_remaining(obs)==pytest.approx(.575-np.max(corners[:,1]))
    assert not c.loaded_goal_reached(dict(obs,table_contacts=0))
    assert not c.loaded_goal_reached(dict(obs,tray_corners=corners-[0,.05,0]))


def test_public_measured_tcp_reference_tracks_hand_not_stuck_body_and_checks_long_rim():
    c=fake_handover();c.p=replace(c.p,push_command_reference=True,push_lead_frame='measured_tcp')
    origin=np.array([.85,-.24,.8]);anchor=np.array([.65,-.44,.875]);R=np.array([[0,-1,0],[1,0,0],[0,0,1.]])
    c.push_anchor=('right',origin,anchor,np.eye(3));actual=np.array([.65,-.405,.87])
    c.sim.tcp=lambda side:(actual,np.eye(3));corners=np.array([[.635,-.52,.8],[1.065,.04,.905]])
    c.observation=lambda:dict(tray_position=origin,tray_rotation=R,tray_corners=corners)
    reference,desired=c._next_tcp_push_reference(origin,'right',.5)
    assert desired[1]==pytest.approx(-.428) and reference[1]==pytest.approx(-.228)
    reference,desired=c._next_tcp_push_reference(origin+[0,.08,0],'right',.5)
    assert desired[1]-actual[1]==pytest.approx(.04)  # excessive lead retracts instead of remaining unbounded
    np.testing.assert_array_equal(desired[[0,2]],anchor[[0,2]])
    actual[1]=.05
    with pytest.raises(Fault,match='long_rim_tracking'):c._next_tcp_push_reference(origin,'right',.5)
    for p in (replace(c.p,push_lead_frame='unknown'),replace(c.p,push_command_reference=False),replace(c.p,push_right_outward_release=1)):
        with pytest.raises(ValueError):p.validate()


def test_public_neutralization_requires_three_real_stable_ticks_and_preserves_normal_preload():
    c=fake_handover();c.p=replace(c.p,push_command_reference=True,push_lead_frame='measured_tcp')
    origin=np.array([.85,-.24,.8]);anchor=np.array([.65,-.44,.875]);reference=origin+[0,.1,0];actual=np.array([.66,-.36,.87])
    c.push_anchor=('right',origin,anchor,np.eye(3));c.push_last_reference_position=reference.copy()
    c.sim.tcp=lambda side:(actual.copy(),np.eye(3));obs=dict(tray_position=origin,gripper_contact_force={'right':2.})
    c.observation=lambda:obs;c._on_table=lambda _:True;submitted=[];c._push_reference_move=lambda p,s:submitted.append(p)
    ticks=[];c.tick=lambda:(ticks.append(1) or obs)
    c._neutralize_right_push_reference()
    np.testing.assert_array_equal(submitted[0][[0,2]],reference[[0,2]])
    assert (anchor+submitted[0]-origin)[1]==pytest.approx(actual[1]) and len(ticks)==3


def test_outward_open_never_precedes_verified_left_grasp_and_offsets_only_front_direction():
    c=fake_handover();c.p=replace(c.p,push_command_reference=True,push_right_outward_release=True)
    with pytest.raises(Fault,match='before_left_contact'):c.release(('right',))
    c.handover_verified=True;c.holding_sides={'left','right'}
    origin=np.array([.85,-.17,.8]);anchor=np.array([.65,-.34,.875]);c.push_anchor=('right',origin,anchor,np.eye(3))
    c.push_last_reference_position=origin.copy();c.sim.target=np.zeros(16)
    state=np.zeros(16);state[15]=.0212;c.sim.state=lambda:state
    obs=dict(gripper_contact_force={'left':40.,'right':0.});c.observation=lambda:obs
    commands=[]
    def move(goals,**kw):
        assert kw['predicate'](obs) and not kw['predicate'](dict(gripper_contact_force={'left':0.}))
        commands.append(goals['right'][0].copy());c.sim.target[15]=kw['openings']['right']
    c.move=move;c.release(('right',),predicate=lambda o:o['gripper_contact_force']['left']>.5)
    assert c.holding_sides=={'left'} and c.sim.target[15]==pytest.approx(.1)
    np.testing.assert_allclose(np.array(commands)[:,1:],np.tile(anchor[1:],(len(commands),1)))
    assert commands[-1][0]==pytest.approx(anchor[0]-.005-(.1-.0212)/2)
    assert len(commands)==50


def test_missing_contact_uses_same_five_mm_footprint_margin_as_supported_table():
    c=fake_handover();corners=np.array([[.5499,-.52,.800005],[1.065,.04,.905]])
    obs=dict(tray_corners=corners,tray_bottom_z=.800005,table_contacts=4)
    assert c._on_table(obs) and c._push_missing_support_geometry(obs)[0]
    corners[0,0]=.54499
    assert not c._on_table(obs) and not c._push_missing_support_geometry(obs)[0]


def test_forward_reference_feedback_is_incremental_and_caps_actual_tcp_error():
    c=fake_handover();c.p=replace(c.p,push_command_reference=True,push_lead_frame='measured_tcp')
    origin=np.array([.87,-.24,.8]);anchor=np.array([.67,-.44,.875]);actual=anchor.copy()
    c.push_anchor=('right',origin,anchor,np.eye(3));R=np.array([[0,-1,0],[1,0,0],[0,0,1.]])
    obs=dict(tray_position=origin,tray_rotation=R,tray_corners=np.array([[.576,-.52,.8],[1.1501,.04,.905]]))
    c.sim.tcp=lambda side:(actual,np.eye(3));c.observation=lambda:obs
    reference,desired=c._next_tcp_push_reference(origin,'right',.5)
    assert desired[0]==pytest.approx(anchor[0]-.002) and desired[1]==pytest.approx(anchor[1]+.012)
    # An arm/reference lag cannot accumulate an unbounded perpendicular effort.
    reference,desired=c._next_tcp_push_reference(origin+[-.05,0,0],'right',.5)
    assert desired[0]-actual[0]==pytest.approx(-.02)
    for p in (replace(c.p,push_forward_reference_step_m=.003),replace(c.p,push_forward_reference_lead_m=.021),
              replace(c.p,push_table_inboard_margin_m=float('nan'))):
        with pytest.raises(ValueError):p.validate()


