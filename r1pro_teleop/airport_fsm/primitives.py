"""Geometry-parameterized, bounded-time actions; no waypoint stop fallback.

The configured action budget is simulation time INCLUDING contact verification.
Strict actions are limited to three seconds; completion-first may declare up to six.
Explicit approximate mode records time without imposing an action deadline.
Navigation and initial grasp acquisition are separate, explicitly labelled states.
No state resets, object attachments, time scaling or successful timeout labels.
"""
from contextlib import contextmanager
from fractions import Fraction
from types import MappingProxyType
import math
import time
import numpy as np
from .contracts import Fault, ARM_COLUMNS, State, wrap_angle
from .geometry import quat_yaw_tilt, rz
from .trajectory import CruiseJointPath, BlendedJointPath, entry_limit_envelope
from .placement_planner import touchdown_position, release_endpoint, descent_budget_frames


def _action_timing(machine, start_step, physical_start, physics_step_start):
    r=machine.r
    frames_s=(r.steps-start_step)/machine.c.fps
    count=getattr(r,'physics_step_count',None)
    dt=getattr(r,'physics_clock_timestep',None)
    if physics_step_start is not None and count is not None and dt is not None:
        exact=(int(count)-int(physics_step_start))*Fraction(str(dt))
        actual=float(exact);beyond=exact>Fraction('3')
        source='executed_physics_steps'
    elif physical_start is not None and getattr(getattr(r,'d',None),'time',None) is not None:
        actual=float(r.d.time)-physical_start
        beyond=actual>3. and not math.isclose(actual,3.,rel_tol=0.,abs_tol=1e-9)
        source='physical_time_fallback'
    else:
        actual=frames_s;beyond=(r.steps-start_step)>3*machine.c.fps
        source='completed_control_frames_fallback'
    return dict(configured_budget_s=machine.c.primitive_seconds,strict_budget_s=3.,
                actual_duration_s=actual,duration_source=source,
                strict_duration_exceeded=bool(beyond))


def _approximate_time_window(r, *, required_frames=0, reason='planning_search'):
    """Keep finite planning arithmetic without making it an action deadline.

    Runtime.tick still performs every physics guard. The 120 second value is
    only a maximum duration for a single candidate reference; rolling it
    forward does not assert that an Episode succeeded or fit a time limit.
    """
    if not getattr(getattr(r,'cfg',None),'approximate_completion_enabled',False):return
    if getattr(r,'primitive_deadline_step',None) is None:return
    search_frames=math.ceil(120.*r.cfg.fps)
    target=r.steps+max(search_frames,int(required_frames))
    if target<=r.primitive_deadline_step:return
    old=r.primitive_deadline_step
    r.primitive_deadline_step=target
    r._approximate_extended_deadline_step=target
    r._approximate_deadline_extended=True
    if getattr(r,'trace',None) is not None:
        r.trace.event('time_budget_extended',reason=reason,
            previous_window_frames=max(0,old-r.steps),new_window_frames=target-r.steps,
            configured_primitive_seconds=r.cfg.primitive_seconds,
            qualification='finite_reference_search_window_not_episode_deadline')


@contextmanager
# 统一控制时间预算；墙钟规划耗时单独记录，失败不能伪装为成功。
def action(machine, name, **parameters):
    r=machine.r;start=r.steps;wall=time.monotonic()
    physics_step_start = getattr(r, 'physics_step_count', None)
    physical_start = getattr(getattr(r, 'd', None), 'time', None)
    if physical_start is not None: physical_start = float(physical_start)
    if getattr(r,'primitive_deadline_step',None) is not None:
        raise Fault('nested_primitive')
    approximate=bool(getattr(machine.c,'approximate_completion_enabled',False))
    r.primitive_deadline_step=start+math.floor(
        (max(30.,machine.c.primitive_seconds) if approximate else machine.c.primitive_seconds)*machine.c.fps)
    if approximate:_approximate_time_window(r,reason='action_start_reference_search')
    try:
        machine.log.event('primitive_start',primitive=name,
            limit_s=(None if approximate else machine.c.primitive_seconds),
            configured_budget_s=machine.c.primitive_seconds,strict_budget_s=3.,
            time_policy=('diagnostic_only_finite_120s_reference_search' if approximate else 'hard_action_budget'),
            parameters=parameters)
        yield
    except Fault as exc:
        machine.log.event('primitive_failed',primitive=name,reason=exc.code,detail=exc.detail,
                          duration_s=(r.steps-start)/machine.c.fps,
                          **_action_timing(machine,start,physical_start,physics_step_start))
        # Never follow a rejected fast action with an unlabelled slow retry.
        failure = Fault(exc.code,exc.detail,recoverable=False)
        physical_end = getattr(getattr(r, 'd', None), 'time', None)
        if physical_end is not None: physical_end = float(physical_end)
        failure.primitive_execution = MappingProxyType({
            'name': name, 'start_step': start, 'end_step': r.steps,
            'elapsed_steps': r.steps-start, 'physical_start': physical_start,
            'physical_end': physical_end,
            'physical_elapsed_s': None if physical_start is None or physical_end is None else physical_end-physical_start})
        raise failure from exc
    else:
        machine.log.event('primitive_complete',primitive=name,duration_s=(r.steps-start)/machine.c.fps,
                          planning_and_execution_wall_s=time.monotonic()-wall,
                          **_action_timing(machine,start,physical_start,physics_step_start))
    finally:
        r.primitive_deadline_step=None
        if approximate:
            r._approximate_extended_deadline_step=None
            r._approximate_deadline_extended=False
        timing=_action_timing(machine,start,physical_start,physics_step_start)
        if (getattr(machine.c,'acceptance_profile','strict')=='completion_first' and
                timing['strict_duration_exceeded']):
            r.record_strict_deviation('primitive_duration_outside_strict_contract',
                dict(primitive=name,**timing,
                     qualification='actual_simulation_duration_not_configured_budget'))


def remaining(r):
    _approximate_time_window(r)
    return (r.primitive_deadline_step-r.steps)/r.cfg.fps


# 先验证整段路径再执行；禁止通过放宽限位或忽略刚性夹持误差换取速度。
def plan(r, points, *, available, minimum=.1, allow_shortcut=False, extra_path_check=None):
    """Select a whole C2 reference before motion; reject rather than speed-limit bypass."""
    original_available=available
    if getattr(getattr(r,'cfg',None),'approximate_completion_enabled',False):
        _approximate_time_window(r)
        available=max(float(available),120.)
    points=np.asarray(points,float)
    low,high=r.m.jnt_range[r.jids].T
    lo,hi=entry_limit_envelope(points[:,ARM_COLUMNS],low,high,r.cfg.joint_margin_rad)
    reasons=[];prepared=[];seen=set()
    candidates=[(kind,points) for kind in (CruiseJointPath,BlendedJointPath)]
    if allow_shortcut:
        for n in (2,3,4,5):
            subset=points[np.unique(np.round(np.linspace(0,len(points)-1,n)).astype(int))]
            candidates.extend((kind,subset) for kind in (CruiseJointPath,BlendedJointPath))
        for middle in range(1,len(points)-1):
            candidates.extend((kind,points[[0,middle,-1]]) for kind in (CruiseJointPath,BlendedJointPath))
            linear=points[0]+(points[-1]-points[0])*middle/(len(points)-1)
            for weight in (.25,.5,.75):
                subset=np.stack([points[0],linear+weight*(points[middle]-linear),points[-1]])
                candidates.extend((kind,subset) for kind in (CruiseJointPath,BlendedJointPath))
    for kind,knots in candidates:
        identity=(kind.__name__,knots.shape,knots.tobytes())
        if identity in seen:continue
        seen.add(identity)
        path=kind(knots,r.v,r.a,r.j,minimum)
        frames=math.ceil(path.duration*r.cfg.fps);duration=frames/r.cfg.fps
        if duration>available+1e-9:
            reasons.append({'mode':kind.__name__,'reason':'duration','required_s':duration});continue
        prepared.append((duration,path,frames))
    # Same minimum-duration choice as exhaustive validation, but stop checking
    # slower candidates once a valid faster path is found. Stable sorting keeps
    # the previous tie-breaking order and therefore the selected reference.
    for duration,path,frames in sorted(prepared,key=lambda x:x[0]):
        kind=type(path)
        reason=r._path_rejection(path,max(64,len(points)*16),lo,hi,True)
        if reason is not None:
            reasons.append({'mode':kind.__name__,**reason});continue
        if extra_path_check is not None:
            reason = extra_path_check(path)
            if reason is not None:
                reasons.append({'mode':kind.__name__,**reason});continue
        try:
            for u in np.linspace(0,1,21):
                q,v,a,_=path.evaluate(u,duration)
                r.audit_online_reference(q,v,a)
        except Fault as exc:
            reasons.append({'mode':kind.__name__,'reason':exc.code});continue
        if (getattr(getattr(r,'cfg',None),'approximate_completion_enabled',False) and
                duration>original_available+1e-9 and getattr(r,'trace',None) is not None):
            r.trace.event('time_budget_extended',reason='complete_reference_duration',
                requested_s=float(original_available),selected_s=float(duration),
                maximum_single_reference_search_s=120.,
                qualification='full_path_guarded_before_physics_no_action_deadline')
        return path,frames
    raise Fault('primitive_path_infeasible',{'available_s':available,'candidates':reasons})


