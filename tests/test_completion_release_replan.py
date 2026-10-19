from types import SimpleNamespace
from dataclasses import replace
import numpy as np
import pytest
from r1pro_teleop.airport_fsm import primitives as p
from r1pro_teleop.airport_fsm.contracts import Config, Fault


def fixture(monkeypatch, **updates):
    cfg=replace(Config(),acceptance_profile='completion_first',completion_release_replan_enabled=True,**updates)
    target=np.arange(16,dtype=float)/100;target[[7,15]]=[.037,0.]
    measured=target.copy();measured[[7,15]]=[.046,.018]
    obs={'gripper_contact_force':np.array([[4.3,14.]]),'table_contact':np.array([4])}
    events=[];calls=[]
    r=SimpleNamespace(cfg=cfg,sim=SimpleNamespace(target=target,state=lambda:measured),
        observation=lambda:obs,steps=20,primitive_deadline_step=40,
        trace=SimpleNamespace(event=lambda name,**kw:events.append((name,kw))))
    def plan(r,points,**kw):
        calls.append((np.array(points),kw));return (points,10)
    def execute(r,planned,predicate):
        r.steps+=planned[1];r.sim.target=planned[0][-1].copy()
        obs['gripper_contact_force'][0,0]=.3
        assert predicate(obs)
        return 2
    monkeypatch.setattr(p,'plan',plan);monkeypatch.setattr(p,'execute',execute)
    return r,events,calls


def invoke(r,consecutive=0,geometry=True):
    return p.replan_supported_release(r,0,['left'],lambda x:x['gripper_contact_force'][0,0]<=.5,
                                      lambda x:geometry and x['table_contact'][0]>0,consecutive)


def test_schema():
    assert Config().completion_release_replan_enabled is False
    with pytest.raises(ValueError,match='requires completion_first'):
        replace(Config(),completion_release_replan_enabled=True).validate()
    for value in [0,1,'true',None]:
        with pytest.raises(ValueError,match='must be boolean'):
            replace(Config(),completion_release_replan_enabled=value).validate()


def test_held_orientation_schema_bounds():
    assert Config().completion_held_ik_orientation_tolerance_rad==.05
    for value in [.05,.08,.12]:
        replace(Config(),completion_held_ik_orientation_tolerance_rad=value).validate()
    for value in [True,False,.049,.121,float('inf'),float('nan'),'.1']:
        with pytest.raises(ValueError,match='completion_held_ik_orientation_tolerance_rad'):
            replace(Config(),completion_held_ik_orientation_tolerance_rad=value).validate()


@pytest.mark.parametrize('mode',['off','strict','already_verified'])
def test_old_paths_do_not_read_or_plan(monkeypatch,mode):
    r,events,calls=fixture(monkeypatch)
    if mode=='off':r.cfg=replace(r.cfg,completion_release_replan_enabled=False)
    if mode=='strict':r.cfg=replace(r.cfg,acceptance_profile='strict')
    r.observation=lambda:pytest.fail('old path must not inspect extra observation')
    assert invoke(r,2 if mode=='already_verified' else 0)==(2 if mode=='already_verified' else 0)
    assert not events and not calls


def test_measured_proposal_keeps_arm_retained_side_and_deadline(monkeypatch):
    r,events,calls=fixture(monkeypatch);before=r.sim.target.copy()
    assert invoke(r)==2
    points,kw=calls[0]
    assert points[1,7]==pytest.approx(.066)
    np.testing.assert_array_equal(points[1,np.arange(16)!=7],before[np.arange(16)!=7])
    assert kw=={'available':.9,'allow_shortcut':False}
    assert r.primitive_deadline_step==40 and r.steps==30
    assert events[0][1]['accepted'] and events[-1][1]['force'][0]<.5


@pytest.mark.parametrize('reason',['geometry','support','force_free','budget','saturated'])
def test_ineligible_keeps_original_target(monkeypatch,reason):
    r,events,calls=fixture(monkeypatch)
    if reason=='support':r.observation()['table_contact'][0]=0
    if reason=='force_free':r.observation()['gripper_contact_force'][0,0]=.5
    if reason=='budget':r.primitive_deadline_step=22
    if reason=='saturated':r.sim.target[7]=r.cfg.gripper_open_m
    original=r.sim.target.copy()
    assert invoke(r,geometry=reason!='geometry')==0
    assert not calls and not events[-1][1]['accepted'] and r.steps==20
    np.testing.assert_array_equal(r.sim.target,original)


def test_planning_rejection_falls_back_but_execute_fault_is_hard(monkeypatch):
    r,events,calls=fixture(monkeypatch);original=r.sim.target.copy()
    def fail_plan(*a,**kw):raise Fault('primitive_path_infeasible',{'reason':'duration'})
    monkeypatch.setattr(p,'plan',fail_plan)
    assert invoke(r)==0
    np.testing.assert_array_equal(r.sim.target,original)
    assert events[-1][1]['reason']=='primitive_path_infeasible'
    r,events,calls=fixture(monkeypatch)
    def fail_execute(*a,**kw):raise Fault('illegal_collision')
    monkeypatch.setattr(p,'execute',fail_execute)
    with pytest.raises(Fault,match='illegal_collision'):invoke(r)


def test_already_free_release_hand_does_not_open_again(monkeypatch):
    r,events,calls=fixture(monkeypatch)
    r.observation()['gripper_contact_force'][0]=[4.,0.]
    old=r.sim.target.copy()
    p.replan_supported_release(r,0,['left','right'],lambda x:True,lambda x:True,0)
    assert calls[0][0][1,15]==old[15]


def test_real_planner_runs_path_and_dynamic_checks(monkeypatch):
    actual_plan=p.plan
    r,events,calls=fixture(monkeypatch)
    monkeypatch.setattr(p,'plan',actual_plan)
    r.m=SimpleNamespace(jnt_range=np.tile([-20.,20.],(14,1)));r.jids=np.arange(14)
    r.v=np.ones(16);r.a=np.ones(16)*3;r.j=np.ones(16)*30
    checks=[]
    r._path_rejection=lambda *a:checks.append('path') or {'reason':'collision_or_wrist'}
    r.audit_online_reference=lambda *a:checks.append('dynamics')
    assert invoke(r)==0 and 'path' in checks
    r._path_rejection=lambda *a:checks.append('path') or None
    monkeypatch.setattr(p,'execute',lambda *a:0)
    assert invoke(r)==0 and checks.count('dynamics')==21
