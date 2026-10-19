from types import SimpleNamespace
import numpy as np
from r1pro_teleop.airport_fsm.trajectory import TimedJointPath, BlendedJointPath, CruiseJointPath
from r1pro_teleop.airport_fsm.runtime import Runtime
from r1pro_teleop.airport_fsm.contracts import Config


def test_safe_continuous_alternative_to_cubic_joint_overshoot():
    points=np.zeros((3,16));points[:,0]=[.98,.985,.97]
    caps=[np.ones(16)*x for x in (1.,3.,30.)]
    low=np.full(14,-.985);high=np.full(14,.985+1e-9)
    runtime=SimpleNamespace(_target_valid=lambda *a,**k:True)
    cubic=TimedJointPath(points,*caps)
    blend=BlendedJointPath(points,*caps)
    assert Runtime._path_rejection(runtime,cubic,200,low,high,False)['reason']=='joint_limit'
    assert Runtime._path_rejection(runtime,blend,200,low,high,False) is None


def test_continuous_alternative_still_rejects_interior_collision():
    points=np.zeros((2,16));points[1,0]=.2
    path=BlendedJointPath(points,1.,3.,30.)
    runtime=SimpleNamespace(_target_valid=lambda q,**k:not .08<q[0]<.12,
        _shadow=lambda q:q,collision=lambda *a,**k:{'test_collision':True},
        camera_guard=lambda _:True,_rigid_grasp_error=lambda _:None)
    reason=Runtime._path_rejection(runtime,path,100,np.full(14,-1.),np.full(14,1.),True)
    assert reason['reason']=='collision_or_grasp_or_camera'
    assert reason['collision']['test_collision']


def test_new_modes_are_opt_in():
    assert Config().trajectory_mode=='legacy'
    assert not Config().adaptive_push_distance
    assert Config(trajectory_mode='hybrid',adaptive_push_distance=True).validate()


def test_cruise_preserves_endpoints_and_analytical_limits():
    rng=np.random.default_rng(3)
    points=np.cumsum(rng.uniform(-.2,.2,(6,4)),axis=0)
    caps=(np.full(4,.8),np.full(4,2.),np.full(4,20.))
    path=CruiseJointPath(points,*caps)
    q,v,a,j=path.evaluate(np.linspace(0,1,10001))
    np.testing.assert_allclose(q[0],points[0],atol=1e-10)
    np.testing.assert_allclose(q[-1],points[-1],atol=1e-10)
    for derivative,cap in zip((v,a,j),caps):assert np.all(abs(derivative)<=cap+1e-9)
    for boundary in (path.ramp,1-path.ramp):
        for before,after in zip(path.evaluate(boundary-1e-10)[:3],path.evaluate(boundary+1e-10)[:3]):
            np.testing.assert_allclose(before,after,atol=1e-7)
    assert np.max(abs(v[[0,-1]]))<1e-10
    assert np.max(abs(a[[0,-1]]))<1e-10


def test_long_cruise_reaches_speed_early_without_raising_velocity_cap():
    path=CruiseJointPath([[0.],[1.]],.1,2.,20.,minimum_seconds=10.)
    old=TimedJointPath([[0.],[1.]],.1,2.,20.,minimum_seconds=18.75)
    assert path.duration<old.duration
    speeds=path.evaluate(np.linspace(.2,.8,20))[1][:,0]
    np.testing.assert_allclose(speeds,.1,rtol=1e-4)


def test_base_cruise_translation_norm_and_yaw_share_progress():
    for distance,angle in ((1.3,.7),(0.,1.8),(.8,0.)):
        caps=(np.array([.3,.5]),np.array([.4,.6]),np.array([1.5,2.]))
        p=CruiseJointPath([[0.,0.],[distance,angle]],*caps)
        q,*derivatives=p.evaluate(np.linspace(0,1,10001))
        for derivative,cap in zip(derivatives,caps):assert np.all(abs(derivative)<=cap+1e-9)
        if distance and angle:np.testing.assert_allclose(q[:,0]/distance,q[:,1]/angle,atol=1e-10)
