"""Completion held IK accepts planning policy only; no physical success is inferred."""
import copy
from dataclasses import replace
from types import SimpleNamespace
import numpy as np
import pytest
from test_placement_planner import _physical_ik_runtime
from r1pro_teleop.airport_fsm.contracts import Fault
from r1pro_teleop.airport_fsm import runtime as module


def runtime(profile='completion_first', bound=.030):
    r=_physical_ik_runtime()
    r.cfg=replace(r.cfg,acceptance_profile=profile,retained_support_integer_clock_enabled=True,
                  completion_held_ik_position_tolerance_m=bound)
    r.holding=0;r.retained_contact=None
    r.grasp_rel={side:np.eye(4) for side in ('left','right')}
    r.events=[];r.trace=SimpleNamespace(event=lambda name,**kw:r.events.append((name,kw)))
    r.physics_step_count=0;r.strict_runtime_passed=True
    return r


def goals(z,both=True):return {s:(np.array([0.,0.,z]),np.eye(3)) for s in (('left','right') if both else ('left',))}


@pytest.mark.parametrize('profile,bound,accepted',[('strict',.03,False),('completion_first',.022,False),('completion_first',.03,True)])
def test_256mm_residual_only_explicit_completion_policy_accepts(profile,bound,accepted):
    r=runtime(profile,bound)
    if not accepted:
        with pytest.raises(Fault,match='ik_unreachable'):r.solve_pair(goals(.0296))
        assert not r.events
    else:
        before=r.d.qpos.copy();target=r.solve_pair(goals(.0296))
        assert np.isfinite(target).all();np.testing.assert_array_equal(r.d.qpos,before)
        event=next(e for name,e in r.events if name=='planning_policy_deviation')
        assert event['detail']['planning_only'] and not event['detail']['execution_confirmed']
        assert {d['stage'] for d in event['detail']['accepted_solution_errors']}=={'independent','coupled'}
        assert not r.strict_runtime_passed


def test_30mm_is_a_real_ceiling_not_implicit40mm():
    r=runtime()
    with pytest.raises(Fault,match='ik_unreachable'):r.solve_pair(goals(.03401))
    assert not r.events


def test_original_later_strict_seed_precedes_earlier_relaxed_seed(monkeypatch):
    r=runtime();calls=[]
    def fit(fn,initial,**kw):
        q=np.zeros(7);q[2]=-.004 if not calls else .004
        calls.append(q.copy());return SimpleNamespace(x=q)
    monkeypatch.setattr(module,'least_squares',fit)
    result=r.solve_pair(goals(.023,both=False))
    assert len(calls)==2 and result[2]==.004
    assert not r.events and r.strict_runtime_passed


def test_original_first_valid_seed_and_reference_unchanged():
    strict=runtime('strict');completion=runtime()
    np.testing.assert_array_equal(strict.solve_pair(goals(.003)),completion.solve_pair(goals(.003)))
    assert not completion.events and completion.strict_runtime_passed


@pytest.mark.parametrize('rigid',[{'position_m':.01501,'rotation_rad':0.}, {'position_m':0.,'rotation_rad':.10001}])
def test_relative_rigidity_is_not_relaxed(rigid):
    r=runtime();r._rigid_grasp_error=lambda d:rigid
    with pytest.raises(Fault,match='coupled_ik_unreachable'):r.solve_pair(goals(.0296))
    assert not r.events and r.strict_runtime_passed


def test_empty_and_retained_bounds_unchanged():
    r=runtime();r.holding=None
    assert r._completion_held_ik_position_bound(.04)==.04
    r.holding=0;r.retained_contact=(0,'left')
    assert r._completion_held_ik_position_bound(.012)==.012
    r.holding=None
    with pytest.raises(Fault,match='ik_unreachable'):r.solve_pair(goals(.008,both=False))
    assert not r.events


def test_trace_less_planning_copy_never_mutates_shared_live_warning_state():
    live=runtime();live.soft_guard_violation_by_code={};live.soft_guard_violation_maxima={}
    probe=copy.copy(live);probe.trace=None;probe.shadow=probe.mj.MjData(probe.m)
    probe.solve_pair(goals(.0296))
    assert live.strict_runtime_passed and not live.events
    assert live.soft_guard_violation_by_code=={} and live.soft_guard_violation_maxima=={}


def test_physical_preview_owned_warning_state_is_private():
    live=runtime();live.soft_guard_violation_by_code={};live.soft_guard_violation_maxima={}
    probe=copy.copy(live);probe.shadow=probe.mj.MjData(probe.m)
    probe.soft_guard_violation_by_code={};probe.soft_guard_violation_maxima={}
    probe.events=[];probe.trace=SimpleNamespace(event=lambda name,**kw:probe.events.append((name,kw)))
    probe.solve_pair(goals(.0296))
    assert not probe.strict_runtime_passed and probe.events
    assert live.strict_runtime_passed and not live.events and not live.soft_guard_violation_by_code