def plan_withdraw_path(r,points,free_midpoint,held_endpoint,held_columns,*,available,extra_path_check=None):
    """Preserve original feasible path; two bounded alternatives on duration only."""
    _approximate_time_window(r,reason='withdraw_search_before_snapshot')
    options=dict(available=available,minimum=min(2.4,available-.05),allow_shortcut=False,
                 extra_path_check=extra_path_check)
    merge_enabled=bool(getattr(getattr(r,'cfg',None),'push_withdraw_merge_fallback_enabled',False))
    if merge_enabled:
        from .withdraw_merge import planning_snapshot,try_merge
        before=planning_snapshot(r)
    try:
        return plan(r,points,**options)
    except Fault as original:
        if original.code!='primitive_path_infeasible' or not isinstance(original.detail,dict):raise
        rejected=original.detail.get('candidates',[])
        if not rejected or any(x.get('reason')!='duration' for x in rejected):raise
        attempts=[]
        for fraction in (.45,.60):
            candidate=np.array(points,float,copy=True)
            middle=np.array(free_midpoint,float,copy=True)
            middle[held_columns]+=fraction*(held_endpoint[held_columns]-middle[held_columns])
            candidate[1]=middle
            try:
                planned=plan(r,candidate,**options)
            except Fault as exc:
                if exc.code!='primitive_path_infeasible':raise
                attempts.append({'fraction':fraction,'reason':exc.code,'detail':exc.detail})
                continue
            r.trace.event('push_withdraw_path_search',original_fraction=.3,selected_fraction=fraction,
                rejected=attempts,maximum_alternatives=2,original_failure=original.detail,
                qualification='zero_motion_planning_only_original_geometry_guards_and_budget')
            return planned
        r.trace.event('push_withdraw_path_search',original_fraction=.3,selected_fraction=None,
            rejected=attempts,maximum_alternatives=2,original_failure=original.detail)
        if merge_enabled:
            merged=try_merge(r,points,held_columns,original,attempts,before,options,plan)
            if merged is not None:return merged
        raise original


def execute(r, planned, predicate=None):
    path,frames=planned
    _approximate_time_window(r,required_frames=frames+2,reason='reference_execution')
    if frames>r.primitive_deadline_step-r.steps:raise Fault('primitive_insufficient_time')
    duration=frames/r.cfg.fps
    r.trace.event('primitive_reference',duration_s=duration,controller=type(path).__name__,
                  knot_stop_fallback=False,reference_bounds=path.reference_bounds)
    consecutive=0
    for frame in range(1,frames+1):
        if r.cfg.substep_control_enabled:
            from .substep_control import sample_path_targets
            targets=sample_path_targets(path,frame-1,frames,r.sim.nstep,r.cfg.fps)
            r.sim.target=targets[-1].copy()
            r.tick(substep_targets=targets)
        else:
            r.sim.target=path.evaluate(frame/frames,duration)[0]
            r.tick()
        if predicate is not None:consecutive=consecutive+1 if predicate(r.observation()) else 0
    return consecutive


def retime_push_to_budget(r, planned, available, *, event_name='primitive_push_budget_retime'):
    """Slow an already checked path to its declared nominal execution duration."""
    approximate=bool(getattr(getattr(r,'cfg',None),'approximate_completion_enabled',False))
    path, frames = planned
    preserve=(getattr(r.cfg,'acceptance_profile','strict')=='completion_first' and
              getattr(r.cfg,'completion_preserve_nominal_timing_enabled',False))
    if approximate and not preserve:
        # The 120s numerical search window is never a requested execution
        # duration when no nominal timing policy was configured.
        return planned
    requested_frames=math.floor(available*r.cfg.fps + 1e-9)
    target_frames=requested_frames
    if preserve:
        if not approximate and frames>requested_frames:
            raise Fault('primitive_path_infeasible',{'reason':'planned_path_exceeds_available_budget',
                'planned_frames':frames,'available_frames':requested_frames})
        nominal_frames=math.floor((3.-r.cfg.primitive_settle_s)*r.cfg.fps+1e-9)
        target_frames=(max(frames,nominal_frames) if approximate else
                       min(requested_frames,max(frames,nominal_frames)))
        r.trace.event('primitive_nominal_timing_policy',retime_event=event_name,
            planned_frames=frames,requested_budget_frames=requested_frames,effective_frames=target_frames,
            requested_budget_s=available,effective_motion_s=target_frames/r.cfg.fps,
            nominal_motion_frames=nominal_frames,verification_reserve_s=r.cfg.primitive_settle_s,
            reason='preserve_original_nominal_time_without_shortening_certified_path',
            qualification=('nominal_execution_duration_with_finite_approximate_search_window'
                           if approximate else 'reference_timing_policy_deadline_and_physics_guards_unchanged'))
    if target_frames <= frames:
        return planned
    duration = target_frames/r.cfg.fps
    # Retiming changes dynamics even when geometry is identical. Recheck the
    # actual duration against inverse-dynamics/effort/reference limits.
    for u in np.linspace(0., 1., 21):
        q, v, a, _ = path.evaluate(u, duration)
        r.audit_online_reference(q, v, a)
    r.trace.event(event_name, original_frames=frames,
                  execution_frames=target_frames, duration_s=duration,
                  verification_reserve_s=r.cfg.primitive_settle_s,
                  geometry_unchanged=True)
    return path, target_frames


def settle(r, predicate, seconds, stable_frames=2):
    count=math.ceil(seconds*r.cfg.fps)
    _approximate_time_window(r,required_frames=count+2,reason='verification')
    if count>r.primitive_deadline_step-r.steps:raise Fault('primitive_no_verification_budget')
    consecutive=0
    for _ in range(count):
        r.tick()
        consecutive=consecutive+1 if predicate(r.observation()) else 0
    if consecutive<min(stable_frames,count):
        x=r.observation();t=r.allowed_tray
        raise Fault('primitive_postcondition_failed',{'stable_frames':consecutive,
                    'tray_pose':x['tray_pose'][t],'bottom_z':float(x['min_z'][t]),
                    'table_contact':int(x['table_contact'][t]),'gripper_force':x['gripper_contact_force'][t]})


def supported_normal_path_rejection(r, path, side, start_z, end_z, *, samples=201):
    """Reject unintended normal excursions between supported command endpoints.

    This is an additional geometric check, never support-force evidence.
    The existing 0.25 mm supported IK accuracy bounds this entire reference.
    Existing explicit endpoint preload is retained; no new preload is added.
    """
    tolerance = .00025
    low, high = min(start_z, end_z)-tolerance, max(start_z, end_z)+tolerance
    for u in np.linspace(0., 1., samples):
        q = path.evaluate(u)[0]
        z = float(r._shadow(q).site(side+'_tcp').xpos[2])
        if not low <= z <= high:
            return {'reason': 'supported_normal_reference_excursion',
                    'side': side, 'path_fraction': float(u), 'command_z_m': z,
                    'allowed_z_m': [float(low), float(high)], 'tolerance_m': tolerance}
    return None


def replan_supported_release(r, tray, release, predicate, geometry_ready, consecutive):
    """One measured-aperture proposal, with unchanged force gate and deadline."""
    if (r.cfg.acceptance_profile!='completion_first' or
            not r.cfg.completion_release_replan_enabled or consecutive>=2):
        return consecutive
    x=r.observation()
    before=np.array(r.sim.target,float,copy=True)
    measured=np.array(r.sim.state(),float,copy=True)
    pending=[s for s in release if x['gripper_contact_force'][tray,0 if s=='left' else 1]>r.cfg.criteria.contact_n]
    detail=dict(tray=tray,release_sides=release,pending_sides=pending,
        before_opening=before[[7,15]],measured_opening=measured[[7,15]],
        force_before=x['gripper_contact_force'][tray].copy(),proposal_opening=None,
        remaining_frames=r.primitive_deadline_step-r.steps,verification_reserve_frames=2)
    reason=None;planned=None
    if not pending:reason='no_unreleased_side'
    elif not geometry_ready(x):reason='placement_geometry_or_support_not_ready'
    elif detail['remaining_frames']<=2:reason='no_motion_budget_after_verification_reserve'
    else:
        try:
            proposal=release_endpoint(before,measured,pending,open_limit=r.cfg.gripper_open_m,
                                      clearance=r.cfg.primitive_release_clearance_m)
            detail['proposal_opening']=proposal[[7,15]]
            if np.array_equal(proposal,before):reason='no_additional_opening_available'
            else:
                planned=plan(r,[before,proposal],available=(detail['remaining_frames']-2)/r.cfg.fps,
                             allow_shortcut=False)
        except ValueError as exc:
            reason='invalid_measured_release_proposal';detail['rejection_detail']=str(exc)
        except Fault as exc:
            if exc.code!='primitive_path_infeasible':raise
            reason=exc.code;detail['rejection_detail']=exc.detail
    r.trace.event('primitive_release_replan',accepted=planned is not None,reason=reason,**detail)
    if planned is None:return consecutive
    # Execution faults are physical evidence and must never become a waiting fallback.
    consecutive=execute(r,planned,predicate)
    r.trace.event('primitive_release_replan_executed',tray=tray,stable_frames=consecutive,
        force=r.observation()['gripper_contact_force'][tray],command_opening=r.sim.target[[7,15]],
        measured_opening=r.sim.state()[[7,15]],remaining_frames=r.primitive_deadline_step-r.steps)
    return consecutive


