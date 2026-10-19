import numpy as np
import pytest
from scipy.spatial.transform import Rotation

from r1pro_teleop.airport_fsm.placement_planner import (
    touchdown_position, release_endpoint, descent_budget_frames, align_carried_lateral_offset,
)
from r1pro_teleop.airport_fsm.trajectory import BlendedJointPath


@pytest.mark.parametrize('source_yaw,target_yaw',[(0.,0.),(.7,-1.3),(np.pi/2,np.pi)])
def test_carried_alignment_centers_payload_using_real_rigid_geometry(source_yaw,target_yaw):
    from r1pro_teleop.airport_fsm.geometry import carried_pose_at_base
    current=np.array([-.5,.2,source_yaw])
    local_offset=np.array([.527,.258,1.])
    rotation=Rotation.from_euler('z',source_yaw).as_matrix()
    payload=rotation@local_offset+np.r_[current[:2],0.]
    goal=np.array([.28,-.645,target_yaw]);original=goal.copy()
    corrected,offset=align_carried_lateral_offset(goal,current,payload)
    predicted,_=carried_pose_at_base(payload,rotation,current,corrected)
    forward=np.array([np.cos(target_yaw),np.sin(target_yaw)])
    lateral=np.array([-np.sin(target_yaw),np.cos(target_yaw)])
    assert offset==pytest.approx(.258)
    assert np.dot(predicted[:2]-goal[:2],lateral)==pytest.approx(0.,abs=1e-12)
    assert np.dot(corrected[:2]-goal[:2],forward)==pytest.approx(0.,abs=1e-12)
    assert corrected[2]==goal[2]
    np.testing.assert_array_equal(goal,original)


def test_carried_alignment_does_not_shift_centered_payload():
    goal=np.array([.28,-.645,0.]);current=np.array([.1,0.,0.])
    corrected,offset=align_carried_lateral_offset(goal,current,[.6,0.,1.])
    np.testing.assert_array_equal(corrected,goal)
    assert offset==0.


@pytest.mark.parametrize('enabled', [False, True])
def test_carry_lateral_compensation_is_explicit_opt_in(enabled):
    from types import SimpleNamespace
    from r1pro_teleop.airport_fsm.machine import Machine
    machine = Machine.__new__(Machine)
    machine.c = SimpleNamespace(keep_place_contact=False, carry_lateral_compensation_enabled=enabled,
                                placement_screen_enabled=False)
    machine._place_location = lambda operation: np.array([1., 2., .8])
    machine._inward_yaw = lambda staged: 0.
    machine.transition = lambda *args, **kw: None
    machine.log = SimpleNamespace(event=lambda *args, **kw: None)
    seen = []
    class NavigationReached(Exception):
        pass
    def navigate(base):
        seen.append(base.copy())
        raise NavigationReached
    machine.r = SimpleNamespace(navigate=navigate,
        sim=SimpleNamespace(base_state=lambda: np.zeros(3)),
        observation=lambda: {'tray_pose':np.array([[.5, .258, 1., 1., 0., 0., 0.]])})
    with pytest.raises(NavigationReached):
        machine.carry_place(SimpleNamespace(tray=0))
    np.testing.assert_allclose(seen[0], [.43, 2.-(.258 if enabled else 0.), 0.])


def test_touchdown_matches_command_orientation_and_does_not_mutate_input():
    vertices = np.array([[x, y, z] for x in (-.28, .28) for y in (-.215, .215) for z in (0, .105)])
    position = np.array([.85, -.3, 1.0])
    tilted = Rotation.from_euler('xy', [4, 2], degrees=True).as_matrix()
    for rotation in (np.eye(3), tilted):
        target = touchdown_position(position, vertices, rotation, table_height=.8, preload=.003)
        actual_bottom = (vertices @ rotation.T + target)[:, 2].min()
        assert actual_bottom == pytest.approx(.797)
    np.testing.assert_array_equal(position, [.85, -.3, 1.0])


def test_release_preserves_retained_hand_and_arm_targets():
    reference = np.zeros(16)
    reference[:7] = np.arange(7) / 10
    measured = reference.copy()
    measured[[7, 15]] = [.014, .013]
    target = release_endpoint(reference, measured, ['left'], open_limit=.1, clearance=.02)
    assert target[7] == pytest.approx(.034)
    np.testing.assert_array_equal(target[np.arange(16) != 7], reference[np.arange(16) != 7])
    assert reference[7] == 0
    assert measured[7] == .014


def test_measured_clearance_reduces_budget_without_increasing_derivative_limits():
    reference = np.zeros(16)
    measured = reference.copy()
    measured[7] = .014
    short = release_endpoint(reference, measured, ['left'], open_limit=.1, clearance=.02)
    full = reference.copy(); full[7] = .1
    limits = (.1, .5, 2.)
    short_path = BlendedJointPath([reference, short], *limits)
    full_path = BlendedJointPath([reference, full], *limits)
    assert short_path.duration < full_path.duration
    for name, limit in zip(('velocity', 'acceleration', 'jerk'), limits):
        assert np.max(short_path.reference_bounds[name]) <= limit


