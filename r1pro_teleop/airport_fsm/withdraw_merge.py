"""One default-off structural retry after all existing duration rejections."""
import numpy as np
from .contracts import Fault


def merged_clearance_points(points,held_columns):
    """Keep the exact real IK midpoint only when it has identical free clearance."""
    points=np.asarray(points,float);held=np.asarray(held_columns)
    if points.shape!=(4,16) or not np.isfinite(points).all():return None
    if not (np.array_equal(held,np.arange(7)) or np.array_equal(held,np.arange(8,15))):return None
    free=np.array([i for i in range(16) if i not in held])
    # Include both gripper references in equality: no release changes are hidden.
    if not np.array_equal(points[1,free],points[2,free]):return None
    return points[[0,2,3]].copy()


def planning_snapshot(r):
    """Capture physical integration state and execution references when available."""
    if not all(hasattr(r,key) for key in ('steps','d','sim','primitive_deadline_step')):return None
    if not all(hasattr(r.d,key) for key in ('time','qpos','qvel','act','ctrl')):return None
    if not all(hasattr(r.sim,key) for key in ('target','base_target')):return None
    snapshot=dict(steps=r.steps,time=float(r.d.time),primitive_deadline_step=r.primitive_deadline_step,
                  target=np.array(r.sim.target,copy=True),base_target=np.array(r.sim.base_target,copy=True))
    for key in ('qpos','qvel','act','ctrl','qacc_warmstart','qfrc_applied','xfrc_applied','mocap_pos','mocap_quat','userdata'):
        if hasattr(r.d,key):snapshot[key]=np.array(getattr(r.d,key),copy=True)
    if all(hasattr(r,key) for key in ('mj','m','integration_size','integration_spec')):
        state=np.empty(r.integration_size,dtype=np.float64)
        r.mj.mj_getState(r.m,r.d,state,r.integration_spec)
        snapshot['mujoco_integration']=state
    return snapshot


def check_unchanged(r,before):
    after=planning_snapshot(r)
    if before is None or after is None:return False
    changes=[key for key in before.keys()|after.keys()
             if key not in before or key not in after or not np.array_equal(before[key],after[key])]
    if changes:
        detail=dict(state_change=sorted(changes),qualification='no_physics_allowed_during_withdraw_planning')
        r.trace.event('push_withdraw_planning_invariant',**detail)
        raise Fault('withdraw_planning_state_changed',detail,recoverable=False)
    return True


def duration_only(detail):
    candidates=detail.get('candidates',[]) if isinstance(detail,dict) else []
    return bool(candidates) and all(x.get('reason')=='duration' for x in candidates)


def try_merge(r,points,held_columns,original,attempts,before,options,planner):
    """Exactly one geometric candidate, with the original planner/check callback."""
    if (len(attempts)!=2 or not duration_only(original.detail) or
            any(x.get('reason')!='primitive_path_infeasible' or not duration_only(x.get('detail')) for x in attempts)):
        return None
    state_known=check_unchanged(r,before)
    candidate=merged_clearance_points(points,held_columns)
    if candidate is None or not state_known:
        r.trace.event('push_withdraw_merge_fallback',accepted=False,reason='structure_or_planning_state_changed')
        return None
    try:
        planned=planner(r,candidate,**options)
    except (Fault,ValueError) as exc:
        check_unchanged(r,before)
        r.trace.event('push_withdraw_merge_fallback',accepted=False,reason=getattr(exc,'code',type(exc).__name__),
            detail=getattr(exc,'detail',str(exc)),original_failure=original.detail,retained_indices=[0,2,3],maximum_alternatives=1)
        return None
    check_unchanged(r,before)
    r.trace.event('push_withdraw_merge_fallback',accepted=True,original_failure=original.detail,
        retained_indices=[0,2,3],maximum_alternatives=1,available_s=options['available'],
        qualification='identical_free_clearance_real_ik_midpoint_original_guards_and_budget')
    return planned
