"""Strict front station planning plus the already authorized 5 cm drift."""
import numpy as np
from ..single_tray_3table.observer import table_front_region_violation

FRONT_FIELDS=('front_reference_xy','front_reference_table_index','front_manipulating',
    'front_reference_strict','front_actual_strict','front_drift_m','front_allowance_used')


def front_drift_check(table,position,reference,*,limit=.05):
    actual=np.asarray(position,float)[:2];reference=np.asarray(reference,float)[:2]
    if actual.shape!=(2,) or reference.shape!=(2,) or not np.isfinite(np.r_[actual,reference]).all():
        raise ValueError('native_front_drift_invalid_reference')
    strict_reference=not table_front_region_violation(table,reference)
    strict_actual=not table_front_region_violation(table,actual)
    drift=float(np.linalg.norm(actual-reference))
    allowed=bool(strict_reference and drift<=limit+1e-9)
    return dict(allowed=allowed,front_reference_xy=reference.copy(),front_reference_strict=strict_reference,
        front_actual_strict=strict_actual,front_drift_m=drift,front_allowance_used=allowed and not strict_actual)
