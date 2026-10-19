from dataclasses import replace
from types import SimpleNamespace
import numpy as np
import pytest
from r1pro_teleop.airport_fsm.contracts import Config,Fault
from r1pro_teleop.airport_fsm.machine import Machine
from r1pro_teleop.airport_fsm import placement_reachability as planner,primitives
from r1pro_teleop.airport_fsm.arrival_replanning import alternative_bases
from r1pro_teleop.airport_fsm.arrival_replanning import zero_motion_place_failure


def setup(monkeypatch, *, failure='primitive_path_infeasible', advance_steps=0,
          advance_time=0., second_failure=False, no_candidate=False,
          lost_contact=False, retained=False, prior_align=False, enabled=True):
    m=object.__new__(Machine);m.c=Config(fixed_primitives=True,
        placement_arrival_rescreen_enabled=enabled)
    m._place_location=lambda op:op.destination.copy()
    m._inward_yaw=lambda position:0.;m.transition=lambda *a,**kw:None
    events=[];order=[];screens=[];bases=[];failures=[]
    m.log=SimpleNamespace(event=lambda name,**kw:events.append((name,kw)))
    current=np.zeros(3);proposal=np.array([.85,.95,-np.pi/2]);force=np.full((3,2),10.)
    r=SimpleNamespace(steps=100,d=SimpleNamespace(time=5.),cfg=m.c,
        holding=0,retained_contact=None,primitive_deadline_step=None);m.r=r
    r.sim=SimpleNamespace(base_state=lambda:current.copy())
    r.observation=lambda:{'gripper_contact_force':force.copy()}
    r.remember_grasp=lambda tray:order.append('remeasure')
    def navigate(base):
        order.append('navigate');bases.append(np.asarray(base).copy());current[:]=base
        r.steps+=20;r.d.time+=1.
        if lost_contact and len(bases)==2:force[0,1]=0.
    r.navigate=navigate
    monkeypatch.setattr(planner,'carried_placement_candidates',lambda *a,**kw:[current.copy(),current+np.array([.0005,0,.0005]),proposal])
    def screen(*args,**kwargs):
        candidates=list(kwargs['candidates']);screens.append(kwargs);order.append('screen')
        assert kwargs['max_candidates']==18
        assert len(candidates)==1 and np.array_equal(candidates[0],proposal)
        return SimpleNamespace(examined=1,qualified=[] if no_candidate else [{'base':proposal}],rejected=[])
    monkeypatch.setattr(planner,'screen_placement',screen)
    calls=[]
    def place(*args):
        order.append('place');calls.append(1)
        if failure is None:return True
        if len(calls)>1 and not second_failure:return True
        if prior_align:r.steps+=36;r.d.time+=1.8
        if retained:r.retained_contact=(0,'left')
        try:
            with primitives.action(m,'place' if prior_align else 'transport_align'):
                r.steps+=advance_steps;r.d.time+=advance_time
                raise Fault(failure,{'original':'detail'},recoverable=True)
        except Fault as exc:
            failures.append(exc);raise
    monkeypatch.setattr(primitives,'place',place)
    operation=SimpleNamespace(tray=0,destination=np.array([.85,.38,.8]),yaw=0.)
    return m,operation,order,events,bases,screens,failures


def test_successful_original_place_never_screens_or_relocates(monkeypatch):
    m,op,order,events,bases,screens,failures=setup(monkeypatch,failure=None)
    assert m.carry_place(op)
    assert order==['navigate','remeasure','place'] and not screens


def test_zero_motion_planning_failure_allows_exactly_one_correction(monkeypatch):
    m,op,order,events,bases,screens,failures=setup(monkeypatch)
    assert m.carry_place(op)
    assert order==['navigate','remeasure','place','remeasure','screen','navigate','remeasure','place']
    assert len(bases)==2 and len(screens)==1
    event=next(data for name,data in events if name=='placement_arrival_base_correction')
    assert event['navigation_seconds']==event['physical_navigation_seconds']==1.
    assert event['counted_in_episode'] and event['excluded_from_primitive']


@pytest.mark.parametrize('steps,seconds',[(1,.05),(0,.002)])
def test_partial_physical_execution_cannot_relocate(monkeypatch,steps,seconds):
    m,op,order,events,bases,screens,failures=setup(monkeypatch,advance_steps=steps,advance_time=seconds)
    with pytest.raises(Fault)as got:m.carry_place(op)
    assert got.value is failures[0] and not screens and len(bases)==1


