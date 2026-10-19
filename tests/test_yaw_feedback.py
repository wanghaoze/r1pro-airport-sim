"""Bounded suffix math and accepted/rejected execution timing contracts."""
from types import SimpleNamespace
from dataclasses import replace
import numpy as np
import pytest
from r1pro_teleop.airport_fsm.contracts import Config,Fault
from r1pro_teleop.airport_fsm.yaw_feedback import FixedDurationQuintic,execute_feedback


def test_suffix_c2_extrema_and_vectorized_substep_sampling():
    q=np.array([.1,-.2]);v=np.array([.3,-.4]);a=np.array([-.6,.2]);end=np.array([.7,.1])
    p=FixedDurationQuintic(q,v,a,end,1.25)
    for actual,expected in zip(p.evaluate(0)[:3],(q,v,a)):np.testing.assert_allclose(actual,expected,atol=1e-13)
    for actual,expected in zip(p.evaluate(1)[:3],(end,np.zeros(2),np.zeros(2))):np.testing.assert_allclose(actual,expected,atol=1e-12)
    values=p.evaluate(np.linspace(0,1,10001))
    for order in range(4):
        low,high=p.extrema[order]
        assert np.all(values[order]>=low-1e-12) and np.all(values[order]<=high+1e-12)
        np.testing.assert_allclose(values[order].min(0),low,atol=1e-6)
        np.testing.assert_allclose(values[order].max(0),high,atol=1e-6)
    with pytest.raises(ValueError):p.evaluate(.5,2)


@pytest.mark.parametrize('field,value',[('push_yaw_feedback_enabled',1),('push_yaw_feedback_seconds',float('nan')),
    ('push_yaw_feedback_seconds',0),('push_yaw_feedback_seconds',2.51),('push_yaw_feedback_gain',-1),
    ('push_yaw_feedback_gain',2.01),('push_yaw_feedback_gain',True),('push_yaw_feedback_max_deg',1.51),
    ('push_yaw_feedback_max_deg',float('inf')),('push_yaw_feedback_max_deg','1')])
def test_invalid_feedback_configuration_rejected(field,value):
    with pytest.raises(ValueError):Config(**{field:value}).validate()


def test_default_off_and_zero_correction_configuration_valid():
    assert Config().validate().push_yaw_feedback_enabled is False
    Config(push_yaw_feedback_gain=0.,push_yaw_feedback_max_deg=0.).validate()


def fixture_runtime(substep=False,reject=None,seconds=1.5):
    cfg=Config(push_yaw_feedback_enabled=True,push_yaw_feedback_seconds=seconds,substep_control_enabled=substep)
    q=np.zeros(16);end=q.copy();end[0]=.1
    path=FixedDurationQuintic(q,q,q,end,2.75)
    events=[];commands=[];substeps=[];audits=[];goals=[]
    r=SimpleNamespace(cfg=cfg,steps=0,primitive_deadline_step=60,sim=SimpleNamespace(target=q.copy(),nstep=25),
        trace=SimpleNamespace(event=lambda name,**kw:events.append(dict(event=name,**kw))),
        m=SimpleNamespace(jnt_range=np.tile([-3.,3.],(14,1))),jids=np.arange(14),v=np.ones(16)*4,a=np.ones(16)*8,j=np.ones(16)*40)
    def tick(**kwargs):
        commands.append(r.sim.target.copy());r.steps+=1
        if kwargs:substeps.append(kwargs['substep_targets'].copy())
    r.tick=tick
    yaw=np.deg2rad(.8);pose=np.array([[0,0,.8,np.cos(yaw/2),0,0,np.sin(yaw/2)]])
    r.observation=lambda:{'tray_pose':pose}
    def solve(targets,seed):
        goals.append(targets)
        if reject=='ik':raise Fault('coupled_ik_failed')
        answer=seed.copy();answer[0]+=.01
        if reject=='derivative':answer[0]=2.8
        return answer
    r.solve_pair=solve
    r._path_rejection=lambda *args:{'reason':'camera_guard'} if reject=='path' else None
    def audit(*args):
        audits.append(args)
        if reject=='effort':raise Fault('online_reference_effort_limit')
    r.audit_online_reference=audit
    normal=lambda path:{'reason':'supported_normal_reference_excursion'} if reject=='normal' else None
    machine=SimpleNamespace(r=r,g=SimpleNamespace(period=2*np.pi))
    op=SimpleNamespace(tray=0,yaw=0.)
    return machine,path,op,normal,events,commands,substeps,audits,goals


@pytest.mark.parametrize('substep',[False,True])
@pytest.mark.parametrize('reject',[None,'ik','derivative','path','normal','effort'])
def test_feedback_keeps_budget_and_rejected_suffix_is_exact_original(substep,reject):
    m,p,op,normal,events,commands,substeps,audits,goals=fixture_runtime(substep,reject)
    execute_feedback(m,(p,55),op,'right',np.array([0,0,.8]),np.eye(3),np.eye(4),None,normal)
    assert m.r.steps==55 and len(commands)==55
    event=next(x for x in events if x['event']=='push_yaw_feedback_suffix')
    assert event['accepted']==(reject is None) and event['remaining_s']==1.25
    assert event['command_yaw_correction_deg']==pytest.approx(-1.5)
    if reject is not None:
        expected=[p.evaluate(i/55,2.75)[0] for i in range(1,56)]
        np.testing.assert_allclose(commands,expected,atol=1e-8 if substep else 1e-14)
    else:
        assert len(audits)>=201
        assert max(event['boundary_errors'])<1e-12
        assert max(event['terminal_errors'])<1e-12
        assert commands[-1][0]==pytest.approx(.11)
    if substep:
        assert len(substeps)==55 and all(x.shape==(25,16) for x in substeps)


def test_feedback_short_path_skips_without_extending_motion():
    m,_,op,normal,events,commands,*_=fixture_runtime()
    q=np.zeros(16);p=FixedDurationQuintic(q,q,q,q,.5)
    execute_feedback(m,(p,10),op,'right',np.array([0,0,.8]),np.eye(3),np.eye(4),None,normal)
    assert m.r.steps==10
    assert events[0]['event']=='push_yaw_feedback_skipped'


def test_zero_gain_preserves_original_curve_exactly():
    m,p,op,normal,events,commands,*_=fixture_runtime()
    m.r.cfg=replace(m.r.cfg,push_yaw_feedback_gain=0.)
    execute_feedback(m,(p,55),op,'right',np.array([0,0,.8]),np.eye(3),np.eye(4),None,normal)
    np.testing.assert_array_equal(commands,[p.evaluate(i/55,2.75)[0] for i in range(1,56)])
    event=next(x for x in events if x['event']=='push_yaw_feedback_suffix')
    assert event['fallback_original_suffix'] and event['rejection']['detail']=='zero_yaw_correction'


def test_physical_guard_failure_is_never_swallowed_by_fallback():
    m,p,op,normal,*_=fixture_runtime()
    original_tick=m.r.tick
    def tick(**kwargs):
        if m.r.steps==35:raise Fault('retained_contact_lost')
        original_tick(**kwargs)
    m.r.tick=tick
    with pytest.raises(Fault,match='retained_contact_lost'):
        execute_feedback(m,(p,55),op,'right',np.array([0,0,.8]),np.eye(3),np.eye(4),None,normal)
    assert m.r.steps==35
