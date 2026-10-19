"""Bounded approximate footprint overlap uses one signed-gap contract."""
from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest

from test_airport_fsm_unit import poses, spec_fixture, valid_rows
from r1pro_teleop.airport_fsm.acceptance_profile import completion_criteria, profile_placement_ok
from r1pro_teleop.airport_fsm.contracts import Config
from r1pro_teleop.airport_fsm.geometry import (
    Geometry, Operation, Scheduler, footprint_signed_boundary_gap, rectangle,
    slot_geometry_ready,
)
from r1pro_teleop.airport_fsm.machine import Machine
from r1pro_teleop.airport_fsm.reservation_plan import propose
from r1pro_teleop.airport_fsm import geometry as geometry_module


def fixture(overlap_m=.001):
    g = Geometry(spec_fixture())
    p = poses(g)
    # The nominal adjacent clearance is 15 mm; move slot 1 toward slot 0.
    p[1, 1] += .015 + overlap_m
    return g, p


def config(approximate=True, cap=.02):
    return replace(Config(acceptance_profile='completion_first',
        retained_support_integer_clock_enabled=True),
        approximate_completion_enabled=approximate,
        completion_collision_penetration_m=cap,
        completion_position_m=.1, completion_gap_max_m=.1)


def test_signed_gap_and_operation_final_agree_on_same_supported_pose():
    g, p = fixture()
    measured = footprint_signed_boundary_gap(g.footprint(p, 0), g.footprint(p, 1))
    assert measured == pytest.approx(-.001, abs=1e-8)
    assert footprint_signed_boundary_gap(rectangle([0, 0], 0, [1, 1]),
        rectangle([1.01, 0], 0, [1, 1])) == pytest.approx(.01)
    rows = valid_rows(); rows['tray_pose'][:] = p
    for approximate, cap, expected in ((True, .02, True), (True, .0005, False),
                                       (False, .02, False)):
        cfg = config(approximate, cap)
        criteria = completion_criteria(cfg)
        ready = slot_geometry_ready(g, p, [0, 1, 2], 1, 1, criteria,
            require_full_footprint=False, use_actual_gap=True,
            approximate_overlap_cap_m=min(cap, .02) if approximate else 0.)
        final, report = profile_placement_ok(rows, g, cfg)
        assert ready is expected
        assert final is expected, report
        if expected:
            assert report['placement']['gap_measure'] == 'signed_rotated_footprint_boundary'
            assert report['placement']['final_gaps_m'][0] == pytest.approx(measured)
            assert not report['strict_accepted']


def test_scheduler_accepts_bounded_overlap_only_when_enabled():
    g, p = fixture()
    for approximate in (True, False):
        cfg = config(approximate)
        scheduler = Scheduler(g, completion_criteria(cfg), consistent_placement=True,
            require_full_footprint=False, use_actual_gap=True,
            approximate_overlap_cap_m=.02 if approximate else 0.)
        scheduler.mapping = [0, 1, 2]
        selected = scheduler.choose(p)
        assert (selected is None) is approximate


def test_postplace_push_skip_uses_same_signed_gap_as_final_acceptance():
    g, p = fixture()
    for approximate, cap, expected in ((True, .02, True), (True, .0005, False),
                                       (False, .02, False)):
        cfg = config(approximate, cap)
        machine = Machine.__new__(Machine)
        machine.c = cfg; machine.g = g
        machine.scheduler = SimpleNamespace(mapping=[0, 1, 2], reservation_plan=None)
        machine._poses = lambda: p
        deviations = []
        machine.r = SimpleNamespace(record_strict_deviation=lambda *args: deviations.append(args))
        operation = Operation(1, 1, g.goals[1], g.goal_yaw[1])
        assert machine._operation_geometry_ready(operation) is expected
        if expected:
            assert deviations[0][0] == 'operation_geometry_outside_strict_contract'


