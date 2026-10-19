from collections import Counter
from types import SimpleNamespace
import numpy as np
import pytest
from r1pro_teleop.airport_fsm.runtime import Runtime
from r1pro_teleop.airport_fsm.contracts import Config, Fault
from test_reachability_planner import runtime


def navigation_fixture(valid):
    r=object.__new__(Runtime)
    r.cfg=Config();r.trace=None;r.holding=0;r.spec={'aisle_gap_m':1.}
    r.g=SimpleNamespace(origin=np.zeros(3),belt_length=2.4,
                        to_belt=lambda p:np.array(p),to_world=lambda p:np.array(p))
    r.observation=lambda:{'tray_pose':np.array([[0.,0.,.9],[-1.,0.,.8],[0.,1.,.8]])}
    checks=[];commands=[]
    r.sim=SimpleNamespace(base_state=lambda:np.zeros(3),set_base_world_target=lambda p:commands.append(p))
    def check(a,b):
        checks.append((np.asarray(a).tobytes(),np.asarray(b).tobytes()))
        return valid
    r._base_segment_valid=check
    def tick():raise RuntimeError('first physical tick')
    r.tick=tick
    return r,checks,commands


def test_identical_static_queries_reused_but_distinct_segments_checked():
    r,checks,commands=navigation_fixture(True)
    with pytest.raises(RuntimeError,match='first physical tick'):
        r.navigate(np.array([1.,0.,0.]))
    counts=Counter(checks)
    assert len(counts)>2 and max(counts.values())==1
    # The preferred escape is checked when routes are generated and queried
    # again when selected; exactly one real sweep serves these two requests.
    escape=(np.zeros(3).tobytes(),np.array([.18,0.,0.]).tobytes())
    assert counts[escape]==1
    assert commands[0][0]>0 and commands[0][1]==0


@pytest.mark.parametrize('valid', [False, True])
def test_next_navigation_rechecks_even_when_arguments_are_identical(valid):
    r,checks,_=navigation_fixture(valid)
    for _ in range(2):
        with pytest.raises(RuntimeError if valid else Fault,
                           match='first physical tick' if valid else 'no_collision_free_base_route'):
            r.navigate(np.array([1.,0.,0.]))
    assert len(set(checks))>2
    assert set(Counter(checks).values())=={2}


def test_shadow_reads_contact_forces_once_for_both_hands(runtime, monkeypatch):
    r=runtime;r.allowed_tray=0
    evidence=r.observation();calls=[]
    monkeypatch.setattr(r,'observation',lambda:(calls.append(1) or evidence))
    r._shadow(r.sim.target)
    assert len(calls)==1
    calls.clear();r.allowed_tray=None
    r._shadow(r.sim.target)
    assert calls==[]