def test_release_saturates_and_never_recloses_open_fingers():
    reference = np.zeros(16); reference[7] = .09
    measured = np.zeros(16); measured[7] = .09; measured[15] = .002
    target = release_endpoint(reference, measured, ['left', 'right'], open_limit=.1, clearance=.02)
    assert target[7] == .1
    assert target[15] == .022
    measured[7] = .001
    assert release_endpoint(reference, measured, ['left'], open_limit=.1, clearance=.02)[7] == .09


def test_frame_budget_is_conservative_and_exhaustion_fails():
    assert descent_budget_frames(remaining_frames=60, release_frames=18) == 40
    with pytest.raises(ValueError):
        descent_budget_frames(remaining_frames=20, release_frames=18)
    with pytest.raises(ValueError):
        descent_budget_frames(remaining_frames=60.5, release_frames=18)


@pytest.mark.parametrize('sides', [[], ['left', 'left'], ['other']])
def test_release_rejects_ambiguous_sides(sides):
    with pytest.raises(ValueError):
        release_endpoint(np.zeros(16), np.zeros(16), sides, open_limit=.1, clearance=.02)


def test_invalid_rotation_does_not_propose_touchdown():
    with pytest.raises(ValueError):
        touchdown_position([0, 0, 1], [[0, 0, 0]], np.zeros((3, 3)), table_height=.8, preload=.003)


def _physical_ik_runtime():
    """Actual MuJoCo kinematics with independent translation/rotation joints."""
    import mujoco
    from types import SimpleNamespace
    from dataclasses import replace
    from r1pro_teleop.airport_fsm.runtime import Runtime
    from r1pro_teleop.airport_fsm.contracts import Config, State
    arms=[]
    for side in ('left', 'right'):
        bodies=[]
        for i, axis in enumerate(('1 0 0', '0 1 0', '0 0 1', '1 0 0', '0 1 0', '0 0 1', '0 0 1')):
            kind='slide' if i < 3 else 'hinge'
            limits='-.004 .004' if i == 2 else '-1 1'
            bodies.append(f'<body><joint type="{kind}" axis="{axis}" range="{limits}"/><geom type="sphere" size=".01" mass=".01" contype="0" conaffinity="0"/>')
        arms.append(''.join(bodies)+f'<site name="{side}_tcp"/>'+('</body>'*7))
    m=mujoco.MjModel.from_xml_string('<mujoco><compiler angle="radian"/><worldbody>'+''.join(arms)+'</worldbody></mujoco>')
    r=Runtime.__new__(Runtime);r.mj=mujoco;r.m=m;r.d=mujoco.MjData(m);r.shadow=mujoco.MjData(m)
    r.cfg=replace(Config(),fixed_primitives=True,joint_margin_rad=0.)
    r.holding=None;r.retained_contact=(0,'left');r.fsm_state=State.ADJUST_TRAY
    r.qids=np.arange(14);r.jids=np.arange(14);r.sim=SimpleNamespace(target=np.zeros(16))
    mujoco.mj_forward(m,r.d)
    return r


def test_supported_push_solver_enforces_submillimetre_normal_accuracy():
    r=_physical_ik_runtime()
    goal=np.array([.001,.002,.003])
    solution=r.solve_pair({'left':(goal,np.eye(3))})
    r.shadow.qpos[:7]=solution[:7];r.mj.mj_forward(r.m,r.shadow)
    assert abs(r.shadow.site('left_tcp').xpos[2]-goal[2]) <= .00025
    assert np.linalg.norm(r.shadow.site('left_tcp').xpos-goal) <= .012
    np.testing.assert_array_equal(r.d.qpos,np.zeros(14))


def test_normal_infeasibility_is_rejected_even_inside_old_position_tolerance():
    from r1pro_teleop.airport_fsm.contracts import Fault
    r=_physical_ik_runtime()
    with pytest.raises(Fault,match='ik_unreachable') as failed:
        r.solve_pair({'left':(np.array([0,0,.008]),np.eye(3))})
    assert .00025 < failed.value.detail['normal_error_m'] < .012
    assert failed.value.detail['normal_tolerance_m'] == .00025
    # The noncontact hand retains its old reaching contract.
    result=r.solve_pair({'right':(np.array([0,0,.008]),np.eye(3))})
    assert np.isfinite(result).all()