def test_coupled_only_absolute_residual_uses_same_policy(monkeypatch):
    r=runtime()
    def fit(fn,initial,**kw):
        q=np.zeros(len(initial))
        if len(q)==7:q[2]=.004
        return SimpleNamespace(x=q)
    monkeypatch.setattr(module,'least_squares',fit)
    r.solve_pair(goals(.0256))
    event=next(e for name,e in r.events if name=='planning_policy_deviation')
    assert {d['stage'] for d in event['detail']['accepted_solution_errors']}=={'coupled'}


@pytest.mark.parametrize('joint,value,code',[(3,.1,'ik_unreachable'),(0,.9,'ik_unreachable')])
def test_non_position_failures_are_not_relaxed(monkeypatch,joint,value,code):
    r=runtime()
    def fit(fn,initial,**kw):
        q=np.zeros(7);q[joint]=value
        return SimpleNamespace(x=q)
    monkeypatch.setattr(module,'least_squares',fit)
    with pytest.raises(Fault,match=code):r.solve_pair(goals(.0296,both=False))
    assert not r.events

def test_silent_loaded_planning_trace_detaches_shared_warning_dictionaries():
    from r1pro_teleop.airport_fsm.placement_reachability import _SilentTrace
    live=runtime();live.soft_guard_violation_by_code={'prior':1}
    live.soft_guard_violation_maxima={'prior':{'value':1.}}
    live.soft_guard_last_step_by_code={'prior':-1}
    expected=copy.deepcopy((live.soft_guard_violation_by_code,live.soft_guard_violation_maxima,live.soft_guard_last_step_by_code))
    probe=copy.copy(live);probe.shadow=probe.mj.MjData(probe.m);probe.trace=_SilentTrace()
    probe.solve_pair(goals(.0296))
    assert not probe.strict_runtime_passed
    assert live.strict_runtime_passed and not live.events
    assert (live.soft_guard_violation_by_code,live.soft_guard_violation_maxima,live.soft_guard_last_step_by_code)==expected
    assert probe.soft_guard_violation_by_code is not live.soft_guard_violation_by_code


def test_branch_limit_is_not_relaxed_even_for_position_eligible_candidate(monkeypatch):
    r=runtime()
    def fit(fn,initial,**kw):
        q=np.zeros(7);q[0]=.9
        return SimpleNamespace(x=q)
    monkeypatch.setattr(module,'least_squares',fit)
    with pytest.raises(Fault,match='ik_branch_jump'):
        r.solve_pair({'left':(np.array([.9,0.,.026]),np.eye(3))})
    assert not r.events

@pytest.mark.parametrize('bound,z',[(.030,.0296),(.040,.0436)])
def test_explicit_30_or40_policy_keeps_original_seed_and_iteration_budget(monkeypatch,bound,z):
    r=runtime(bound=bound);calls=[]
    def fit(fn,initial,**kw):
        calls.append((len(initial),kw['max_nfev']))
        q=np.zeros(len(initial));q[2]=.004
        if len(q)==14:q[9]=.004
        return SimpleNamespace(x=q)
    monkeypatch.setattr(module,'least_squares',fit)
    result=r.solve_pair(goals(z))
    assert np.isfinite(result).all()
    assert calls==[(7,r.cfg.max_ik_iterations)]*16+[(14,min(60,r.cfg.max_ik_iterations))]
    assert not r.strict_runtime_passed


def test_explicit40_still_rejects_residual_above40mm():
    r=runtime(bound=.04)
    with pytest.raises(Fault,match='ik_unreachable'):r.solve_pair(goals(.04401))
    assert not r.events

def test_arrival_proposal_never_reuses_private_trajectory(monkeypatch):
    from test_placement_arrival_rescreen import setup
    from r1pro_teleop.airport_fsm import placement_reachability as planner
    m,op,order,events,bases,screens,failures=setup(monkeypatch)
    screen=planner.screen_placement
    class ForbiddenPreviewTrajectory:
        def __array__(self,*a,**kw):raise AssertionError('private points cannot execute')
        def evaluate(self,*a,**kw):raise AssertionError('private path cannot execute')
    def with_unusable_trajectory(*a,**kw):
        result=screen(*a,**kw)
        result.qualified[0].update(points=ForbiddenPreviewTrajectory(),path=ForbiddenPreviewTrajectory())
        return result
    monkeypatch.setattr(planner,'screen_placement',with_unusable_trajectory)
    assert m.carry_place(op)
    assert order==['navigate','remeasure','place','remeasure','screen','navigate','remeasure','place']
