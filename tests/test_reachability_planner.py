import json
from pathlib import Path
import numpy as np
import pytest
from types import SimpleNamespace
from r1pro_teleop.airport_fsm import reachability_planner as planner
from r1pro_teleop.airport_fsm.contracts import Config, Fault


def test_lattice_decouples_heading_from_position_and_is_deterministic():
    a = list(planner.candidate_lattice([1., 2., .8], .8, 0.))
    b = list(planner.candidate_lattice([1., 2., .8], .8, 0.))
    np.testing.assert_array_equal(a[0][0], b[0][0])
    assert a[0][0][1] == 2. and a[0][0][2] == pytest.approx(.8)
    keys = [tuple(np.round(np.r_[base, face, rim], 8)) for base, face, rim in a]
    assert len(keys) == len(set(keys))
    assert 0 < len(a) <= 36


def test_lattice_covariant_under_global_rigid_transform():
    theta = 1.3
    R = np.array([[np.cos(theta), -np.sin(theta)], [np.sin(theta), np.cos(theta)]])
    p = np.array([1., 2.]); offset = np.array([3., -4.])
    a = list(planner.candidate_lattice(p, .8, 0.))
    b = list(planner.candidate_lattice(R@p+offset, .8+theta, theta))
    assert len(a) == len(b)
    for (x, f, r), (y, g, s) in zip(a, b):
        np.testing.assert_allclose(y[:2], R@x[:2]+offset)
        assert planner.wrap_angle(y[2]-x[2]-theta) == pytest.approx(0.)
        assert r == s


def test_failure_budget_and_hard_failures_are_not_silently_accepted(monkeypatch):
    monkeypatch.setattr(planner, 'planning_copy', lambda r: object())
    def reject(*args):
        raise Fault('ik_unreachable', {'side': 'left'}, recoverable=True)
    monkeypatch.setattr(planner, 'qualify_candidate', reject)
    result = planner.screen_candidates(None, 0, range(100), max_probes=3)
    assert result.examined == 3 and not result.candidates and not result.exhausted
    assert len(result.rejected) == 3
    def hard(*args):
        raise Fault('illegal_collision')
    monkeypatch.setattr(planner, 'qualify_candidate', hard)
    with pytest.raises(Fault, match='illegal_collision'):
        planner.screen_candidates(None, 0, range(100))


def test_screen_stops_at_qualified_budget(monkeypatch):
    monkeypatch.setattr(planner, 'planning_copy', lambda r: object())
    monkeypatch.setattr(planner, 'qualify_candidate', lambda *a: {'qualification': 'kinematic_only'})
    result = planner.screen_candidates(None, 0, range(100), max_qualified=2)
    assert result.examined == 2 and len(result.candidates) == 2


def _fixture_mobile_source(source, destination):
    """Server resources may already contain the actuated base model."""
    import mujoco
    from r1pro_teleop.airport_mobile import make_mobile_scene
    model = mujoco.MjModel.from_xml_path(str(source))
    if mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, 'agent_base_x') >= 0:
        return source
    make_mobile_scene(source, destination)
    return destination


@pytest.fixture(params=[False, True], ids=['source_as_supplied', 'already_mobile_source'])
def runtime(tmp_path, request):
    from r1pro_teleop.airport_fsm.runtime import Runtime
    scene = next(Path('resources/scenes').rglob('scene.json'))
    spec = json.loads(scene.read_text())
    source = scene.parent/spec.get('scene_file', 'scene.xml')
    if request.param:
        source = _fixture_mobile_source(source, tmp_path/'already_mobile.xml')
    xml = _fixture_mobile_source(source, tmp_path/'mobile.xml')
    r = Runtime(spec, xml, Config())
    yield r
    r.sim.close()


def test_real_mujoco_clone_keeps_live_integration_and_readers_isolated(runtime):
    r = runtime
    before = np.empty(r.integration_size)
    r.mj.mj_getState(r.m, r.d, before, r.integration_spec)
    target_before = r.sim.target.copy()
    trays_before = r.observation()['tray_pose'].copy()
    tcp_before = r.sim.tcp('left')[0].copy()
    probe = planner.planning_copy(r)
    q = probe.sim.state().astype(float)
    q[0] += .1
    base = probe.sim.base_state().astype(float); base[0] += .2
    planner._set_private_configuration(probe, q, base)
    assert not np.allclose(probe.sim.tcp('left')[0], tcp_before)
    np.testing.assert_array_equal(r.sim.tcp('left')[0], tcp_before)
    np.testing.assert_array_equal(r.observation()['tray_pose'], trays_before)
    np.testing.assert_allclose(probe.observation()['tray_pose'], trays_before, atol=1e-12)
    np.testing.assert_array_equal(r.sim.target, target_before)
    after = np.empty(r.integration_size)
    r.mj.mj_getState(r.m, r.d, after, r.integration_spec)
    np.testing.assert_array_equal(before, after)
    with pytest.raises(RuntimeError, match='cannot execute'):
        probe.tick()
    with pytest.raises(RuntimeError, match='cannot execute'):
        probe.sim.step()