def test_verify_operation_uses_bounded_signed_gap_without_changing_strict_evidence():
    g, p = fixture()
    for approximate, cap, expected in ((True, .02, True), (True, .0005, False),
                                       (False, .02, False)):
        cfg = replace(config(approximate, cap), fixed_primitives=True)
        machine = Machine.__new__(Machine)
        machine.c = cfg; machine.g = g
        machine.scheduler = SimpleNamespace(mapping=[0, 1, 2], reservation_plan=None)
        machine.transition = lambda *args, **kwargs: None
        deviations = []
        observation = dict(tray_pose=p, table_contact=np.ones(3),
                           gripper_contact_force=np.zeros((3, 2)))
        machine.r = SimpleNamespace(wait=lambda _seconds, check, _stable:
            [check(observation) for _ in range(24)][-1],
            record_strict_deviation=lambda *args: deviations.append(args))
        operation = Operation(1, 1, g.goals[1], g.goal_yaw[1])
        assert machine.verify_operation(operation) is expected
        if expected:
            assert any(item[0] == 'operation_outside_strict_contract' for item in deviations)


def test_final_approximate_still_requires_release_and_support():
    g, p = fixture()
    rows = valid_rows(); rows['tray_pose'][:] = p
    cfg = config()
    assert profile_placement_ok(rows, g, cfg)[0]
    rows['table_contact'][-1, 1] = 0
    assert not profile_placement_ok(rows, g, cfg)[0]
    rows['table_contact'][-1, 1] = 1
    rows['gripper_contact_force'][-1, 1, 0] = 1
    assert not profile_placement_ok(rows, g, cfg)[0]


def test_nonadjacent_overlap_is_rejected_by_operation_and_final():
    g = Geometry(spec_fixture())
    p = poses(g)
    p[2] = p[0]
    # Isolate the all-pairs rule: each adjacent pair has a positive gap, while
    # trays 0 and 2 occupy the same footprint. Goal pose checks still pass.
    g.goals = p[:, :3].copy()
    cfg = config()
    criteria = completion_criteria(cfg)
    assert not slot_geometry_ready(g, p, [0, 1, 2], 1, 1, criteria,
        require_full_footprint=False, use_actual_gap=True,
        approximate_overlap_cap_m=.02)
    rows = valid_rows(); rows['tray_pose'][:] = p
    valid, report = profile_placement_ok(rows, g, cfg)
    assert not valid
    assert 'pose_or_gap_outside_contract' in report['reasons']


def test_reservation_preserves_pending_clearance_with_existing_bounded_overlap(monkeypatch):
    g, p = fixture()
    # The first two trays are stable, while the third is still at its source.
    p[2, :3] = np.array([-1.25, 0., .801])
    samples = [dict(tray_pose=p.copy(), table_contact=np.ones(3),
                    gripper_contact_force=np.zeros((3, 2))) for _ in range(24)]
    monkeypatch.setattr('r1pro_teleop.airport_fsm.scheduler._executable_geometry',
                        lambda *args: True)
    # Exercise the candidate branch when a separate operation defect caused
    # verification to fall through; keep the protected-footprint check real.
    monkeypatch.setattr('r1pro_teleop.airport_fsm.reservation_plan.slot_geometry_ready',
        lambda *args, **kwargs: (False if kwargs.get('reservation_positions') is None
                                 else geometry_module.slot_geometry_ready(*args, **kwargs)))
    operation = Operation(1, 1, g.goals[1], g.goal_yaw[1])
    for approximate in (True, False):
        cfg = replace(config(approximate), completion_adaptive_reservation_enabled=True,
                      fixed_primitives=True)
        events = []
        machine = SimpleNamespace(c=cfg, g=g,
            scheduler=SimpleNamespace(mapping=[0, 1, 2], reservation_plan=None),
            verified_final_trays={0}, r=SimpleNamespace(holding=None,
                retained_contact=None, steps=100),
            log=SimpleNamespace(event=lambda name, **kw: events.append((name, kw))))
        result = propose(machine, operation, samples)
        assert (result is not None) is approximate, events
        if approximate:
            assert result['pending_tray'] == 2
            # A future placement keeps its 2 mm reservation clearance.
            assert result['candidate_index'] in range(9)
        else:
            assert events[-1][0] == 'adaptive_reservation_rejected'
            assert all(item['reason'] == 'reserved_clearance'
                       for item in events[-1][1]['rejected'])
