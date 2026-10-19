"""Bounded, side-effect-free grasp qualification before physical navigation.

These are kinematic planning results, never physical success evidence.  The
caller must navigate and replan from measured state with all normal guards.
Only private MuJoCo data are repositioned; no object or live robot is moved.
"""
from __future__ import annotations

import copy
import time
from dataclasses import dataclass
import numpy as np
from .contracts import Fault, State, ARM_COLUMNS, wrap_angle


def candidate_lattice(position, face, normal, *, rim_jitter=.025, distances=(.58, .62, .55, .66)):
    """Separate chassis position direction from heading; deterministic ordering.

    A yawed tray near a table edge may need an aisle-side chassis with its arms
    facing the tray.  The previous radial candidates tied these two decisions.
    Do not interpret any geometric candidate as collision free or reachable.
    """
    position = np.asarray(position, float)
    if position.shape not in ((2,), (3,)) or not np.isfinite(position).all():
        raise ValueError('position must be finite XY or XYZ')
    if not np.isfinite([face, normal, rim_jitter]).all() or rim_jitter < 0:
        raise ValueError('invalid grasp candidate parameters')
    heading = normal + float(np.clip(wrap_angle(face-normal), -.5, .5))
    seen = set()
    for distance in distances:
        for direction, yaw, lateral, rim in (
                (normal, face, 0., 0.), (normal, heading, 0., 0.),
                (face, face, 0., 0.), (normal, face, .06, 0.),
                (normal, face, -.06, 0.), (normal, face, 0., rim_jitter),
                (normal, face, 0., -rim_jitter),
                (normal, normal, .06, 0.), (normal, normal, -.06, 0.)):
            xy = position[:2] - distance*np.array([np.cos(direction), np.sin(direction)])
            xy += lateral*np.array([-np.sin(normal), np.cos(normal)])
            base = np.r_[xy, wrap_angle(yaw)]
            key = tuple(np.round(np.r_[base, face, rim], 8))
            if key not in seen:
                seen.add(key)
                yield base, float(face), float(rim)


def alternate_candidate_lattice(position, size, tray_yaw, normal, *, inset, rim_jitter=.025):
    """Cover both physical edge pairs and all distances before finer offsets."""
    from .rim_affordances import rim_pairs, RimCandidate
    families = []
    for distance in (.58, .62, .55, .66):
        for pair in rim_pairs(size, tray_yaw, normal, inset=inset):
            families.append((pair, list(candidate_lattice(position, pair.face, normal,
                             rim_jitter=rim_jitter, distances=(distance,)))))
    for index in range(max(len(values) for _, values in families)):
        for pair, values in families:
            if index < len(values):
                yield RimCandidate(*values[index], pair)


def _no_motion(*args, **kwargs):
    raise RuntimeError('reachability planning cannot execute physical motion')


def planning_copy(runtime):
    """Clone state and state readers, sharing only immutable model/geometry.

    Runtime, Simulation, Evidence and all MuJoCo workspaces must be separate:
    copying just MjData would leave tcp()/state()/observation() reading live data.
    """
    if (runtime.holding is not None or runtime.retained_contact is not None or
            np.max(runtime.observation()['gripper_contact_force']) > .5):
        raise Fault('reachability_probe_requires_empty_arms')
    probe = copy.copy(runtime)
    probe.sim = copy.copy(runtime.sim)
    probe.d = runtime.mj.MjData(runtime.m)
    state = np.empty(runtime.integration_size)
    runtime.mj.mj_getState(runtime.m, runtime.d, state, runtime.integration_spec)
    runtime.mj.mj_setState(runtime.m, probe.d, state, runtime.integration_spec)
    probe.sim.data = probe.d
    probe.sim.target = runtime.sim.target.copy()
    probe.sim.base_target = runtime.sim.base_target.copy()
    probe.sim.ik_data = runtime.mj.MjData(runtime.m)
    probe.shadow = runtime.mj.MjData(runtime.m)
    probe.inverse = runtime.mj.MjData(runtime.m)
    probe.evidence = copy.copy(runtime.evidence)
    probe.evidence.sim = probe.sim
    probe.trace = None
    probe.tick = _no_motion
    probe.sim.step = _no_motion
    probe.sim.apply_target = _no_motion
    runtime.mj.mj_forward(runtime.m, probe.d)
    return probe


def _set_private_configuration(probe, target, base=None):
    shadow = probe._shadow(np.asarray(target), base)
    probe.d.qpos[:] = shadow.qpos
    probe.d.qvel[:] = 0.
    probe.sim.target = np.asarray(target, float).copy()
    probe.mj.mj_forward(probe.m, probe.d)


