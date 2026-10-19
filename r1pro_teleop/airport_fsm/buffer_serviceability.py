"""Bounded, post-grasp planning for provenance-backed rear prerequisites.

The selected operation still executes through live navigation and placement.
No predicted state or trajectory is committed to the simulator.
"""
from copy import deepcopy
from dataclasses import asdict, dataclass
import time
import numpy as np
from .contracts import Fault
from .geometry import Operation
from .scheduler import rear_buffer_candidates, release_location, _executable_geometry
from .placement_reachability import carried_placement_candidates, screen_placement


@dataclass
class PrerequisiteContext:
    requested: Operation
    selected: Operation
    source_poses: np.ndarray
    mapping: tuple
    protected: frozenset
    metadata: dict
    operation_index: int
    consumed: bool = False
    screened: bool = False


def same_operation(left, right):
    return (left.tray == right.tray and left.slot == right.slot and
            left.temporary == right.temporary and left.yaw == right.yaw and
            np.array_equal(left.destination, right.destination))


def prerequisite_context(requested, selected, poses, mapping, protected, metadata, index):
    return PrerequisiteContext(deepcopy(requested), deepcopy(selected), poses.copy(),
        tuple(mapping), frozenset(protected), deepcopy(metadata), index)


def select_buffer(machine, operation, context):
    """Return (operation, optional base proposal), with at most 3 x 18 probes.

    Consumed before any screening; an outer physical recovery cannot trigger a
    second destination selection for the same numbered prerequisite.
    """
    if context is None or context.consumed or not machine.c.temporary_buffer_serviceability_enabled:
        return operation, None
    context.consumed = True
    started = time.monotonic()
    r, g, c = machine.r, machine.g, machine.c
    reasons = []
    if (not operation.temporary or operation.slot != -1 or
            not same_operation(operation, context.selected)):
        reasons.append('not_original_temporary_prerequisite')
    if (tuple(machine.scheduler.mapping) != context.mapping or
            frozenset(machine.verified_final_trays) != context.protected or
            machine.operations != context.operation_index):
        reasons.append('stale_scheduler_context')
    tray = operation.tray
    if (tray in context.protected or tray == context.requested.tray or
            context.metadata.get('selected_blocker') != tray or
            tray not in context.metadata.get('blockers', []) or
            not g.top_available(context.source_poses, tray)):
        reasons.append('ineligible_blocker')
    source_choices = rear_buffer_candidates(g, context.source_poses, tray)
    if not any(same_operation(operation, candidate) for candidate in source_choices):
        reasons.append('not_existing_rear_prerequisite')
    if reasons:
        machine.log.event('temporary_buffer_serviceability_skipped', reasons=reasons,
            operation_index=context.operation_index, requested=asdict(context.requested))
        return operation, None
    evidence = r.observation()
    forces = evidence['gripper_contact_force'][tray]
    if (r.holding != tray or getattr(r, 'retained_contact', None) is not None or
            not np.all(np.isfinite(forces)) or np.any(forces <= c.criteria.contact_n)):
        raise Fault('temporary_buffer_grasp_context_invalid', {'tray': tray})
    pose = evidence['tray_pose'].copy()
    context.screened = True
    geometry_rejected = []
    candidates = rear_buffer_candidates(g, pose, tray,
        source_position=context.source_poses[tray, :3], rejected=geometry_rejected)
    # Preserve the existing destination first, then the original stable order.
    candidates.sort(key=lambda candidate: not same_operation(candidate, operation))
    records = []
    examined = 0
    selected = None
    for candidate in candidates:
        record = {'operation': asdict(candidate)}
        records.append(record)
        if not _executable_geometry(g, pose, candidate, c):
            record['reason'] = 'buffer_release_geometry'
            continue
        predicted = pose.copy()
        predicted[tray, :3] = candidate.destination
        predicted[tray, 3:] = [np.cos(candidate.yaw/2), 0, 0, np.sin(candidate.yaw/2)]
        if not _executable_geometry(g, predicted, context.requested, c):
            record['reason'] = 'requested_release_geometry'
            continue
        staged = release_location(g, pose, candidate, c)
        normal = machine._inward_yaw(staged)
        anchor = staged[:2].copy()
        if c.keep_place_contact:
            anchor = .5*(anchor+candidate.destination[:2])
        nominal = np.r_[anchor-.57*np.array([np.cos(normal), np.sin(normal)]), normal]
        proposals = carried_placement_candidates(r, nominal, anchor, goal_tray_yaw=candidate.yaw)
        screen = screen_placement(r, staged, candidate.destination, candidate.yaw, nominal,
            candidates=proposals, max_candidates=c.placement_max_probes, max_qualified=1)
        examined += screen.examined
        record.update(examined=screen.examined, rejected=screen.rejected, qualified=screen.qualified)
        if screen.qualified:
            proposal = {'operation': deepcopy(candidate), 'staged': staged.copy(),
                'base': np.asarray(screen.qualified[0]['base'], float).copy()}
            selected = (deepcopy(candidate), proposal)
            break
    machine.log.event('temporary_buffer_serviceability_screen',
        operation_index=context.operation_index, requested=asdict(context.requested),
        original_operation=asdict(operation), selected_operation=asdict(selected[0]) if selected else None,
        buffers_considered=len(candidates), buffer_budget=3, probe_budget_per_buffer=c.placement_max_probes,
        maximum_probes=3*c.placement_max_probes, examined=examined, candidates=records,
        geometry_rejected=geometry_rejected, planning_wall_seconds=time.monotonic()-started,
        fallback_to_original=selected is None,
        qualification='private_prediction_live_navigation_and_placement_required')
    if selected and not same_operation(selected[0], operation):
        machine.log.event('operation_destination_revised', operation_index=context.operation_index,
            original_operation=asdict(operation), operation=asdict(selected[0]),
            requested=asdict(context.requested), reason='temporary_buffer_serviceability')
    return selected if selected is not None else (operation, None)
