"""Predeclared per-attempt approximate push geometry; no live state dependence."""
from dataclasses import replace


def _check_attempt(attempt):
    if type(attempt) is not int or attempt < 0:
        raise ValueError('attempt must be a nonnegative integer')


def attempt_policy_label(cfg, attempt):
    """Stable metadata label for the selected attempt-level route."""
    _check_attempt(attempt)
    if getattr(cfg, 'completion_supported_push_fallback_attempt_enabled', False) and attempt >= 1:
        if not getattr(cfg, 'approximate_completion_enabled', False):
            raise ValueError('supported push fallback requires approximate completion')
        return 'supported_overhang_wide_push'
    return 'baseline'


def effective_attempt_config(cfg, attempt):
    """Return the unchanged baseline or a frozen config for attempts 1+."""
    label = attempt_policy_label(cfg, attempt)
    if label == 'baseline':
        return cfg
    return replace(cfg, allow_supported_overhang=True,
        push_max_distance_m=cfg.completion_supported_push_fallback_distance_m,
        push_max_yaw_deg=cfg.completion_supported_push_fallback_yaw_deg)


def attempt_policy_fields(cfg, attempt):
    """Trace metadata for the declared schedule and this attempt's controls."""
    label = attempt_policy_label(cfg, attempt)
    enabled = bool(getattr(cfg, 'completion_supported_push_fallback_attempt_enabled', False))
    schedule = ({'attempt_0': 'baseline', 'attempt_1_plus': 'supported_overhang_wide_push'}
                if enabled else {'all_attempts': 'baseline'})
    return {
        'effective_controller_policy': label,
        'declared_controller_attempt_schedule': schedule,
        'effective_push_max_distance_m': float(
            getattr(cfg, 'completion_supported_push_fallback_distance_m', .6)
            if label != 'baseline' else getattr(cfg, 'push_max_distance_m', .18)),
        'effective_push_max_yaw_deg': float(
            getattr(cfg, 'completion_supported_push_fallback_yaw_deg', 90.)
            if label != 'baseline' else getattr(cfg, 'push_max_yaw_deg', 15.)),
        'allow_supported_overhang': (True if label != 'baseline' else
            bool(getattr(cfg, 'allow_supported_overhang', False))),
    }
