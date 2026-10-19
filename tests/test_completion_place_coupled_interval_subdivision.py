"""A failed coupled Cartesian knot may be split only in the declared place scope."""
from dataclasses import replace
from types import SimpleNamespace
import numpy as np
import pytest

from r1pro_teleop.airport_fsm.contracts import Config, Fault, State
from r1pro_teleop.airport_fsm.runtime import Runtime


def runtime(*, enabled=True):
    r=Runtime.__new__(Runtime)
    r.cfg=Config(acceptance_profile='completion_first',
        retained_support_integer_clock_enabled=True,
        completion_place_coupled_interval_subdivision_enabled=enabled)
    r.holding=0;r.retained_contact=None;r.fsm_state=State.PLACE_TRAY
    r.sim=SimpleNamespace(target=np.zeros(16),
        tcp=lambda side:(np.zeros(3),np.eye(3)))
    r.events=[];r.trace=SimpleNamespace(event=lambda name,**detail:r.events.append((name,detail)))
    r._target_valid=lambda *args,**kwargs:True
    return r


def goals():
    return {side:(np.array([.05,0.,0.]),np.eye(3)) for side in ('left','right')}


def test_original_qualified_route_has_exact_legacy_knots_and_no_extra_solve():
    r=runtime();calls=[]
    def solve(request,seed):
        x=request['left'][0][0];calls.append(x)
        q=np.array(seed,copy=True);q[0]=x;return q
    r.solve_pair=solve
    points=r.cartesian(goals(),preview_only=True,wrist=True)
    assert calls==pytest.approx([.025,.05])
    assert [p[0] for p in points]==pytest.approx([0.,.025,.05])
    assert not r.events


def test_coupled_failure_splits_one_interval_and_complete_path_is_returned():
    r=runtime();calls=[]
    def solve(request,seed):
        x=request['left'][0][0];calls.append((x,float(seed[0])))
        if abs(x-.025)<1e-10 and seed[0]==0.:
            raise Fault('coupled_ik_unreachable',recoverable=True)
        q=np.array(seed,copy=True);q[0]=x;return q
    r.solve_pair=solve
    points=r.cartesian(goals(),preview_only=True,wrist=True)
    assert [x for x,_ in calls]==pytest.approx([.025,.0125,.025,.05])
    assert [p[0] for p in points]==pytest.approx([0.,.0125,.025,.05])
    event=next(detail for name,detail in r.events if name=='cartesian_coupled_interval_subdivision')
    assert event['subdivisions']==1 and event['qualified'] and not event['executed']
    np.testing.assert_array_equal(r.sim.target,np.zeros(16))


def test_depth_four_is_hard_ceiling_and_failure_never_returns_partial_path():
    r=runtime();calls=[]
    def fail(request,seed):
        calls.append(request['left'][0][0])
        raise Fault('coupled_ik_unreachable',recoverable=True)
    r.solve_pair=fail
    with pytest.raises(Fault,match='coupled_ik_unreachable'):
        r.cartesian(goals(),preview_only=True,wrist=True)
    assert len(calls)==5 # original, then four left-half retries
    assert calls==pytest.approx([.025,.0125,.00625,.003125,.0015625])
    event=next(detail for name,detail in r.events if name=='cartesian_coupled_interval_subdivision')
    assert event['subdivisions']==4 and not event['qualified'] and not event['executed']
    np.testing.assert_array_equal(r.sim.target,np.zeros(16))


@pytest.mark.parametrize('scope',['flag','profile','state','holding','retained','single_arm','nonrecoverable'])
def test_no_subdivision_outside_declared_scope(scope):
    r=runtime();calls=[]
    if scope=='flag':r.cfg=replace(r.cfg,completion_place_coupled_interval_subdivision_enabled=False)
    if scope=='profile':r.cfg=replace(r.cfg,acceptance_profile='strict',
        completion_place_coupled_interval_subdivision_enabled=False)
    if scope=='state':r.fsm_state=State.TRANSPORT_TRAY
    if scope=='holding':r.holding=None
    if scope=='retained':r.retained_contact=(0,'left')
    selected=goals() if scope!='single_arm' else {'left':goals()['left']}
    def fail(request,seed):
        calls.append(request['left'][0][0])
        raise Fault('coupled_ik_unreachable',recoverable=(scope!='nonrecoverable'))
    r.solve_pair=fail
    with pytest.raises(Fault,match='coupled_ik_unreachable'):
        r.cartesian(selected,preview_only=True,wrist=True)
    assert len(calls)==1 and not r.events


def test_existing_branch_jump_subdivision_is_unchanged_when_new_flag_off():
    r=runtime(enabled=False);calls=[]
    def solve(request,seed):
        x=request['left'][0][0];calls.append((x,float(seed[0])))
        if abs(x-.025)<1e-10 and seed[0]==0.:
            raise Fault('ik_branch_jump',recoverable=True)
        q=np.array(seed,copy=True);q[0]=x;return q
    r.solve_pair=solve
    r.cartesian(goals(),preview_only=True,wrist=True)
    assert [x for x,_ in calls]==pytest.approx([.025,.0125,.025,.05])
    assert [name for name,_ in r.events]==['cartesian_branch_subdivision']
