import numpy as np
import pytest
from scipy.spatial.transform import Rotation
from r1pro_teleop.airport_fsm.rim_affordances import rim_pairs


@pytest.mark.parametrize('yaw', [0., .7, 2.2, -1.38])
def test_each_pair_hits_its_actual_physical_edges(yaw):
    center = np.array([.8, -.2, .9])
    rotation = Rotation.from_euler('z', yaw).as_matrix()
    width, length = rim_pairs([.56, .43, .08], yaw, 0., inset=.01)
    for pair, index, span in ((width, 1, .205), (length, 0, .27)):
        goals = pair.goals(center, x_offset=.025)
        local = [(pose-center) @ rotation for pose, _ in goals.values()]
        assert sorted(round(x[index], 6) for x in local) == [-span, span]
        assert all(np.isclose(abs(x[1-index]), .025) for x in local)
        assert np.isclose(np.linalg.norm(goals['left'][0]-goals['right'][0]), 2*span)
        for _, orientation in goals.values():
            np.testing.assert_allclose(orientation.T@orientation, np.eye(3), atol=1e-12)


def test_offset_bound_changes_with_edge_pair():
    width, length = rim_pairs([.56, .43, .08], 0., 0., inset=.01)
    width.goals([0, 0, 0], x_offset=.24)
    with pytest.raises(ValueError):
        length.goals([0, 0, 0], x_offset=.24)


@pytest.mark.parametrize('normal', [-3.14, -1., 0., 2.7])
def test_face_is_nearest_equivalent_aisle_direction(normal):
    for pair in rim_pairs([.56, .43], 1.1, normal, inset=.01):
        assert abs(np.arctan2(np.sin(pair.face-normal), np.cos(pair.face-normal))) <= np.pi/2+1e-12


@pytest.mark.parametrize('args', [('diagonal', 0., .2, .3), ('width', np.nan, .2, .3),
                                   ('length', 0., 0., .3), ('length', 0., .2, -1.)])
def test_restored_geometry_must_be_valid(args):
    from r1pro_teleop.airport_fsm.rim_affordances import RimPair
    with pytest.raises(ValueError):
        RimPair(*args)


def test_first_eight_candidates_cover_both_axes_and_all_distances():
    from r1pro_teleop.airport_fsm.reachability_planner import alternate_candidate_lattice
    candidates = list(alternate_candidate_lattice([0., 0., .8], [.56, .43], .7, 0., inset=.01))
    first = candidates[:8]
    assert {c.rim_pair.axis for c in first} == {'width', 'length'}
    assert {round(np.linalg.norm(c[0][:2]), 2) for c in first} == {.55, .58, .62, .66}


def _machine(monkeypatch):
    from types import SimpleNamespace, MethodType
    from r1pro_teleop.airport_fsm.contracts import Config, Fault
    from r1pro_teleop.airport_fsm.machine import Machine
    from r1pro_teleop.airport_fsm.runtime import Runtime
    from r1pro_teleop.airport_fsm import reachability_planner as planner
    cfg = Config(alternate_rim_enabled=True, reachability_screen_enabled=True, prefer_direct_grasp=True)
    pose = np.array([[0., 0., .8, 1., 0., 0., 0.]])
    calls, events = [], []
    width, length = rim_pairs([.56, .43], 0., 0., inset=cfg.rim_inset_m)
    runtime = SimpleNamespace(cfg=cfg, holding=None, retained_contact=None,
        g=SimpleNamespace(sizes=np.array([[.56, .43, .08]])),
        sim=SimpleNamespace(state=lambda: np.zeros(16)),
        observation=lambda: {'tray_pose':pose.copy(), 'gripper_contact_force':np.zeros((1, 2))},
        rim_goals=lambda center, face, **kw: width.goals(center, **kw),
        navigate=lambda base: None, joints=lambda *a, **kw: None, tucked=np.zeros(16),
        _target_valid=lambda *a, **kw: True,
        close_grippers_on_contact=lambda *a, **kw: None,
        wait=lambda *a, **kw: True)
    runtime.grasp_goals = MethodType(Runtime.grasp_goals, runtime)
    def solve(goals, *a, **kw):
        span = np.linalg.norm(goals['left'][0]-goals['right'][0])
        if span < .5:
            raise Fault('ik_unreachable', recoverable=True)
        return np.zeros(16)
    runtime.solve_pair = solve
    def cartesian(goals, **kw):
        calls.append((goals, kw))
        return [np.zeros(16)]
    runtime.cartesian = cartesian
    machine = Machine.__new__(Machine)
    machine.r, machine.c, machine.g = runtime, cfg, runtime.g
    machine.pending_grasp_contact = None
    machine.grasp_rim_pair = None
    machine.transition = lambda *a, **kw: None
    machine._inward_yaw = lambda position: 0.
    machine._candidate_list = lambda tray: [(np.array([-.6, 0., 0.]), 0., 0.)]*12
    machine.log = SimpleNamespace(event=lambda name, **kw: events.append((name, kw)))
    monkeypatch.setattr(planner, 'planning_copy', lambda r: r)
    monkeypatch.setattr(planner, '_set_private_configuration', lambda *a: None)
    monkeypatch.setattr(planner, 'preview_contact_closure', lambda *a: {})
    return machine, calls, events, length


