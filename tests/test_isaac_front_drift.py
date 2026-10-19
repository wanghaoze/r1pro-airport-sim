import numpy as np
from r1pro_teleop.real2sim.isaac_front_drift import front_drift_check

TABLE=dict(table_id='front_left',center_world=[.85,0,0],dimensions_m=[1.2,.6,.8],yaw_world=np.pi/2)


def test_actual_false_side_stop_is_within_existing_drift_authorization():
    result=front_drift_check(TABLE,[.3201575,-.60011798],[.321714,-.5901272])
    assert result['allowed'] and not result['front_actual_strict']
    assert result['front_reference_strict'] and result['front_allowance_used']
    assert .010<result['front_drift_m']<.011


def test_drift_cannot_authorize_a_planned_side_station():
    result=front_drift_check(TABLE,[.32,-.62],[.32,-.62])
    assert not result['allowed'] and not result['front_reference_strict']


def test_fixed_reference_prevents_accumulating_small_moves_past_five_cm():
    assert front_drift_check(TABLE,[.32,.049],[.32,0])['allowed']
    assert not front_drift_check(TABLE,[.32,.051],[.32,0])['allowed']
    assert not front_drift_check(TABLE,[.36,.04],[.32,0])['allowed']


def test_runtime_does_not_reanchor_to_a_creeping_command():
    from types import SimpleNamespace
    from r1pro_teleop.real2sim.isaac_three_tray_runtime import NativeRuntime
    r=NativeRuntime.__new__(NativeRuntime);r.world=SimpleNamespace(current_time=5.)
    r._last_obs_time=5.;r._last_obs=dict(state=np.zeros(19),robot_position=np.array([.32,0.,0.]))
    r.command=np.zeros(19);r.command[16]=.32;r.base_origin=np.zeros(3)
    r.context=TABLE;r.tables=[TABLE];r.manipulating=True
    assert r.observation()['front_region_ok']
    r.command[17]=.04;r._last_obs['robot_position'][1]=.04
    assert r.observation()['front_region_ok']
    r.command[17]=.08;r._last_obs['robot_position'][1]=.08
    result=r.observation()
    assert not result['front_region_ok'] and result['front_drift_m']==.08
    assert np.array_equal(result['front_reference_xy'],[.32,0.])
