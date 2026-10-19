from dataclasses import replace
from types import SimpleNamespace
import numpy as np
import pytest
from r1pro_teleop.airport_fsm.contracts import Config,Fault,State
from r1pro_teleop.airport_fsm.primitives import action,plan,execute
from r1pro_teleop.airport_fsm.runtime import Runtime


@pytest.mark.parametrize('updates',[{'primitive_seconds':3.01},{'primitive_lift_m':.149},{'primitive_lift_m':.201},
    {'primitive_push_compensation_m':.041},{'primitive_push_compensation_m':-.001}])
def test_invalid_primitive_contract(updates):
    with pytest.raises(ValueError):replace(Config(),**updates).validate()


def fake_planner():
    return SimpleNamespace(cfg=Config(),m=SimpleNamespace(jnt_range=np.tile([-20.,20.],(14,1))),
        jids=np.arange(14),v=np.ones(16),a=np.ones(16)*3,j=np.ones(16)*30,
        _path_rejection=lambda *a:None,audit_online_reference=lambda *a:None)


def test_whole_reference_is_bounded_and_has_no_interior_stop():
    r=fake_planner();p=np.zeros((4,16));p[:,0]=[0,.05,.1,.15]
    path,frames=plan(r,p,available=2.85)
    duration=frames/20
    assert duration<=2.85
    for u in np.linspace(.05,.95,101):
        q,v,a,j=path.evaluate(u,duration)
        assert np.max(abs(v))<=1.+1e-5 and np.max(abs(a))<=3.+1e-5 and np.max(abs(j))<=30.+1e-5
        assert v[0]>0
    for u in (0,1):
        assert np.max(abs(path.evaluate(u,duration)[1]))<1e-8
        assert np.max(abs(path.evaluate(u,duration)[2]))<1e-8


def test_infeasible_motion_rejected_before_execution():
    p=np.zeros((2,16));p[1,0]=5.
    with pytest.raises(Fault,match='primitive_path_infeasible'):plan(fake_planner(),p,available=3.)


def test_deadline_counts_complete_action_and_does_not_claim_success():
    events=[];r=SimpleNamespace(steps=0,cfg=Config())
    m=SimpleNamespace(r=r,c=Config(),log=SimpleNamespace(event=lambda name,**kw:events.append((name,kw))))
    with pytest.raises(Fault,match='primitive_deadline_exceeded'):
        with action(m,'lift'):
            assert r.primitive_deadline_step==60
            r.steps=60
            Runtime.tick(r)  # Deadline must be checked before touching simulation.
    assert r.primitive_deadline_step is None
    assert [x[0] for x in events]==['primitive_start','primitive_failed']
    assert events[-1][1]['duration_s']==3.


def test_contact_confirmation_overlaps_motion_without_extra_waits():
    from r1pro_teleop.airport_fsm.trajectory import BlendedJointPath
    path=BlendedJointPath(np.zeros((2,16)),1.,3.,30.,minimum_seconds=.5)
    r=SimpleNamespace(cfg=Config(),steps=0,primitive_deadline_step=60,
        sim=SimpleNamespace(target=np.zeros(16)),trace=SimpleNamespace(event=lambda *a,**k:None))
    def tick():r.steps+=1
    r.tick=tick;r.observation=lambda:{'contact':r.steps>=9}
    assert execute(r,(path,10),lambda x:x['contact'])==2
    assert r.steps==10


def test_zero_lift_bias_is_valid():
    assert Config(primitive_lift_compensation_m=0.).validate().primitive_lift_compensation_m==0.


def test_retained_hand_does_not_tighten_released_hand_ik():
    r=SimpleNamespace(cfg=Config(fixed_primitives=True),holding=None,retained_contact=(0,'right'),fsm_state=State.ADJUST_TRAY)
    assert Runtime._ik_tolerances(r,'right')[0]==.012
    assert Runtime._ik_tolerances(r,'left')[0]==r.cfg.ik_position_tolerance_m
    r.fsm_state=State.APPROACH_TRAY
    assert Runtime._ik_tolerances(r,'left')[0]==.012
    r.holding=0;r.retained_contact=None
    assert Runtime._ik_tolerances(r,'left')[0]==.022
    assert Runtime._ik_tolerances(r,'right')[0]==.022


@pytest.mark.parametrize('gap_ok',[False,True])
def test_final_release_verification_includes_neighbour_gap(monkeypatch,gap_ok):
    from r1pro_teleop.airport_fsm.machine import Machine
    from r1pro_teleop.airport_fsm import geometry
    calls=[]
    def gap(*args, **kwargs):
        assert kwargs == {'require_full_footprint': True, 'use_actual_gap': False}
        assert args[-1] is machine.c.criteria
        calls.append(True)
        return gap_ok
    monkeypatch.setattr(geometry,'slot_geometry_ready',gap)
    evidence={'tray_pose':np.array([[0.,0.,.8,1.,0.,0.,0.]]),
              'table_contact':np.array([1]),'gripper_contact_force':np.zeros((1,2))}
    def wait(seconds,predicate,stable):
        predicate(evidence)  # First sample initializes measured speed.
        return predicate(evidence)
    machine=SimpleNamespace(c=Config(fixed_primitives=True),g=SimpleNamespace(period=np.pi),
        scheduler=SimpleNamespace(mapping=[0]),r=SimpleNamespace(wait=wait),transition=lambda *a,**k:None)
    operation=SimpleNamespace(tray=0,slot=0,destination=np.array([0.,0.,.8]),yaw=0.,temporary=False)
    assert Machine.verify_operation(machine,operation)==gap_ok
    assert calls
