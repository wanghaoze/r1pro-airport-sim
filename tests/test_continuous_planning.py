from types import SimpleNamespace
import numpy as np
from r1pro_teleop.airport_fsm.runtime import Runtime
from r1pro_teleop.airport_fsm.machine import Machine
from r1pro_teleop.airport_fsm.contracts import Config


def test_preview_never_executes_even_when_shortcut_enabled():
    executed=[];target=np.zeros(16)
    r=SimpleNamespace(cfg=Config(free_space_joint_shortcut=True),
        sim=SimpleNamespace(target=target,tcp=lambda _: (np.zeros(3),np.eye(3))),
        solve_pair=lambda goals,seed:seed.copy(),_target_valid=lambda *a,**k:True,
        follow_joint_path=lambda *a,**k:executed.append(1),joints=lambda *a,**k:executed.append(1))
    points=Runtime.cartesian(r,{'left':(np.array([.01,0,0]),np.eye(3))},preview_only=True)
    assert not executed and len(points)==2
    np.testing.assert_array_equal(target,np.zeros(16))


def test_blocked_closure_keeps_separation_fallback():
    calls=[];m=Machine.__new__(Machine);m.c=Config(prefer_direct_grasp=True);m.pending_grasp_contact=None
    m.r=SimpleNamespace(rim_goals=lambda *a,**k:{},cartesian=lambda *a,**k:[np.zeros(16)],
        _target_valid=lambda *a,**k:False,joints=lambda *a,**k:calls.append('retreat'),tucked=np.zeros(16))
    m.log=SimpleNamespace(event=lambda *a,**k:None)
    m._poses=lambda:np.zeros((3,7))
    m.align=lambda *a,**k:(calls.append('align') or (0.,0.))
    m.separate_if_needed=lambda *a:calls.append('separate')
    assert m.prepare_pick(0,0)==(0.,0.)
    assert calls==['align','retreat','separate','align']
