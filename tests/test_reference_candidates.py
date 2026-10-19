from types import SimpleNamespace
import numpy as np
import pytest
from r1pro_teleop.airport_fsm.contracts import Config,Fault
from r1pro_teleop.airport_fsm.reference_candidates import plan_reference_candidate


def runtime():
    events=[]
    r=SimpleNamespace(cfg=Config(),steps=25,d=SimpleNamespace(time=1.25),
        primitive_deadline_step=85,holding=0,retained_contact=None,
        grasp_rel={'left':np.eye(4),'right':np.eye(4)},
        trace=SimpleNamespace(event=lambda name,**kw:events.append((name,kw))),
        observation=lambda:{'gripper_contact_force':np.full((3,2),10.)})
    saved={s:v.copy()for s,v in r.grasp_rel.items()};saved['left'][0,3]=.02
    return r,saved,events


@pytest.mark.parametrize('enabled',[False,True])
def test_successful_original_plan_keeps_exact_reference_and_no_candidate(enabled):
    r,saved,events=runtime();original=r.grasp_rel;result=object();calls=[]
    got=plan_reference_candidate(r,lambda:calls.append(r.grasp_rel)or result,saved,
        enabled=enabled,check_command=lambda *a:pytest.fail('no alternative needed'))
    assert got is result and calls==[original] and r.grasp_rel is original and not events


def test_planning_rejection_selects_owned_alternative_under_same_deadline():
    r,saved,events=runtime();calls=[];original=Fault('primitive_path_infeasible',{'budget':1.9})
    def plan():
        calls.append(r.grasp_rel)
        if len(calls)==1:raise original
        assert r.steps==25 and r.d.time==1.25 and r.primitive_deadline_step==85
        assert r.grasp_rel['left'][0,3]==.02
        return 'alternative'
    checks=[]
    assert plan_reference_candidate(r,plan,saved,enabled=True,check_command=lambda x:checks.append(x))=='alternative'
    assert checks==[r] and len(calls)==2 and r.grasp_rel is not saved
    assert events[-1][1]['selected'] and events[-1][1]['elapsed_steps']==0
    r.grasp_rel['left'][0,3]=.03
    assert saved['left'][0,3]==.02


def test_both_plans_reject_restores_original_relation_and_fault():
    r,saved,events=runtime();original=Fault('ik_unreachable',{'side':'left'});calls=[]
    def plan():
        calls.append(1);raise original if len(calls)==1 else Fault('primitive_path_infeasible')
    with pytest.raises(Fault)as got:
        plan_reference_candidate(r,plan,saved,enabled=True,check_command=lambda *a:None)
    assert got.value is original and len(calls)==2
    np.testing.assert_array_equal(r.grasp_rel['left'],np.eye(4))
    assert events[-1][1]['alternative_reason']=='primitive_path_infeasible'


@pytest.mark.parametrize('mode',['physical_frame','physical_substep','deadline','nonplanning','lost_contact','retained','no_alignment'])
def test_ineligible_failure_never_attempts_alternative(mode):
    r,saved,events=runtime();calls=[]
    failure=Fault('primitive_path_infeasible'if mode!='nonplanning'else'primitive_release_not_verified')
    if mode=='lost_contact':r.observation=lambda:{'gripper_contact_force':np.array([[10.,.5]])}
    if mode=='retained':r.retained_contact=(0,'right')
    if mode=='no_alignment':saved=None
    def plan():
        calls.append(1)
        if mode=='physical_frame':r.steps+=1;r.d.time+=.05
        if mode=='physical_substep':r.d.time+=.002
        if mode=='deadline':r.primitive_deadline_step+=1
        raise failure
    with pytest.raises(Fault)as got:
        plan_reference_candidate(r,plan,saved,enabled=True,check_command=lambda *a:pytest.fail('must not check alternative'))
    assert got.value is failure and len(calls)==1 and not events


def test_compliance_failure_is_not_masked_by_original_planning_fault():
    r,saved,events=runtime();compliance=Fault('primitive_excess_servo_deflection')
    def plan():raise Fault('ik_unreachable')
    def checked(*args):raise compliance
    with pytest.raises(Fault)as got:plan_reference_candidate(r,plan,saved,enabled=True,check_command=checked)
    assert got.value is compliance and not events


def test_physics_failure_in_candidate_is_not_masked():
    r,saved,events=runtime();calls=[];physical=Fault('measured_joint_overspeed')
    def plan():
        calls.append(1)
        if len(calls)==1:raise Fault('ik_unreachable')
        r.d.time+=.002;raise physical
    with pytest.raises(Fault)as got:
        plan_reference_candidate(r,plan,saved,enabled=True,check_command=lambda *a:None)
    assert got.value is physical and len(calls)==2


def test_prediction_explicitly_labels_geometric_alignment_not_actual_contact():
    r,saved,events=runtime();r.observation=lambda:pytest.fail('no invented future force evidence');calls=[]
    def plan():
        calls.append(1)
        if len(calls)==1:raise Fault('cartesian_collision_or_wrist')
        return 'geometry_only'
    assert plan_reference_candidate(r,plan,saved,enabled=True,check_command=lambda *a:None,
        actual_alignment=False)=='geometry_only'
    assert events[0][1]['source']=='private_predicted_alignment'
