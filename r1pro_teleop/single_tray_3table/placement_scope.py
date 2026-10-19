"""Private joint standing-pose qualification for empty Place and loaded Push.

All candidates require original live navigation and replanning. No future
contact, force, support or task completion is inferred from these predictions.
"""
import copy
import numpy as np
from ..airport_fsm.contracts import Fault
from ..airport_fsm.geometry import rectangle
from ..airport_fsm.placement_reachability import (carried_placement_candidates,
    loaded_planning_copy,screen_placement,_project)
from ..single_tray_lab.control import SingleTrayController
from ..airport_fsm.rim_affordances import rim_pairs


def candidate_stations(runtime,nominal,anchor,yaw):
    forward=np.array([np.cos(nominal[2]),np.sin(nominal[2])])
    # Standing poses, not a fixed override. The original candidates and their
    # heading alternatives remain available behind these reach-aware proposals.
    for distance in (.53,.51,.49,.47,.45,.40):
        yield np.r_[anchor-distance*forward,nominal[2]]
    yield from carried_placement_candidates(runtime,nominal,anchor,goal_tray_yaw=yaw)


def future_left_endpoint(runtime,manifest,operation,base):
    """Actual command geometry at the earliest explicitly accepted left edge."""
    probe=loaded_planning_copy(runtime);_project(probe,base=base)
    target=runtime.g.tables[manifest['target_table']]
    forward=np.array([np.cos(base[2]),np.sin(base[2]),0.]);left=np.array([-forward[1],forward[0],0.])
    corners=rectangle(target['center_world'],target.get('yaw_world',0.),target['dimensions_m'])
    limits=manifest['loaded_push_target']
    edge=float(np.max(corners@left[:2]))-limits.get('table_edge_margin_m',.025)
    yaw=operation.yaw;c,s=np.cos(yaw),np.sin(yaw)
    R=np.array([[c,-s,0.],[s,c,0.],[0.,0.,1.]])
    half=float(np.abs(left@R[:,:2])@(runtime.g.sizes[0,:2]/2))
    centre=np.asarray(operation.destination,float).copy()
    centre+=(edge-limits.get('goal_edge_tolerance_m',.03)-half-float(centre@left))*left
    centre[2]+=runtime.cfg.rim_height_local_m
    pairs=rim_pairs(runtime.g.sizes[0],operation.yaw,base[2],inset=runtime.cfg.rim_inset_m)
    wanted='width' if runtime.g.sizes[0,0]>=runtime.g.sizes[0,1] else 'length'
    pair=next(p for p in pairs if p.axis==wanted)
    goal=probe.grasp_goals(centre,pair.face,rim_pair=pair,sides=('left',))['left']
    # Reuse the existing held private solver's exact residual bounds and
    # deterministic seeds, without constructing a controller or executing it.
    checker=SingleTrayController.__new__(SingleTrayController)
    checker.sim=probe.sim;checker.m=probe.m;checker.d=probe.d;checker.mj=probe.mj
    from types import SimpleNamespace
    checker.p=SimpleNamespace(held_private_ik_position_tolerance_m=.012,
        held_private_ik_angle_tolerance_rad=.10)
    checker.holding_sides={'left'};checker.private_incremental_command_prediction=True
    solutions=checker._ik_candidates('left',*goal,warm_only=False)
    right_center=np.asarray(operation.destination,float).copy();right_center[2]+=runtime.cfg.rim_height_local_m
    right_goal=probe.grasp_goals(right_center,pair.face,rim_pair=pair,sides=('right',))['right']
    # Acquisition is empty-arm motion and keeps its original strict 2mm/
    # .02rad criteria. It cannot borrow the held-reference residual budget.
    checker.holding_sides=set();checker.private_incremental_command_prediction=False
    right_checks=[]
    clearance=manifest.get('loaded_push_target',{}).get('approach_clearance_m',.09)
    for stage,position in (('approach',right_goal[0]+np.array([0,0,clearance])),('contact',right_goal[0])):
        right=checker._ik_candidates('right',position,right_goal[1],warm_only=False)
        right_checks.append(dict(stage=stage,position=position,position_error_m=right[0][2],angle_error_rad=right[0][3]))
    takeover_center=np.asarray(operation.destination,float).copy()
    reach=manifest.get('loaded_push_target',{}).get('right_reach_lateral_m',-.08)
    takeover_center+=(float(np.asarray(base[:2])@left[:2])+reach+pair.half_span-float(takeover_center@left))*left
    takeover_center[2]+=runtime.cfg.rim_height_local_m
    takeover_goal=probe.grasp_goals(takeover_center,pair.face,rim_pair=pair,sides=('left',))['left']
    takeover_checks=[]
    for stage,position in (('approach',takeover_goal[0]+np.array([0,0,clearance])),('contact',takeover_goal[0])):
        takeover=checker._ik_candidates('left',position,takeover_goal[1],warm_only=False)
        takeover_checks.append(dict(stage=stage,position=position,position_error_m=takeover[0][2],angle_error_rad=takeover[0][3]))
    return dict(position=goal[0],rotation=goal[1],position_error_m=solutions[0][2],
        angle_error_rad=solutions[0][3],right_acquire_checks=right_checks,
        left_takeover_checks=takeover_checks,actual_edge_target_m=edge,
        qualification='private_endpoint_only_no_future_contact_or_path_certificate')


def select_joint_station(machine,operation):
    r=machine.r;staged=machine._place_location(operation);anchor=staged[:2].copy()
    if machine.c.keep_place_contact:anchor=.5*(anchor+operation.destination[:2])
    normal=machine._inward_yaw(staged)
    nominal=np.r_[anchor-.57*np.array([np.cos(normal),np.sin(normal)]),normal]
    target=r.g.tables[machine.manifest['target_table']]
    inward=np.array([np.cos(normal),np.sin(normal)])
    center=np.asarray(target['center_world'])[:2];long_axis=r.g.R[:2,0]
    half_long,half_depth=np.asarray(target['dimensions_m'])[:2]/2
    rejected=[];seen=set()
    for base in candidate_stations(r,nominal,anchor,operation.yaw):
        key=tuple(np.round(base,8))
        if key in seen:continue
        seen.add(key)
        if float((base[:2]-center)@inward)>-half_depth or abs(float((base[:2]-center)@long_axis))>half_long:
            rejected.append(dict(base=base,reason='not_table_front'));continue
        try:
            future=future_left_endpoint(r,machine.manifest,operation,base)
            screen=screen_placement(r,staged,operation.destination,operation.yaw,nominal,
                candidates=[base],max_candidates=1,max_qualified=1)
            if not screen.qualified:
                rejected.extend(screen.rejected);continue
        except Fault as exc:
            rejected.append(dict(base=base,reason=exc.code,detail=exc.detail));continue
        machine.log.event('three_table_joint_station_qualified',base=base,
            future_left_endpoint=future,rejected=rejected,
            qualification='private_geometry_only_original_navigation_place_and_loaded_physics_required')
        return dict(operation=operation,staged=staged,base=np.asarray(base).copy())
    raise Fault('three_table_no_joint_place_push_station',rejected)
