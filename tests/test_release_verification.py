"""Release verification consumes only the original primitive's remaining frames."""
from types import SimpleNamespace
import numpy as np
import pytest
from r1pro_teleop.airport_fsm.contracts import Fault
from r1pro_teleop.airport_fsm.primitives import finish_release_verification


def runtime(values, *, step=51, deadline=60, fault=None):
    r=SimpleNamespace(steps=step,primitive_deadline_step=deadline,
                      sim=SimpleNamespace(target=np.arange(16,dtype=float)),calls=0)
    r.events=[]
    r.trace=SimpleNamespace(event=lambda name,**fields:r.events.append((name,fields)))
    iterator=iter(values);r.latest=False
    def tick():
        assert r.steps<r.primitive_deadline_step
        r.calls+=1
        if fault:raise fault
        r.latest=next(iterator);r.steps+=1
    r.tick=tick;r.observation=lambda:{'placed':r.latest}
    return r


def test_terminal_first_good_frame_gets_one_guarded_hold():
    r=runtime([True]);target=r.sim.target.copy()
    assert finish_release_verification(r,lambda e:e['placed'],1)==2
    assert r.calls==1 and r.steps==52 and r.primitive_deadline_step==60
    np.testing.assert_array_equal(r.sim.target,target)
    assert r.events==[('primitive_release_verification_wait',dict(
        initial_stable_frames=1,final_stable_frames=2,wait_frames=1,remaining_frames=9,required=2))]


def test_unstable_contact_resets_count_and_cannot_extend_deadline():
    r=runtime([True,False,True],step=57)
    assert finish_release_verification(r,lambda e:e['placed'],0)==1
    assert r.calls==3 and r.steps==60 and r.primitive_deadline_step==60


def test_persistent_failure_uses_remaining_budget_without_success():
    r=runtime([False]*9)
    assert finish_release_verification(r,lambda e:e['placed'],1)==0
    assert r.calls==9 and r.steps==60


def test_exhausted_budget_does_not_step_or_manufacture_second_frame():
    r=runtime([],step=60)
    assert finish_release_verification(r,lambda e:e['placed'],1)==1
    assert r.calls==0
    assert r.events[0][1]['wait_frames']==0 and r.events[0][1]['remaining_frames']==0


def test_already_verified_does_not_add_wait():
    r=runtime([])
    assert finish_release_verification(r,lambda e:e['placed'],2)==2
    assert r.calls==0 and r.steps==51
    assert not r.events


def test_hold_preserves_physical_guard_failure():
    fault=Fault('measured_joint_overspeed');r=runtime([],fault=fault)
    with pytest.raises(Fault)as exc:finish_release_verification(r,lambda e:e['placed'],1)
    assert exc.value is fault and r.calls==1 and r.steps==51
