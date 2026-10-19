"""Finite, private supported staging search after a zero-motion loaded IK fault.

The geometric pass is a necessary condition only. The selected candidate is
planned from a fresh measured-state copy and must still execute the ordinary
physical place, push, and verification path.
"""
import numpy as np

from .contracts import Fault
from .geometry import overlap, rectangle, push_overhang_kwargs
from .placement_reachability import loaded_planning_copy, qualify_placement
from .reservation_plan import positions, protected_unchanged


MAX_PRIVATE_PROBES = 12
MIN_TRANSLATION_REDUCTION_M = .12


def supported_candidates(machine, operation, original_stage, observed_pose):
    """Rank a finite goal-relative lattice by saved bilateral carry distance."""
    g = machine.g
    tray = operation.tray
    destination = np.asarray(operation.destination, float)
    current = np.asarray(observed_pose[tray, :3], float)
    original = np.asarray(original_stage, float)
    if not np.isfinite(np.r_[destination, current, original, operation.yaw]).all():
        return []
    reservations = positions(g, machine.scheduler.mapping,
                             machine.scheduler.reservation_plan)
    if reservations is not None and not protected_unchanged(
            g, machine.scheduler.mapping, machine.scheduler.reservation_plan,
            observed_pose, machine.scheduler.criteria):
        return []
    original_distance = float(np.linalg.norm(current[:2] - original[:2]))
    maximum_push = min(.18, float(machine.c.push_max_distance_m))
    # The direct ray preserves the failed carry direction. The fixed 19x19
    # lattice finds edge-supported alternatives when that ray is blocked.
    toward = current[:2] - destination[:2]
    toward /= max(float(np.linalg.norm(toward)), 1e-12)
    xy_points = [destination[:2] + radius*toward
                 for radius in np.linspace(.02, .18, 17)]
    xy_points += [destination[:2] + [dx, dy]
                  for dx in np.linspace(-.18, .18, 19)
                  for dy in np.linspace(-.18, .18, 19)]
    seen = set()
    eligible = []
    yaw = float(operation.yaw)
    quat = np.array([np.cos(yaw/2), 0., 0., np.sin(yaw/2)])
    for xy in xy_points:
        key = tuple(np.round(xy, 5))
        if key in seen:
            continue
        seen.add(key)
        stage = destination.copy()
        stage[:2] = xy
        push_distance = float(np.linalg.norm(xy-destination[:2]))
        reduction = original_distance - float(np.linalg.norm(xy-current[:2]))
        if (push_distance < .02 or push_distance > maximum_push + 1e-9 or
                np.linalg.norm(xy-original[:2]) < .02 or
                reduction < MIN_TRANSLATION_REDUCTION_M):
            continue
        if not g.footprint_supported(stage, yaw, g.sizes[tray]):
            continue
        if g.blockers(observed_pose, tray, stage, yaw, clearance=.002):
            continue
        # Future protected positions are respected even if their tray is not
        # currently at that point. The whole push corridor must remain clear.
        if reservations is not None:
            reserved_polys = [rectangle(reservations[slot], float(g.goal_yaw[slot]),
                                        g.sizes[other])
                              for slot, other in enumerate(machine.scheduler.mapping)
                              if other != tray]
            if any(overlap(rectangle((1-u)*stage + u*destination, yaw,
                                     g.sizes[tray]), poly, clearance=.002)
                   for u in np.linspace(0., 1., 25) for poly in reserved_polys):
                continue
        virtual = np.asarray(observed_pose, float).copy()
        virtual[tray, :3] = stage
        virtual[tray, 3:] = quat
        if not g.push_possible(virtual, tray, destination, yaw,
                               max_distance=maximum_push,
                               max_yaw=np.deg2rad(machine.c.push_max_yaw_deg),
                               **push_overhang_kwargs(machine.c)):
            continue
        eligible.append((reduction, stage))
    eligible.sort(key=lambda hit: (-hit[0], float(hit[1][0]), float(hit[1][1])))
    return [stage for _, stage in eligible]


def screen_supported_staging(machine, operation, original_stage):
    """Return one fully planned candidate, or None without live MuJoCo ticks."""
    r = machine.r
    observed = r.observation()['tray_pose']
    candidates = supported_candidates(machine, operation, original_stage, observed)
    base = r.sim.base_state().astype(float)
    rejected = []
    combined_candidate = None
    examined = 0
    for stage in candidates[:MAX_PRIVATE_PROBES]:
        examined += 1
        try:
            probe = loaded_planning_copy(r)
            plan = qualify_placement(probe, stage, operation.destination,
                                     operation.yaw, base)
        except Fault as exc:
            rejected.append({'stage': stage.tolist(), 'reason': exc.code})
        else:
            if plan.get('prediction_mode') == 'combined_descent':
                if combined_candidate is None:
                    combined_candidate = stage, plan
                continue
            machine.log.event('completion_supported_staging_screen',
                target_tray=operation.tray, eligible_geometry=len(candidates),
                examined=examined, rejected=rejected, selected=stage,
                planned=plan, current_base=base,
                qualification='private_complete_loaded_reference_no_physical_motion')
            return stage
    if combined_candidate is not None:
        stage, plan = combined_candidate
        machine.log.event('completion_supported_staging_screen',
            target_tray=operation.tray, eligible_geometry=len(candidates),
            examined=examined, rejected=rejected, selected=stage,
            planned=plan, current_base=base,
            qualification='private_combined_descent_reference_no_physical_motion')
        return stage
    machine.log.event('completion_supported_staging_screen',
        target_tray=operation.tray, eligible_geometry=len(candidates),
        examined=examined, rejected=rejected,
        selected=None, current_base=base,
        qualification='all_private_candidates_rejected_original_fault_preserved')
    return None
