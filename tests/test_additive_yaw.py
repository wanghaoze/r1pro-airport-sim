"""Certified additive fallback retains the original successful curve."""
from dataclasses import replace
import numpy as np
import pytest
from r1pro_teleop.airport_fsm.additive_yaw import AdditiveYawSuffix, certified_range
from r1pro_teleop.airport_fsm.contracts import Config, Fault
from r1pro_teleop.airport_fsm.trajectory import BlendedJointPath
from r1pro_teleop.airport_fsm.yaw_feedback import execute_feedback, FixedDurationQuintic
from test_yaw_feedback import fixture_runtime


def test_default_disabled_and_boolean_validation():
    assert Config().validate().push_yaw_feedback_additive_fallback_enabled is False
    for value in (1,None,'true'):
        with pytest.raises(ValueError):Config(push_yaw_feedback_additive_fallback_enabled=value).validate()


def test_exact_bernstein_interior_peak_and_fail_closed():
    lo,hi,n,_=certified_range([0,4,-4],1.00001)
    assert lo<=0 and 1<=hi<=1.00001 and n>1
    assert certified_range([0,4,-4],.9)[1]>.9
    assert certified_range([0,4,-4],1.00001,max_depth=0)[1]>1.00001
    with pytest.raises((ValueError,OverflowError)):certified_range([float('nan')],1)


def blended_fixture(substep=False):
    m,_,op,normal,events,commands,subs,audits,goals=fixture_runtime(substep)
    m.r.cfg=replace(m.r.cfg,push_yaw_feedback_additive_fallback_enabled=True)
    q=np.zeros(16);mid=q.copy();mid[0]=.04;end=q.copy();end[0]=.1
    p=BlendedJointPath([q,mid,end],m.r.v,m.r.a,m.r.j)
    return m,p,op,normal,events,commands,subs,audits,goals


def test_additive_c2_endpoints_vectorization_bounds_and_zero_identity():
    m,p,*_=blended_fixture();T=2.75;start=30/55;end=p.evaluate(1,T)[0]+np.r_[.01,np.zeros(15)]
    candidate=AdditiveYawSuffix(p,T,start,end,(m.r.v,m.r.a,m.r.j))
    for got,want in zip(candidate.evaluate(0)[:3],p.evaluate(start,T)[:3]):np.testing.assert_array_equal(got,want)
    for got,want in zip(candidate.evaluate(1)[:3],(end,np.zeros(16),np.zeros(16))):np.testing.assert_allclose(got,want,atol=1e-11)
    u=np.linspace(0,1,901);values=candidate.evaluate(u)
    assert values[0].shape==(901,16)
    lo,hi=candidate.extrema[0];assert np.all(values[0]>=lo) and np.all(values[0]<=hi)
    for order,name in enumerate(('velocity','acceleration','jerk'),1):assert np.all(abs(values[order])<=candidate.reference_bounds[name])
    zero=AdditiveYawSuffix(p,T,start,p.evaluate(1,T)[0],(m.r.v,m.r.a,m.r.j))
    for got,want in zip(zero.evaluate(u),p.evaluate(start+(1-start)*u,T)):np.testing.assert_array_equal(got,want)
    with pytest.raises(ValueError):candidate.evaluate(.5,10)
    with pytest.raises(ValueError):AdditiveYawSuffix(FixedDurationQuintic(np.zeros(16),np.zeros(16),np.zeros(16),end,T),T,start,end,(m.r.v,m.r.a,m.r.j))


@pytest.mark.parametrize('substep',[False,True])
@pytest.mark.parametrize('reject_additive',[False,True])
def test_single_additive_after_original_normal_rejection_preserves_budget(substep,reject_additive):
    m,p,op,_,events,commands,subs,audits,goals=blended_fixture(substep)
    checked=[]
    def normal(candidate):
        checked.append(type(candidate).__name__)
        return {'reason':'supported_normal_reference_excursion'} if isinstance(candidate,FixedDurationQuintic) or reject_additive else None
    execute_feedback(m,(p,55),op,'right',np.array([0,0,.8]),np.eye(3),np.eye(4),None,normal)
    assert checked==['FixedDurationQuintic','AdditiveYawSuffix'] and len(goals)==1
    assert m.r.steps==55 and len(commands)==55
    event=next(x for x in events if x['event']=='push_yaw_feedback_suffix')
    assert event['accepted']==(not reject_additive)
    assert len([x for x in events if x['event']=='push_yaw_feedback_additive_fallback'])==1
    if reject_additive:np.testing.assert_allclose(commands,[p.evaluate(i/55,2.75)[0] for i in range(1,56)],atol=1e-14)
    else:
        assert event['selected_reference']=='additive' and len(audits)>=201
        assert commands[-1][0]==pytest.approx(.11)
    if substep:assert len(subs)==55 and all(x.shape==(25,16) for x in subs)


