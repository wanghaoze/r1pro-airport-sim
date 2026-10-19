"""Completion-first is an explicit bounded policy, never strict compliance."""
from types import SimpleNamespace
import numpy as np
import pytest
from r1pro_teleop.airport_fsm.contracts import Config, Fault, State
from r1pro_teleop.airport_fsm.runtime import Runtime


def runtime(profile='completion_first'):
    r=Runtime.__new__(Runtime)
    r.cfg=Config(acceptance_profile=profile,retained_support_integer_clock_enabled=True).validate()
    r.physics_step_count=0;r.physics_clock_origin_time=0.;r.physics_clock_timestep=.002
    r.retained_support_missing_step=None;r.retained_support_missing_since=None
    r.completion_speed_since_step=None;r.strict_runtime_passed=True
    r.soft_guard_violation_count=0;r.soft_guard_violation_by_code={}
    r.soft_guard_violation_maxima={};r.soft_guard_last_step_by_code={}
    r.m=SimpleNamespace(opt=SimpleNamespace(timestep=.002))
    r.d=SimpleNamespace(time=0.,qpos=np.zeros(17),qvel=np.zeros(17),
        warning=[SimpleNamespace(number=0)],actuator_force=np.zeros(1),actuator_velocity=np.zeros(1))
    r.previous_warning=np.zeros(1);r.dofs=np.arange(14);r.base_dofs=np.arange(14,17)
    r.actual_velocity_cap=np.ones(14);r.peak_power=0.;r.power_cap=None;r.holding=None
    r.collision=lambda:None;r.camera_guard=lambda **kw:True
    r.retained_contact=(0,'left');r.sim=SimpleNamespace(target=np.zeros(16))
    r.g=SimpleNamespace(support_table=lambda pose:'table',tables={'table':{'dimensions_m':[1,1,.8]}})
    e={'floor_contact':np.zeros(1),'max_penetration':0.,'gripper_contact_force':np.ones((1,2)),
       'table_contact':np.ones(1),'support_contact':np.ones(1),'min_z':np.array([.8001]),
       'tray_pose':np.array([[0,0,.8,1,0,0,0.]])}
    r.observation=lambda:e;r.events=[];r.trace=SimpleNamespace(event=lambda name,**kw:r.events.append((name,kw)))
    return r,e


def at_step(r,step):
    r.physics_step_count=step;r.d.time=step*.002


def test_strict_default_rejects_original_overspeed_and_support_gap():
    assert Config().acceptance_profile=='strict'
    r,e=runtime('strict');r.d.qvel[0]=1.01001
    with pytest.raises(Fault,match='measured_joint_overspeed'):r.guard()
    assert r.strict_runtime_passed and r.soft_guard_violation_count==0
    r.d.qvel[0]=0.;e['table_contact'][0]=0;r.check_retained_contact()
    at_step(r,75);r.check_retained_contact()
    at_step(r,100)
    with pytest.raises(Fault,match='retained_contact_lost'):r.check_retained_contact()


def test_small_speed_excursion_records_original_failure_and_deduplicates():
    r,e=runtime();r.d.qvel[4]=1.02
    r.guard();r.guard()
    assert not r.strict_runtime_passed
    assert r.soft_guard_violation_count==1
    assert r.soft_guard_violation_by_code=={'measured_joint_overspeed':1}
    event=r.events[-1][1]
    assert event['code']=='measured_joint_overspeed'
    assert event['detail']['strict_ratio_max']==1.01
    assert event['detail']['completion_ratio_max']==1.05
    assert r.soft_guard_violation_maxima['measured_joint_overspeed']['ratio']==1.02
    at_step(r,1);r.guard()
    assert r.soft_guard_violation_count==2
    r.d.qvel[4]=1.;r.guard()
    assert r.completion_speed_since_step is None and not r.strict_runtime_passed


def test_speed_upper_ratio_and_duration_are_hard_boundaries():
    r,e=runtime();r.d.qvel[0]=1.05;r.guard()
    at_step(r,100);r.guard()  # exact .200 seconds since first observed excursion
    at_step(r,101)
    with pytest.raises(Fault,match='measured_joint_overspeed'):r.guard()
    r,e=runtime();r.d.qvel[0]=np.nextafter(1.05,np.inf)
    with pytest.raises(Fault,match='measured_joint_overspeed'):r.guard()
    assert r.soft_guard_violation_count==0