def finish_release_verification(r, predicate, consecutive, *, required=2):
    """Hold the release endpoint inside the existing action deadline only.

    The final reference sample can be the first force-free observation. Keep
    the same target while accumulating the unchanged consecutive-frame gate;
    every hold still runs Runtime.tick and all physics guards.
    """
    if r.primitive_deadline_step is None:
        raise Fault('primitive_no_verification_budget')
    if consecutive >= required:
        return consecutive
    _approximate_time_window(r,reason='release_verification')
    start = r.steps
    initial = consecutive
    remaining_frames = max(0, r.primitive_deadline_step-start)
    if getattr(getattr(r,'cfg',None),'approximate_completion_enabled',False):
        # A dropped tray has ample time to fall 20 mm in this measured hold;
        # avoid waiting for the full numerical planning window after a bad
        # release while retaining the original consecutive-contact gate.
        remaining_frames=min(remaining_frames,math.ceil(2.*r.cfg.fps))
    try:
        while consecutive < required and r.steps-start < remaining_frames:
            r.tick()
            consecutive = consecutive+1 if predicate(r.observation()) else 0
    finally:
        r.trace.event('primitive_release_verification_wait',
                      initial_stable_frames=initial, final_stable_frames=consecutive,
                      wait_frames=r.steps-start, remaining_frames=remaining_frames,
                      required=required)
    return consecutive


def _object_tcp_goals(r, position, yaw=None):
    from .runtime import _homogeneous
    b=r.d.body(r.g.ids[r.holding]);R=b.xmat.reshape(3,3).copy() if yaw is None else rz(yaw)
    T=_homogeneous(position,R)
    return {s:((T@rel)[:3,3],(T@rel)[:3,:3]) for s,rel in r.grasp_rel.items()}


def object_points(r, position, yaw=None):
    goals=_object_tcp_goals(r,position,yaw)
    return r.cartesian(goals,opening=r.cfg.gripper_close_m,wrist=True,preview_only=True,
                       start_from_command=(r.cfg.loaded_command_reference_enabled and
                                           r.cfg.loaded_command_reference_scope == 'all'))


def _private_place_descent_points(r, position, yaw):
    """Only a private place clone may try one joint endpoint after Cartesian IK."""
    try:
        return object_points(r,position,yaw),None
    except Fault as original:
        if (not getattr(r,'_place_private_joint_endpoint_enabled',False) or
                r.cfg.acceptance_profile!='completion_first' or
                r.fsm_state!=State.PLACE_TRAY or r.holding is None or
                r.retained_contact is not None or
                original.code!='coupled_ik_unreachable'):
            raise
        start=r.sim.target.copy()
        try:
            endpoint=r.solve_pair(_object_tcp_goals(r,position,yaw),seed=start)
        except Fault as alternative:
            r.trace.event('private_place_joint_endpoint',selected=False,
                original_reason=original.code,rejection=alternative.code,
                stage='endpoint_ik',qualification='private_geometry_only_no_live_motion')
            raise original from alternative
        endpoint=np.asarray(endpoint,float).copy()
        for side,col in (('left',7),('right',15)):
            if side in r.grasp_rel:endpoint[col]=r.cfg.gripper_close_m
        points=np.stack((start,endpoint))
        r.trace.event('private_place_joint_endpoint',
            original_reason=original.code,stage='endpoint_found_full_path_pending',
            qualification='private_geometry_only_no_live_motion')
        return points,original


def valid_command_grasp(r,tray):
    relation=getattr(r,'grasp_rel',None)
    valid_relation=(getattr(r,'holding',None)==tray and isinstance(relation,dict) and
        set(relation)=={'left','right'} and all(
            np.shape(value)==(4,4) and np.isfinite(value).all() and
            np.allclose(np.asarray(value)[3],[0.,0.,0.,1.],atol=1e-9,rtol=0) and
            np.allclose(np.asarray(value)[:3,:3].T@np.asarray(value)[:3,:3],np.eye(3),atol=1e-6,rtol=0) and
            np.linalg.det(np.asarray(value)[:3,:3])>0
            for value in relation.values()))
    return valid_relation


def checked_command_tcp(r):
    """Read commanded TCPs while preserving the original 5 cm compliance guard."""
    from .runtime import _homogeneous
    shadow=r._shadow(r.sim.target)
    commanded={};errors={}
    for side in ('left','right'):
        site=shadow.site(side+'_tcp');p=site.xpos.copy();R=site.xmat.reshape(3,3).copy()
        errors[side]=float(np.linalg.norm(p-r.sim.tcp(side)[0]))
        if errors[side]>.05:raise Fault('primitive_excess_servo_deflection',errors)
        commanded[side]=_homogeneous(p,R)
    return commanded,errors


def continue_loaded_reference(r):
    """Preserve measured servo compression instead of resetting it at each move.

These are COMMAND offsets, not observed object poses or synthetic contacts.
Actual bilateral forces and the complete physics guards remain authoritative.
"""
    from .runtime import _homogeneous
    b=r.d.body(r.g.ids[r.holding]);T=_homogeneous(b.xpos,b.xmat.reshape(3,3))
    commanded,errors=checked_command_tcp(r)
    rel={side:np.linalg.inv(T)@pose for side,pose in commanded.items()}
    r.grasp_rel=rel
    r.trace.event('primitive_command_compliance_reference',tcp_deflection_m=errors,
                  qualification='command_reference_only_not_observed_rigid_attachment')


# 高度依据托盘实际离桌距离验收，不用末端执行器指令位移替代。
def lift_postcondition(r,tray,start_bottom):
    """Check measured lift; approximate mode records bounded intermediate deviations."""
    from .acceptance_profile import predicate_with_strict_evidence
    c=r.cfg
    minimum=c.completion_lift_min_m if c.acceptance_profile=='completion_first' else .15
    approximate=bool(getattr(c,'approximate_completion_enabled',False))
    def accepted(x,lower,upper,tilt_limit,require_free):
        height=float(x['min_z'][tray]-start_bottom)
        return (lower<=height<=upper and (not require_free or x['support_contact'][tray]==0) and
                np.all(x['gripper_contact_force'][tray]>c.criteria.contact_n) and
                quat_yaw_tilt(x['tray_pose'][tray,3:])[1]<=np.deg2rad(tilt_limit))
    upper=.35 if approximate else .20
    tilt_limit=25. if approximate else c.criteria.tilt_deg
    return predicate_with_strict_evidence(r,
        lambda x:accepted(x,.15,.20,c.criteria.tilt_deg,True),
        lambda x:accepted(x,minimum,upper,tilt_limit,not approximate),
        'primitive_lift_outside_strict_contract',lambda x:{'tray':tray,
            'measured_height_m':float(x['min_z'][tray]-start_bottom),
            'strict_height_range_m':[.15,.20],'effective_height_range_m':[minimum,upper],
            'support_contact':float(x['support_contact'][tray]),
            'gripper_force_n':np.asarray(x['gripper_contact_force'][tray]).tolist(),
            'strict_tilt_limit_deg':c.criteria.tilt_deg,'effective_tilt_limit_deg':tilt_limit,
            'tilt_deg':float(np.degrees(quat_yaw_tilt(x['tray_pose'][tray,3:])[1]))})


def _select_lift_path(r,candidates,available):
    """Original inward order first; extended time retries cached duration failures only."""
    from .withdraw_merge import duration_only, planning_snapshot
    preserve=(r.cfg.acceptance_profile=='completion_first' and
              r.cfg.completion_preserve_nominal_timing_enabled and
              not getattr(getattr(r,'cfg',None),'approximate_completion_enabled',False))
    nominal=min(available,3.-r.cfg.primitive_settle_s) if preserve else available
    before=planning_snapshot(r) if preserve else None
    if preserve and before is None:raise Fault('lift_planning_state_unavailable')
    failures=[];cached=[]
    def checked():
        if not preserve:return
        after=planning_snapshot(r)
        if after is None:raise Fault('lift_planning_state_unavailable')
        changed=[key for key in before if key not in after or not np.array_equal(before[key],after[key])]
        if changed:raise Fault('lift_planning_state_changed',{'state_change':changed})
    try:
        for inward,candidate in candidates:
            event_start=len(getattr(r.trace,"lift_events",[])) if hasattr(r,"trace") else 0
            points=None
            try:
                if hasattr(r,'_lift_geometry_queries'):r._lift_geometry_queries+=1
                points=object_points(r,candidate)
                planned=plan(r,points,available=nominal,allow_shortcut=True)
            except Fault as exc:
                if exc.code not in ('ik_unreachable','coupled_ik_unreachable','ik_branch_jump','primitive_path_infeasible'):raise
                failures.append({'inward_m':inward,'reason':exc.code,'detail':exc.detail})
                if preserve and exc.code=='primitive_path_infeasible' and duration_only(exc.detail):
                    cached.append((inward,candidate.copy(),np.array(points,copy=True),
                        list(getattr(r.trace,"lift_events",[])[event_start:]) if hasattr(r,"trace") else []))
                continue
            if hasattr(getattr(r,'trace',None),'lift_events'):
                r._selected_lift_events=r.trace.lift_events[event_start:]
            return planned,inward,candidate,failures,('nominal' if preserve else 'original')
        if preserve and available>nominal:
            for inward,candidate,points,candidate_events in cached:
                try:planned=plan(r,points,available=available,allow_shortcut=True)
                except Fault as exc:
                    if exc.code!='primitive_path_infeasible':raise
                    failures.append({'inward_m':inward,'reason':exc.code,'detail':exc.detail,'budget_phase':'extended'})
                    continue
                if hasattr(getattr(r,'trace',None),'lift_events'):
                    r._selected_lift_events=candidate_events
                return planned,inward,candidate,failures,'extended_cached_duration_only'
        raise Fault('primitive_lift_path_unavailable',failures)
    finally:checked()


