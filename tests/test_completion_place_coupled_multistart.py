"""Coupled alternatives use only the original bounded independent seed lists."""
from dataclasses import replace
from types import SimpleNamespace
import numpy as np
import pytest

from test_completion_held_ik import runtime
from r1pro_teleop.airport_fsm import runtime as module
from r1pro_teleop.airport_fsm.contracts import Fault, State


def setup(*, goal_x=.083,enabled=True):
    r=runtime(bound=.080)
    r.cfg=replace(r.cfg,completion_held_ik_orientation_tolerance_rad=.12,
        completion_place_coupled_multistart_enabled=enabled)
    r.fsm_state=State.PLACE_TRAY
    goals={side:(np.array([goal_x,0.,0.]),np.eye(3)) for side in ('left','right')}
    return r,goals


def fake_fit(*, original_pair='fail'):
    calls=[];side_calls=0;pair_calls=0
    def fit(fn,seed,**kwargs):
        nonlocal side_calls,pair_calls
        calls.append((len(seed),kwargs['max_nfev']))
        if len(seed)==7:
            index=side_calls%8;side_calls+=1
            q=np.zeros(7);q[0]=(.01,.03,.05)[min(index,2)]
        else:
            pair_calls+=1
            q=np.zeros(14) if pair_calls==1 and original_pair=='fail' else np.asarray(seed).copy()
        return SimpleNamespace(x=q,nfev=1)
    return fit,calls


def test_original_coupled_success_has_no_extra_fit(monkeypatch):
    r,goals=setup();fit,calls=fake_fit(original_pair='success')
    monkeypatch.setattr(module,'least_squares',fit)
    r.solve_pair(goals)
    assert [size for size,_ in calls].count(14)==1
    assert not any(name=='place_coupled_multistart' for name,_ in r.events)


def test_third_deterministic_combination_repairs_rigid_disagreement(monkeypatch):
    r,goals=setup();fit,calls=fake_fit()
    monkeypatch.setattr(module,'least_squares',fit)
    before=r.d.qpos.copy()
    target=r.solve_pair(goals)
    assert target[0]==target[8]==pytest.approx(.01)
    np.testing.assert_array_equal(r.d.qpos,before)
    assert [size for size,_ in calls].count(7)==16
    assert [budget for size,budget in calls if size==14]==[60]*4
    event=next(detail for name,detail in r.events if name=='place_coupled_multistart')
    assert event['independent_choices']=={'left':3,'right':3}
    assert [(a['left_choice'],a['right_choice'],a['qualified']) for a in event['attempts']]==[
        (1,0,False),(0,1,False),(1,1,True)]
    assert event['selected_pair']==[1,1]
    assert event['planning_only'] and not event['execution_confirmed']


def test_early_strict_seed_is_completed_to_original_eight_only_after_pair_failure(monkeypatch):
    r,goals=setup(goal_x=.02);calls=[];side_counts=[0,0];pair_calls=0
    def fit(fn,seed,**kwargs):
        nonlocal pair_calls
        size=len(seed);calls.append((size,kwargs['max_nfev']))
        if size==7:
            # First two calls are the strict left/right answers; later calls
            # are exactly the seven remaining original seeds on each side.
            side=0 if sum(side_counts)==0 or (sum(side_counts)>=2 and side_counts[0]<8) else 1
            side_counts[side]+=1
            q=np.zeros(7);q[0]=.02+.02*(side_counts[side]%3)
            if side_counts[side]==1:q[0]=.02
            return SimpleNamespace(x=q,nfev=1)
        pair_calls+=1
        return SimpleNamespace(x=np.zeros(14) if pair_calls==1 else np.asarray(seed).copy(),nfev=1)
    monkeypatch.setattr(module,'least_squares',fit)
    r._rigid_grasp_error=lambda data:{'position_m':.016,'rotation_rad':0.}
    with pytest.raises(Fault,match='coupled_ik_unreachable') as failed:r.solve_pair(goals)
    assert [size for size,_ in calls].count(7)==16
    assert [size for size,_ in calls].count(14)==5
    assert all(budget<=60 for size,budget in calls if size==14)
    assert len(failed.value.detail['coupled_multistart_attempts'])==4
    assert failed.value.detail['rigid_grasp_error']['position_m']==pytest.approx(.016)


def test_default_off_preserves_original_failure_and_fit_budget(monkeypatch):
    r,goals=setup(enabled=False);fit,calls=fake_fit()
    monkeypatch.setattr(module,'least_squares',fit)
    with pytest.raises(Fault,match='coupled_ik_unreachable') as failed:r.solve_pair(goals)
    assert [size for size,_ in calls].count(14)==1
    assert 'coupled_multistart_attempts' not in failed.value.detail
    assert not any(name=='place_coupled_multistart' for name,_ in r.events)


@pytest.mark.parametrize('scope',['transport','retained','unheld'])
def test_multistart_is_not_used_outside_loaded_place_scope(monkeypatch,scope):
    r,goals=setup();fit,calls=fake_fit()
    monkeypatch.setattr(module,'least_squares',fit)
    if scope=='transport':r.fsm_state=State.TRANSPORT_TRAY
    if scope=='retained':r.retained_contact=(0,'left')
    if scope=='unheld':r.holding=None
    if scope=='unheld':
        r.solve_pair(goals)
    else:
        with pytest.raises(Fault):r.solve_pair(goals)
    assert [size for size,_ in calls].count(14)<=1
