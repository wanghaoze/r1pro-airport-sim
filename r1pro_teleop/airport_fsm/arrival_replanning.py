"""Permit one relocation only after a proven zero-motion planning rejection."""
import numpy as np
from .contracts import wrap_angle


PLANNING_FAILURES = frozenset({
    'ik_unreachable', 'ik_branch_jump', 'coupled_ik_unreachable',
    'cartesian_collision_or_wrist', 'primitive_path_infeasible',
    'primitive_insufficient_time',
})


def zero_motion_place_failure(runtime, tray, failure):
    evidence = getattr(failure, 'primitive_execution', None)
    if (failure.code not in PLANNING_FAILURES or evidence is None or
            evidence['name'] not in ('transport_align', 'place') or
            evidence['elapsed_steps'] != 0 or evidence['physical_elapsed_s'] != 0. or
            runtime.steps != evidence['end_step'] or
            float(runtime.d.time) != evidence['physical_end'] or
            runtime.holding != tray or runtime.retained_contact is not None):
        return False
    force = runtime.observation()['gripper_contact_force'][tray]
    return bool(np.all(np.isfinite(force)) and np.all(force > runtime.cfg.criteria.contact_n))


def alternative_bases(candidates, failed_base):
    """Exclude the failed physical stance, including nominal rounding drift."""
    failed = np.asarray(failed_base, float)
    seen = set()
    for candidate in candidates:
        value = np.asarray(candidate, float)
        if (np.linalg.norm(value[:2]-failed[:2]) <= .001 and
                abs(float(wrap_angle(value[2]-failed[2]))) <= .001):
            continue
        key = tuple(np.round(np.r_[value[:2], wrap_angle(value[2])], 8))
        if key not in seen:
            seen.add(key)
            yield value.copy()
