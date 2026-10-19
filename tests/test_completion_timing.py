"""Explicit completion budgets retain actual-duration and strict-policy evidence."""
from types import SimpleNamespace
import pytest
from r1pro_teleop.airport_fsm.contracts import Config,Fault
from r1pro_teleop.airport_fsm.primitives import action,remaining
from r1pro_teleop.airport_fsm.placement_planner import descent_budget_frames


def config(seconds=5.,profile='completion_first'):
    return Config(acceptance_profile=profile,retained_support_integer_clock_enabled=True,
                  primitive_seconds=seconds).validate()


@pytest.mark.parametrize('seconds',[.1,3.,5.,6.])
def test_completion_accepts_declared_budget_only_up_to_six(seconds):
    assert config(seconds).primitive_seconds==seconds


@pytest.mark.parametrize('seconds',[0.,-1.,6.001,float('inf'),float('nan')])
def test_invalid_completion_budget_rejected(seconds):
    with pytest.raises(ValueError,match='Primitive duration'):config(seconds)


def test_strict_default_stays_three_and_rejects_longer():
    assert Config().validate().primitive_seconds==3.
    with pytest.raises(ValueError,match='3 seconds'):config(3.001,'strict')


def machine(seconds=5.):
    cfg=config(seconds);events=[];warnings=[]
    r=SimpleNamespace(steps=100,physics_step_count=2500,physics_clock_timestep=.002,
                      d=SimpleNamespace(time=5.),primitive_deadline_step=None,cfg=cfg)
    r.record_strict_deviation=lambda code,detail:warnings.append((code,detail))
    m=SimpleNamespace(r=r,c=cfg,log=SimpleNamespace(event=lambda name,**kw:events.append((name,kw))))
    return m,events,warnings


@pytest.mark.parametrize('physics_steps,frames,expected',[(1000,40,False),(1500,60,False),(1501,60,True),(2000,80,True)])
def test_only_actual_duration_beyond_three_records_deviation(physics_steps,frames,expected):
    m,events,warnings=machine()
    with action(m,'push'):
        assert m.r.primitive_deadline_step==200
        assert remaining(m.r)==5.
        m.r.steps+=frames;m.r.physics_step_count+=physics_steps
        m.r.d.time+=physics_steps*.002+1e-11
    final=next(row for name,row in events if name=='primitive_complete')
    assert final['actual_duration_s']==pytest.approx(physics_steps*.002)
    assert final['configured_budget_s']==5 and final['strict_budget_s']==3
    assert final['duration_source']=='executed_physics_steps'
    assert bool(warnings)==expected
    assert m.r.primitive_deadline_step is None


def test_failure_after_partial_substep_retains_original_failure_and_duration():
    m,events,warnings=machine()
    with pytest.raises(Fault,match='retained_contact_lost') as caught:
        with action(m,'push'):
            m.r.steps+=60;m.r.physics_step_count+=1501;m.r.d.time+=3.002
            raise Fault('retained_contact_lost',{'force':0.},recoverable=True)
    assert caught.value.detail=={'force':0.} and not caught.value.recoverable
    assert caught.value.primitive_execution['elapsed_steps']==60
    failure=next(row for name,row in events if name=='primitive_failed')
    assert failure['duration_s']==3 and failure['actual_duration_s']==3.002
    assert warnings[0][0]=='primitive_duration_outside_strict_contract'
    assert warnings[0][1]['actual_duration_s']==3.002
    assert m.r.primitive_deadline_step is None


def test_duration_excludes_navigation_prior_wait_and_planning_wall_time():
    m,events,warnings=machine()
    m.r.steps+=400;m.r.physics_step_count+=10000;m.r.d.time+=20
    with action(m,'place'):
        assert remaining(m.r)==5.
        assert descent_budget_frames(remaining_frames=100,release_frames=18,support_frames=2)==80
        m.r.steps+=40;m.r.physics_step_count+=1000;m.r.d.time+=2
    assert not warnings
    assert events[-1][1]['actual_duration_s']==2