def preview_contact_closure(runtime, target):
    """Sweep each finger aperture only until its first target rim intersection.

    Contact prevents an actual gripper from reaching its zero-aperture command.
    Sweeping through the rim to zero invents a finger/finger collision. Freeze
    each hand independently at first geometric contact, keep all other collision
    and camera checks, and require both hands to intersect the intended tray.
    This is a geometric prediction; the live force-limited close must follow.
    """
    q = np.asarray(target, float).copy()
    stopped = {}
    for opening in np.linspace(runtime.cfg.gripper_open_m, runtime.cfg.gripper_close_m, 101):
        for side, col in (('left', 7), ('right', 15)):
            q[col] = stopped.get(side, float(opening))
        shadow = runtime._shadow(q)
        collision = runtime.collision(shadow, planning=True)
        if collision or not runtime.camera_guard(shadow):
            raise Fault('direct_grasp_closure_blocked', {
                'opening_m': float(opening), 'collision': collision,
                'camera_metrics': runtime.camera_metrics(shadow)}, recoverable=True)
        for contact in shadow.contact:
            if contact.dist > 0:
                continue
            a, b = [int(runtime.m.geom_bodyid[g]) for g in (contact.geom1, contact.geom2)]
            for finger, other in ((a, b), (b, a)):
                if runtime.tray_bodies.get(other) != runtime.allowed_tray:
                    continue
                name = runtime.m.body(finger).name
                for side, col in (('left', 7), ('right', 15)):
                    if name.startswith(side+'_gripper_finger'):
                        stopped.setdefault(side, float(q[col]))
        if len(stopped) == 2:
            return {'predicted_contact_apertures_m': stopped,
                    'qualification': 'geometric_intersection_only_not_contact_force'}
    raise Fault('direct_grasp_no_rim_intersection', {'contact_sides': sorted(stopped)}, recoverable=True)


def qualify_candidate(probe, tray, candidate):
    """Check endpoint, approach and closure without executing a single tick.

    Caller supplies a fresh planning_copy for each candidate. Navigation and
    timing remain live execution responsibilities. No simulated contact force
    produced by moving the private chassis is accepted as grasp evidence.
    """
    base, face, rim = candidate
    probe.allowed_tray = tray
    probe.fsm_state, probe.phase = State.APPROACH_TRAY, 'pregrasp'
    start = probe.sim.state().astype(float)
    _set_private_configuration(probe, start, base)
    if not probe._target_valid(start):
        raise Fault('reachability_base_configuration_collision', recoverable=True)
    center = probe.observation()['tray_pose'][tray, :3].copy()
    center[2] += probe.cfg.rim_height_local_m
    pre = center.copy(); pre[2] += probe.cfg.pregrasp_clearance_m
    # Cheap endpoint gate before spending time on the complete pregrasp route.
    # The actual descent still uses local branch limits at every waypoint.
    pair = getattr(candidate, 'rim_pair', None)
    def goals(position):
        if pair is None:
            return probe.rim_goals(position, face, x_offset=rim)
        return probe.grasp_goals(position, face, rim_pair=pair, x_offset=rim)
    contact_goals = goals(center)
    endpoint = probe.solve_pair(contact_goals, start, free_endpoint=True)
    endpoint[[7, 15]] = probe.cfg.gripper_open_m
    if not probe._target_valid(endpoint, wrist=True):
        raise Fault('reachability_contact_configuration_collision_or_wrist', recoverable=True)
    approach = probe.cartesian(goals(pre),
                               speed=probe.cfg.transit_tcp_speed,
                               opening=probe.cfg.gripper_open_m, preview_only=True)
    _set_private_configuration(probe, approach[-1])
    probe.phase = 'approach'
    descent = probe.cartesian(contact_goals, speed=probe.cfg.contact_tcp_speed,
                              opening=probe.cfg.gripper_open_m,
                              wrist=True, preview_only=True)
    closure = preview_contact_closure(probe, descent[-1])
    return {'pregrasp_knots': len(approach), 'descent_knots': len(descent),
            'max_arm_displacement_rad': float(np.max(np.abs(descent[-1][ARM_COLUMNS]-start[ARM_COLUMNS]))),
            'closure': closure,
            'qualification': 'kinematic_only_requires_live_navigation_replanning_and_contact'}


@dataclass
class ProbeResult:
    candidates: list
    rejected: list
    examined: int
    planning_wall_seconds: float
    exhausted: bool


def screen_candidates(runtime, tray, candidates, *, max_probes=24, max_qualified=2):
    """Finite candidate budget; never turn planner exhaustion into infeasibility proof."""
    if max_probes < 1 or max_qualified < 1:
        raise ValueError('probe budgets must be positive')
    began = time.monotonic()
    accepted, rejected = [], []
    examined = 0
    iterator = iter(candidates)
    exhausted = False
    for _ in range(max_probes):
        try:
            candidate = next(iterator)
        except StopIteration:
            exhausted = True
            break
        examined += 1
        try:
            details = qualify_candidate(planning_copy(runtime), tray, candidate)
        except Fault as exc:
            if not exc.recoverable:
                raise
            rejected.append({'candidate': examined-1, 'code': exc.code, 'detail': exc.detail})
            continue
        accepted.append((candidate, details))
        if len(accepted) >= max_qualified:
            break
    return ProbeResult(accepted, rejected, examined, time.monotonic()-began, exhausted)
