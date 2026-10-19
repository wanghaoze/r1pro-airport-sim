"""Measured, guarded free-hand clearance before an existing retained push.

This opt-in candidate does not alter the support or contact acceptance gates.
It separates jaw opening from arm withdrawal and starts the push only after
real finger geometry and force confirm clearance.
"""
from __future__ import annotations

import numpy as np

from .contracts import Fault, State


FREE_FORCE_LIMIT_N = .5
MIN_OPENING_M = .09
MIN_FINGER_TOP_CLEARANCE_M = .005
MIN_PREDICTED_FINGER_TOP_CLEARANCE_M = .020
VERTICAL_CANDIDATES_M = (.04, .06, .08, .10)


def check_monitor(runtime, observation, monitor):
    """Extra 2-ms interlock; the ordinary physical guard still runs."""
    tray, free = monitor
    free_index = 0 if free == 'left' else 1
    force = float(observation['gripper_contact_force'][tray, free_index])
    if force > runtime.cfg.criteria.contact_n:
        detail = {'tray': tray, 'free_side': free, 'force_n': force}
        if getattr(runtime.cfg, 'approximate_completion_enabled', False):
            runtime._approximate_deviation('handoff_clearance_free_recontact', detail)
        else:
            raise Fault('handoff_clearance_free_recontact', detail)
    if observation['table_contact'][tray] <= 0:
        table = runtime.g.support_table(observation['tray_pose'][tray, :3])
        gap = (float(observation['min_z'][tray] - runtime.g.tables[table]['dimensions_m'][2])
               if table is not None else float('inf'))
        if gap > .002:
            detail = {'tray': tray, 'bottom_gap_m': gap,
                      'table_contact': int(observation['table_contact'][tray])}
            if (getattr(runtime.cfg, 'approximate_completion_enabled', False) and
                    np.isfinite(gap) and gap <= runtime.cfg.completion_release_gap_m):
                runtime._approximate_deviation('handoff_clearance_support_lost', detail)
            else:
                raise Fault('handoff_clearance_support_lost', detail)


def finger_top_clearance(runtime, tray, free, target=None):
    """Minimum free-finger box bottom above the current tray's highest vertex."""
    d = runtime.d if target is None else runtime._shadow(target)
    body = int(runtime.m.body(runtime.g.ids[tray]).id)
    vertices = runtime.evidence.local_vertices[body]
    tray_body = d.body(runtime.g.ids[tray])
    rotation = tray_body.xmat.reshape(3, 3)
    top = float(np.max(vertices @ rotation[2] + tray_body.xpos[2]))
    bottoms = []
    for geom in range(runtime.m.ngeom):
        if runtime.m.geom_group[geom] != 3:
            continue
        name = runtime.m.body(int(runtime.m.geom_bodyid[geom])).name
        if not name.startswith(free + '_gripper_finger_'):
            continue
        if runtime.m.geom_type[geom] != runtime.mj.mjtGeom.mjGEOM_BOX:
            continue
        matrix = d.geom_xmat[geom].reshape(3, 3)
        extent = float(np.sum(np.abs(matrix[2]) * runtime.m.geom_size[geom]))
        bottoms.append(float(d.geom_xpos[geom, 2] - extent))
    if len(bottoms) != 2:
        raise Fault('handoff_clearance_finger_geometry_unavailable',
                    {'free_side': free, 'finger_boxes': len(bottoms)})
    return min(bottoms) - top


def observed_ready(runtime, tray, free):
    e = runtime.observation()
    col = 7 if free == 'left' else 15
    idx = 0 if free == 'left' else 1
    return (e['table_contact'][tray] > 0 and
            e['gripper_contact_force'][tray, idx] <= FREE_FORCE_LIMIT_N and
            runtime.sim.state()[col] >= MIN_OPENING_M)