def select_lift_path(r,candidates,available):
    """Prefer the complete original orientation search before a private relaxed pass."""
    enabled=(r.cfg.acceptance_profile=='completion_first' and
        getattr(r.cfg,'completion_lift_strict_orientation_first_enabled',False) and
        r.cfg.completion_held_ik_orientation_tolerance_rad>.05)
    if not enabled:return _select_lift_path(r,candidates,available)
    from dataclasses import replace
    import copy
    from .placement_reachability import loaded_planning_copy
    from .withdraw_merge import planning_snapshot,check_unchanged
    candidates=[(inward,np.array(target,copy=True)) for inward,target in candidates]
    if not 1<=len(candidates)<=7:raise Fault('lift_orientation_candidate_budget_invalid')
    before=planning_snapshot(r)
    if before is None:raise Fault('lift_planning_state_unavailable')
    class Trace:
        def __init__(self):self.lift_events=[]
        def event(self,name,**detail):self.lift_events.append((name,copy.deepcopy(detail)))
    started=time.monotonic();original=None;phases=[]
    try:
        for phase,bound in (('original',.05),('configured',r.cfg.completion_held_ik_orientation_tolerance_rad)):
            probe=loaded_planning_copy(r)
            probe.cfg=replace(r.cfg,completion_held_ik_orientation_tolerance_rad=bound)
            probe.trace=Trace();probe._lift_geometry_queries=0
            try:result=_select_lift_path(probe,candidates,available)
            except Fault as exc:
                if exc.code!='primitive_lift_path_unavailable':raise
                phases.append(dict(phase=phase,orientation_tolerance_rad=bound,qualified=False,
                    rejected=exc.detail,geometry_queries=probe._lift_geometry_queries))
                if original is None:original=exc
                continue
            phases.append(dict(phase=phase,orientation_tolerance_rad=bound,qualified=True,
                selected_inward_m=result[1],rejected=result[3],geometry_queries=probe._lift_geometry_queries))
            check_unchanged(r,before)
            # Only the selected geometric candidate contributes policy evidence.
            # These accepted queries remain planning-only, not executed knots.
            for name,detail in getattr(probe,'_selected_lift_events',[]):
                if name=='held_ik_query_diagnostic':r.trace.event(name,**detail)
                elif name=='planning_policy_deviation':
                    r.trace.event(name,**detail)
                    r.record_strict_deviation(detail['code'],detail['detail'])
            return result
        raise original
    finally:
        check_unchanged(r,before)
        r.trace.event('lift_orientation_search',phases=phases,
            maximum_geometry_queries=2*len(candidates),
            geometry_queries=sum(p['geometry_queries'] for p in phases),wall_seconds=time.monotonic()-started,
            qualification='private_planning_only_original_deadline_no_physical_retry')


def lift(machine,tray):
    r=machine.r;c=machine.c;e=r.observation()
    start_bottom=float(e['min_z'][tray])
    minimum=c.completion_lift_min_m if c.acceptance_profile=='completion_first' else .15
    upper=.35 if getattr(c,'approximate_completion_enabled',False) else .20
    with action(machine,'lift',height_m=c.primitive_lift_m,accepted_height_m=[minimum,upper],
                strict_accepted_height_m=[.15,.20]):
        continue_loaded_reference(r)
        target=e['tray_pose'][tray,:3].copy()
        target[2]+=c.primitive_lift_m+c.primitive_lift_compensation_m
        machine.transition(State.GRASP_TRAY,'lift')
        toward=r.d.body('base_link').xpos[:2]-target[:2]
        toward=toward/max(float(np.linalg.norm(toward)),1e-9)
        candidates=[]
        # At the workspace rim a purely vertical lift can be unreachable.
        # Preplan a small inward tuck while preserving the SAME lift height;
        # this performs no live retry, release, or intermediate waypoint stop.
        for inward in (0.,.02,-.02,.04,-.04,.06,-.06):
            candidate=target.copy();candidate[:2]+=inward*toward
            if inward:
                candidate[2]+=max(0.,min(.02,.20-c.primitive_lift_m-c.primitive_lift_compensation_m))
            candidates.append((inward,candidate))
        available=remaining(r)-c.primitive_settle_s
        planned,inward,candidate,failures,budget_phase=select_lift_path(r,candidates,available)
        machine.log.event('primitive_lift_path_selected',inward_m=inward,target_position=candidate,
                          command_height_m=float(candidate[2]-e['tray_pose'][tray,2]),
                          rejected_candidates=failures,budget_phase=budget_phase,
                          available_s=available,nominal_motion_s=min(available,3.-c.primitive_settle_s))
        r.primitive_lift_xy_shift_m=abs(inward)
        execute(r,planned)
        machine.transition(State.GRASP_TRAY,'stabilize')
        settle(r,lift_postcondition(r,tray,start_bottom),c.primitive_settle_s)
        machine.log.event('primitive_lift_measured',height_m=float(r.observation()['min_z'][tray]-start_bottom),
                          strict_height_range_m=[.15,.20],effective_height_range_m=[minimum,upper])
        # Keep the validated commanded pair relationship for navigation.
        # Replacing it here with compliance-shifted measured TCP transforms
        # invalidates the unchanged command at the start of every base route.
        # Arrival planning remeasures both contact and command references.


# 桌面真实承重后才释放；衔接推动时保留一侧接触。
def _plan_place_descent(machine, operation, staged, e, top, combined_descent, keep, release, alignment_completed,
                        release_gap_m=0.):
    r=machine.r;c=machine.c;tray=operation.tray
    target=e['tray_pose'][tray,:3].copy()
    yaw,_=quat_yaw_tilt(e['tray_pose'][tray,3:])
    yaw=yaw+float(wrap_angle(operation.yaw-yaw,machine.g.period))
    # Correct measured alignment residual as part of the fully planned
    # descent, rather than preserving an off-centre table-edge arrival.
    target[:2]=staged[:2]
    # All descents command a level tray, including an already aligned
    # arrival. Retaining the measured arrival tilt embeds servo sag in the
    # target; later physical leveling would then lift its bottom off-table.
    body_id=r.m.body(machine.g.ids[tray]).id
    vertices=r.evidence.local_vertices[body_id]
    target_rotation=rz(yaw)
    target=touchdown_position(target,vertices,target_rotation,table_height=top,
                              preload=c.primitive_touchdown_preload_m)
    if release_gap_m:
        # Remove touchdown preload and leave the true lowest collision vertex
        # no more than the configured gap above the tabletop. The physical
        # state still has to fall onto the table after opening.
        target[2]+=c.primitive_touchdown_preload_m+release_gap_m
    if c.placement_alignment_xy_feedforward_enabled:
        from .alignment_feedforward import alignment_xy_target
        target, correction_info = alignment_xy_target(machine.g, e['tray_pose'], tray,
            staged, target, yaw, alignment_completed=alignment_completed,
            scope=c.placement_alignment_xy_feedforward_scope)
        machine.log.event('placement_alignment_xy_feedforward', target_tray=tray, **correction_info)
    points, joint_endpoint_original = _private_place_descent_points(r,target,yaw)
    machine.log.event('primitive_descent_geometry',combined_xy_descent=combined_descent,target_position=target,
                      target_yaw_rad=yaw,target_tilt_rad=0.)
    if combined_descent and keep:
        for s in release:
            col=7 if s=='left' else 15;start=float(points[0][col])
            preload=max(c.gripper_close_m,float(r.sim.state()[col])-.005)
            for i,point in enumerate(points):point[col]=start+(preload-start)*i/max(1,len(points)-1)
        machine.log.event('primitive_supported_release_preload',sides=release,
                          qualification='fingers_remain_clamped_until_measured_table_contact')
    # Release only enough to clear measured fingers; the ordinary open
    # limit remains unchanged. Full opening may follow during retreat.
    release_start=np.array(points[-1],float)
    release_end=release_endpoint(release_start,r.sim.state(),release,
                                open_limit=c.gripper_open_m,clearance=c.primitive_release_clearance_m)
    machine.log.event('primitive_release_plan',sides=release,measured_opening=r.sim.state()[[7,15]],
                      command_opening=release_end[[7,15]],clearance_m=c.primitive_release_clearance_m)
    try:
        release_plan=plan(r,[release_start,release_end],available=remaining(r)-.3)
        try:
            descent_frames=descent_budget_frames(remaining_frames=r.primitive_deadline_step-r.steps,
                                                release_frames=release_plan[1],support_frames=math.ceil(.1*c.fps))
        except ValueError as exc:
            raise Fault('primitive_insufficient_time',str(exc)) from exc
        descent=plan(r,points,available=descent_frames/c.fps,allow_shortcut=True)
    except Fault as alternative:
        if joint_endpoint_original is None:raise
        r.trace.event('private_place_joint_endpoint',selected=False,
            original_reason=joint_endpoint_original.code,rejection=alternative.code,
            stage='complete_joint_path',qualification='private_geometry_only_no_live_motion')
        raise joint_endpoint_original from alternative
    if joint_endpoint_original is not None:
        r.trace.event('private_place_joint_endpoint',selected=True,
            original_reason=joint_endpoint_original.code,
            path_frames=descent[1],release_frames=release_plan[1],
            stage='complete_joint_path',qualification='original_plan_checks_before_one_live_execution')
    return descent, release_plan


def _place_original_orientation_first(r):
    return (r.cfg.acceptance_profile=='completion_first' and
            getattr(r.cfg,'completion_place_ik_fallback_enabled',False) and
            r.cfg.completion_held_ik_orientation_tolerance_rad>.05 and
            r.holding is not None and r.retained_contact is None)


@contextmanager
def _original_place_orientation(r):
    """Scope the original 0.05 rad IK decision to planning, never a physics tick."""
    if not _place_original_orientation_first(r):
        yield
        return
    from dataclasses import replace
    configured=r.cfg
    r.cfg=replace(configured,completion_held_ik_orientation_tolerance_rad=.05)
    try:
        yield
    finally:
        r.cfg=configured


