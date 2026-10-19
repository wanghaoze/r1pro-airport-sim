"""Bounded geometric reservations, never a claim of future physical success."""
import hashlib
import json
import numpy as np
from .contracts import wrap_angle
from .geometry import (Operation, quat_yaw_tilt, footprint_neighbour_gaps,
                       footprint_signed_neighbour_gaps, footprint_signed_boundary_gap,
                       overlap, slot_geometry_ready)


OFFSETS=(0.,-.01,.01,-.02,.02,-.03,.03,-.04,.04)


def goal_hash(g):
    return hashlib.sha256(json.dumps([g.goals.tolist(),g.goal_yaw.tolist(),g.ids],
                                    separators=(',',':')).encode()).hexdigest()


def validate_plan(g,mapping,plan):
    """Checkpoint identity and absolute geometry validation; no live edits."""
    if plan is None:return
    if (not isinstance(plan,dict) or plan.get('version')!=1 or
            plan.get('nominal_goals_sha256')!=goal_hash(g) or
            plan.get('mapping')!=list(mapping) or sorted(mapping)!=[0,1,2]):
        raise ValueError('Invalid reservation identity')
    slot=plan.get('pending_slot');tray=plan.get('pending_tray')
    index=plan.get('candidate_index')
    if (type(slot) is not int or slot not in range(3) or tray!=mapping[slot] or
            type(index) is not int or index not in range(len(OFFSETS)) or
            plan.get('protected_trays')!=sorted(set(range(3))-{tray})):
        raise ValueError('Invalid reservation mapping')
    dest=np.asarray(plan.get('destination'),float)
    expected=g.goals[slot]+g.R[:,0]*OFFSETS[index]
    fixed=np.asarray(plan.get('protected_pose'),float)
    if (dest.shape!=(3,) or not np.isfinite(dest).all() or
            not np.allclose(dest,expected,rtol=0,atol=1e-12) or
            plan.get('yaw')!=float(g.goal_yaw[slot]) or fixed.shape!=(3,7) or
            not np.isfinite(fixed).all() or
            np.any(abs(np.linalg.norm(fixed[:,3:],axis=1)-1)>.02) or
            type(plan.get('source_frame')) is not int or plan['source_frame']<0):
        raise ValueError('Invalid reservation geometry')


def positions(g,mapping,plan):
    validate_plan(g,mapping,plan)
    if plan is None:return None
    result=g.goals.copy();result[plan['pending_slot']]=plan['destination']
    return result


def validate_context(g,mapping,plan,cfg):
    if plan is not None and (cfg.acceptance_profile!='completion_first' or
                            not cfg.completion_adaptive_reservation_enabled):
        raise ValueError('Reservation requires enabled completion profile')
    validate_plan(g,mapping,plan)


def at_nominal(g,pose,tray,slot,criteria):
    return g.at_slot(pose,tray,slot,position_tol=criteria.position_m,
        angle_tol=np.deg2rad(criteria.yaw_deg),tilt_tol=np.deg2rad(criteria.tilt_deg))


def protected_unchanged(g,mapping,plan,pose,criteria):
    validate_plan(g,mapping,plan)
    if plan is None:return True
    old=np.asarray(plan['protected_pose']);yaw,tilt=quat_yaw_tilt(pose[:,3:]);old_yaw,_=quat_yaw_tilt(old[:,3:])
    for tray in plan['protected_trays']:
        if (not at_nominal(g,pose,tray,mapping.index(tray),criteria) or
                np.linalg.norm(pose[tray,:3]-old[tray,:3])>1e-4 or
                abs(wrap_angle(yaw[tray]-old_yaw[tray],g.period))>1e-3):return False
    return True