@pytest.mark.parametrize('mode',['success','zero','ik','physical'])
def test_no_additive_after_success_zero_or_unavailable_endpoint_and_physical_fault_propagates(mode):
    m,p,op,normal,events,commands,subs,audits,goals=blended_fixture()
    if mode=='zero':m.r.cfg=replace(m.r.cfg,push_yaw_feedback_gain=0.)
    if mode=='ik':m.r.solve_pair=lambda *args:(_ for _ in ()).throw(Fault('coupled_ik_failed'))
    if mode=='physical':
        tick=m.r.tick
        def checked_tick(**kw):
            if m.r.steps==35:raise Fault('retained_contact_lost')
            tick(**kw)
        m.r.tick=checked_tick
    def run():execute_feedback(m,(p,55),op,'right',np.array([0,0,.8]),np.eye(3),np.eye(4),None,normal)
    if mode=='physical':
        with pytest.raises(Fault,match='retained_contact_lost'):run()
    else:run()
    assert not any(x['event']=='push_yaw_feedback_additive_fallback' for x in events)


@pytest.mark.parametrize('reject',['path','normal','effort'])
def test_additive_failure_keeps_original_and_all_planning_guards(reject):
    m,p,op,_,events,commands,*_=blended_fixture()
    normal=lambda candidate:{'reason':'original_quintic_normal'} if isinstance(candidate,FixedDurationQuintic) else ({'reason':'additive_normal'} if reject=='normal' else None)
    if reject=='path':m.r._path_rejection=lambda candidate,*args:{'reason':'additive_collision'} if isinstance(candidate,AdditiveYawSuffix) else None
    if reject=='effort':m.r.audit_online_reference=lambda *args:(_ for _ in ()).throw(Fault('online_reference_effort_limit'))
    execute_feedback(m,(p,55),op,'right',np.array([0,0,.8]),np.eye(3),np.eye(4),None,normal)
    event=next(x for x in events if x['event']=='push_yaw_feedback_additive_fallback')
    assert not event['accepted'] and event['rejection'] is not None
    np.testing.assert_array_equal(commands,[p.evaluate(i/55,2.75)[0] for i in range(1,56)])


def test_original_planning_effort_rejection_can_try_same_endpoint_once():
    m,p,op,normal,events,commands,subs,audits,goals=blended_fixture()
    count=[0]
    def audit(*args):
        count[0]+=1
        if count[0]==1:raise Fault('online_reference_effort_limit')
    m.r.audit_online_reference=audit
    execute_feedback(m,(p,55),op,'right',np.array([0,0,.8]),np.eye(3),np.eye(4),None,normal)
    event=next(x for x in events if x['event']=='push_yaw_feedback_additive_fallback')
    assert event['accepted'] and event['original_quintic_rejection']['reason']=='online_reference_effort_limit'
    assert len(goals)==1 and m.r.steps==55



def test_certificate_total_node_budget_fails_closed():
    with pytest.raises(ValueError,match='node budget'):
        certified_range([0,4,-4],1.00001,max_nodes=2)
    m,p,*_=blended_fixture()
    with pytest.raises(ValueError,match='node budget'):
        AdditiveYawSuffix(p,2.75,30/55,p.evaluate(1,2.75)[0],(m.r.v,m.r.a,m.r.j),max_certificate_nodes=2)


def test_separate_term_roundoff_reserve_survives_strong_cancellation():
    # A zero combined polynomial can result from two very large opposite
    # terms that are still separately evaluated in runtime floating arithmetic.
    lo,hi,_,reserve=certified_range([0.,0.,0.],1.,evaluation_scale=2e12)
    assert reserve>=200. and lo< -1. and hi>1.
    small=certified_range([0.,0.,0.],1.)
    assert small[0]> -1. and small[1]<1.
