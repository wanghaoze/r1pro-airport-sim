import numpy as np
from types import SimpleNamespace
from r1pro_teleop.airport_fsm.geometry import carried_pose_at_base,rz
from r1pro_teleop.airport_fsm.runtime import Runtime


def test_measured_carry_preserves_sag_and_tilt_during_turn():
    p=np.array([1.,0.,.94]);R=rz(.2);base=np.zeros(3)
    out,Q=carried_pose_at_base(p,R,base,[2.,3.,np.pi/2])
    assert np.allclose(out,[2.,4.,.94])
    assert np.allclose(Q,rz(np.pi/2)@R)
    assert np.array_equal(p,[1.,0.,.94])


def test_measured_carry_wraparound_is_short_rotation():
    p,Q=carried_pose_at_base([1,0,.94],np.eye(3),[0,0,np.pi-.01],[0,0,-np.pi+.01])
    assert np.allclose(p,rz(.02)@np.array([1,0,.94]))


def test_base_route_rejects_measured_envelope_even_if_command_is_clear():
    r=object.__new__(Runtime);r.holding=0;r.sim=SimpleNamespace(target=np.zeros(16))
    r._target_valid=lambda *a,**k:True
    r._measured_payload_clear=lambda p:p[0]<.05
    assert not r._base_segment_valid(np.zeros(3),np.array([.1,0,0]))


def test_empty_base_route_does_not_require_payload_envelope():
    r=object.__new__(Runtime);r.holding=None;r.sim=SimpleNamespace(target=np.zeros(16))
    r._target_valid=lambda *a,**k:True
    r._measured_payload_clear=lambda p:(_ for _ in ()).throw(AssertionError('unexpected payload'))
    assert r._base_segment_valid(np.zeros(3),np.array([.1,0,0]))


def test_branch_subdivision_plans_before_any_motion():
    from r1pro_teleop.airport_fsm.contracts import Config,Fault
    r=object.__new__(Runtime);r.cfg=Config();r.trace=None
    r.sim=SimpleNamespace(target=np.zeros(16),tcp=lambda s:(np.zeros(3),np.eye(3)))
    r._target_valid=lambda *a,**k:True
    def solve(goals,seed):
        value=goals['left'][0][0]
        if abs(value-seed[0])>.0126:raise Fault('ik_branch_jump',recoverable=True)
        q=seed.copy();q[0]=value;return q
    r.solve_pair=solve
    r.tick=lambda:(_ for _ in ()).throw(AssertionError('preview must not execute'))
    path=r.cartesian({'left':(np.array([.05,0,0]),np.eye(3))},preview_only=True)
    assert np.isclose(path[-1][0],.05)
    assert np.max(abs(np.diff(np.array(path)[:,0])))<=.0126
    assert np.array_equal(r.sim.target,np.zeros(16))


def test_branch_subdivision_has_finite_budget():
    import pytest
    from r1pro_teleop.airport_fsm.contracts import Config,Fault
    r=object.__new__(Runtime);r.cfg=Config();r.trace=None
    r.sim=SimpleNamespace(target=np.zeros(16),tcp=lambda s:(np.zeros(3),np.eye(3)))
    calls=[]
    def solve(*args):
        calls.append(1);raise Fault('ik_branch_jump',recoverable=True)
    r.solve_pair=solve
    with pytest.raises(Fault,match='ik_branch_jump'):
        r.cartesian({'left':(np.array([.05,0,0]),np.eye(3))},preview_only=True)
    assert len(calls)==5
