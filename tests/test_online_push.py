import numpy as np
import pytest
pytest.importorskip('ruckig')
from r1pro_teleop.airport_fsm.online_push import OnlineJointReference


def test_retarget_preserves_momentum_and_brakes_within_limits():
    r=OnlineJointReference([0.,0.],[.5,.4],[1.,1.],[5.,5.],.05)
    r.target([1.,.7],.5)
    for _ in range(12):q,v,a,_=r.step()
    assert np.linalg.norm(v)>.1
    before=np.array(r.input.current_velocity)
    r.target([1.3,.9],.4)
    np.testing.assert_array_equal(r.input.current_velocity,before)
    previous_a=a.copy()
    for _ in range(12):
        q,v,a,_=r.step()
        assert np.all(abs(v)<=np.array([.5,.4])+1e-9)
        assert np.all(abs(a)<=1.+1e-9)
        assert np.all(abs(a-previous_a)/.05<=5.+1e-7)
        previous_a=a.copy()
    r.brake()
    for _ in range(100):
        q,v,a,finished=r.step()
        if finished:break
    assert finished and np.max(abs(v))<1e-8 and np.max(abs(a))<1e-8
