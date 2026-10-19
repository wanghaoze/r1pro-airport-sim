from types import SimpleNamespace
import numpy as np
import pytest
from r1pro_teleop.airport_fsm.contracts import Config, Fault
from r1pro_teleop.airport_fsm.primitives import retime_push_to_budget
from r1pro_teleop.airport_fsm.trajectory import CruiseJointPath


def test_budget_retime_keeps_geometry_and_rechecks_lower_dynamic_reference():
    path = CruiseJointPath([np.zeros(16), np.full(16,.02)],1.,2.,20.,2.)
    checks=[];events=[]
    r=SimpleNamespace(cfg=Config(),audit_online_reference=lambda q,v,a:checks.append((q,v,a)),
                      trace=SimpleNamespace(event=lambda *a,**k:events.append(k)))
    actual, frames=retime_push_to_budget(r,(path,49),2.9)
    assert actual is path and frames==58 and frames+2==60
    assert len(checks)==21 and len(events)==1
    for u,(q,v,a) in zip(np.linspace(0,1,21),checks):
        old=path.evaluate(u,2.45)
        np.testing.assert_allclose(q,old[0])
        np.testing.assert_allclose(v,old[1]*2.45/2.9)
        np.testing.assert_allclose(a,old[2]*(2.45/2.9)**2)


def test_retime_cannot_hide_inverse_dynamics_rejection():
    path=CruiseJointPath([np.zeros(16),np.full(16,.02)],1.,2.,20.,2.)
    def reject(*args):raise Fault('inverse_dynamics_overload')
    r=SimpleNamespace(cfg=Config(),audit_online_reference=reject)
    with pytest.raises(Fault,match='inverse_dynamics_overload'):
        retime_push_to_budget(r,(path,49),2.9)
    assert retime_push_to_budget(r,(path,58),2.9)==(path,58)


def test_transport_align_retime_declares_stage_and_reserves_verification():
    path=CruiseJointPath([np.zeros(16),np.full(16,.02)],1.,2.,20.,2.)
    events=[]
    r=SimpleNamespace(cfg=Config(primitive_settle_s=.1),audit_online_reference=lambda *args:None,
        trace=SimpleNamespace(event=lambda name,**kw:events.append((name,kw))))
    assert retime_push_to_budget(r,(path,42),2.9,event_name='primitive_transport_align_budget_retime')[1]==58
    assert events[0][0]=='primitive_transport_align_budget_retime'
    assert events[0][1]['verification_reserve_s']==.1
    assert Config().validate().transport_align_use_full_budget is False
    with pytest.raises(ValueError):Config(transport_align_use_full_budget=1).validate()
    with pytest.raises(ValueError):Config(transport_align_use_full_budget=True,fixed_primitives=False).validate()
