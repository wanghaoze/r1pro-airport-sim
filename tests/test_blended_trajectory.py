import numpy as np
import pytest
from r1pro_teleop.airport_fsm.trajectory import BlendedJointPath,entry_limit_envelope

@pytest.mark.parametrize('seed',range(8))
def test_bounds_continuity_and_no_overshoot(seed):
    rng=np.random.default_rng(seed)
    points=np.cumsum(rng.uniform(-.1,.1,(12,5)),axis=0)
    limits=[np.full(5,x) for x in (.8,2.,12.)]
    path=BlendedJointPath(points,*limits)
    for i,(start,end) in enumerate(zip(path.knots[:-1],path.knots[1:])):
        q,*derivatives=path.evaluate(np.linspace(start,end,701))
        assert np.all(q>=np.minimum(points[i],points[i+1])-1e-9)
        assert np.all(q<=np.maximum(points[i],points[i+1])+1e-9)
        for d,cap in zip(derivatives,limits):assert np.all(np.max(abs(d),axis=0)<=cap+1e-7)
    for knot in path.knots[1:-1]:
        for left,right in zip(path.evaluate(knot-1e-10)[:3],path.evaluate(knot+1e-10)[:3]):
            assert np.allclose(left,right,atol=1e-5)
    for end in (0,1):
        assert np.max(abs(path.evaluate(end)[1]))<1e-9
        assert np.max(abs(path.evaluate(end)[2]))<1e-9

def test_through_motion_does_not_stop_at_each_waypoint():
    path=BlendedJointPath([[0.],[.1],[.2],[.3]],1.,3.,30.)
    for knot in path.knots[1:-1]:assert path.evaluate(knot)[1][0]>.01

def test_stationary_path():
    path=BlendedJointPath([[1.,2.],[1.,2.]],1.,2.,3.)
    q,v,a,j=path.evaluate(np.linspace(0,1,10))
    assert np.allclose(q,[1.,2.]) and np.max(abs(v))==0

def test_margin_entry_does_not_allow_new_outward_targets():
    lo,hi=entry_limit_envelope([[.999],[.9],[.8]],[-1],[1],.015)
    assert hi[0]<1 and lo[0]>-1
    with pytest.raises(ValueError):entry_limit_envelope([[.999],[.9995]],[-1],[1],.015)
    with pytest.raises(ValueError):entry_limit_envelope([[1.01],[.8]],[-1],[1],.015)

def test_near_stationary_ik_knot_does_not_stretch_whole_path():
    path=BlendedJointPath([[0.],[.1],[.10001],[.2]],1.,3.,30.)
    assert path.duration<3.
