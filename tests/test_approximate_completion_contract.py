"""Configuration boundaries for explicitly enabled approximate simulation runs."""
from dataclasses import replace
from pathlib import Path

import pytest

from r1pro_teleop.airport_fsm.contracts import Config


def approximate(**changes):
    base = Config(acceptance_profile='completion_first',
                  retained_support_integer_clock_enabled=True,
                  approximate_completion_enabled=True)
    return replace(base, **changes)


def test_default_and_strict_contract_are_unchanged():
    default = Config().validate()
    assert default.acceptance_profile == 'strict'
    assert default.approximate_completion_enabled is False
    assert default.primitive_seconds == 3.
    with pytest.raises(ValueError, match='requires completion_first'):
        replace(default, approximate_completion_enabled=True).validate()
    with pytest.raises(ValueError, match='Primitive duration'):
        replace(default, primitive_seconds=3.01).validate()


def test_extended_completion_bounds_require_explicit_switch():
    original = approximate(approximate_completion_enabled=False)
    with pytest.raises(ValueError, match='completion_position_m'):
        replace(original, completion_position_m=.10).validate()
    with pytest.raises(ValueError, match='completion_gap_max_m'):
        replace(original, completion_gap_max_m=.10).validate()
    with pytest.raises(ValueError, match='completion_held_ik_position_tolerance_m'):
        replace(original, completion_held_ik_position_tolerance_m=.10).validate()
    with pytest.raises(ValueError, match='completion_held_ik_orientation_tolerance_rad'):
        replace(original, completion_held_ik_orientation_tolerance_rad=.20).validate()
    assert approximate(completion_position_m=.10, completion_gap_max_m=.10,
                       completion_held_ik_position_tolerance_m=.10,
                       completion_held_ik_orientation_tolerance_rad=.20).validate()


@pytest.mark.parametrize('field,invalid', [
    ('completion_release_gap_m', -.001),
    ('completion_release_gap_m', .020001),
    ('completion_collision_penetration_m', -.001),
    ('completion_collision_penetration_m', .030001),
    ('completion_release_gap_m', True),
    ('completion_collision_penetration_m', float('nan')),
])
def test_approximate_release_and_penetration_are_bounded(field, invalid):
    with pytest.raises(ValueError, match=field):
        replace(approximate(), **{field: invalid}).validate()
    assert approximate(completion_release_gap_m=0.,
                       completion_collision_penetration_m=0.).validate()


def test_long_primitive_budget_and_zero_shift_switch_are_scoped():
    assert approximate(primitive_seconds=20., fixed_primitives=True,
        completion_place_zero_shift_combined_fallback_enabled=True).validate()
    with pytest.raises(ValueError, match='Primitive duration'):
        approximate(primitive_seconds=20.001).validate()
    with pytest.raises(ValueError, match='Primitive duration'):
        approximate(approximate_completion_enabled=False,
                    primitive_seconds=6.001).validate()
    with pytest.raises(ValueError, match='fixed place'):
        approximate(completion_place_zero_shift_combined_fallback_enabled=True).validate()
    with pytest.raises(ValueError, match='must be boolean'):
        approximate(completion_place_zero_shift_combined_fallback_enabled=1).validate()


def test_approximate_config_loads_without_changing_original_candidate():
    root = Path(__file__).resolve().parents[1]
    new = Config.load(root/'configs/airport_approximate_completion_retry3.json')
    old = Config.load(root/'configs/airport_completion_handoff_clearance_retry3.json')
    assert new.approximate_completion_enabled and not old.approximate_completion_enabled
    assert (new.completion_position_m, new.completion_yaw_deg, new.completion_gap_max_m) == (.10, 15., .10)
    assert (new.completion_held_ik_position_tolerance_m,
            new.completion_held_ik_orientation_tolerance_rad) == (.10, .20)
    assert (new.completion_release_gap_m,
            new.completion_collision_penetration_m) == (.02, .02)
    assert new.completion_place_private_position_tolerance_m == .10
    assert new.completion_place_zero_shift_combined_fallback_enabled
    assert new.primitive_seconds == 20.
    assert old.primitive_seconds == 5.
