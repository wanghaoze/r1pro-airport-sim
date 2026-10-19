"""Bounded temporary destination selection; no live motion or state restoration."""
from copy import deepcopy
from dataclasses import dataclass, asdict
import time
import numpy as np
from .contracts import Fault
from .geometry import Operation, rectangle, rz, slot_geometry_ready
from .buffer_serviceability import same_operation
from .scheduler import release_location, _executable_geometry
from .placement_reachability import carried_placement_candidates, screen_placement


@dataclass
class BufferContext:
    original: Operation
    requested: Operation
    source_poses: np.ndarray
    mapping: tuple
    protected: frozenset
    operation_index: int
    source: str
    scene_id: str = ''
    consumed: bool = False
    screened: bool = False


def enabled(machine):
    return (machine.c.acceptance_profile == 'completion_first' and
            machine.c.temporary_buffer_serviceability_enabled and
            getattr(machine.c,'completion_direct_buffer_enabled',False))


def capture_context(machine, operation, source_poses, prerequisite=None):
    """Fail closed when the ordinary scheduler's blocker purpose is ambiguous."""
    if not enabled(machine) or not operation.temporary or operation.slot != -1:
        return None
    if getattr(machine.scheduler,'reservation_plan',None) is not None:
        machine.log.event('general_buffer_skipped',reason='active_adaptive_reservation',
            qualification='preserve_selected_absolute_future_destination')
        return None
    g=machine.g; mapping=tuple(machine.scheduler.mapping); protected=frozenset(machine.verified_final_trays)
    if operation.tray in protected or not g.top_available(source_poses,operation.tray):return None
    if prerequisite is not None:
        if not same_operation(operation,prerequisite.selected):return None
        requested=deepcopy(prerequisite.requested); source=prerequisite.source_poses.copy()
        if (prerequisite.metadata.get('selected_blocker')!=operation.tray or
                operation.tray not in prerequisite.metadata.get('blockers',[])):return None
        identity='release_prerequisite'
    else:
        # Repeat only the pure scheduler decision on its exact source snapshot.
        scheduler=deepcopy(machine.scheduler)
        selected=scheduler.choose(source_poses.copy())
        if selected is None or not same_operation(selected,operation):return None
        requested=None; source=source_poses.copy()
        for slot,tray in enumerate(mapping):
            c=scheduler.criteria
            ready=g.at_slot(source,tray,slot,position_tol=c.position_m,
                angle_tol=np.deg2rad(c.yaw_deg),tilt_tol=np.deg2rad(c.tilt_deg))
            if ready and scheduler.consistent_placement:
                ready=slot_geometry_ready(g,source,mapping,tray,slot,c,
                    require_full_footprint=scheduler.require_full_footprint,use_actual_gap=scheduler.use_actual_gap)
            if not ready:
                requested=Operation(tray,slot,g.goals[slot].copy(),float(g.goal_yaw[slot]));break
        if requested is None or requested.tray==operation.tray:return None
        # Ordinary direct destination blocker only. Unknown stack-resolution
        # purposes retain their original behavior rather than being guessed.
        if operation.tray not in g.blockers(source,requested.tray,requested.destination,requested.yaw,.002):return None
        identity='ordinary_scheduler_destination_blocker'
    if requested.temporary or requested.slot<0 or requested.tray==operation.tray:return None
    return BufferContext(deepcopy(operation),requested,source,mapping,protected,
                         machine.operations+1,identity,g.spec['scene_id'])


def footprint_supported(g, candidate):
    if g.footprint_supported(candidate.destination,candidate.yaw,g.sizes[candidate.tray]):return True
    rear=getattr(g,'tables',{}).get('rear')
    if rear is None:return False
    center=np.asarray(rear['center_world'],float);rotation=rz(float(rear.get('yaw_world',0.)))
    local=(rectangle(candidate.destination,candidate.yaw,g.sizes[candidate.tray])-center[:2])@rotation[:2,:2]
    return bool(abs(candidate.destination[2]-rear['dimensions_m'][2])<=.002 and
                np.all(abs(local)<=np.asarray(rear['dimensions_m'][:2])/2-.004))


