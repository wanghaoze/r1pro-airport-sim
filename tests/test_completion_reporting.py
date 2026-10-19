from types import SimpleNamespace
import pytest
from r1pro_teleop.airport_fsm.completion import completion_fields, outcome_counts
from r1pro_teleop.airport_fsm.contracts import Config
from scripts.control_regression import summarize_results


def test_completion_is_separate_from_strict_and_recovery():
    runtime = SimpleNamespace(cfg=SimpleNamespace(acceptance_profile='completion_first'),
                              strict_runtime_passed=False, soft_guard_violation_count=2,
                              soft_guard_violation_by_code={'arm_overspeed': 2})
    fields = completion_fields(runtime, True)
    assert fields['task_completed'] and not fields['strict_success']
    rows = [dict(fields, scene_id='s', recovery_used=True),
            dict(fields, scene_id='s', recovery_used=False),
            dict(fields, scene_id='probe', diagnostic_only=True)]
    counts = outcome_counts(rows)
    assert counts['task_completed_scenes'] == 1
    assert counts['strict_clean_successful_scenes'] == 0
    assert counts['completed_with_recovery_scenes'] == 1


def test_approximate_result_and_summary_keep_changed_acceptance_visible():
    runtime = SimpleNamespace(cfg=SimpleNamespace(acceptance_profile='completion_first',
        approximate_completion_enabled=True), strict_runtime_passed=False,
        approximate_deviation_counts={'illegal_collision': 27})
    fields = completion_fields(runtime, True)
    assert fields['effective_acceptance_profile'] == 'approximate_completion'
    assert fields['approximate_deviation_counts'] == {'illegal_collision': 27}
    counts = outcome_counts([dict(fields, scene_id='s')])
    assert counts['effective_acceptance_profiles'] == ['approximate_completion']
    assert counts['strict_clean_successful_scenes'] == 0


def test_profile_70_requires_all400_and_reports_original_standard():
    ids = [str(i) for i in range(400)]
    rows = [dict(scene_id=s, physics_success=i < 280, task_completed=i < 280,
                 strict_success=False, acceptance_profile='completion_first') for i, s in enumerate(ids)]
    report = summarize_results(rows, ids, 1)
    assert report['task_completion_target_70_percent_reached']
    assert not report['strict_target_70_percent_reached']
    assert report['task_completion_rate'] == .7
    assert not summarize_results(rows[:-1], ids, 1)['task_completion_target_70_percent_reached']


@pytest.mark.parametrize('changes', [dict(acceptance_profile='anything'),
    dict(acceptance_profile='completion_first'), dict(completion_speed_ratio_max=float('nan')),
    dict(completion_support_grace_s=2.), dict(completion_yaw_deg=90.)])
def test_invalid_profiles_are_rejected(changes):
    with pytest.raises(ValueError):
        Config(**changes).validate()


def test_checkpoint_preserves_deviations_and_active_speed_timer(tmp_path):
    from test_support_clock_checkpoint import clock_machine, step_physics
    from r1pro_teleop.experiments.checkpoint_tree import CheckpointTree
    import json
    a = clock_machine(tmp_path, 'completion_a')
    b = clock_machine(tmp_path, 'completion_b')
    try:
        for m in (a, b):
            m.r.cfg.acceptance_profile = 'completion_first'
            m.r.strict_runtime_passed = False
            m.r.soft_guard_violation_count = 1
            m.r.soft_guard_violation_by_code = {'measured_joint_overspeed': 1}
            m.r.soft_guard_violation_maxima = {'measured_joint_overspeed': {'ratio': 1.03}}
            m.r.soft_guard_last_step_by_code = {'measured_joint_overspeed': 0}
            m.r.completion_speed_since_step = 0
        step_physics(a.r, 3)
        tree = CheckpointTree(a, tmp_path/'completion_cp')
        tree.plan(['settled'])
        cp = tree.save('settled', lambda _: True)
        CheckpointTree(b, tmp_path/'completion_restore').restore(cp)
        assert b.r.completion_speed_since_step == 0
        assert b.r.physics_step_count == 3
        assert b.r.soft_guard_violation_by_code == a.r.soft_guard_violation_by_code
        assert not b.r.strict_runtime_passed
        data = json.loads((cp/'metadata.json').read_text())
        del data['context']['runtime']['completion_speed_since_step']
        from r1pro_teleop.experiments.checkpoint_tree import validate_completion_context
        with pytest.raises(ValueError, match='checkpoint_completion_context_missing'):
            validate_completion_context(a.r.cfg, data['context']['runtime'])
    finally:
        a.log.close()
        b.log.close()


def test_initialization_failure_keeps_declared_profile(tmp_path, monkeypatch):
    from r1pro_teleop.airport_fsm import runtime
    from r1pro_teleop.airport_fsm.machine import run_attempt
    def fail(*args, **kwargs):
        raise RuntimeError('initialization fixture failure')
    monkeypatch.setattr(runtime, 'Runtime', fail)
    cfg = Config(acceptance_profile='completion_first', retained_support_integer_clock_enabled=True)
    result = run_attempt({'scene_id': 'fixture', 'split': 'train'}, 'unused.xml', cfg, tmp_path/'failure')
    assert result['acceptance_profile'] == 'completion_first'
    assert not result['task_completed'] and not result['strict_success']
    assert result['frames'] == 0


def test_multiple_attempts_never_inflate_unique_completion_rate():
    rows = [dict(scene_id='a', attempt=0, task_completed=False),
            dict(scene_id='a', attempt=1, task_completed=True, strict_success=False),
            dict(scene_id='a', attempt=2, task_completed=True, strict_success=False),
            dict(scene_id='b', attempt=0, task_completed=True, strict_success=True)]
    result = outcome_counts(rows)
    assert result['task_completed_scenes'] == 2
    assert result['task_completed_attempts'] == 3
    assert result['first_attempt_task_completed_scenes'] == 1
    assert result['maximum_attempts_observed_per_scene'] == 3
