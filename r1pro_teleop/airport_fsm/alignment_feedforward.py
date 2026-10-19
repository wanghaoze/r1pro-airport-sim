"""One measured post-alignment command correction; never change acceptance goals."""
import numpy as np
from .geometry import rectangle, rz


def _supported_footprint(g, position, yaw, size, table, margin):
    if table is None:
        return False
    if str(table).startswith('front'):
        return g.footprint_supported(position, yaw, size, margin=margin)
    spec = g.tables[table]
    center = np.asarray(spec['center_world'], float)
    rotation = rz(float(spec.get('yaw_world', 0.)))
    local = (rectangle(position, yaw, size)-center[:2])@rotation[:2,:2]
    return bool(np.all(abs(local) <= np.asarray(spec['dimensions_m'][:2])/2-margin))


def alignment_xy_target(g, poses, tray, staged, target, yaw, *, alignment_completed, scope='all'):
    """Return an owned command and audit details, bounded to 10 mm in XY.

    The caller enables this only after a real independent alignment. A shadow
    future endpoint is not a measurement and must not supply this residual.
    """
    if scope not in ('all', 'support_risk'):
        raise ValueError('Unknown alignment feedforward scope')
    original = np.asarray(target, float).copy()
    selected = original.copy()
    staged = np.asarray(staged, float)
    measured = np.asarray(poses[tray, :2], float)
    residual = staged[:2]-measured
    info = dict(original_command=original.copy(), measured_xy=measured.copy(),
        alignment_residual_xy=residual.copy(), max_norm_m=.01,
        footprint_margin_m=.004, blocker_clearance_m=.065,
        acceptance_staged=staged.copy(), alignment_completed=bool(alignment_completed),
        applied=False, rejection=None, scope=scope)
    if not alignment_completed:
        info['rejection'] = 'no_completed_independent_alignment'
    elif not np.all(np.isfinite(residual)):
        info['rejection'] = 'nonfinite_alignment_residual'
    else:
        original_table = g.support_table(staged)
        # A measured residual is only a risk estimate, never a forecast of
        # physical success. Keep benign alignment errors on the original path.
        projected = original.copy()
        projected[:2] -= residual
        supported = _supported_footprint(g, projected, yaw, g.sizes[tray], original_table, 0.)
        info.update(projected_uncorrected_position=projected.copy(),
                    projected_uncorrected_footprint_supported=bool(supported),
                    risk_footprint_margin_m=0.)
        if scope == 'support_risk' and supported:
            info['rejection'] = 'uncorrected_footprint_supported'
            info['selected_command'] = selected.copy()
            info['qualification'] = 'bounded_command_feedforward_original_acceptance_and_physics_unchanged'
            return selected, info
        correction = residual*min(1., .01/max(float(np.linalg.norm(residual)), 1e-12))
        candidate = original.copy()
        candidate[:2] += correction
        info.update(candidate_command=candidate.copy(), bounded_offset_xy=correction.copy())
        table = g.support_table(candidate)
        same_support = table is not None and (table == original_table or
            str(table).startswith('front') and str(original_table).startswith('front'))
        footprint = same_support and _supported_footprint(g, candidate, yaw, g.sizes[tray], table, .004)
        blockers = g.blockers(poses, tray, candidate, yaw, .065)
        info.update(footprint_supported=bool(footprint), blockers=blockers)
        if not same_support:
            info['rejection'] = 'support_region_changed'
        elif not footprint:
            info['rejection'] = 'unsupported_command_footprint'
        elif blockers:
            info['rejection'] = 'command_release_blocked'
        else:
            selected = candidate
            info['applied'] = True
    info['selected_command'] = selected.copy()
    info['qualification'] = 'bounded_command_feedforward_original_acceptance_and_physics_unchanged'
    return selected, info
