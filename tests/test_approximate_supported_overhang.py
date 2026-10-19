"""Overhanging source trays may start a real push only with the opt-in flag."""
from dataclasses import replace

import numpy as np
import pytest

from test_airport_fsm_unit import poses, spec_fixture
from r1pro_teleop.airport_fsm.contracts import Config
from r1pro_teleop.airport_fsm.geometry import Geometry, Operation, push_overhang_kwargs
from r1pro_teleop.airport_fsm.scheduler import _executable_geometry


def cfg(enabled=False):
    return replace(Config(acceptance_profile='completion_first',
        approximate_completion_enabled=True,
        retained_support_integer_clock_enabled=True), allow_supported_overhang=enabled)


def overhanging_source():
    g = Geometry(spec_fixture())
    p = poses(g)
    p[2, 0] = .829
    assert g.front_supported(p[2, :3])
    assert not g.footprint_supported(p[2, :3], g.goal_yaw[2], g.sizes[2])
    return g, p


def test_opt_in_com_supported_push_and_default_full_footprint():
    g, p = overhanging_source()
    assert not g.push_possible(p, 2, g.goals[2], g.goal_yaw[2])
    assert g.push_possible(p, 2, g.goals[2], g.goal_yaw[2],
                           **push_overhang_kwargs(cfg(True)))
    assert push_overhang_kwargs(cfg(False)) == {}
    assert push_overhang_kwargs(Config()) == {}
    assert not Config().allow_supported_overhang
    cfg(True).validate()
    with pytest.raises(ValueError, match='requires approximate'):
        replace(Config(), allow_supported_overhang=True).validate()


def test_opt_in_preserves_front_com_top_tilt_distance_yaw_and_neighbour_guards(monkeypatch):
    g, p = overhanging_source()
    goal = g.goals[2]
    checked = []
    original = g.front_supported
    def record(point):
        checked.append(np.asarray(point).copy())
        return original(point)
    monkeypatch.setattr(g, 'front_supported', record)
    assert g.push_possible(p, 2, goal, g.goal_yaw[2], allow_supported_overhang=True)
    # Source, destination and the full 25-point sweep each check the COM.
    assert len(checked) == 27
    assert not g.push_possible(p, 2, [-1.25, 0., .8], g.goal_yaw[2],
                               max_distance=5., allow_supported_overhang=True)
    assert not g.push_possible(p, 2, goal, g.goal_yaw[2],
                               max_distance=.01, allow_supported_overhang=True)
    assert not g.push_possible(p, 2, goal, g.goal_yaw[2]+np.deg2rad(20),
                               allow_supported_overhang=True)
    pitched = p.copy()
    pitched[2, 4] = np.sin(np.deg2rad(6)/2)
    pitched[2, 3] = np.cos(np.deg2rad(6)/2)
    assert not g.push_possible(pitched, 2, goal, g.goal_yaw[2],
                               allow_supported_overhang=True)
    blocked = p.copy(); blocked[0, :3] = goal
    assert not g.push_possible(blocked, 2, goal, g.goal_yaw[2],
                               allow_supported_overhang=True)


def test_scheduler_geometry_forwards_flag_only_when_enabled(monkeypatch):
    g, p = overhanging_source()
    operation = Operation(2, 2, g.goals[2], g.goal_yaw[2])
    calls = []
    actual = g.push_possible
    def observe(*args, **kwargs):
        calls.append(kwargs.copy())
        return actual(*args, **kwargs)
    monkeypatch.setattr(g, 'push_possible', observe)
    assert _executable_geometry(g, p, operation, cfg(True))
    assert calls[0]['allow_supported_overhang'] is True
    calls.clear()
    _executable_geometry(g, p, operation, cfg(False))
    assert 'allow_supported_overhang' not in calls[0]
