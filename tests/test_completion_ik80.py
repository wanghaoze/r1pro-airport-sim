"""80mm is an explicit held-only planning candidate, never a success certificate."""
import numpy as np
import pytest
from types import SimpleNamespace
from test_completion_held_ik import runtime,goals
from r1pro_teleop.airport_fsm.contracts import Config,Fault
from r1pro_teleop.airport_fsm import runtime as module


def test_field_default_and_explicit_eighty_limit():
    assert Config().completion_held_ik_position_tolerance_m==.022
    assert Config(acceptance_profile='completion_first',retained_support_integer_clock_enabled=True,
                  completion_held_ik_position_tolerance_m=.080).validate()
    for value in [.08001,.02199,float('inf'),float('nan')]:
        with pytest.raises(ValueError,match='completion_held_ik_position'):
            Config(completion_held_ik_position_tolerance_m=value).validate()


def test_held_eighty_is_not_clamped_by_empty_arm_forty_and_logs_truthful_query():
    r=runtime(bound=.08);before=r.d.qpos.copy()
    assert r.cfg.ik_position_tolerance_m==.04
    target=r.solve_pair(goals(.0796))
    assert np.isfinite(target).all();np.testing.assert_array_equal(r.d.qpos,before)
    query=next(e for name,e in r.events if name=='held_ik_query_diagnostic')
    assert query['scope']=='single_accepted_solver_query'
    assert not query['execution_confirmed'] and not query['selected_path_confirmed']
    assert query['selected_path_max_position_error_m'] is None
    assert .075<query['query_max_position_error_m']<.08
    assert query['rigid_grasp_error']['position_m']<.015
    for error in query['tcp_errors'].values():
        np.testing.assert_allclose(np.asarray(error['desired_position_world_m'])-error['solved_position_world_m'],error['position_error_vector_m'])
        assert np.linalg.norm(error['position_error_vector_m'])==pytest.approx(error['position_error_m'])
    assert not r.strict_runtime_passed


def test_eighty_does_not_mean_unbounded_position():
    r=runtime(bound=.08)
    with pytest.raises(Fault,match='ik_unreachable'):r.solve_pair(goals(.08401))
    assert not r.events


@pytest.mark.parametrize('profile,held,retained,original,expected',[
    ('strict',0,None,.022,.022),('completion_first',None,None,.04,.04),
    ('completion_first',0,(0,'left'),.012,.012)])
def test_other_modes_retain_their_old_bounds(profile,held,retained,original,expected):
    r=runtime(profile,bound=.08);r.holding=held;r.retained_contact=retained
    assert r._completion_held_ik_position_bound(original)==expected


def test_eighty_does_not_increase_solver_work_budget(monkeypatch):
    r=runtime(bound=.08);calls=[]
    def fit(fn,initial,**kw):
        calls.append((len(initial),kw['max_nfev']));q=np.zeros(len(initial));q[2]=.004
        if len(q)==14:q[9]=.004
        return SimpleNamespace(x=q)
    monkeypatch.setattr(module,'least_squares',fit)
    r.solve_pair(goals(.0796))
    assert calls==[(7,r.cfg.max_ik_iterations)]*16+[(14,min(60,r.cfg.max_ik_iterations))]

def test_strict_return_after_relaxed_seed_does_not_emit_detailed_pose_log(monkeypatch):
    r=runtime(bound=.08)
    def fit(fn,initial,**kw):
        q=np.zeros(len(initial))
        if len(q)==14:q[2]=q[9]=.004
        return SimpleNamespace(x=q)
    monkeypatch.setattr(module,'least_squares',fit)
    r.solve_pair(goals(.025))
    assert not any(name=='held_ik_query_diagnostic' for name,_ in r.events)
    detail=next(e['detail'] for name,e in r.events if name=='planning_policy_deviation')
    assert not detail['returned_solution_outside_strict_position']
    assert detail['query_tcp_errors']=={}
    assert not r.strict_runtime_passed  # Conservative accepted-seed policy remains explicit.