def test_contact_state_is_never_used_for_empty_arm_probe(runtime):
    runtime.holding = 0
    with pytest.raises(Fault, match='requires_empty_arms'):
        planner.planning_copy(runtime)


def closure_fixture(*, missing_right=False, collision=False):
    observed = []
    def shadow(q):
        observed.append(q.copy())
        contacts = []
        if q[7] <= .06: contacts.append(SimpleNamespace(geom1=0, geom2=2, dist=-.0001))
        if q[15] <= .03 and not missing_right:
            contacts.append(SimpleNamespace(geom1=1, geom2=2, dist=-.0001))
        return SimpleNamespace(contact=contacts, q=q)
    names = ['left_gripper_finger1', 'right_gripper_finger1', 'tray_0']
    r = SimpleNamespace(cfg=Config(), allowed_tray=0, tray_bodies={2:0},
        m=SimpleNamespace(geom_bodyid=np.arange(3), body=lambda i:SimpleNamespace(name=names[i])),
        _shadow=shadow, camera_guard=lambda d:True, camera_metrics=lambda d:{},
        collision=lambda d,planning: {'neighbour':True} if collision and d.q[7] < .08 else None)
    return r, observed


def test_closure_stops_each_hand_at_its_own_contact_before_fictitious_zero():
    r, observed = closure_fixture()
    result = planner.preview_contact_closure(r, np.zeros(16))
    apertures = result['predicted_contact_apertures_m']
    assert .059 <= apertures['left'] <= .06
    assert .029 <= apertures['right'] <= .03
    assert min(q[7] for q in observed) == apertures['left']
    assert min(q[15] for q in observed) == apertures['right']


def test_closure_requires_both_rims_and_rejects_other_collisions():
    r, _ = closure_fixture(missing_right=True)
    with pytest.raises(Fault, match='no_rim_intersection'):
        planner.preview_contact_closure(r, np.zeros(16))
    r, _ = closure_fixture(collision=True)
    with pytest.raises(Fault, match='closure_blocked'):
        planner.preview_contact_closure(r, np.zeros(16))


@pytest.mark.parametrize('qualified,contact', [(True,False),(False,False),(True,True)])
def test_machine_uses_qualified_base_or_preserves_original_fallback(monkeypatch, qualified, contact):
    from r1pro_teleop.airport_fsm.machine import Machine
    m = object.__new__(Machine)
    m.c = Config(reachability_screen_enabled=True)
    m.pending_grasp_contact = None
    m.transition = lambda *a, **k: None
    m.log = SimpleNamespace(event=lambda *a, **k: None)
    poses = np.array([[1., 0., .8, 1., 0., 0., 0.]])
    m._poses = lambda: poses.copy()
    m._inward_yaw = lambda p: 0.
    original = (np.array([.4, 0., 0.]), 0., 0.)
    selected = (np.array([.5, .05, .1]), 0., .01)
    m._candidate_list = lambda t: [original]
    moved = []
    m.r = SimpleNamespace(navigate=lambda b: moved.append(b.copy()),
        rim_goals=lambda *a, **k:{}, cartesian=lambda *a, **k: None,
        holding=None, retained_contact=None,
        observation=lambda:{'gripper_contact_force':np.full((1,2),float(contact))})
    def screen(*args, **kw):
        assert not contact, 'residual contact must bypass the empty-arm screen'
        return planner.ProbeResult([(selected, {})] if qualified else [], [], 1, .1, False)
    monkeypatch.setattr(planner, 'screen_candidates', screen)
    face, rim = m.align(0, 0, forward_offset=.02)
    expected = selected[0] if qualified and not contact else original[0]+[.02,0.,0.]
    np.testing.assert_allclose(moved[0], expected)
    assert rim == (selected[2] if qualified and not contact else original[2])