def _plan_place_original_then_relaxed(machine, operation, staged, e, top,
                                      combined_descent, keep, release,
                                      alignment_completed, saved_alignment_relation,
                                      release_gap_m=0.):
    """Use relaxed loaded IK only after a zero-motion full strict place rejection."""
    from .reference_candidates import plan_reference_candidate
    r=machine.r;c=machine.c
    _approximate_time_window(r,reason='place_search_before_snapshot')
    def live_plan():
        return plan_reference_candidate(r,
            lambda:_plan_place_descent(machine,operation,staged,e,top,combined_descent,
                keep,release,alignment_completed,release_gap_m),saved_alignment_relation,
            enabled=c.placement_preserve_command_grasp_enabled,check_command=checked_command_tcp)
    if not _place_original_orientation_first(r):
        return live_plan()
    from .withdraw_merge import planning_snapshot,check_unchanged
    before=planning_snapshot(r)
    if before is None:raise Fault('place_orientation_planning_state_unavailable')
    start_step=r.steps;start_time=float(r.d.time);deadline=r.primitive_deadline_step
    original_failure=None
    try:
        with _original_place_orientation(r):
            result=live_plan()
    except Fault as original:
        if (original.code not in ('ik_unreachable','coupled_ik_unreachable') or
                r.steps!=start_step or float(r.d.time)!=start_time or
                r.primitive_deadline_step!=deadline):
            raise
        original_failure=original
    else:
        check_unchanged(r,before)
        machine.log.event('primitive_place_orientation_search',selected='original',
            original_orientation_tolerance_rad=.05,
            configured_orientation_tolerance_rad=c.completion_held_ik_orientation_tolerance_rad,
            qualification='complete_strict_plan_before_physics')
        return result
    check_unchanged(r,before)
    import copy
    from .placement_reachability import loaded_planning_copy
    class PlanningTrace:
        def __init__(self):self.events=[]
        def event(self,name,**detail):self.events.append((name,copy.deepcopy(detail)))
    probe=loaded_planning_copy(r)
    probe.cfg=c
    probe._prefer_original_held_ik_seed=True
    if c.completion_place_private_joint_endpoint_enabled:
        probe._place_private_joint_endpoint_enabled=True
    private_position=float(c.completion_place_private_position_tolerance_m)
    if private_position>.08:
        probe._place_private_position_bound_m=private_position
    private=copy.copy(machine)
    private.r=probe
    private.log=probe.trace=PlanningTrace()
    saved=({side:value.copy() for side,value in saved_alignment_relation.items()}
           if saved_alignment_relation is not None else None)
    try:
        selected=plan_reference_candidate(probe,
            lambda:_plan_place_descent(private,operation,staged,e,top,combined_descent,
                keep,release,alignment_completed,release_gap_m),saved,
            enabled=c.placement_preserve_command_grasp_enabled,check_command=checked_command_tcp)
    except Fault as relaxed:
        check_unchanged(r,before)
        if relaxed.code not in ('ik_unreachable','coupled_ik_unreachable',
                                'primitive_path_infeasible','cartesian_collision_or_wrist'):
            raise
        machine.log.event('primitive_place_orientation_search',selected=None,
            original_reason=original_failure.code,relaxed_reason=relaxed.code,
            joint_endpoint_attempts=[detail for name,detail in private.log.events
                if name=='private_place_joint_endpoint'],
            qualification='both_private_and_original_plans_rejected_before_physics')
        raise original_failure from relaxed
    check_unchanged(r,before)
    r.grasp_rel={side:value.copy() for side,value in probe.grasp_rel.items()}
    for name,detail in private.log.events:
        machine.log.event(name,**detail)
        if name=='planning_policy_deviation':
            r.record_strict_deviation(detail['code'],detail['detail'])
    machine.log.event('primitive_place_orientation_search',selected='configured',
        original_reason=original_failure.code,original_orientation_tolerance_rad=.05,
        configured_orientation_tolerance_rad=c.completion_held_ik_orientation_tolerance_rad,
        private_position_tolerance_m=private_position,
        strict_position_tolerance_m=.022,
        independent_seed_priority='original_orientation_candidate_if_available',
        actual_motion_steps_before_selection=r.steps-start_step,
        qualification='private_complete_reference_then_single_live_execution')
    return selected


def _plan_place_approximate_collision_fallback(machine, operation, staged, e, top,
        combined_descent, keep, release, alignment_completed,
        saved_alignment_relation, release_gap_m, original_failure):
    """Qualify the whole place reference privately before scoped live replanning."""
    from .withdraw_merge import planning_snapshot,check_unchanged
    from .placement_reachability import loaded_planning_copy
    import copy
    r=machine.r;c=machine.c
    if (not getattr(c,'approximate_completion_enabled',False) or
            r.fsm_state not in (State.PLACE_TRAY,State.ADJUST_TRAY) or
            r.holding!=operation.tray or r.retained_contact is not None or
            c.completion_collision_penetration_m>.02 or
            original_failure.code not in ('cartesian_collision_or_wrist',
                'primitive_path_infeasible','ik_unreachable','coupled_ik_unreachable')):
        return None
    _approximate_time_window(r,reason='place_collision_search_before_snapshot')
    before=planning_snapshot(r)
    if before is None:raise Fault('place_collision_planning_state_unavailable')
    class PlanningTrace:
        def __init__(self):self.events=[]
        def event(self,name,**detail):self.events.append((name,copy.deepcopy(detail)))
    probe=loaded_planning_copy(r)
    probe._approximate_planning_relaxed=True
    # A private candidate may emit policy diagnostics; only the selected live
    # replan is permitted to update runtime evidence counters.
    probe.record_strict_deviation=lambda *args,**kwargs:None
    private=copy.copy(machine);private.r=probe;private.log=probe.trace=PlanningTrace()
    try:
        selected=_plan_place_original_then_relaxed(private,operation,staged,e,top,
            combined_descent,keep,release,alignment_completed,
            saved_alignment_relation,release_gap_m)
    except Fault as rejected:
        check_unchanged(r,before)
        machine.log.event('primitive_place_collision_fallback',selected=False,
            stage='private_full_reference',original_reason=original_failure.code,
            rejected_reason=rejected.code,release_gap_m=release_gap_m,
            maximum_planning_penetration_m=c.completion_collision_penetration_m,
            qualification='no_physics_no_partial_reference')
        return None
    check_unchanged(r,before)
    previous=bool(getattr(r,'_approximate_planning_relaxed',False))
    r._approximate_planning_relaxed=True
    try:
        try:
            live=_plan_place_original_then_relaxed(machine,operation,staged,e,top,
                combined_descent,keep,release,alignment_completed,
                saved_alignment_relation,release_gap_m)
        except Fault as rejected:
            check_unchanged(r,before)
            machine.log.event('primitive_place_collision_fallback',selected=False,
                stage='live_full_replan',original_reason=original_failure.code,
                rejected_reason=rejected.code,release_gap_m=release_gap_m,
                maximum_planning_penetration_m=c.completion_collision_penetration_m,
                qualification='no_physics_no_partial_reference')
            return None
    finally:
        r._approximate_planning_relaxed=previous
    check_unchanged(r,before)
    r.record_strict_deviation('primitive_place_collision_planning_fallback',
        dict(original_reason=original_failure.code,release_gap_m=release_gap_m,
             maximum_planning_penetration_m=c.completion_collision_penetration_m,
             qualification='accepted_complete_reference_with_approximate_collision_planning'))
    machine.log.event('primitive_place_collision_fallback',selected=True,
        original_reason=original_failure.code,release_gap_m=release_gap_m,
        private_descent_frames=selected[0][1],private_release_frames=selected[1][1],
        live_descent_frames=live[0][1],live_release_frames=live[1][1],
        maximum_planning_penetration_m=c.completion_collision_penetration_m,
        camera_and_rigid_guards_unchanged=True,
        qualification='private_complete_reference_then_live_replan_before_any_motion')
    return live


def _near_table_release_ready(machine, operation, staged, top, observation):
    """Observed, supported-footprint precondition for a bounded gravity drop."""
    r=machine.r;c=machine.c;tray=operation.tray
    pose=observation['tray_pose'][tray]
    yaw,tilt=quat_yaw_tilt(pose[3:])
    gap=float(observation['min_z'][tray]-top)
    limit=min(.02,float(c.completion_release_gap_m))
    from .acceptance_profile import completion_criteria
    criteria=completion_criteria(c)
    geometry=(0.<=gap<=limit+1e-9 and
        np.linalg.norm(pose[:2]-staged[:2])<=criteria.position_m and
        abs(wrap_angle(yaw-operation.yaw,machine.g.period))<=np.deg2rad(criteria.yaw_deg) and
        tilt<=np.deg2rad(criteria.tilt_deg) and
        machine.g.support_table(pose[:3])==machine.g.support_table(staged) and
        machine.g.footprint_supported(pose[:3],yaw,machine.g.sizes[tray],margin=0.) and
        not machine.g.blockers(observation['tray_pose'],tray,pose[:3],yaw,.002))
    bilateral=bool(np.all(observation['gripper_contact_force'][tray]>criteria.contact_n))
    return bool(geometry and bilateral),dict(gap_m=gap,limit_m=limit,
        footprint_and_pose_ok=bool(geometry),bilateral_grip=bilateral)