def test_switching_fast_joint_cannot_restart_continuous_excursion():
    r,e=runtime();r.d.qvel[0]=1.02;r.guard()
    at_step(r,90);r.d.qvel[0]=0.;r.d.qvel[4]=1.02;r.guard()
    assert r.completion_speed_since_step==0
    at_step(r,101)
    with pytest.raises(Fault,match='measured_joint_overspeed'):r.guard()


def test_support_extension_preserves_missing_origin_and_raw_contacts():
    r,e=runtime();e['table_contact'][0]=0;r.check_retained_contact()
    at_step(r,75);r.check_retained_contact()
    assert r.strict_runtime_passed
    at_step(r,100);r.check_retained_contact();r.check_retained_contact()
    assert not r.strict_runtime_passed and e['table_contact'][0]==0
    assert r.retained_support_missing_step==0 and r.soft_guard_violation_count==1
    at_step(r,150);r.check_retained_contact()
    assert r.soft_guard_violation_maxima['retained_contact_lost']['missing_seconds']==.30
    at_step(r,151)
    with pytest.raises(Fault,match='retained_contact_lost'):r.check_retained_contact()
    e['table_contact'][0]=1;r.check_retained_contact()
    assert r.retained_support_missing_step is None and not r.strict_runtime_passed


@pytest.mark.parametrize('change', ['gap','force','opening','outside_table'])
def test_support_policy_does_not_relax_geometry_or_pinch(change):
    r,e=runtime();e['table_contact'][0]=0;r.check_retained_contact();at_step(r,100)
    if change=='gap':e['min_z'][0]=.80201
    if change=='force':e['gripper_contact_force'][0,0]=.5
    if change=='opening':r.sim.target[7]=.1
    if change=='outside_table':r.g.support_table=lambda pose:None
    with pytest.raises(Fault,match='retained_contact_lost'):r.check_retained_contact()
    assert r.soft_guard_violation_count==0


def test_substep_contacts_do_not_reset_twenty_hz_support_timer():
    r,e=runtime();e['table_contact'][0]=0;r.check_retained_contact()
    at_step(r,90);e['table_contact'][0]=1;r.guard()  # no retained-contact observation here
    assert r.retained_support_missing_step==0
    e['table_contact'][0]=0;at_step(r,151)
    with pytest.raises(Fault,match='retained_contact_lost'):r.check_retained_contact()


@pytest.mark.parametrize('change,code',[
    ('nonfinite','nonfinite_physics'),('collision','illegal_collision'),
    ('floor','tray_on_floor'),('penetration','excess_penetration'),
    ('warning','mujoco_warning'),('base','measured_base_overspeed'),
    ('power','mechanical_power_cap'),('tilt','carried_tray_tilt'),
    ('bilateral','bilateral_contact_lost'),('camera','wrist_camera_front_guard'),
])
def test_completion_profile_retains_hard_physics_guards(change,code):
    r,e=runtime()
    if change=='nonfinite':r.d.qpos[0]=np.nan
    if change=='collision':r.collision=lambda:{'distance_m':-.1}
    if change=='floor':e['floor_contact'][0]=1
    if change=='penetration':e['max_penetration']=r.cfg.criteria.penetration_m+.0001
    if change=='warning':r.d.warning[0].number=1
    if change=='base':r.d.qvel[14]=100
    if change=='power':r.power_cap=1.;r.d.actuator_force[0]=2;r.d.actuator_velocity[0]=2
    if change=='camera':
        r.camera_guard=lambda **kw:False;r.camera_metrics=lambda **kw:{}
    if change=='bilateral':
        r.holding=0;r.fsm_state=State.PLACE_TRAY;r.lost_time=.12
        e['gripper_contact_force'][0,0]=0
    if change=='tilt':
        r.holding=0;r.fsm_state=State.PLACE_TRAY;r.initial_bottom=np.array([.8]);r.lost_time=0.
        e['tray_pose'][0,3:]=[np.cos(np.pi/8),np.sin(np.pi/8),0,0]
    with pytest.raises(Fault,match=code):r.guard()


def test_external_postcondition_recorder_keeps_permanent_strict_deviation():
    r,e=runtime()
    r.record_strict_deviation('primitive_postcondition_failed',{'yaw_error_deg':6.1})
    at_step(r,1);r.record_strict_deviation('primitive_postcondition_failed',{'yaw_error_deg':5.9})
    assert not r.strict_runtime_passed
    assert r.soft_guard_violation_count==2
    assert r.soft_guard_violation_maxima['primitive_postcondition_failed']['yaw_error_deg']==6.1
