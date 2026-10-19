"""Attempt policy is declared before motion and never mutates the base config."""
from dataclasses import replace
from types import SimpleNamespace
import math

import pytest

from r1pro_teleop.airport_fsm.attempt_policy import (
    attempt_policy_fields, attempt_policy_label, effective_attempt_config,
)
from r1pro_teleop.airport_fsm.contracts import Config


def cfg(enabled=True):
    return Config(acceptance_profile='completion_first',
        approximate_completion_enabled=True,
        retained_support_integer_clock_enabled=True,
        completion_supported_push_fallback_attempt_enabled=enabled)


def test_attempt_zero_preserves_base_and_retries_use_declared_wider_push():
    base = cfg().validate()
    original = base.dump()
    assert effective_attempt_config(base, 0) is base
    assert attempt_policy_label(base, 0) == 'baseline'
    for attempt in (1, 2, 17):
        effective = effective_attempt_config(base, attempt)
        assert effective is not base
        assert effective.allow_supported_overhang
        assert effective.push_max_distance_m == .6
        assert effective.push_max_yaw_deg == 90.
        assert effective.validate() is effective
        fields = attempt_policy_fields(base, attempt)
        assert fields == {
            'effective_controller_policy': 'supported_overhang_wide_push',
            'declared_controller_attempt_schedule': {
                'attempt_0': 'baseline', 'attempt_1_plus': 'supported_overhang_wide_push'},
            'effective_push_max_distance_m': .6,
            'effective_push_max_yaw_deg': 90.,
            'allow_supported_overhang': True,
        }
    assert base.dump() == original
    first = attempt_policy_fields(base, 0)
    assert first['effective_push_max_distance_m'] == .18
    assert first['effective_push_max_yaw_deg'] == 15.
    assert not first['allow_supported_overhang']


def test_disabled_policy_returns_same_object_and_simple_metadata():
    base = cfg(False).validate()
    assert effective_attempt_config(base, 2) is base
    assert attempt_policy_fields(base, 2)['declared_controller_attempt_schedule'] == {
        'all_attempts': 'baseline'}
    simple = SimpleNamespace(push_max_distance_m=.25, push_max_yaw_deg=20.)
    assert attempt_policy_fields(simple, 0)['effective_push_max_distance_m'] == .25
    assert attempt_policy_fields(simple, 1)['effective_controller_policy'] == 'baseline'


@pytest.mark.parametrize('attempt', [True, False, -1, 1.0, '1', None])
def test_invalid_attempt_rejected(attempt):
    for function in (attempt_policy_label, effective_attempt_config,
                     attempt_policy_fields):
        with pytest.raises(ValueError, match='nonnegative integer'):
            function(cfg(), attempt)


def test_config_activation_and_finite_declared_bounds():
    with pytest.raises(ValueError, match='requires approximate'):
        replace(Config(), completion_supported_push_fallback_attempt_enabled=True).validate()
    with pytest.raises(ValueError, match='must be boolean'):
        replace(cfg(), completion_supported_push_fallback_attempt_enabled=1).validate()
    for field, low, high in (
            ('completion_supported_push_fallback_distance_m', .18, .8),
            ('completion_supported_push_fallback_yaw_deg', 15., 90.)):
        for value in (True, math.nan, math.inf, low-.001, high+.001):
            with pytest.raises(ValueError, match=field):
                replace(cfg(), **{field: value}).validate()
        replace(cfg(), **{field: low}).validate()
        replace(cfg(), **{field: high}).validate()


def test_run_attempt_instantiates_runtime_with_effective_policy(monkeypatch, tmp_path):
    from r1pro_teleop.airport_fsm import machine as machine_module
    from r1pro_teleop.airport_fsm import runtime as runtime_module
    from r1pro_teleop.airport_fsm.completion import completion_fields
    observed = []

    def runtime_factory(spec, xml, effective):
        observed.append(effective)
        return SimpleNamespace(cfg=effective)

    class FakeMachine:
        def __init__(self, runtime, directory, **kwargs):
            self.runtime = runtime

        def run(self):
            return {'passed': True}

        def finish(self, success, acceptance):
            return completion_fields(self.runtime, success)

    monkeypatch.setattr(runtime_module, 'Runtime', runtime_factory)
    monkeypatch.setattr(machine_module, 'Machine', FakeMachine)
    base = cfg().validate()
    result = machine_module.run_attempt({'seed': 1}, 'unused.xml', base, tmp_path, attempt=1)
    assert observed[0].push_max_distance_m == .6
    assert observed[0].allow_supported_overhang
    assert base.push_max_distance_m == .18 and not base.allow_supported_overhang
    assert result['effective_controller_policy'] == 'supported_overhang_wide_push'
    assert result['task_completed']