def place(machine,operation,staged):
    """One local descent plus confirmed unloading/release; base travel is separate."""
    r=machine.r;c=machine.c;tray=operation.tray;e=r.observation()
    table=machine.g.support_table(staged)
    if table is None:raise Fault('primitive_place_no_table')
    top=machine.g.tables[table]['dimensions_m'][2]
    need_push=np.linalg.norm(staged[:2]-operation.destination[:2])>.01
    keep=None
    if need_push and c.keep_place_contact:
        direction=operation.destination[:2]-staged[:2]
        keep=min(('left','right'),key=lambda s:np.dot(r.sim.tcp(s)[0][:2]-staged[:2],direction))
    release=[s for s in ('left','right') if s!=keep]
    # Explicit transport endpoint, not repeated corrections hidden in place.
    # It has its own complete configured primitive budget and audit event.
    combined_descent=getattr(r,'primitive_lift_xy_shift_m',0.)>.005
    alignment_plan=None
    alignment_completed=False
    if combined_descent:
        # The pickup's lateral escape does not imply that the destination
        # requires a combined move. Try a complete private loaded alignment
        # first; a rejected proposal has executed no part of the trajectory.
        try:
            continue_loaded_reference(r)
            current=r.observation()['tray_pose'][tray]
            aligned=current[:3].copy();aligned[:2]=staged[:2]
            yaw,_=quat_yaw_tilt(current[3:])
            goal_yaw=yaw+float(wrap_angle(operation.yaw-yaw,machine.g.period))
            with _original_place_orientation(r):
                points=object_points(r,aligned,goal_yaw)
                alignment_plan=plan(r,points,available=c.primitive_seconds-c.primitive_settle_s,allow_shortcut=True)
        except Fault as exc:
            machine.log.event('transport_align_deferred',reason=exc.code,detail=exc.detail,
                              qualification='planning_rejection_before_any_alignment_motion')
        else:
            combined_descent=False
            machine.log.event('transport_align_separated',qualification='complete_alignment_planned_before_execution')
    elif (getattr(c,'completion_place_zero_shift_combined_fallback_enabled',False) and
          c.acceptance_profile=='completion_first' and r.holding==tray and
          r.retained_contact is None):
        # The absence of a lateral pickup shift says nothing about whether a
        # diagonal approach to the support is reachable. Preserve the original
        # separate alignment as first choice, but screen its pure zero-motion
        # IK failure before opening a physical action. A successful full
        # private descent/release reference authorizes one live replan only.
        from .placement_reachability import loaded_planning_copy, _qualify_combined_descent
        alignment_probe=loaded_planning_copy(r)
        try:
            continue_loaded_reference(alignment_probe)
            current=alignment_probe.observation()['tray_pose'][tray]
            aligned=current[:3].copy();aligned[:2]=staged[:2]
            yaw,_=quat_yaw_tilt(current[3:])
            goal_yaw=yaw+float(wrap_angle(operation.yaw-yaw,machine.g.period))
            with _original_place_orientation(alignment_probe):
                points=object_points(alignment_probe,aligned,goal_yaw)
                alignment_plan=plan(alignment_probe,points,
                    available=c.primitive_seconds-c.primitive_settle_s,
                    allow_shortcut=True)
        except Fault as alignment_failure:
            if alignment_failure.code in ('ik_unreachable','coupled_ik_unreachable'):
                combined_probe=loaded_planning_copy(r)
                try:
                    prediction=_qualify_combined_descent(combined_probe,staged,
                        operation.destination,operation.yaw,r.sim.base_state(),
                        alignment_failure)
                except Fault as combined_failure:
                    machine.log.event('transport_align_combined_fallback',selected=False,
                        original_reason=alignment_failure.code,
                        combined_rejection=combined_failure.code,
                        qualification='private_zero_motion_complete_path_only')
                else:
                    combined_descent=True
                    machine.log.event('transport_align_combined_fallback',selected=True,
                        original_reason=alignment_failure.code,
                        descent_frames=prediction['descent_frames'],
                        release_frames=prediction['release_frames'],
                        qualification='private_complete_path_requires_live_replan_and_contact')
        else:
            # The original alignment remains preferred. Its private joint
            # path is valid only from the same measured command/state; live
            # execution still passes the full runtime guards.
            alignment_plan=None
            machine.log.event('transport_align_combined_fallback',selected=False,
                original_alignment_qualified=True,
                qualification='private_alignment_reference_before_live_execution')
    if not combined_descent:
        with action(machine,'transport_align',destination_xy=staged[:2]):
            if alignment_plan is None:
                continue_loaded_reference(r)
                current=r.observation()['tray_pose'][tray]
                aligned=current[:3].copy();aligned[:2]=staged[:2]
                yaw,_=quat_yaw_tilt(current[3:]);goal_yaw=yaw+float(wrap_angle(operation.yaw-yaw,machine.g.period))
                with _original_place_orientation(r):
                    points=object_points(r,aligned,goal_yaw)
                    alignment_plan=plan(r,points,available=remaining(r)-c.primitive_settle_s,allow_shortcut=True)
            machine.transition(State.TRANSPORT_TRAY,'preplace')
            if c.transport_align_use_full_budget:
                alignment_plan=retime_push_to_budget(r,alignment_plan,remaining(r)-c.primitive_settle_s,
                    event_name='primitive_transport_align_budget_retime')
            execute(r,alignment_plan)
            from .acceptance_profile import completion_criteria, predicate_with_strict_evidence
            task_criteria=completion_criteria(c)
            aligned_ok=predicate_with_strict_evidence(r,
                lambda x:np.linalg.norm(x['tray_pose'][tray,:2]-staged[:2])<=c.criteria.position_m,
                lambda x:np.linalg.norm(x['tray_pose'][tray,:2]-staged[:2])<=task_criteria.position_m,
                'primitive_alignment_outside_strict_contract',
                lambda x:{'tray':tray,'position_error_m':float(np.linalg.norm(x['tray_pose'][tray,:2]-staged[:2]))})
            settle(r,aligned_ok,c.primitive_settle_s)
        alignment_completed=True
    e=r.observation()
    with action(machine,'place',table_height_m=top,staged=staged,retained_side=keep):
        machine.transition(State.PLACE_TRAY,'descend')
        saved_alignment_relation = ({side:value.copy() for side,value in r.grasp_rel.items()}
            if c.placement_preserve_command_grasp_enabled and alignment_completed and valid_command_grasp(r,tray) else None)
        # The original measured reference always gets first refusal. Compliance
        # validation remains outside the candidate planning catch.
        continue_loaded_reference(r)
        release_gap_m=0.
        try:
            descent, release_plan = _plan_place_original_then_relaxed(machine, operation,
                staged,e,top,combined_descent,keep,release,alignment_completed,
                saved_alignment_relation)
        except Fault as exact_failure:
            if (not c.approximate_completion_enabled or exact_failure.code not in
                    ('ik_unreachable','coupled_ik_unreachable','primitive_path_infeasible',
                     'cartesian_collision_or_wrist')):
                raise
            from .placement_reachability import loaded_planning_copy, _SilentTrace
            import copy
            attempts=[]
            for gap in (.005,.01,.015,.02):
                if gap>c.completion_release_gap_m+1e-9:continue
                probe=loaded_planning_copy(r)
                private=copy.copy(machine);private.r=probe;private.log=probe.trace=_SilentTrace()
                try:
                    _plan_place_original_then_relaxed(private,operation,staged,e,top,
                        combined_descent,keep,release,alignment_completed,
                        saved_alignment_relation,gap)
                except Fault as rejected:
                    attempts.append(dict(gap_m=gap,reason=rejected.code))
                    continue
                release_gap_m=gap
                machine.log.event('primitive_near_table_release_search',selected_gap_m=gap,
                    original_reason=exact_failure.code,rejected=attempts,
                    qualification='private_complete_path_and_release_replanned_live')
                break
            if not release_gap_m:
                machine.log.event('primitive_near_table_release_search',selected_gap_m=None,
                    original_reason=exact_failure.code,rejected=attempts)
                collision_selected=None
                for gap in (0.,.005,.01,.015,.02):
                    if gap>c.completion_release_gap_m+1e-9:continue
                    collision_selected=_plan_place_approximate_collision_fallback(
                        machine,operation,staged,e,top,combined_descent,keep,release,
                        alignment_completed,saved_alignment_relation,gap,exact_failure)
                    if collision_selected is not None:
                        release_gap_m=gap
                        break
                if collision_selected is None:raise exact_failure
                descent,release_plan=collision_selected
            else:
                try:
                    descent,release_plan=_plan_place_original_then_relaxed(machine,operation,
                        staged,e,top,combined_descent,keep,release,alignment_completed,
                        saved_alignment_relation,release_gap_m)
                except Fault as strict_live_failure:
                    collision_selected=_plan_place_approximate_collision_fallback(
                        machine,operation,staged,e,top,combined_descent,keep,release,
                        alignment_completed,saved_alignment_relation,release_gap_m,
                        strict_live_failure)
                    if collision_selected is None:raise
                    descent,release_plan=collision_selected
        machine.transition(State.PLACE_TRAY,'descend')
        support_frames=execute(r,descent,lambda x:x['table_contact'][tray]>0)
        machine.transition(State.PLACE_TRAY,'support_contact')
        # Touchdown authorizes STARTING the smooth opening ramp. Table support
        # is checked throughout that ramp; final placement still needs stable
        # release observations and the task's separate one-second acceptance.
        near_table_release=False
        if support_frames<1:
            if c.approximate_completion_enabled:
                near_table_release,detail=_near_table_release_ready(machine,operation,staged,top,r.observation())
                machine.log.event('primitive_near_table_release_precondition',accepted=near_table_release,**detail)
            if not near_table_release:
                settle(r,lambda x:x['table_contact'][tray]>0,.1,stable_frames=1)
        r.holding=None;r.grasp_rel=None
        if keep and not near_table_release:
            r.retained_contact=(tray,keep);r.check_retained_contact()
        cols=[0 if s=='left' else 1 for s in release]
        def placed(x,criteria=c.criteria,check_force=True):
            pose=x['tray_pose'][tray];a,tilt=quat_yaw_tilt(pose[3:])
            return (x['table_contact'][tray]>0 and
                (not check_force or np.all(x['gripper_contact_force'][tray,cols]<=criteria.contact_n)) and
                np.linalg.norm(pose[:3]-staged)<=criteria.position_m and
                abs(wrap_angle(a-operation.yaw,machine.g.period))<=np.deg2rad(criteria.yaw_deg) and
                tilt<=np.deg2rad(criteria.tilt_deg))
        from .acceptance_profile import completion_criteria, predicate_with_strict_evidence
        task_criteria=completion_criteria(c)
        original_placed=placed
        placed=predicate_with_strict_evidence(r,original_placed,
            lambda x:original_placed(x,task_criteria),'primitive_release_outside_strict_contract',
            lambda x:{'tray':tray,'pose':x['tray_pose'][tray].tolist(),'staged':staged.tolist(),
                      'yaw_target_rad':float(operation.yaw)})
        machine.transition(State.PLACE_TRAY,'open')
        release_frames=execute(r,release_plan,placed)
        release_frames=replan_supported_release(r,tray,release,placed,
            lambda x:original_placed(x,task_criteria,check_force=False),release_frames)
        release_frames=finish_release_verification(r,placed,release_frames)
        if release_frames<2:
            x=r.observation()
            raise Fault('primitive_release_not_verified',{'stable_frames':release_frames,
                'force':x['gripper_contact_force'][tray],'table_contact':int(x['table_contact'][tray]),
                'pose':x['tray_pose'][tray],'command_opening':r.sim.target[[7,15]],
                'measured_opening':r.sim.state()[[7,15]]})
        if keep and near_table_release:
            r.retained_contact=(tray,keep);r.check_retained_contact()
    if keep:
        if c.completion_handoff_clearance_enabled:
            from .handoff_clearance import perform_handoff_clearance
            perform_handoff_clearance(machine, operation, keep)
            try:
                return machine.push(operation, retained_side=keep, free_precleared=True)
            finally:
                r._handoff_clearance_monitor = None
        return machine.push(operation,retained_side=keep)
    machine.retreat()
    return False


