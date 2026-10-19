from types import SimpleNamespace
import numpy as np
import pytest
from r1pro_teleop.airport_fsm import primitives as p
from r1pro_teleop.airport_fsm.contracts import Config,Fault


def setup(monkeypatch,reasons):
    calls=[];events=[]
    def plan(r,points,**kw):
        calls.append((points.copy(),kw))
        reason=reasons[len(calls)-1]
        if reason:raise Fault('primitive_path_infeasible',{'candidates':[{'reason':reason}]})
        return 'path',58
    monkeypatch.setattr(p,'plan',plan)
    r=SimpleNamespace(trace=SimpleNamespace(event=lambda name,**kw:events.append(kw)))
    points=np.zeros((4,16));points[-1]=1;points[1,:7]=.3
    return r,points,calls,events


def invoke(r,points):
    return p.plan_withdraw_path(r,points,np.zeros(16),np.ones(16),np.arange(7),available=2.9,extra_path_check='normal')


def test_existing_feasible_path_is_unchanged(monkeypatch):
    r,points,calls,events=setup(monkeypatch,[None])
    assert invoke(r,points)==('path',58)
    assert len(calls)==1 and not events
    np.testing.assert_array_equal(points,calls[0][0])


def test_only_duration_rejection_enables_bounded_path_alternatives(monkeypatch):
    r,points,calls,events=setup(monkeypatch,['duration',None])
    assert invoke(r,points)==('path',58)
    np.testing.assert_array_equal(calls[1][0][[0,2,3]],points[[0,2,3]])
    np.testing.assert_allclose(calls[1][0][1,:7],.45)
    np.testing.assert_allclose(points[1,:7],.3)
    assert all(c[1]['available']==2.9 and c[1]['extra_path_check']=='normal' and not c[1]['allow_shortcut'] for c in calls)
    assert events[0]['selected_fraction']==.45


def test_original_geometry_rejection_does_not_trigger_search(monkeypatch):
    r,points,calls,events=setup(monkeypatch,['collision'])
    with pytest.raises(Fault):invoke(r,points)
    assert len(calls)==1 and not events


def test_at_most_two_alternatives_and_exhaustion_remains_failure(monkeypatch):
    r,points,calls,events=setup(monkeypatch,['duration','collision','duration'])
    with pytest.raises(Fault):invoke(r,points)
    assert len(calls)==3 and events[0]['selected_fraction'] is None
    np.testing.assert_allclose(calls[2][0][1,:7],.6)


def test_config_opt_in_and_fixed_only():
    assert not Config().push_withdraw_path_search_enabled
    with pytest.raises(ValueError):Config(push_withdraw_path_search_enabled=1).validate()
    with pytest.raises(ValueError):Config(push_withdraw_path_search_enabled=True,fixed_primitives=False).validate()
