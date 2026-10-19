from dataclasses import replace
from contextlib import contextmanager
from types import SimpleNamespace

import numpy as np
import pytest

from r1pro_teleop.airport_fsm import primitives
from r1pro_teleop.airport_fsm.contracts import Config, Fault, State
from r1pro_teleop.airport_fsm.withdraw_merge import planning_snapshot
from test_place_orientation_fallback import enabled
from test_physical_preview import machine


def approximate(machine):
    r=enabled(machine)
    machine.c=r.cfg=replace(machine.c,approximate_completion_enabled=True)
    r.primitive_deadline_step=r.steps+30
    return r


def test_approximate_place_extends_search_before_immutable_snapshot(machine,monkeypatch):
    r=approximate(machine)
    selected=(('descent',12),('release',8))
    calls=[]
    def prepare(candidate,*args):
        calls.append(candidate.r is r)
        if candidate.r is r:raise Fault('coupled_ik_unreachable')
        return selected
    monkeypatch.setattr(primitives,'_plan_place_descent',prepare)
    result=primitives._plan_place_original_then_relaxed(machine,SimpleNamespace(tray=0),
        np.zeros(3),None,.8,True,None,['left','right'],False,None)
    assert result is selected and calls==[True,False]
    assert r.primitive_deadline_step>=r.steps+120*r.cfg.fps


@pytest.mark.parametrize('change',('qpos','target'))
def test_approximate_place_still_rejects_physical_or_command_change(machine,monkeypatch,change):
    r=approximate(machine)
    def prepare(candidate,*args):
        if change=='qpos':r.d.qpos[0]+=.001
        else:r.sim.target[0]+=.001
        raise Fault('coupled_ik_unreachable')
    monkeypatch.setattr(primitives,'_plan_place_descent',prepare)
    with pytest.raises(Fault,match='withdraw_planning_state_changed'):
        primitives._plan_place_original_then_relaxed(machine,SimpleNamespace(tray=0),
            np.zeros(3),None,.8,True,None,['left','right'],False,None)


def test_near_table_release_requires_gap_footprint_and_bilateral_force():
    cfg=replace(Config(acceptance_profile='completion_first',
        retained_support_integer_clock_enabled=True),
        completion_release_gap_m=.02,completion_position_m=.1,
        completion_yaw_deg=12.,approximate_completion_enabled=True)
    geometry=SimpleNamespace(period=2*np.pi,sizes=[np.array([.3,.2,.04])],
        support_table=lambda p:'front0',footprint_supported=lambda *a,**k:True,
        blockers=lambda *a,**k:[])
    m=SimpleNamespace(r=SimpleNamespace(cfg=cfg),c=cfg,g=geometry)
    operation=SimpleNamespace(tray=0,yaw=0.)
    staged=np.array([0.,0.,.82])
    e=dict(tray_pose=np.array([[0.,0.,.82,1.,0.,0.,0.]]),
        min_z=np.array([.815]),gripper_contact_force=np.array([[100.,100.]]))
    accepted,_=primitives._near_table_release_ready(m,operation,staged,.8,e)
    assert accepted
    e['min_z'][0]=.821
    assert not primitives._near_table_release_ready(m,operation,staged,.8,e)[0]
    e['min_z'][0]=.815;e['gripper_contact_force'][0,1]=0.
    assert not primitives._near_table_release_ready(m,operation,staged,.8,e)[0]
    e['gripper_contact_force'][0,1]=100.;geometry.footprint_supported=lambda *a,**k:False
    assert not primitives._near_table_release_ready(m,operation,staged,.8,e)[0]


def test_zero_shift_ik_rejection_selects_private_combined_reference(monkeypatch):
    from r1pro_teleop.airport_fsm import placement_reachability
    cfg=replace(Config(acceptance_profile='completion_first',
        retained_support_integer_clock_enabled=True),
        completion_place_zero_shift_combined_fallback_enabled=True)
    events=[]
    pose=np.array([[.85,-.17,.91,1.,0.,0.,0.]])
    sim=SimpleNamespace(base_state=lambda:np.zeros(3))
    r=SimpleNamespace(cfg=cfg,holding=0,retained_contact=None,
        primitive_lift_xy_shift_m=0.,observation=lambda:{'tray_pose':pose},sim=sim)
    g=SimpleNamespace(support_table=lambda p:'front',tables={'front':{'dimensions_m':[1.,1.,.8]}},period=2*np.pi)
    m=SimpleNamespace(r=r,c=cfg,g=g,log=SimpleNamespace(event=lambda name,**d:events.append((name,d))))
    operation=SimpleNamespace(tray=0,destination=np.array([.85,-.17,.8]),yaw=0.)
    monkeypatch.setattr(placement_reachability,'loaded_planning_copy',lambda runtime:runtime)
    monkeypatch.setattr(placement_reachability,'_qualify_combined_descent',
        lambda *a:{'descent_frames':45,'release_frames':16})
    monkeypatch.setattr(primitives,'continue_loaded_reference',lambda runtime:None)
    monkeypatch.setattr(primitives,'object_points',lambda *a:(_ for _ in ()).throw(Fault('coupled_ik_unreachable')))
    @contextmanager
    def action_probe(machine,name,**kwargs):
        events.append(('selected_action',{'name':name}))
        raise RuntimeError('selected')
        yield
    monkeypatch.setattr(primitives,'action',action_probe)
    with pytest.raises(RuntimeError,match='selected'):
        primitives.place(m,operation,np.array([.85,-.17,.8]))
    assert ('selected_action',{'name':'place'}) in events
    assert any(name=='transport_align_combined_fallback' and detail['selected'] for name,detail in events)