@pytest.mark.parametrize('alignment_feasible', [False, True])
@pytest.mark.parametrize('preserve_enabled', [False, True])
@pytest.mark.parametrize('valid_relation', [False, True])
@pytest.mark.parametrize('alignment_stable', [False, True])
def test_loaded_alignment_is_planned_before_motion_and_descent_always_levels(monkeypatch, alignment_feasible, preserve_enabled, valid_relation, alignment_stable):
    from types import SimpleNamespace
    from r1pro_teleop.airport_fsm import primitives
    from r1pro_teleop.airport_fsm.contracts import Config, Fault
    cfg=Config(placement_preserve_command_grasp_enabled=preserve_enabled); events=[]; motions=[]; targets=[]; plans=[]; references=[]
    # Measured body is tilted: its corner offset must not carry into the new
    # horizontal placement goal after either alignment branch.
    quat=Rotation.from_euler('y', 3, degrees=True).as_quat()[[3,0,1,2]]
    observation={'tray_pose':np.array([[.8,0,1.,*quat]]),'gripper_contact_force':np.array([[10.,10.]])}
    r=SimpleNamespace(cfg=cfg,steps=0,d=SimpleNamespace(time=0.),primitive_deadline_step=None,primitive_lift_xy_shift_m=.06,
                      observation=lambda:observation,sim=SimpleNamespace(state=lambda:np.zeros(16)),
                      m=SimpleNamespace(body=lambda name:SimpleNamespace(id=0)),
                      evidence=SimpleNamespace(local_vertices={0:np.array([[0,0,0],[.28,.215,.105]])}))
    m=SimpleNamespace(r=r,c=cfg,g=SimpleNamespace(support_table=lambda p:'front',ids=['tray'],period=2*np.pi,
                      tables={'front':{'dimensions_m':[1.2,.6,.8]}}),
                      log=SimpleNamespace(event=lambda name,**kw:events.append((name,kw))),
                      transition=lambda *args,**kw:None)
    def reference(runtime):
        references.append(runtime.steps)
        runtime.holding=0
        runtime.grasp_rel={side:np.eye(4) for side in ('left','right')} if valid_relation else None
    monkeypatch.setattr(primitives,'continue_loaded_reference',reference)
    checked=[]
    def check_reference(runtime):
        checked.append(True);return {},{'left':.02,'right':.02}
    monkeypatch.setattr(primitives,'checked_command_tcp',check_reference)
    def object_points(r,p,yaw=None):
        targets.append((p.copy(),yaw));return np.zeros((2,16))
    monkeypatch.setattr(primitives,'object_points',object_points)
    def plan(r,points,**kw):
        plans.append(kw)
        if len(plans)==1 and not alignment_feasible:raise Fault('primitive_path_infeasible')
        if len(plans)==3:raise RuntimeError('descent_ready')
        return object(),10
    monkeypatch.setattr(primitives,'plan',plan)
    monkeypatch.setattr(primitives,'execute',lambda *args,**kw:motions.append('alignment'))
    def settle(*args,**kw):
        if not alignment_stable:raise RuntimeError('alignment_not_stable')
    monkeypatch.setattr(primitives,'settle',settle)
    op=SimpleNamespace(tray=0,yaw=0.,destination=np.array([.85,0,.8]))
    with pytest.raises(RuntimeError,match='descent_ready' if alignment_stable or not alignment_feasible else 'alignment_not_stable'):
        primitives.place(m,op,op.destination.copy())
    assert motions == (['alignment'] if alignment_feasible else [])
    if alignment_feasible and not alignment_stable:
        assert len(references)==1 and len(targets)==1
        assert not any(name=='placement_command_grasp_preserved' for name,_ in events)
        return
    assert targets[-1][1] == pytest.approx(0.)
    np.testing.assert_array_equal(targets[-1][0][:2],op.destination[:2])
    assert targets[-1][0][2] == pytest.approx(.8-cfg.primitive_touchdown_preload_m)
    assert any(name==('transport_align_separated' if alignment_feasible else 'transport_align_deferred') for name,_ in events)

    # The original measured relation is always planned first. A non-planning
    # sentinel must not authorize the optional saved-alignment candidate.
    assert len(references)==2 and not checked
    assert not any(name=='placement_command_reference_candidate' for name,_ in events)


def test_placement_preserve_command_grasp_configuration():
    from r1pro_teleop.airport_fsm.contracts import Config
    assert Config().placement_preserve_command_grasp_enabled is False
    Config(placement_preserve_command_grasp_enabled=True,fixed_primitives=True).validate()
    for value in (1,0,'true',None):
        with pytest.raises(ValueError,match='placement_preserve_command_grasp_enabled'):
            Config(placement_preserve_command_grasp_enabled=value).validate()
    with pytest.raises(ValueError,match='requires fixed_primitives'):
        Config(placement_preserve_command_grasp_enabled=True,fixed_primitives=False).validate()


@pytest.mark.parametrize('offset',[.05,.05001])
def test_command_tcp_compliance_guard_retained(offset):
    from types import SimpleNamespace
    from r1pro_teleop.airport_fsm.primitives import checked_command_tcp
    from r1pro_teleop.airport_fsm.contracts import Fault
    shadow=SimpleNamespace(site=lambda name:SimpleNamespace(xpos=np.array([offset,0.,0.]),xmat=np.eye(3)))
    r=SimpleNamespace(_shadow=lambda target:shadow,sim=SimpleNamespace(target=np.zeros(16),tcp=lambda side:(np.zeros(3),np.eye(3))))
    if offset>.05:
        with pytest.raises(Fault,match='primitive_excess_servo_deflection'):
            checked_command_tcp(r)
    else:
        _,errors=checked_command_tcp(r)
        assert errors=={'left':offset,'right':offset}