@pytest.mark.parametrize('code',['measured_joint_overspeed','primitive_postcondition_failed',
    'primitive_release_not_verified','primitive_excess_servo_deflection'])
def test_nonplanning_failures_propagate_without_screen(monkeypatch,code):
    m,op,order,events,bases,screens,failures=setup(monkeypatch,failure=code)
    with pytest.raises(Fault)as got:m.carry_place(op)
    assert got.value is failures[0] and not screens


def test_no_alternative_reraises_exact_original_fault(monkeypatch):
    m,op,order,events,bases,screens,failures=setup(monkeypatch,no_candidate=True)
    with pytest.raises(Fault)as got:m.carry_place(op)
    assert got.value is failures[0] and got.value.detail=={'original':'detail'}
    assert len(bases)==1 and len(screens)==1


def test_second_zero_motion_failure_never_rescreens(monkeypatch):
    m,op,order,events,bases,screens,failures=setup(monkeypatch,second_failure=True)
    with pytest.raises(Fault)as got:m.carry_place(op)
    assert got.value is failures[-1] and len(failures)==2 and len(screens)==1 and len(bases)==2


def test_lost_contact_after_navigation_prevents_place_retry(monkeypatch):
    m,op,order,events,bases,screens,failures=setup(monkeypatch,lost_contact=True)
    with pytest.raises(Fault,match='preplace_bilateral_contact_missing'):m.carry_place(op)
    assert order.count('place')==1 and order[-1]=='navigate'


def test_retained_contact_is_not_eligible(monkeypatch):
    m,op,order,events,bases,screens,failures=setup(monkeypatch,retained=True)
    with pytest.raises(Fault)as got:m.carry_place(op)
    assert got.value is failures[0] and not screens


def test_completed_prior_alignment_counts_in_episode_but_does_not_fake_place_progress(monkeypatch):
    m,op,order,events,bases,screens,failures=setup(monkeypatch,prior_align=True)
    assert m.carry_place(op)
    evidence=failures[0].primitive_execution
    assert evidence['name']=='place' and evidence['elapsed_steps']==0 and evidence['physical_elapsed_s']==0.
    assert evidence['start_step']==156 and m.r.steps==176
    assert m.r.d.time==pytest.approx(8.8)
    with pytest.raises(TypeError):evidence['elapsed_steps']=1
    assert failures[0].detail=={'original':'detail'} and not failures[0].recoverable


def test_feature_off_propagates_original_planning_failure(monkeypatch):
    m,op,order,events,bases,screens,failures=setup(monkeypatch,enabled=False)
    with pytest.raises(Fault)as got:m.carry_place(op)
    assert got.value is failures[0] and not screens


def test_failed_base_exclusion_wraps_yaw_and_uses_both_thresholds():
    base=np.array([0.,0.,np.pi])
    values=[base,base+np.array([.0009,0,-2*np.pi+.0009]),
        base+np.array([.0011,0,0]),base+np.array([0,0,.0011])]
    result=list(alternative_bases(values,base))
    assert len(result)==2
    np.testing.assert_array_equal(result[0],values[2])


def test_arrival_screen_configuration_is_opt_in_and_independent():
    assert not Config().placement_arrival_rescreen_enabled
    Config(fixed_primitives=True,placement_arrival_rescreen_enabled=True).validate()
    with pytest.raises(ValueError,match='requires fixed primitives'):
        Config(placement_arrival_rescreen_enabled=True).validate()


@pytest.mark.parametrize('condition',['missing_metadata','no_holding','force_threshold','force_nan','stale_time'])
def test_missing_execution_provenance_or_grasp_never_authorizes_relocation(monkeypatch,condition):
    m,op,order,events,bases,screens,failures=setup(monkeypatch)
    try:
        with primitives.action(m,'place'):raise Fault('ik_unreachable')
    except Fault as failure:
        if condition=='missing_metadata':failure=Fault('ik_unreachable')
        elif condition=='no_holding':m.r.holding=None
        elif condition=='stale_time':m.r.d.time+=.002
        else:
            forces=np.full((3,2),10.)
            forces[0,0]=.5 if condition=='force_threshold' else np.nan
            m.r.observation=lambda:{'gripper_contact_force':forces}
        assert not zero_motion_place_failure(m.r,0,failure)
