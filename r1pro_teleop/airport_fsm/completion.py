"""Report task completion separately from conformance to strict execution rules."""
from collections import Counter


def completion_fields(runtime, success):
    profile = getattr(runtime.cfg, 'acceptance_profile', 'strict')
    strict = bool(success and getattr(runtime, 'strict_runtime_passed', True))
    return {
        **dict(getattr(runtime, 'attempt_controller_policy', {})),
        'acceptance_profile': profile,
        'approximate_completion_enabled': bool(getattr(runtime.cfg, 'approximate_completion_enabled', False)),
        'effective_acceptance_profile': ('approximate_completion' if
            getattr(runtime.cfg, 'approximate_completion_enabled', False) else profile),
        'task_completed': bool(success),
        'strict_success': strict,
        'strict_success_semantics': 'No accepted relaxed planning, control or placement condition; conservatively includes accepted planning candidates whose execution is unconfirmed.',
        'physics_success_semantics': 'complete_task_under_recorded_acceptance_profile',
        'acceptance_deviations': {
            'count': int(getattr(runtime, 'soft_guard_violation_count', 0)),
            'by_code': dict(getattr(runtime, 'soft_guard_violation_by_code', {})),
            'maxima': dict(getattr(runtime, 'soft_guard_violation_maxima', {})),
        },
        'approximate_deviation_counts': dict(getattr(runtime, 'approximate_deviation_counts', {})),
    }


def outcome_counts(results):
    """Unique scenes; diagnostics never qualify, recovery remains separately visible."""
    actual = [r for r in results if not r.get('diagnostic_only')]
    completed = [r for r in actual if r.get('task_completed', r.get('physics_success', False))]
    strict = [r for r in completed if r.get('strict_success',
              r.get('acceptance_profile', 'strict') == 'strict') and not r.get('recovery_used')]
    attempts_per_scene = Counter(r['scene_id'] for r in actual)
    return {
        'task_completed_scenes': len({r['scene_id'] for r in completed}),
        'task_completed_attempts': len(completed),
        'strict_clean_successful_scenes': len({r['scene_id'] for r in strict}),
        'completed_with_recovery_scenes': len({r['scene_id'] for r in completed if r.get('recovery_used')}),
        'acceptance_profiles': sorted({r.get('acceptance_profile', 'strict') for r in actual}),
        'effective_acceptance_profiles': sorted({r.get('effective_acceptance_profile',
            'approximate_completion' if r.get('approximate_completion_enabled') else
            r.get('acceptance_profile', 'strict')) for r in actual}),
        'effective_controller_policies': sorted({r.get('effective_controller_policy', 'configured') for r in actual}),
        'first_attempt_task_completed_scenes': len({r['scene_id'] for r in completed if r.get('attempt', 0) == 0}),
        'first_attempt_strict_clean_scenes': len({r['scene_id'] for r in strict if r.get('attempt', 0) == 0}),
        'maximum_attempts_observed_per_scene': max(attempts_per_scene.values(), default=0),
    }
