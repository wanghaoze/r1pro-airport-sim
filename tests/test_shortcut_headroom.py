"""Normal shortcut timing compatibility never disables physical guards."""
from dataclasses import replace,asdict
from types import SimpleNamespace
import numpy as np
import pytest
from r1pro_teleop.airport_fsm.contracts import Config,Fault,minimum_duration
from r1pro_teleop.airport_fsm.runtime import Runtime
from test_empty_arm_fallback import fake


def normal(enabled=None):
    r=fake()
    if enabled is not None:r.cfg=replace(r.cfg,empty_arm_shortcut_headroom_enabled=enabled)
    r.v=np.ones(16);r.a=np.ones(16)*2;r.j=np.ones(16)*8
    def solve(goals,seed,free_endpoint=False):
        result=seed.copy();result[0]=1.;return result
    r.solve_pair=solve
    calls=[];events=[];r.joints=lambda q,**kw:calls.append((q.copy(),kw))
    r.trace=SimpleNamespace(event=lambda event,**kw:events.append(dict(event=event,**kw)))
    return r,calls,events


@pytest.mark.parametrize('enabled',[None,True,False])
def test_default_equals_v26_and_false_uses_exact_historical_minimum(enabled):
    r,calls,events=normal(enabled);before=[x.copy() for x in (r.v,r.a,r.j)]
    distance=.02;speed=.2
    r.cartesian({'left':(np.array([distance,0,0]),np.eye(3))},speed=speed)
    q,kwargs=calls[0];old=max(.15,1.875*distance/speed)
    expected=old if enabled is False else max(old,minimum_duration(q,r.v*.5,r.a*.5,r.j*.5))
    assert kwargs['minimum_seconds']==expected
    for a,b in zip(before,(r.v,r.a,r.j)):np.testing.assert_array_equal(a,b)
    timing=next(e for e in events if e['event']=='empty_arm_shortcut_timing')
    assert timing['headroom_applied']==(enabled is not False) and not timing['endpoint_fallback']


def test_false_never_changes_failed_ik_endpoint_fallback_headroom():
    r=fake();r.cfg=replace(r.cfg,empty_arm_shortcut_headroom_enabled=False)
    r.v=np.ones(16);r.a=np.ones(16)*2;r.j=np.ones(16)*8;calls=[]
    r.joints=lambda q,**kw:calls.append((q.copy(),kw))
    r.cartesian({'left':(np.array([.02,0,0]),np.eye(3))},speed=.2)
    q,kw=calls[0]
    assert kw['minimum_seconds']==max(.1875,minimum_duration(q,r.v*.5,r.a*.5,r.j*.5))


def test_config_boolean_and_single_field_ablation():
    assert Config().validate().empty_arm_shortcut_headroom_enabled is True
    with pytest.raises(ValueError):Config(empty_arm_shortcut_headroom_enabled=1).validate()
    a=asdict(Config());b=asdict(replace(Config(),empty_arm_shortcut_headroom_enabled=False))
    assert [k for k in a if a[k]!=b[k]]==['empty_arm_shortcut_headroom_enabled']


@pytest.mark.parametrize('enabled',[True,False])
def test_actual_runtime_overspeed_guard_runs_on_shortcut_execution(enabled):
    r,_,_=normal(enabled)
    # Run the real joints() path/timing loop and its tick boundary; only the
    # physical observation is a fixture with a deliberately over-cap velocity.
    del r.joints
    r.allowed_tray=None
    r.m=SimpleNamespace(jnt_range=np.tile([-3.,3.],(14,1)));r.jids=np.arange(14)
    r._inverse_ratio=lambda *args:1.;r.id_slowdowns=0
    r.d=SimpleNamespace(qpos=np.zeros(14),qvel=np.ones(14)*1.02,time=0.,warning=[],actuator_force=np.zeros(14),actuator_velocity=np.zeros(14))
    r.dofs=np.arange(14);r.actual_velocity_cap=np.ones(14);r.previous_warning=np.array([])
    r.collision=lambda *args,**kw:None
    r.observation=lambda:{'gripper_contact_force':np.zeros((3,2)),'floor_contact':np.zeros(3),'max_penetration':0.,'tray_pose':np.zeros((3,7)),'min_z':np.ones(3)}
    calls=[]
    def tick():calls.append(True);Runtime.guard(r)
    r.tick=tick
    with pytest.raises(Fault,match='measured_joint_overspeed'):
        r.cartesian({'left':(np.array([.02,0,0]),np.eye(3))},speed=.2)
    assert calls==[True]