def test_selected_geometry_survives_screen_align_prepare_and_live_grasp(monkeypatch):
    machine, calls, events, length = _machine(monkeypatch)
    face, offset = machine.prepare_pick(0, 0)
    assert machine.grasp_rim_pair.axis == 'length'
    assert any(name == 'reachability_screen' for name, _ in events)
    class GraspMeasured(Exception):
        pass
    def remember(tray):
        raise GraspMeasured
    machine.r.remember_grasp = remember
    with pytest.raises(GraspMeasured):
        machine.grasp(0, face, offset)
    # Every planned and physically requested arm pair has the real long-axis
    # separation: neither pregrasp nor closure switches back to width geometry.
    assert len(calls) >= 5
    for goals, _ in calls:
        assert np.linalg.norm(goals['left'][0]-goals['right'][0]) == pytest.approx(2*length.half_span)


def test_failed_selected_geometry_clears_before_legacy_fallback_and_budget(monkeypatch):
    from r1pro_teleop.airport_fsm.contracts import Fault
    machine, calls, events, _ = _machine(monkeypatch)
    from dataclasses import replace
    machine.c = machine.r.cfg = replace(machine.c, max_candidate_count=3)
    visited = []
    def reject(base):
        visited.append(machine.grasp_rim_pair)
        raise Fault('base_path_unavailable', recoverable=True)
    machine.r.navigate = reject
    with pytest.raises(Fault, match='no_feasible_grasp_approach'):
        machine.align(0, 0)
    assert len(visited) == 3
    assert [p.axis if p else None for p in visited] == ['length', 'length', None]
    assert machine.grasp_rim_pair is None


def test_default_geometry_uses_original_rim_interface(monkeypatch):
    machine, _, _, _ = _machine(monkeypatch)
    from dataclasses import replace
    machine.c = machine.r.cfg = replace(machine.c, alternate_rim_enabled=False, reachability_screen_enabled=False)
    machine.align(0, 0)
    assert machine.grasp_rim_pair is None
    center = np.array([0., 0., .8])
    expected = machine.r.rim_goals(center, 0.)
    for side, actual in machine._grasp_goals(center, 0.).items():
        np.testing.assert_array_equal(actual[0], expected[side][0])


def test_alternate_search_preserves_qualified_historical_first_candidate(monkeypatch):
    machine, _, events, _ = _machine(monkeypatch)
    machine.r.solve_pair = lambda *a, **kw: np.zeros(16)
    visited=[]
    machine.r.navigate=lambda base:visited.append(base.copy())
    machine.align(0,0)
    np.testing.assert_array_equal(visited[0],[-.6,0.,0.])
    assert machine.grasp_rim_pair is None
    screen=next(fields for name,fields in events if name=='reachability_screen')
    assert screen['qualified'][0]['grasp_geometry'] is None


def test_push_alignment_disables_alternate_geometry_even_when_config_enabled(monkeypatch):
    from types import SimpleNamespace
    machine, calls, events, _ = _machine(monkeypatch)
    machine.g.push_possible = lambda *a: True
    machine.g.footprint_supported = lambda *a: True
    real_align = machine.align
    class AlignmentCompleted(Exception):
        pass
    def align(*a, **kw):
        assert kw['allow_alternate'] is False
        face, rim = real_align(*a, **kw)
        assert machine.grasp_rim_pair is None
        assert face == 0.
        raise AlignmentCompleted
    machine.align = align
    with pytest.raises(AlignmentCompleted):
        machine.push(SimpleNamespace(tray=0,slot=0,destination=np.array([.1,0.,.8]),yaw=0.))
    assert events[-2][0] == 'reachability_screen'
    assert events[-2][1]['alternate_rim_allowed'] is False
    # With the fake width IK unavailable, screen rejects candidates and the
    # ordinary width fallback is used; an available length grasp is not used.
    assert len(calls) == 1
    goals = calls[0][0]
    assert np.linalg.norm(goals['left'][0]-goals['right'][0]) == pytest.approx(.41)
