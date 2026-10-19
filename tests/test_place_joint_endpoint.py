from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest

from r1pro_teleop.airport_fsm import primitives
from r1pro_teleop.airport_fsm.contracts import Fault, State
from r1pro_teleop.airport_fsm.withdraw_merge import planning_snapshot
from test_physical_preview import machine


def configured(machine):
    cfg=replace(machine.c,acceptance_profile='completion_first',
        retained_support_integer_clock_enabled=True,
        completion_place_ik_fallback_enabled=True,
        completion_place_private_joint_endpoint_enabled=True)
    machine.c=machine.r.cfg=cfg
    r=machine.r;r.holding=0;r.retained_contact=None
    r.grasp_rel={'left':np.eye(4),'right':np.eye(4)}
    r.fsm_state=State.PLACE_TRAY;r.primitive_deadline_step=r.steps+100
    assert cfg.validate() is cfg
    return r


def test_private_endpoint_scope_goals_and_current_command_seed(machine,monkeypatch):
    r=configured(machine);start=r.sim.target.copy();before=planning_snapshot(r)
    target=r.observation()['tray_pose'][0,:3].copy();yaw=0.
    attempts=[]
    def fail_cartesian(*args):
        attempts.append('cartesian')
        raise Fault('coupled_ik_unreachable',{'original':True})
    monkeypatch.setattr(primitives,'object_points',fail_cartesian)
    def endpoint(goals,seed=None):
        attempts.append('endpoint')
        assert set(goals)=={'left','right'}
        np.testing.assert_array_equal(seed,start)
        result=start.copy();result[0]+=.02
        return result
    monkeypatch.setattr(r,'solve_pair',endpoint)
    with pytest.raises(Fault,match='coupled_ik_unreachable'):
        primitives._private_place_descent_points(r,target,yaw)
    assert attempts==['cartesian']
    r._place_private_joint_endpoint_enabled=True
    points,original=primitives._private_place_descent_points(r,target,yaw)
    assert attempts==['cartesian','cartesian','endpoint']
    assert original.code=='coupled_ik_unreachable'
    np.testing.assert_array_equal(points[0],start)
    assert points.shape==(2,16) and points[1,0]==start[0]+.02
    assert points[1,7]==r.cfg.gripper_close_m and points[1,15]==r.cfg.gripper_close_m
    for key,value in before.items():np.testing.assert_array_equal(planning_snapshot(r)[key],value)


@pytest.mark.parametrize('descent_rejected',[False,True])
def test_joint_endpoint_runs_original_full_path_planner_or_preserves_fault(
        machine,monkeypatch,descent_rejected):
    r=configured(machine);r._place_private_joint_endpoint_enabled=True
    start=r.sim.target.copy();r.solve_pair=lambda goals,seed=None:start.copy()
    def fail_cartesian(*args):raise Fault('coupled_ik_unreachable',{'original':True})
    monkeypatch.setattr(primitives,'object_points',fail_cartesian)
    monkeypatch.setattr(primitives,'release_endpoint',lambda start,*args,**kw:np.asarray(start).copy())
    plans=[]
    def checked_plan(runtime,points,*,available,**kwargs):
        value=np.asarray(points);plans.append((value.copy(),available,kwargs))
        if len(plans)==2 and descent_rejected:raise Fault('cartesian_collision_or_wrist')
        return ('original_checked_path',4)
    monkeypatch.setattr(primitives,'plan',checked_plan)
    e=r.observation();op=SimpleNamespace(tray=0,yaw=0.)
    staged=e['tray_pose'][0,:3].copy()
    if descent_rejected:
        with pytest.raises(Fault,match='coupled_ik_unreachable')as exc:
            primitives._plan_place_descent(machine,op,staged,e,.8,False,None,['left','right'],False)
        assert exc.value.detail=={'original':True}
    else:
        result=primitives._plan_place_descent(machine,op,staged,e,.8,False,None,
            ['left','right'],False)
        assert result==(('original_checked_path',4),('original_checked_path',4))
    assert len(plans)==2
    assert plans[0][0].shape==(2,16) and plans[1][0].shape==(2,16)
    assert plans[1][2]['allow_shortcut'] is True
    np.testing.assert_array_equal(plans[1][0][0],start)