@pytest.mark.parametrize('planned,nominal_enabled,expected',
    [(40,True,58),(80,True,80),(40,False,40)])
def test_approximate_retime_preserves_nominal_without_using_search_window(
        planned,nominal_enabled,expected):
    cfg=replace(Config(acceptance_profile='completion_first',
        retained_support_integer_clock_enabled=True),
        approximate_completion_enabled=True,primitive_settle_s=.1,
        completion_preserve_nominal_timing_enabled=nominal_enabled)
    events=[];audits=[]
    path=SimpleNamespace(evaluate=lambda u,t:(np.zeros(16),)*4)
    r=SimpleNamespace(cfg=cfg,trace=SimpleNamespace(event=lambda name,**kw:events.append((name,kw))),
        audit_online_reference=lambda *args:audits.append(args))
    assert primitives.retime_push_to_budget(r,(path,planned),119.9)==(path,expected)
    assert len(audits)==(21 if expected>planned else 0)
    assert not any(detail.get('effective_frames',0)>expected for _,detail in events)
    if nominal_enabled:
        assert events[0][0]=='primitive_nominal_timing_policy'
        assert events[0][1]['effective_frames']==expected


def _collision_fallback_args(machine):
    operation=SimpleNamespace(tray=0)
    return (machine,operation,np.zeros(3),None,.8,True,None,
        ['left','right'],False,None,0.,Fault('cartesian_collision_or_wrist'))


def test_place_collision_fallback_private_then_live_complete_replan(machine,monkeypatch):
    r=approximate(machine);r.fsm_state=State.PLACE_TRAY
    before=planning_snapshot(r)
    calls=[];selected=(('descent',12),('release',8))
    def whole_path(candidate,*args):
        calls.append((candidate.r is r,bool(getattr(candidate.r,'_approximate_planning_relaxed',False))))
        return selected
    monkeypatch.setattr(primitives,'_plan_place_original_then_relaxed',whole_path)
    result=primitives._plan_place_approximate_collision_fallback(*_collision_fallback_args(machine))
    assert result is selected and calls==[(False,True),(True,True)]
    assert not r._approximate_planning_relaxed
    assert r.soft_guard_violation_by_code['primitive_place_collision_planning_fallback']==1
    after=planning_snapshot(r)
    for key in before:
        if key=='primitive_deadline_step':continue
        np.testing.assert_array_equal(after[key],before[key])


def test_place_collision_fallback_rejects_private_path_without_live_motion(machine,monkeypatch):
    r=approximate(machine);r.fsm_state=State.PLACE_TRAY
    calls=[]
    def reject(candidate,*args):
        calls.append(candidate.r is r)
        raise Fault('primitive_path_infeasible')
    monkeypatch.setattr(primitives,'_plan_place_original_then_relaxed',reject)
    assert primitives._plan_place_approximate_collision_fallback(*_collision_fallback_args(machine)) is None
    assert calls==[False] and not getattr(r,'_approximate_planning_relaxed',False)
    assert r.soft_guard_violation_by_code.get('primitive_place_collision_planning_fallback',0)==0


def test_place_collision_fallback_excludes_initial_grasp(machine,monkeypatch):
    r=approximate(machine);r.fsm_state=State.GRASP_TRAY
    monkeypatch.setattr(primitives,'_plan_place_original_then_relaxed',
        lambda *args:pytest.fail('wrong planning scope'))
    assert primitives._plan_place_approximate_collision_fallback(*_collision_fallback_args(machine)) is None
    assert not getattr(r,'_approximate_planning_relaxed',False)


def test_place_collision_fallback_detects_live_command_mutation(machine,monkeypatch):
    r=approximate(machine);r.fsm_state=State.PLACE_TRAY
    selected=(('descent',12),('release',8))
    def corrupt(candidate,*args):
        if candidate.r is r:r.sim.target[0]+=.001
        return selected
    monkeypatch.setattr(primitives,'_plan_place_original_then_relaxed',corrupt)
    with pytest.raises(Fault,match='withdraw_planning_state_changed'):
        primitives._plan_place_approximate_collision_fallback(*_collision_fallback_args(machine))
    assert not r._approximate_planning_relaxed
