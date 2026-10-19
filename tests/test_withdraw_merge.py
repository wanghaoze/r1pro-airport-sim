from types import SimpleNamespace
import numpy as np
import pytest
from r1pro_teleop.airport_fsm.contracts import Config,Fault
from r1pro_teleop.airport_fsm import primitives as p
from r1pro_teleop.airport_fsm.withdraw_merge import merged_clearance_points


def fixture(monkeypatch,reasons,enabled=True,mutate=False):
    cfg=Config(push_withdraw_path_search_enabled=True,push_withdraw_merge_fallback_enabled=enabled)
    events=[];calls=[];errors=[]
    r=SimpleNamespace(cfg=cfg,steps=9,primitive_deadline_step=60,d=SimpleNamespace(time=.45,qpos=np.zeros(3),qvel=np.zeros(3),act=np.zeros(0),ctrl=np.zeros(3),qacc_warmstart=np.zeros(3),qfrc_applied=np.zeros(3)),
        sim=SimpleNamespace(target=np.zeros(16),base_target=np.zeros(3)),trace=SimpleNamespace(event=lambda name,**kw:events.append(dict(event=name,**kw))))
    points=np.zeros((4,16));points[1,:7]=.3;points[2,:7]=.2;points[-1]=1
    def planner(runtime,knots,**options):
        calls.append((knots.copy(),options));reason=reasons[len(calls)-1]
        if mutate and len(calls)==3:r.d.qpos[0]+=.001
        if reason:
            error=Fault('primitive_path_infeasible',{'candidates':[{'reason':reason}]});errors.append(error);raise error
        return 'validated',50
    monkeypatch.setattr(p,'plan',planner)
    return r,points,calls,events,errors


def invoke(r,points):
    return p.plan_withdraw_path(r,points,np.zeros(16),np.ones(16),np.arange(7),available=2.9,extra_path_check='same-normal-check')


def test_default_disabled_and_dependency():
    assert not Config().validate().push_withdraw_merge_fallback_enabled
    with pytest.raises(ValueError):Config(push_withdraw_merge_fallback_enabled=1).validate()
    with pytest.raises(ValueError):Config(push_withdraw_merge_fallback_enabled=True).validate()
    Config(push_withdraw_merge_fallback_enabled=True,push_withdraw_path_search_enabled=True,fixed_primitives=True).validate()


@pytest.mark.parametrize('held',[np.arange(7),np.arange(8,15)])
def test_exact_geometry_only_and_input_immutable(held):
    q=np.zeros((4,16));q[1,held]=.3;q[2,held]=.2;q[-1]=1;before=q.copy()
    got=merged_clearance_points(q,held)
    np.testing.assert_array_equal(got,q[[0,2,3]]);np.testing.assert_array_equal(q,before)
    got[0,0]=7;assert q[0,0]==0
    q[1,7]+=1e-15;assert merged_clearance_points(q,held) is None
    assert merged_clearance_points(q[:3],held) is None
    assert merged_clearance_points(before,[0,1]) is None


def test_single_structural_retry_after_all_three_pure_duration_rejections(monkeypatch):
    r,q,calls,events,_=fixture(monkeypatch,['duration']*3+[None]);before=q.copy()
    assert invoke(r,q)==('validated',50)
    assert len(calls)==4
    np.testing.assert_array_equal(calls[-1][0],q[[0,2,3]])
    np.testing.assert_array_equal(q,before)
    assert all(x[1]==calls[0][1] for x in calls)
    assert not calls[-1][1]['allow_shortcut'] and calls[-1][1]['available']==2.9
    assert events[-1]['event']=='push_withdraw_merge_fallback' and events[-1]['accepted']


@pytest.mark.parametrize('reasons',[['duration','duration','collision'],['duration','collision','duration'],['collision']])
def test_non_duration_never_triggers_structural_retry(monkeypatch,reasons):
    r,q,calls,events,errors=fixture(monkeypatch,reasons)
    with pytest.raises(Fault) as raised:invoke(r,q)
    assert raised.value is errors[0] and len(calls)==len(reasons)
    assert not any(x['event']=='push_withdraw_merge_fallback' for x in events)


@pytest.mark.parametrize('reasons',[[None],['duration',None],['duration','duration',None]])
def test_original_or_existing_alternative_success_is_unchanged(monkeypatch,reasons):
    r,q,calls,events,_=fixture(monkeypatch,reasons)
    assert invoke(r,q)==('validated',50) and len(calls)==len(reasons)
    assert not any(x['event']=='push_withdraw_merge_fallback' for x in events)


@pytest.mark.parametrize('mode',['disabled','unknown','candidate_collision'])
def test_failure_preserves_original_planning_exception(monkeypatch,mode):
    reasons=['duration']*3+(['collision'] if mode=='candidate_collision' else [])
    r,q,calls,events,errors=fixture(monkeypatch,reasons,enabled=mode!='disabled',mutate=mode=='physical_change')
    if mode=='unknown':q[1,8]=1e-15
    with pytest.raises(Fault) as raised:invoke(r,q)
    assert raised.value is errors[0]
    assert len(calls)==(4 if mode=='candidate_collision' else 3)
    assert r.steps==9 and r.d.time==.45


@pytest.mark.parametrize('field',['qpos','qacc_warmstart','qfrc_applied','base_target','primitive_deadline_step'])
@pytest.mark.parametrize('at_call',[3,4])
def test_planning_state_mutation_is_explicit_nonrecoverable_invariant(monkeypatch,field,at_call):
    r,q,calls,events,errors=fixture(monkeypatch,['duration']*3+[None])
    planner=p.plan
    def mutating(runtime,knots,**options):
        try:return planner(runtime,knots,**options)
        finally:
            if len(calls)==at_call:
                if field=='primitive_deadline_step':r.primitive_deadline_step+=1
                elif field=='base_target':r.sim.base_target[0]+=.001
                else:getattr(r.d,field)[0]+=.001
    monkeypatch.setattr(p,'plan',mutating)
    with pytest.raises(Fault) as raised:invoke(r,q)
    assert raised.value.code=='withdraw_planning_state_changed' and not raised.value.recoverable
    assert field in raised.value.detail['state_change']
    assert events[-1]['event']=='push_withdraw_planning_invariant'



def test_full_integration_state_is_checked_even_if_visible_joint_state_is_unchanged(monkeypatch):
    from r1pro_teleop.airport_fsm.withdraw_merge import planning_snapshot,check_unchanged
    r,*_=fixture(monkeypatch,[None]);hidden=np.array([.25,.75])
    r.m=object();r.integration_size=2;r.integration_spec=99
    r.mj=SimpleNamespace(mj_getState=lambda model,data,out,spec:np.copyto(out,hidden))
    before=planning_snapshot(r);hidden[1]+=.001
    with pytest.raises(Fault) as raised:check_unchanged(r,before)
    assert raised.value.detail['state_change']==['mujoco_integration'] and not raised.value.recoverable
