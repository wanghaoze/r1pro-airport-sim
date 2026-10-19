"""Release-space prerequisites selected before a physical pick starts.

All pose edits below are private geometric hypotheses. Each prerequisite is a
normal numbered FSM operation; no hidden motion, live reset or extra budget.
"""
import numpy as np
from .contracts import Fault
from .geometry import Operation, rectangle, rz, push_overhang_kwargs


def release_location(g, pose, operation, cfg):
    destination = operation.destination.copy()
    if not g.blockers(pose, operation.tray, destination, operation.yaw, .065):
        return destination
    for sign in (1., -1.):
        staged = destination + g.R[:, 0]*sign*(cfg.staging_clearance_m+.025)
        if not g.footprint_supported(staged, operation.yaw, g.sizes[operation.tray]):
            continue
        if g.blockers(pose, operation.tray, staged, operation.yaw, .045):
            continue
        predicted = pose.copy()
        predicted[operation.tray, :3] = staged
        predicted[operation.tray, 3:] = [np.cos(operation.yaw/2), 0, 0, np.sin(operation.yaw/2)]
        if g.push_possible(predicted, operation.tray, destination, operation.yaw,
                           cfg.push_max_distance_m, np.deg2rad(cfg.push_max_yaw_deg),
                           **push_overhang_kwargs(cfg)):
            return staged
    raise Fault('no_safe_release_clearance', recoverable=True)


def _executable_geometry(g, pose, op, cfg):
    if g.push_possible(pose, op.tray, op.destination, op.yaw,
                       cfg.push_max_distance_m, np.deg2rad(cfg.push_max_yaw_deg),
                       **push_overhang_kwargs(cfg)):
        return True
    try:
        release_location(g, pose, op, cfg)
        return True
    except Fault as exc:
        if exc.code != 'no_safe_release_clearance':
            raise
        return False


def rear_buffer_candidates(g, pose, tray, *, source_position=None, rejected=None):
    """Existing three rear positions, with unchanged footprint/clearance gates."""
    rear = g.tables.get('rear')
    if rear is None:
        return []
    center = np.asarray(rear['center_world'], float)
    rotation = rz(float(rear.get('yaw_world', 0.)))
    half = np.asarray(rear['dimensions_m'][:2], float)/2
    source = pose[tray, :2] if source_position is None else np.asarray(source_position)[:2]
    choices = []
    for offset in (0., -.25, .25):
        destination = center + rotation@np.array([offset, 0., 0.])
        destination[2] = rear['dimensions_m'][2]+.001
        yaw = float(g.goal_yaw[0])
        corners = rectangle(destination, yaw, g.sizes[tray])
        local = (corners-center[:2])@rotation[:2,:2]
        reasons = []
        if not np.all(abs(local) <= half-.004):
            reasons.append('rear_footprint')
        if np.linalg.norm(destination[:2]-source) < .15:
            reasons.append('source_displacement')
        if g.blockers(pose, tray, destination, yaw, .025):
            reasons.append('neighbour_clearance')
        if not reasons:
            choices.append(Operation(tray, -1, destination, yaw, True))
        elif rejected is not None:
            rejected.append({'destination': destination.copy(), 'yaw': yaw, 'reasons': reasons})
    return choices


def release_prerequisite(g, pose, operation, mapping, protected_trays, cfg, *, planning_destination=None):
    """Return one finite prerequisite, or the unchanged feasible operation.

    Only currently top-accessible, unverified blockers may move. A proposed
    blocker placement must itself be releasable and leave the original target
    releasable in the predicted layout. This avoids moving a blocker to its
    tight final slot only to discover that both neighbours now prevent release.
    Recheck actual state after that numbered prerequisite completes.
    """
    if _executable_geometry(g, pose, operation, cfg):
        return operation, None
    blockers = g.blockers(pose, operation.tray, operation.destination, operation.yaw, .065)
    eligible = [t for t in blockers if t not in protected_trays and g.top_available(pose, t)]
    examined = 0
    for tray in eligible:
        slot = mapping.index(tray)
        choices = [Operation(tray, slot, g.goals[slot].copy() if planning_destination is None else planning_destination(slot), float(g.goal_yaw[slot]))]
        for u in np.linspace(g.belt_length-.25, .25, 30):
            destination = g.to_world([u, g.belt_width/2, 0.]); destination[2] += .001
            yaw = float(g.goal_yaw[0])
            if np.linalg.norm(destination[:2]-pose[tray, :2]) < .15:
                continue
            if (g.footprint_supported(destination, yaw, g.sizes[tray]) and
                    not g.blockers(pose, tray, destination, yaw, .025)):
                choices.append(Operation(tray, -1, destination, yaw, True))
        choices.extend(rear_buffer_candidates(g, pose, tray))
        for proposed in choices:
            examined += 1
            if not _executable_geometry(g, pose, proposed, cfg):
                continue
            predicted = pose.copy()
            predicted[tray, :3] = proposed.destination
            predicted[tray, 3:] = [np.cos(proposed.yaw/2), 0, 0, np.sin(proposed.yaw/2)]
            if not _executable_geometry(g, predicted, operation, cfg):
                continue
            return proposed, {'requested_tray': operation.tray, 'requested_slot': operation.slot,
                'blockers': blockers, 'protected_trays': sorted(protected_trays),
                'selected_blocker': tray, 'examined': examined,
                'qualification': 'geometric_prerequisite_requires_full_physical_operation'}
    raise Fault('no_safe_release_precondition', {
        'requested_tray': operation.tray, 'requested_slot': operation.slot,
        'blockers': blockers, 'protected_trays': sorted(protected_trays),
        'eligible_blockers': eligible, 'examined': examined,
        'cause': 'no_safe_release_clearance'})