# 保留接触手沿桌面推进，释放手避让；最终间隙在释放后的稳定阶段验收。
def _execute_push_reference(machine, planned, operation, side, position, rotation,
                            relation, free_goal, target_z, *, separation):
    """Scope feedback using the explicit operation contract, never FSM phase."""
    r = machine.r
    c = machine.c
    final_placement = (not separation and operation.slot >= 0 and not operation.temporary)
    enabled = c.push_yaw_feedback_enabled and (c.push_yaw_feedback_scope == 'all' or final_placement)
    if c.push_yaw_feedback_enabled:
        machine.log.event('push_yaw_feedback_scope', scope=c.push_yaw_feedback_scope,
            separation=bool(separation), temporary=bool(operation.temporary),
            target_slot=operation.slot, final_placement=final_placement, enabled=enabled)
    if enabled:
        from .yaw_feedback import execute_feedback
        start_z = float(r._shadow(r.sim.target).site(side+'_tcp').xpos[2])
        normal_check = lambda path: supported_normal_path_rejection(r, path, side, start_z, target_z)
        return execute_feedback(machine, planned, operation, side, position, rotation,
                                relation, free_goal, normal_check)
    return execute(r, planned)


def completion_free_open_points(r, points, side, *, free_retreat, withdraw_free):
    """One declared jaw-reference candidate; the caller still plans the whole curve."""
    if not (r.cfg.acceptance_profile=='completion_first' and
            getattr(r.cfg,'completion_push_free_open_enabled',False) and
            free_retreat and not withdraw_free):
        return points
    col=15 if side=='left' else 7
    candidate=np.array(points,float,copy=True)
    if candidate.ndim!=2 or candidate.shape[1]!=16 or len(candidate)<2:
        raise Fault('completion_free_open_path_invalid')
    start=float(candidate[0,col]);limit=float(r.cfg.gripper_open_m)
    if not np.isfinite(candidate).all() or not np.isfinite(limit) or start>limit:
        raise Fault('completion_free_open_path_invalid',{'start_opening_m':start,'open_limit_m':limit})
    candidate[:,col]=np.linspace(start,limit,len(candidate))
    r.trace.event('completion_push_free_open_candidate',retained_side=side,
        free_side='right' if side=='left' else 'left',start_opening_m=start,
        target_opening_m=limit,waypoints=len(candidate),
        primitive_deadline_step=r.primitive_deadline_step,
        arm_waypoints_unchanged=True,retained_opening_unchanged=True,
        qualification='unvalidated_reference_candidate_full_path_planning_and_actual_execution_required')
    return candidate


def hold_precleared_free_arm(points, target, free):
    """Keep a verified free hand's complete 8-column command constant."""
    columns = np.arange(8, 16) if free == 'right' else np.arange(0, 8)
    fixed = np.asarray(target)[columns].copy()
    for point in points:
        point[columns] = fixed
    return points


def completion_free_first_goal(machine, operation, free_tcp, *, tray_pose):
    """Bound a released hand's retreat outside both old and new tray footprints.

    This is a geometric proposal only. The caller plans and validates the full
    C2 joint reference, then the ordinary live contact and support guards run.
    """
    r=machine.r
    if not (r.cfg.acceptance_profile=='completion_first' and
            getattr(r.cfg,'completion_push_free_first_enabled',False)):
        return None
    tray=operation.tray
    old=np.asarray(tray_pose[:2],float)
    free=np.asarray(free_tcp[:2],float)
    outward=free-old
    norm=float(np.linalg.norm(outward))
    if not np.isfinite(norm) or norm<.04:
        r.trace.event('completion_push_free_first_candidate',accepted=False,
            reason='free_tcp_direction_ambiguous',target_tray=tray)
        return None
    outward/=norm
    corners=completion_free_first_sweep_corners(machine,operation,tray_pose)
    # The margin includes a conservative allowance for finger reach beyond TCP.
    required=float(np.max(corners@outward)+.065-free@outward)
    shift=max(0.,required)
    if not np.isfinite(shift) or shift>.18:
        r.trace.event('completion_push_free_first_candidate',accepted=False,
            reason='retreat_exceeds_18cm_bound',target_tray=tray,required_shift_m=shift)
        return None
    goal=np.asarray(free_tcp,float).copy()
    goal[:2]+=shift*outward
    goal[2]+=.10
    r.trace.event('completion_push_free_first_candidate',accepted=True,
        target_tray=tray,shift_m=shift,clearance_margin_m=.065,
        start_tcp_world_m=np.asarray(free_tcp,float).tolist(),goal_tcp_world_m=goal.tolist(),
        qualification='geometry_only_full_joint_path_and_live_contact_validation_required')
    return goal


def completion_free_first_sweep_corners(machine,operation,tray_pose):
    """Planning envelope for intermediate tray position and yaw, not physics."""
    from .geometry import rectangle
    start_yaw,_=quat_yaw_tilt(tray_pose[3:])
    turn=float(wrap_angle(operation.yaw-start_yaw,machine.g.period))
    return np.vstack([rectangle(
        (1-u)*tray_pose[:3]+u*operation.destination,
        start_yaw+u*turn,machine.g.sizes[operation.tray])
        for u in np.linspace(0.,1.,9)])


def completion_free_first_path_rejection(machine,path,operation,free,side,tray_pose,free_tcp):
    """Reject a path that starts pushing before both free fingers clear the sweep."""
    r=machine.r
    outward=np.asarray(free_tcp[:2],float)-np.asarray(tray_pose[:2],float)
    outward/=np.linalg.norm(outward)
    farthest=float(np.max(completion_free_first_sweep_corners(machine,operation,tray_pose)@outward))
    finger_geoms=[i for i in range(r.m.ngeom)
        if r.m.geom_group[i]==3 and
        r.m.body(int(r.m.geom_bodyid[i])).name.startswith(free+'_gripper_finger_')]
    if len(finger_geoms)!=2:
        return {'reason':'completion_free_first_finger_geometry_unavailable',
                'finger_collision_geoms':len(finger_geoms)}
    initial=r._shadow(path.evaluate(0.,path.duration)[0]).site(side+'_tcp').xpos.copy()
    direction=np.r_[outward,0.]
    for u in np.linspace(0.,1.,81):
        q=path.evaluate(float(u),path.duration)[0]
        shadow=r._shadow(q)
        held=shadow.site(side+'_tcp').xpos
        if np.linalg.norm(held[:2]-initial[:2])<=.003:
            continue
        free_position=shadow.site(free+'_tcp').xpos
        if float(free_position[:2]@outward)<farthest+.065-1e-6:
            return {'reason':'completion_free_first_sweep_clearance',
                    'sample_fraction':float(u),'part':'free_tcp',
                    'clearance_m':float(free_position[:2]@outward-farthest)}
        for geom in finger_geoms:
            xmat=shadow.geom_xmat[geom].reshape(3,3)
            extent=float(np.sum(np.abs(xmat.T@direction)*r.m.geom_size[geom]))
            clearance=float(shadow.geom_xpos[geom,:2]@outward-extent-farthest)
            if clearance<.005:
                return {'reason':'completion_free_first_sweep_clearance',
                        'sample_fraction':float(u),'part':'free_finger',
                        'geom':int(geom),'clearance_m':clearance}
    return None


