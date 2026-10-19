"""Conservative pre-grasp pull proposal; all live motion remains in Runtime.

The two radii are tunable engineering heuristics, NOT measured workspace limits.
A proposal is never a success label. It still requires single-hand IK, swept
table support, physical contact, measured progress and a post-pull grasp plan.
"""
import numpy as np
from .contracts import Fault
from .geometry import rectangle, overlap, quat_yaw_tilt


def estimate(goals, shoulders, cfg):
    distances = {s: float(np.linalg.norm(goals[s][0]-shoulders[s])) for s in goals}
    return dict(distances_m=distances,
                dual_likely_unreachable=max(distances.values()) > cfg.reach_pull_dual_radius_m,
                single_candidates=sorted((s for s, d in distances.items()
                                          if d <= cfg.reach_pull_single_radius_m), key=distances.get),
                qualification='engineering_heuristic_not_workspace_calibration')


def supported_sweep(g, poses, tray, destination):
    """Require FULL footprint on the same table, including rounded-edge margin.

    Unlike ordinary separation's COM-only check this forbids pulling a tray lip
    beyond a table edge. It is deliberately conservative for rear-table layouts.
    """
    start = poses[tray, :3]
    table = g.support_table(start)
    if table is None or not g.top_available(poses, tray):
        return False
    yaw, tilt = quat_yaw_tilt(poses[tray, 3:])
    if tilt > np.deg2rad(5):
        return False
    t = g.tables[table]
    angle = t['yaw_world']
    R = np.array([[np.cos(angle), -np.sin(angle)], [np.sin(angle), np.cos(angle)]])
    half = np.asarray(t['dimensions_m'][:2])/2-.005
    for u in np.linspace(0, 1, 25):
        p = (1-u)*start+u*destination
        poly = rectangle(p, yaw, g.sizes[tray])
        local = (poly-np.asarray(t['center_world'][:2])) @ R
        if np.any(np.abs(local) > half+1e-9):
            return False
        if any(j != tray and overlap(poly, g.footprint(poses, j), .002) for j in range(3)):
            return False
    return True


def try_pull(machine, tray, slot, face, rim_x):
    """At an already parked base, optionally perform ONE pull per tray/episode."""
    r, c, g = machine.r, machine.c, machine.g
    used = getattr(machine, 'reach_pull_used', set())
    if tray in used:
        return False
    poses = machine._poses()
    observation = r.observation()
    if observation['table_contact'][tray] <= 0 or not g.top_available(poses, tray):
        machine.log.event('reach_pull_skipped', reason='not_directly_table_supported', target_tray=tray)
        return False
    center = poses[tray, :3].copy()
    center[2] += c.rim_height_local_m+.014
    goals = r.rim_goals(center, face, x_offset=rim_x)
    shoulders = {s: r.d.xanchor[r.m.joint(s+'_arm_joint1').id].copy() for s in goals}
    assessment = estimate(goals, shoulders, c)
    machine.log.event('reach_assessment', target_tray=tray, **assessment)
    if not assessment['dual_likely_unreachable']:
        return False
    toward = r.d.body('base_link').xpos[:2]-poses[tray, :2]
    length = float(np.linalg.norm(toward))
    if length < 1e-6:
        return False
    destination = None
    for distance in np.linspace(c.reach_pull_distance_m,c.reach_pull_min_progress_m,4):
        candidate=poses[tray,:3].copy()
        candidate[:2]+=distance*toward/length
        if supported_sweep(g,poses,tray,candidate):
            destination=candidate
            break
    if destination is None:
        machine.log.event('reach_pull_skipped', reason='unsupported_or_blocked_sweep', target_tray=tray)
        return False
    # Do not pull merely because one distance is large: the proposed translation
    # must reduce the worst dual-arm reach estimate, including table/base yaw.
    after_goals = {s: (value[0]+destination-poses[tray,:3], value[1]) for s,value in goals.items()}
    after = estimate(after_goals, shoulders, c)
    if max(after['distances_m'].values()) >= max(assessment['distances_m'].values())-.005:
        machine.log.event('reach_pull_skipped', reason='no_estimated_reach_improvement', target_tray=tray)
        return False
    from .geometry import Operation
    for side in assessment['single_candidates']:
        try:
            pre = goals[side][0].copy(); pre[2] += c.pregrasp_clearance_m
            # Single-arm pre-approach, not the old two-arm align prerequisite.
            # cartesian preview is read-only: a rejection cannot move the tray.
            r.cartesian({side:(pre,goals[side][1])}, opening=c.gripper_open_m,
                        wrist=True, preview_only=True)
            r.cartesian({side:goals[side]}, opening=c.gripper_open_m,
                        wrist=True, preview_only=True)
        except Fault as exc:
            if not exc.recoverable:
                raise
            machine.log.event('reach_pull_candidate_rejected',side=side,reason=exc.code)
            continue
        used.add(tray); machine.reach_pull_used = used
        start = poses[tray,:3].copy()
        machine.log.event('reach_pull_started',target_tray=tray,side=side,
                          start_position=start,destination=destination,budget_per_tray=1)
        yaw,_ = quat_yaw_tilt(poses[tray,3:])
        try:
            machine.push(Operation(tray,-1,destination,float(yaw),True),separation=True,
                         pull_context=(side,face,rim_x))
            actual = machine._poses()
            progress = float(np.dot(actual[tray,:2]-start[:2],toward/length))
            if progress < c.reach_pull_min_progress_m or not supported_sweep(g,actual,tray,actual[tray,:3]):
                raise Fault('reach_pull_progress_or_support_failed',{'progress_m':progress})
            # Preview the joining hand from the actual post-pull position. No
            # base move or clearance retreat is permitted with retained contact.
            actual_center = actual[tray,:3].copy();actual_center[2] += c.rim_height_local_m
            other = 'right' if side == 'left' else 'left'
            post_goals = r.rim_goals(actual_center,face,x_offset=rim_x,sides=(other,))
            r.cartesian(post_goals,opening=c.gripper_open_m,wrist=True,preview_only=True)
        except Fault as exc:
            raise Fault('reach_pull_failed',{'reason':exc.code,'detail':exc.detail}) from exc
        r.target_slot = slot
        machine.log.event('reach_pull_completed',target_tray=tray,side=side,
                          measured_progress_m=progress,joining_hand_preview=True)
        return True
