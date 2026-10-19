"""Bounded coupled-IK repair changes only failed held place planning queries."""
from dataclasses import replace
from types import SimpleNamespace
import numpy as np
import pytest

from test_completion_held_ik import runtime
from r1pro_teleop.airport_fsm import runtime as module
from r1pro_teleop.airport_fsm.contracts import Fault, State


def setup():
    r=runtime(bound=.080)
    r.cfg=replace(r.cfg,completion_held_ik_orientation_tolerance_rad=.12,
                  completion_place_coupled_position_refit_enabled=True)
    r.fsm_state=State.PLACE_TRAY
    goals={side:(np.array([.083,0.,0.]),np.eye(3)) for side in ('left','right')}
    return r,goals


def fit_factory(coupled_x):
    calls=[]
    def fit(fn, initial, **kwargs):
        calls.append((len(initial),kwargs['max_nfev']))
        q=np.zeros(len(initial))
        if len(q)==7:
            q[0]=.01
        else:
            x=coupled_x[len([size for size,_ in calls if size==14])-1]
            q[0]=q[7]=x
        return SimpleNamespace(x=q,nfev=1)
    return fit,calls


def test_original_qualified_coupled_fit_wins_without_extra_solve(monkeypatch):
    r,goals=setup();fit,calls=fit_factory([.01])
    monkeypatch.setattr(module,'least_squares',fit)
    result=r.solve_pair(goals)
    assert result[0]==pytest.approx(.01)
    assert [size for size,_ in calls].count(14)==1
    assert not any(name=='place_coupled_position_refit' for name,_ in r.events)


def test_two_extra_fits_are_bounded_and_second_can_qualify(monkeypatch):
    r,goals=setup();fit,calls=fit_factory([0.,0.,.01])
    monkeypatch.setattr(module,'least_squares',fit)
    before=r.d.qpos.copy()
    result=r.solve_pair(goals)
    assert result[0]==result[8]==pytest.approx(.01)
    np.testing.assert_array_equal(r.d.qpos,before)
    assert [budget for size,budget in calls if size==14]==[60,60,60]
    event=next(detail for name,detail in r.events if name=='place_coupled_position_refit')
    assert event['selected_seed']=='independent_fit'
    assert len(event['attempts'])==2
    assert event['attempts'][0]['tcp_errors']['left']['position_m']==pytest.approx(.083)
    assert event['attempts'][1]['tcp_errors']['left']['position_m']==pytest.approx(.073)
    assert event['planning_only'] and not event['execution_confirmed']


def test_failed_refits_preserve_original_fault_and_position_ceiling(monkeypatch):
    r,goals=setup();fit,calls=fit_factory([0.,0.,0.])
    monkeypatch.setattr(module,'least_squares',fit)
    with pytest.raises(Fault,match='coupled_ik_unreachable') as failed:
        r.solve_pair(goals)
    assert [size for size,_ in calls].count(14)==3
    assert failed.value.detail['tcp_errors']['left']['position_m']==pytest.approx(.083)
    assert len(failed.value.detail['position_refit_attempts'])==2
    assert not any(item['qualified'] for item in failed.value.detail['position_refit_attempts'])


@pytest.mark.parametrize('disabled_scope', ['flag','state','retained','profile'])
def test_refit_never_runs_outside_declared_scope(monkeypatch,disabled_scope):
    r,goals=setup();fit,calls=fit_factory([0.])
    monkeypatch.setattr(module,'least_squares',fit)
    if disabled_scope=='flag':
        r.cfg=replace(r.cfg,completion_place_coupled_position_refit_enabled=False)
    elif disabled_scope=='state':
        r.fsm_state=State.TRANSPORT_TRAY
    elif disabled_scope=='retained':
        r.retained_contact=(0,'left')
    else:
        r.cfg=replace(r.cfg,acceptance_profile='strict',
                      completion_place_coupled_position_refit_enabled=False)
    with pytest.raises(Fault):r.solve_pair(goals)
    assert [size for size,_ in calls].count(14)<=1