def push(machine,operation,side,relation,*,separation=False,free_retreat=False,
         free_precleared=False):
    from .runtime import _homogeneous
    r=machine.r;c=machine.c;tray=operation.tray
    with action(machine,'push',destination=operation.destination,yaw=operation.yaw,separation=separation):
        free_goal=None
        withdraw_free=False
        if free_retreat:
            free='right' if side=='left' else 'left';p,R=r.sim.tcp(free)
            withdraw_free=(not free_precleared and
                           getattr(r,'primitive_lift_xy_shift_m',0.)>.005)
            if not free_precleared:p[2]+=.10
            if withdraw_free:p[:2]-=.06*r.d.body('base_link').xmat.reshape(3,3)[:2,0]
            free_goal=(free,p,R)
        e=r.observation();actual=e['tray_pose'][tray];yaw,_=quat_yaw_tilt(actual[3:])
        free_first=False
        original_free_goal=free_goal
        if free_retreat and not withdraw_free and not free_precleared:
            proposed=completion_free_first_goal(machine,operation,r.sim.tcp(free)[0],tray_pose=actual)
            if proposed is not None:
                free_goal=(free,proposed,free_goal[2])
                free_first=True
        if free_retreat:
            # Continue the already loaded retained hand's COMMAND relationship.
            # Reconstructing from the deflected measured TCP discards its servo
            # compression, leaving a systematic short push at every handoff.
            shadow=r._shadow(r.sim.target).site(side+'_tcp')
            measured=r.sim.tcp(side)[0]
            error=float(np.linalg.norm(shadow.xpos-measured))
            if error>.05:raise Fault('primitive_excess_servo_deflection',{side:error})
            body=r.d.body(machine.g.ids[tray])
            relation=np.linalg.inv(_homogeneous(body.xpos,body.xmat.reshape(3,3)))@_homogeneous(shadow.xpos,shadow.xmat.reshape(3,3))
            machine.log.event('primitive_push_compliance_reference',side=side,tcp_deflection_m=error,
                              qualification='command_reference_only_not_observed_rigid_attachment')
        delta=operation.destination[:2]-actual[:2]
        position=actual[:3].copy();position[:2]=operation.destination[:2]
        feedforward=.012 if separation else c.primitive_push_compensation_m
        if withdraw_free:feedforward=min(feedforward,.020)
        position[:2]+=feedforward*delta/max(float(np.linalg.norm(delta)),1e-9)
        if withdraw_free:position[2]-=c.push_withdraw_preload_scale*c.primitive_touchdown_preload_m
        machine.log.event('primitive_push_feedforward',distance_m=feedforward,
                          nominal_destination=operation.destination,command_position=position)
        R=r.d.body(machine.g.ids[tray]).xmat.reshape(3,3).copy()
        R=rz(float(wrap_angle(operation.yaw-yaw,machine.g.period)))@R
        T=_homogeneous(position,R)@relation
        goals={side:(T[:3,3],T[:3,:3])}
        if free_goal is not None and not free_precleared:
            goals[free_goal[0]]=(free_goal[1],free_goal[2])
        # Free-arm clearance and the held-arm push share ONE continuous path.
        # Preserve the free gripper's open target; only the retained hand closes.
        command_reference = c.loaded_command_reference_enabled
        normal_start_z = (float(r._shadow(r.sim.target).site(side+'_tcp').xpos[2])
                          if command_reference else None)
        def original_points_after_rejection(rejected,stage):
            r.trace.event('completion_push_free_first_fallback',reason=rejected.code,
                detail=rejected.detail,stage=stage,
                qualification='zero_motion_original_reference_replanned')
            goals[free]=(original_free_goal[1],original_free_goal[2])
            return r.cartesian(goals,wrist=True,preview_only=True,
                               start_from_command=command_reference)
        try:
            points=r.cartesian(goals,wrist=True,preview_only=True,start_from_command=command_reference)
        except Fault as rejected:
            if not free_first:raise
            points=original_points_after_rejection(rejected,'combined_cartesian')
            free_goal=original_free_goal;free_first=False
        if free_precleared:
            # A newly verified free hand is no longer a push participant.
            # Solve only the retained side and pin every free joint reference,
            # including the already open jaw, through the whole push curve.
            points=hold_precleared_free_arm(points,r.sim.target,free)
            machine.log.event('handoff_clearance_free_arm_command_held',
                free_side=free, target_tray=tray,
                qualification='constant_free_joint_reference_full_push_path_revalidated')
        for point in points:point[7 if side=='left' else 15]=c.gripper_close_m
        if not free_first:
            points=completion_free_open_points(r,points,side,
                free_retreat=free_retreat,withdraw_free=withdraw_free)
        if withdraw_free:
            col=7 if free=='left' else 15;start=float(points[0][col])
            for i,point in enumerate(points):point[col]=start+(c.gripper_open_m-start)*i/max(1,len(points)-1)
        available=remaining(r)-c.primitive_settle_s
        if withdraw_free or free_first:
            try:
                free_points=r.cartesian({free:(free_goal[1],free_goal[2])},opening=c.gripper_open_m,
                                        wrist=True,preview_only=True,start_from_command=command_reference)
                # Free fingers clear first; held-hand motion shares one C2 reference.
                from scipy.spatial.transform import Rotation,Slerp
                previous=np.array(free_points[-1],float);shadow=r._shadow(previous).site(side+'_tcp')
                start_p=shadow.xpos.copy();start_R=shadow.xmat.reshape(3,3).copy()
                rotations=Slerp([0,1],Rotation.from_matrix(np.stack([start_R,T[:3,:3]])))
                count=max(1,math.ceil(float(np.linalg.norm(T[:3,3]-start_p))/.025))
                held_points=[previous.copy()]
                for u in np.linspace(0,1,count+1)[1:]:
                    previous=r.solve_pair({side:(start_p+u*(T[:3,3]-start_p),rotations(u).as_matrix())},previous)
                    previous[7 if side=='left' else 15]=c.gripper_close_m
                    held_points.append(previous.copy())
                middle=np.array(free_points[-1],float)
                cols=np.arange(0,7) if side=='left' else np.arange(8,15)
                if not free_first:
                    middle[cols]+=.3*(held_points[-1][cols]-middle[cols])
                points=np.stack([points[0],middle,held_points[len(held_points)//2],held_points[-1]])
            except Fault as rejected:
                if not free_first:raise
                points=original_points_after_rejection(rejected,'ordered_waypoints')
                free_goal=original_free_goal;free_first=False
                for point in points:point[7 if side=='left' else 15]=c.gripper_close_m
                points=completion_free_open_points(r,points,side,
                    free_retreat=free_retreat,withdraw_free=False)
        normal_check = None
        if command_reference:
            normal_check = lambda path: supported_normal_path_rejection(
                r, path, side, normal_start_z, float(T[2,3]))
            machine.log.event('supported_command_reference',side=side,
                start_z_m=normal_start_z,end_z_m=float(T[2,3]),normal_tolerance_m=.00025,
                validation_samples=201,shortcut_enabled=not (withdraw_free or free_first),
                qualification='command_geometry_only_original_physical_support_guards_required')
        def path_check(path):
            if normal_check is not None:
                reason=normal_check(path)
                if reason is not None:return reason
            if free_first:
                return completion_free_first_path_rejection(
                    machine,path,operation,free,side,actual,original_free_goal[1])
            return None
        try:
            if (withdraw_free or free_first) and c.push_withdraw_path_search_enabled:
                planned=plan_withdraw_path(r,points,free_points[-1],held_points[-1],cols,
                                          available=available,extra_path_check=path_check)
            else:
                planned=plan(r,points,available=available,minimum=min(2.4,available-.05),
                             allow_shortcut=not (withdraw_free or free_first),extra_path_check=path_check)
        except Fault as rejected:
            if not free_first or rejected.code!='primitive_path_infeasible':
                raise
            # No motion has occurred; retain the original simultaneous path
            # when the new geometry candidate cannot pass whole-path review.
            r.trace.event('completion_push_free_first_fallback',reason=rejected.code,
                detail=rejected.detail,stage='whole_path',
                qualification='zero_motion_original_reference_replanned')
            free_goal=original_free_goal
            goals[free]=(free_goal[1],free_goal[2])
            points=r.cartesian(goals,wrist=True,preview_only=True,start_from_command=command_reference)
            for point in points:point[7 if side=='left' else 15]=c.gripper_close_m
            points=completion_free_open_points(r,points,side,
                free_retreat=free_retreat,withdraw_free=False)
            planned=plan(r,points,available=available,minimum=min(2.4,available-.05),
                         allow_shortcut=True,extra_path_check=normal_check)
        if c.push_use_full_budget:
            planned=retime_push_to_budget(r,planned,available)
        _execute_push_reference(machine, planned, operation, side, position, R, relation,
                                free_goal, float(T[2,3]), separation=separation)
        def accepted(x,criteria=c.criteria):
            pose=x['tray_pose'][tray];a,_=quat_yaw_tilt(pose[3:])
            geometry=(not machine.g.blockers(x['tray_pose'],tray,pose[:3],a,.085)) if separation else (
                np.linalg.norm(pose[:2]-operation.destination[:2])<=criteria.position_m and
                abs(wrap_angle(a-operation.yaw,machine.g.period))<=np.deg2rad(criteria.yaw_deg))
            # Final neighbour clearance is checked after measured release in
            # Machine.verify_operation; a loaded gripper elastically biases yaw.
            if free_retreat:
                geometry=geometry and x['gripper_contact_force'][tray,1 if side=='left' else 0]<=criteria.contact_n
            return geometry and x['table_contact'][tray]>0 and x['gripper_contact_force'][tray,0 if side=='left' else 1]>criteria.contact_n
        from .acceptance_profile import completion_criteria, predicate_with_strict_evidence
        task_criteria=completion_criteria(c)
        original_accepted=accepted
        accepted=predicate_with_strict_evidence(r,original_accepted,
            lambda x:original_accepted(x,task_criteria),'primitive_push_outside_strict_contract',
            lambda x:{'tray':tray,'pose':x['tray_pose'][tray].tolist(),
                      'destination':operation.destination.tolist(),'yaw_target_rad':float(operation.yaw)})
        settle(r,accepted,c.primitive_settle_s)
