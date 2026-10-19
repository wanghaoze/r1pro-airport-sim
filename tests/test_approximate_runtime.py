from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest

from test_completion_acceptance import shifted_rows
from test_completion_runtime_guards import runtime
from r1pro_teleop.airport_fsm.acceptance_profile import profile_placement_ok
from r1pro_teleop.airport_fsm.contracts import Config, Fault, State
from r1pro_teleop.airport_fsm.runtime import Runtime
from r1pro_teleop.airport_fsm.handoff_clearance import check_monitor


def approximate_config():
    return replace(Config(acceptance_profile='completion_first',
        retained_support_integer_clock_enabled=True),
        approximate_completion_enabled=True, completion_position_m=.10,
        completion_gap_max_m=.10)


def test_approximate_guard_records_bounded_midcourse_deviations_but_keeps_hard_limits():
    r, e = runtime()
    r.cfg = approximate_config()
    r.collision = lambda **kw: ({'distance_m': -.01} if kw.get('limit_override') is not None else None)
    e['floor_contact'][0] = 1
    e['max_penetration'] = .01
    r.d.qvel[14] = 10.
    r.d.qvel[0] = 1.5
    r.holding = 0
    r.fsm_state = State.TRANSPORT_TRAY
    r.initial_bottom = np.array([.8, .8, .8])
    r.lost_time = .12
    for key in ('support_contact', 'min_z', 'tray_pose'):
        e[key] = np.repeat(e[key], 3, axis=0)
    e['gripper_contact_force'][0, 0] = 0.
    r.guard()
    codes = set(r.approximate_deviation_counts)
    assert {'illegal_collision', 'tray_on_floor', 'excess_penetration',
            'measured_joint_overspeed', 'measured_base_overspeed',
            'carried_payload_support_contact', 'bilateral_contact_lost'} <= codes
    assert not r.strict_runtime_passed
    assert r.soft_guard_violation_by_code['illegal_collision'] == 1
    assert r.soft_guard_violation_maxima['illegal_collision']['distance_m'] == .01
    e['max_penetration'] = .021
    with pytest.raises(Fault, match='excess_penetration'):
        r.guard()
    e['max_penetration'] = 0.
    r.d.qpos[0] = np.nan
    with pytest.raises(Fault, match='nonfinite_physics'):
        r.guard()


def test_approximate_collision_allows_only_configured_finite_depth():
    r = Runtime.__new__(Runtime)
    r.cfg = approximate_config()
    contact = SimpleNamespace(dist=-.01, geom1=0, geom2=1)
    r.d = SimpleNamespace(contact=[contact])
    r.m = SimpleNamespace(geom=lambda idx: SimpleNamespace(name=f'g{idx}'))
    r._pair_allowed = lambda *args: False
    r.robot_geoms = np.array([], dtype=int)
    r.table_geoms = np.array([], dtype=int)
    assert r.collision(planning=True)['distance_m'] == -.01
    assert r.collision() is None
    assert r.collision(limit_override=-.0002)['distance_m'] == -.01
    r._approximate_planning_relaxed = True
    assert r.collision(planning=True) is None
    contact.dist = -.021
    assert r.collision(planning=True)['distance_m'] == -.021
    r._approximate_planning_relaxed = False
    contact.dist = .0005
    assert r.collision(planning=True)['distance_m'] == .0005
    assert r.collision() is None
    r.cfg = replace(r.cfg, approximate_completion_enabled=False)
    contact.dist = -.01
    assert r.collision(planning=True)['distance_m'] == -.01


def test_approximate_handoff_monitor_softens_only_bounded_support_gap():
    deviations = []
    r = SimpleNamespace(cfg=approximate_config(),
        g=SimpleNamespace(support_table=lambda _: 'table',
            tables={'table': {'dimensions_m': [1., 1., .8]}}),
        _approximate_deviation=lambda code, detail: deviations.append((code, detail)))
    e = {'gripper_contact_force': np.array([[10., .7]]),
         'table_contact': np.array([0]), 'min_z': np.array([.815]),
         'tray_pose': np.array([[0., 0., .815, 1., 0., 0., 0.]])}
    check_monitor(r, e, (0, 'right'))
    assert [code for code, _ in deviations] == [
        'handoff_clearance_free_recontact', 'handoff_clearance_support_lost']
    e['min_z'][0] = .825
    with pytest.raises(Fault, match='handoff_clearance_support_lost'):
        check_monitor(r, e, (0, 'right'))


def test_approximate_final_uses_stable_supported_released_tail_not_old_flags():
    geometry, rows = shifted_rows()
    cfg = approximate_config()
    rows['illegal_collision'][0] = 1
    rows['floor_contact'][0, 0] = 1
    rows['max_penetration'][0] = .015
    rows['wrist_violation'][0] = 1
    rows['transition_completed'][0] = False
    valid, report = profile_placement_ok(rows, geometry, cfg)
    assert valid and report['acceptance_profile'] == 'approximate_completion'
    assert not report['strict_accepted']
    rows['table_contact'][-1, 0] = 0
    assert not profile_placement_ok(rows, geometry, cfg)[0]
    rows['table_contact'][-1, 0] = 1
    rows['gripper_contact_force'][-1, 0, 0] = .6
    assert not profile_placement_ok(rows, geometry, cfg)[0]


def test_approximate_tick_can_outlive_repeated_planning_windows():
    r = Runtime.__new__(Runtime)
    r.cfg = approximate_config()
    r.steps = 800
    r.primitive_deadline_step = 600
    r._approximate_extended_deadline_step = 600
    r._approximate_deadline_extended = True
    records = []
    r._approximate_deviation = lambda *args: records.append(args)
    r.validate_retained_clock_state = lambda: None
    def reached_physics_guard():
        raise RuntimeError('passed_time_gate')
    r.check_retained_contact = reached_physics_guard
    for _ in range(2):
        with pytest.raises(RuntimeError, match='passed_time_gate'):
            r.tick()
        assert r.primitive_deadline_step > r.steps
        r.steps = r.primitive_deadline_step
    assert len(records) == 2
    r.cfg = replace(r.cfg, approximate_completion_enabled=False)
    with pytest.raises(Fault, match='primitive_deadline_exceeded'):
        r.tick()