def propose(machine,operation,samples):
    """One nine-point search after ordinary verification; existing samples only."""
    c=machine.c;g=machine.g;scheduler=machine.scheduler
    if (c.acceptance_profile!='completion_first' or not c.completion_adaptive_reservation_enabled or
            operation.temporary or operation.slot<0 or scheduler.reservation_plan is not None or
            getattr(machine.r,'holding',None) is not None or
            getattr(machine.r,'retained_contact',None) is not None):return None
    from .acceptance_profile import completion_criteria
    from .scheduler import _executable_geometry
    criteria=completion_criteria(c);count=int(np.ceil(criteria.stable_s*c.fps))+1
    overlap_cap=(min(c.completion_collision_penetration_m,.02)
                 if getattr(c,'approximate_completion_enabled',False) else 0.)
    if len(samples)<count:return None
    samples=samples[-count:];pose=np.array(samples[-1]['tray_pose'],copy=True);mapping=list(scheduler.mapping)
    pending=[t for s,t in enumerate(mapping) if not at_nominal(g,pose,t,s,criteria)]
    if len(pending)!=1 or operation.tray in pending:return None
    tray=pending[0];slot=mapping.index(tray);fixed=sorted(set(range(3))-{tray})
    if not set(fixed)-{operation.tray}<=machine.verified_final_trays:return None
    for t in fixed:
        for x in samples:
            if (not at_nominal(g,x['tray_pose'],t,mapping.index(t),criteria) or
                    x['table_contact'][t]<=0 or np.max(x['gripper_contact_force'][t])>.5):return None
        speed=np.linalg.norm(np.diff([x['tray_pose'][t,:3] for x in samples],axis=0),axis=1)*c.fps
        if np.any(speed>.01):return None
    if any(np.linalg.norm(x['tray_pose'][operation.tray,:3]-operation.destination)>criteria.position_m
           for x in samples):return None
    if any(abs(wrap_angle(quat_yaw_tilt(x['tray_pose'][operation.tray,3:])[0]-operation.yaw,g.period))>
           np.deg2rad(criteria.yaw_deg) for x in samples):return None
    if all(slot_geometry_ready(g,x['tray_pose'],mapping,operation.tray,operation.slot,criteria,
           require_full_footprint=False,use_actual_gap=True,
           approximate_overlap_cap_m=overlap_cap) for x in samples):return None
    rejected=[]
    for index,offset in enumerate(OFFSETS):
        destination=g.goals[slot]+g.R[:,0]*offset
        future=pose.copy();future[tray,:3]=destination
        future[tray,3:]=[np.cos(g.goal_yaw[slot]/2),0,0,np.sin(g.goal_yaw[slot]/2)]
        yaw,_=quat_yaw_tilt(future[:,3:]);reason=None
        if np.linalg.norm(destination-g.goals[slot])>criteria.position_m:reason='nominal_tolerance'
        elif (not g.footprint_supported(destination,yaw[tray],g.sizes[tray]) or
              any(g.support_table(future[t,:3]) is None for t in fixed)):reason='table_support'
        elif (any((footprint_signed_boundary_gap(g.footprint(future,i),g.footprint(future,j)) < -overlap_cap
                   if overlap_cap > 0 and tray not in (i,j) else
                   overlap(g.footprint(future,i),g.footprint(future,j),clearance=.002))
                  for i in range(3) for j in range(i+1,3))):reason='reserved_clearance'
        else:
            gaps=(footprint_signed_neighbour_gaps(future[mapping,:3],yaw[mapping],g.sizes[mapping])
                  if overlap_cap > 0 else
                  footprint_neighbour_gaps(future[mapping,:3],yaw[mapping],g.sizes[mapping]))
            minimum_gap=-overlap_cap if overlap_cap > 0 else criteria.gap_min_m
            if gaps is None or np.any(gaps<minimum_gap) or np.any(gaps>criteria.gap_max_m):reason='gap'
        if reason is None and not _executable_geometry(g,pose,Operation(tray,slot,destination,float(g.goal_yaw[slot])),c):
            reason='release_or_push_geometry'
        if reason is None:
            reserved=g.goals.copy();reserved[slot]=destination
            if not all(slot_geometry_ready(g,x['tray_pose'],mapping,t,mapping.index(t),criteria,
                require_full_footprint=False,use_actual_gap=True,reservation_positions=reserved,
                approximate_overlap_cap_m=overlap_cap)
                for x in samples for t in fixed):reason='stable_window_reservation'
        if reason is not None:
            rejected.append(dict(candidate_index=index,offset_m=offset,reason=reason));continue
        result=dict(version=1,nominal_goals_sha256=goal_hash(g),mapping=mapping,pending_tray=tray,
            pending_slot=slot,destination=destination.tolist(),yaw=float(g.goal_yaw[slot]),
            protected_trays=fixed,protected_pose=pose.tolist(),source_frame=int(machine.r.steps),candidate_index=index)
        validate_plan(g,mapping,result)
        machine.log.event('adaptive_reservation_selected',plan=result,rejected=rejected,maximum_candidates=9,
            qualification='geometric_reservation_only_future_grasp_ik_and_contact_unproven')
        return result
    machine.log.event('adaptive_reservation_rejected',rejected=rejected,maximum_candidates=9)
    return None