def select_direct_buffer(machine, operation, context):
    if not enabled(machine) or context is None or context.consumed:return operation,None
    context.consumed=True
    r,g,c=machine.r,machine.g,machine.c; tray=operation.tray
    if (not same_operation(operation,context.original) or tuple(machine.scheduler.mapping)!=context.mapping or
            frozenset(machine.verified_final_trays)!=context.protected or machine.operations!=context.operation_index or
            tray in context.protected or not g.top_available(context.source_poses,tray) or
            (context.scene_id and context.scene_id!=g.spec['scene_id'])):
        machine.log.event('general_buffer_skipped',reason='stale_source_context');return operation,None
    evidence=r.observation();forces=evidence['gripper_contact_force'][tray]
    if r.holding!=tray or r.retained_contact is not None or not np.isfinite(forces).all() or np.any(forces<=c.criteria.contact_n):
        raise Fault('temporary_buffer_grasp_context_invalid',{'tray':tray})
    poses=evidence['tray_pose'].copy();started=time.monotonic();records=[];context.screened=True
    raw=[deepcopy(operation)]
    try:
        staged=release_location(g,poses,operation,c)
        if not np.array_equal(staged,operation.destination):raw.append(Operation(tray,-1,staged.copy(),operation.yaw,True))
    except Fault as exc:
        if exc.code!='no_safe_release_clearance':raise
    # Existing deterministic front-belt buffer lattice, no scene resampling.
    for u in np.linspace(g.belt_length-.25,.25,30):
        p=g.to_world([u,g.belt_width/2,0.]);p[2]+=.001
        raw.append(Operation(tray,-1,p,float(g.goal_yaw[0]),True))
    examined=0;buffers=0;selected=None;seen=set()
    for candidate in raw:
        key=tuple(candidate.destination)+(candidate.yaw,)
        if key in seen:continue
        seen.add(key)
        record={'operation':asdict(candidate)}
        if (np.linalg.norm(candidate.destination[:2]-context.source_poses[tray,:2])<.15 or
                not footprint_supported(g,candidate) or
                g.blockers(poses,tray,candidate.destination,candidate.yaw,.025)):
            record['reason']='buffer_geometry';records.append(record);continue
        predicted=poses.copy();predicted[tray,:3]=candidate.destination
        predicted[tray,3:]=[np.cos(candidate.yaw/2),0,0,np.sin(candidate.yaw/2)]
        if (tray in g.blockers(predicted,context.requested.tray,context.requested.destination,context.requested.yaw,.002) or
                not g.top_available(predicted,context.requested.tray) or
                not _executable_geometry(g,predicted,context.requested,c)):
            record['reason']='requested_clearance';records.append(record);continue
        try:staged=release_location(g,poses,candidate,c)
        except Fault as exc:
            if exc.code!='no_safe_release_clearance':raise
            record['reason']='release_geometry';records.append(record);continue
        if not np.array_equal(staged,candidate.destination):
            record['reason']='policy_prefers_direct_release_not_infeasibility';records.append(record);continue
        if buffers>=3:break
        buffers+=1;normal=machine._inward_yaw(staged);anchor=staged[:2].copy()
        nominal=np.r_[anchor-.57*np.array([np.cos(normal),np.sin(normal)]),normal]
        proposals=carried_placement_candidates(r,nominal,anchor,goal_tray_yaw=candidate.yaw)
        budget=min(18,c.placement_max_probes)
        screen=screen_placement(r,staged,candidate.destination,candidate.yaw,nominal,candidates=proposals,max_candidates=budget,max_qualified=1)
        examined+=screen.examined;record.update(examined=screen.examined,rejected=screen.rejected,qualified=screen.qualified);records.append(record)
        if screen.qualified:
            selected=(deepcopy(candidate),{'operation':deepcopy(candidate),'staged':staged.copy(),'base':np.asarray(screen.qualified[0]['base'],float).copy()});break
    machine.log.event('general_buffer_serviceability',source=context.source,operation_index=context.operation_index,
        original_operation=asdict(operation),requested=asdict(context.requested),selected_operation=asdict(selected[0]) if selected else None,
        scene_id=context.scene_id,source_poses=context.source_poses,mapping=context.mapping,protected=sorted(context.protected),
        policy='completion_first_prefers_direct_temporary_release_original_direct_candidate_first',
        original_push_infeasibility_claimed=False,buffers_screened=buffers,buffer_budget=3,probe_budget_per_buffer=min(18,c.placement_max_probes),
        examined=examined,candidates=records,planning_wall_seconds=time.monotonic()-started,fallback_to_original=selected is None)
    if selected and not same_operation(operation,selected[0]):
        machine.log.event('operation_destination_revised',operation_index=context.operation_index,original_operation=asdict(operation),
            operation=asdict(selected[0]),requested=asdict(context.requested),reason='completion_direct_temporary_buffer_policy')
    return selected if selected else (operation,None)