def perform_handoff_clearance(machine, operation, keep):
    """Execute one separately budgeted interlock; leave monitor for the push.

    Caller must clear ``_handoff_clearance_monitor`` in a finally block after
    the retained push. A failure here clears it immediately and remains a
    failed physical attempt; it never falls back after partial motion.
    """
    from .primitives import action, execute, plan, remaining

    r = machine.r
    tray = operation.tray
    free = 'right' if keep == 'left' else 'left'
    free_col = 15 if free == 'right' else 7
    if (r.holding is not None or r.retained_contact != (tray, keep) or
            getattr(r, 'primitive_deadline_step', None) is not None):
        raise Fault('handoff_clearance_requires_retained_support')
    r.check_retained_contact()
    before = r.observation()
    if before['table_contact'][tray] <= 0 or before['gripper_contact_force'][tray, 1 if free=='right' else 0] > FREE_FORCE_LIMIT_N:
        raise Fault('handoff_clearance_initial_contact_not_free')
    if getattr(r, '_handoff_clearance_monitor', None) is not None:
        raise Fault('handoff_clearance_monitor_already_active')
    r._handoff_clearance_monitor = (tray, free)
    try:
        with action(machine, 'handoff_clearance', target_tray=tray,
                    retained_side=keep, free_side=free,
                    vertical_candidates_m=VERTICAL_CANDIDATES_M):
            machine.transition(State.PLACE_TRAY, 'handoff_open')
            start = r.sim.target.copy()
            opened = start.copy()
            opened[free_col] = r.cfg.gripper_open_m
            opening = plan(r, [start, opened], available=remaining(r)-.15,
                           minimum=.25)
            execute(r, opening)
            if not r.wait(.15, lambda _: observed_ready(r, tray, free), .1):
                raise Fault('handoff_clearance_open_not_verified', {
                    'measured_opening_m': float(r.sim.state()[free_col]),
                    'free_force_n': float(r.observation()['gripper_contact_force'][tray, 1 if free=='right' else 0])})
            machine.log.event('handoff_clearance_open_verified', target_tray=tray,
                free_side=free, measured_opening_m=float(r.sim.state()[free_col]),
                stable_seconds=.1)
            machine.transition(State.PLACE_TRAY, 'handoff_vertical')
            position, rotation = r.sim.tcp(free)
            rejected = []
            selected = None
            for rise in VERTICAL_CANDIDATES_M:
                goal = position.copy()
                goal[2] += rise
                try:
                    points = r.cartesian({free: (goal, rotation)},
                        speed=r.cfg.transit_tcp_speed, opening=r.cfg.gripper_open_m,
                        wrist=True, preview_only=True)
                    clearance = finger_top_clearance(r, tray, free, points[-1])
                    if clearance < MIN_PREDICTED_FINGER_TOP_CLEARANCE_M:
                        rejected.append({'rise_m': rise, 'reason': 'endpoint_finger_clearance',
                                         'clearance_m': clearance})
                        continue
                    candidate = plan(r, points, available=remaining(r)-.1,
                                     minimum=.1)
                except Fault as exc:
                    rejected.append({'rise_m': rise, 'reason': exc.code})
                    continue
                selected = rise, candidate, clearance
                break
            if selected is None:
                raise Fault('handoff_clearance_vertical_path_unavailable', rejected)
            rise, planned, predicted_clearance = selected
            machine.log.event('handoff_clearance_vertical_selected', target_tray=tray,
                free_side=free, rise_m=rise, predicted_finger_top_clearance_m=predicted_clearance,
                rejected=rejected, qualification='full_reference_before_motion_not_contact_evidence')
            execute(r, planned)
            if not observed_ready(r, tray, free):
                raise Fault('handoff_clearance_vertical_not_verified',
                    {'reason': 'opening_force_or_table_support'})
            actual_clearance = finger_top_clearance(r, tray, free)
            if actual_clearance < MIN_FINGER_TOP_CLEARANCE_M:
                raise Fault('handoff_clearance_vertical_not_verified',
                    {'finger_top_clearance_m': actual_clearance})
            r.check_retained_contact()
            machine.log.event('handoff_clearance_verified', target_tray=tray,
                free_side=free, rise_m=rise,
                actual_finger_top_clearance_m=actual_clearance,
                free_force_n=float(r.observation()['gripper_contact_force'][tray, 1 if free=='right' else 0]),
                qualification='actual_support_force_and_finger_geometry_before_retained_push')
    except BaseException:
        r._handoff_clearance_monitor = None
        raise
