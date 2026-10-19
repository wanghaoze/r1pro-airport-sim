"""Free-run is a separate raw servo integrator; task faults cannot truncate it."""
from types import SimpleNamespace
import numpy as np
import mujoco as mj
import pytest
from r1pro_teleop.single_tray_3table.free_run_runtime import FreeRunRuntime
from r1pro_teleop.single_tray_3table.control import ThreeTableRuntime
from r1pro_teleop.airport_fsm.contracts import Fault,State
from r1pro_teleop.airport_fsm.runtime import Runtime
import time


def actual_runtime(monkeypatch):
    joints=''.join(f'<body name="b{i}" pos="0 0 {i*.1}"><joint name="j{i}" axis="0 1 0"/><geom type="sphere" size=".02" mass="1"/></body>' for i in range(19))
    actuators=''.join(f'<position joint="j{i}" kp="25" ctrllimited="true" ctrlrange="-.25 .25" forcelimited="true" forcerange="-40 40"/>' for i in range(19))
    model=mj.MjModel.from_xml_string(f'<mujoco><option timestep=".002" gravity="0 0 0"/><worldbody><body name="base_link">{joints}</body><body name="tray" pos=".85 .05 .801"><geom type="box" size=".28 .215 .05"/></body></worldbody><actuator>{actuators}</actuator></mujoco>')
    data=mj.MjData(model);mj.mj_forward(model,data)
    class Sim:
        target=np.zeros(16,np.float32);base_target=np.zeros(3,np.float32);nstep=25
        def state(self):return data.qpos[:16].copy()
        def base_state(self):return data.qpos[16:].copy()
        def apply_target(self):data.ctrl[:]=np.r_[self.target,self.base_target]
    r=FreeRunRuntime.__new__(FreeRunRuntime);r.m=model;r.d=data;r.mj=mj;r.sim=Sim()
    r.cfg=SimpleNamespace(fps=20,criteria=SimpleNamespace(penetration_m=.003),completion_collision_penetration_m=.02,
        base_speed=.4,base_yaw_speed=.8,limit_fraction=1.,max_episode_seconds=0.,max_attempt_wall_seconds=0.,
        primitive_seconds=0.,substep_control_enabled=False)
    r.steps=0;r.physics_step_count=0;r.integration_spec=mj.mjtState.mjSTATE_INTEGRATION
    r.integration_size=mj.mj_stateSize(model,r.integration_spec);r.fsm_state=State.GRASP_TRAY;r.phase='free_run_pick_empty'
    r.allowed_tray=0;r.target_slot=0;r.recovery=False;r.holding=None;r.dofs=np.arange(14);r.base_dofs=np.arange(16,19)
    r.actual_velocity_cap=np.ones(14);r.power_cap=None;r.primitive_deadline_step=0
    r.record_ctrl_substeps=True;r.wall_start=time.monotonic()
    rows=[];r.trace=SimpleNamespace(append=lambda row:rows.append(row))
    r.observation=lambda:dict(tray_pose=np.array([[0,0,.8,1,0,0,0]]),min_z=np.array([.8]),gripper_contact_force=np.zeros((1,2)),
        max_penetration=np.float64(.004),floor_contact=np.array([1]),support_contact=np.array([1]))
    r.collision=lambda:dict(pair='actual diagnostic collision');r.camera_guard=lambda **kw:True
    r._check_measured_arm_speed=lambda *args:None
    def task_fault(self):raise Fault('illegal_collision',{'pair':'diagnostic'})
    monkeypatch.setattr(ThreeTableRuntime,'guard',task_fault)
    r.check_retained_contact=lambda:(_ for _ in ()).throw(Fault('retained_contact_lost'))
    r._setup_diagnostics();return r,rows


def test_real_mujoco_four_ticks_continue_after_collision_retained_and_deadline_faults(monkeypatch):
    r,rows=actual_runtime(monkeypatch)
    for _ in range(4):r.apply_model_target(np.zeros(19));r.tick()
    assert r.steps==4 and r.physics_step_count==100 and r.d.time==pytest.approx(.2)
    assert len(rows)==4 and all(row['transition_completed'] for row in rows)
    assert all(row['executed_substeps']==25 and row['ctrl_substeps'].shape==(25,19) for row in rows)
    assert rows[0]['sim_time']==0 and rows[1]['sim_time']==pytest.approx(.05)
    checks={x['name']:x for x in r.diagnostic_last_frame[-1]['checks']}
    assert checks['original_runtime_guard']['code']=='illegal_collision'
    assert checks['retained_contact']['code']=='retained_contact_lost'
    assert checks['episode_simulation_budget']['passed'] is False
    assert r.diagnostic_fault_count>0


def test_finite_outside_bounds_is_raw_servo_target_with_original_mujoco_motor_caps(monkeypatch):
    r,rows=actual_runtime(monkeypatch);raw=np.ones(19,np.float32)
    r.apply_model_target(raw);r.tick()
    np.testing.assert_array_equal(r.last_model_raw_action19,raw)
    np.testing.assert_array_equal(rows[0]['action'],raw[:16]);np.testing.assert_array_equal(rows[0]['base_action'],raw[16:])
    np.testing.assert_array_equal(rows[0]['ctrl_substeps'],np.ones((25,19)))
    np.testing.assert_array_equal(rows[0]['effective_ctrl_substeps'],np.full((25,19),.25))
    np.testing.assert_array_equal(r.d.ctrl,np.ones(19))
    assert np.max(abs(r.d.actuator_force))<=40 and np.all(r.m.actuator_ctrlrange==[-.25,.25])


def test_numerical_failure_preserves_actual_partial_prefix_then_stops(monkeypatch):
    r,rows=actual_runtime(monkeypatch);original=r._finite_physics
    def numeric():
        if r.physics_step_count==3:raise Fault('nonfinite_physics')
        original()
    r._finite_physics=numeric
    with pytest.raises(Fault,match='nonfinite_physics'):r.tick()
    assert r.physics_step_count==3 and rows[0]['executed_substeps']==3 and not rows[0]['transition_completed']
    assert r.d.time==pytest.approx(.006) and r.steps==0


def test_no_planner_rate_or_hidden_interpolation_and_nonfinite_target_stops_before_physics(monkeypatch):
    r,rows=actual_runtime(monkeypatch)
    with pytest.raises(ValueError,match='no_interpolation'):r.tick(substep_targets=np.zeros((25,16)))
    with pytest.raises(Fault,match='nonfinite_or_invalid'):r.apply_model_target(np.full(19,np.nan))
    assert r.physics_step_count==0 and not rows
    r.register_diagnostic_check('actual_opposed_rim',lambda runtime:np.bool_(False));r.tick()
    assert r.diagnostic_last_frame[-1]['checks'][-1]['passed'] is False


def test_formal_tick_still_rejects_its_original_deadline(monkeypatch):
    r,rows=actual_runtime(monkeypatch)
    with pytest.raises(Fault,match='primitive_deadline_exceeded'):Runtime.tick(r)
    assert r.physics_step_count==0 and not rows


def test_actual_free_servo_integration_matches_original_tick_without_task_faults(monkeypatch):
    free,free_rows=actual_runtime(monkeypatch);formal,formal_rows=actual_runtime(monkeypatch)
    formal.primitive_deadline_step=None;formal.cfg.max_episode_seconds=100.;formal.cfg.max_attempt_wall_seconds=100.
    formal.check_retained_contact=lambda:None;formal.guard=lambda:formal.observation()
    raw=np.linspace(-.5,.5,19,dtype=np.float32)
    for _ in range(4):
        free.apply_model_target(raw);formal.sim.target=raw[:16].copy();formal.sim.base_target=raw[16:].copy()
        free.tick();Runtime.tick(formal)
    np.testing.assert_array_equal(free.d.qpos,formal.d.qpos);np.testing.assert_array_equal(free.d.qvel,formal.d.qvel)
    assert free.d.time==formal.d.time
    for a,b in zip(free_rows,formal_rows):
        np.testing.assert_array_equal(a['integration_state'],b['integration_state'])
        np.testing.assert_array_equal(a['ctrl_substeps'],b['ctrl_substeps'])


def test_measured_rim_axis_support_and_base_metrics_are_read_only(monkeypatch):
    import r1pro_teleop.single_tray_3table.learned as learned
    r,_=actual_runtime(monkeypatch)
    tables=[dict(table_id=name,center_world=[x,0,0],dimensions_m=[.6,1.2,.8],yaw_world=0.)
        for name,x in (('front_left',.85),('front_right',2.85),('rear',-1.))]
    r.manifest=dict(tray={'size':[.56,.43,.105]},tables=tables,source_table='rear',target_table='front_left')
    r.g=SimpleNamespace(tables={t['table_id']:t for t in tables});r.passenger_loaded=False
    r.diagnostic_initial_base_world=np.zeros(3);r.diagnostic_initial_base_joints=np.zeros(3)
    r.sim.base_joint_state=lambda:r.d.qpos[16:].copy()
    corners=np.array([[.85+x,.05+y,.801+z] for x in (-.28,.28) for y in (-.215,.215) for z in (0,.105)])
    snapshot=dict(gripper_tray_contact_points_local=np.array([[[0,-.205,.075]],[[0,.205,.075]]]),
        gripper_tray_contact_normals_local=np.array([[[0,-1.,0]],[[0,1.,0]]]),gripper_tray_contact_active=np.ones((2,1),bool),
        gripper_contact_force=np.array([10.,11.]),tray_corners_world=corners,tray_long_axis_world=np.array([1.,0,0]),
        robot_forward_world=np.array([1.,0,0]),table_contact_counts=np.array([4,0,0]),tray_footprint_on_table=np.array([True,False,False]))
    monkeypatch.setattr(learned,'contact_snapshot',lambda *args:snapshot)
    before=(r.d.qpos.copy(),r.sim.target.copy(),r.sim.base_target.copy(),r.d.time)
    metrics=r._measured_metrics()
    assert metrics['available'] and metrics['actual_rim_codes']==[-1,1] and metrics['opposed_long_rims']
    assert metrics['tray_axis_robot_forward_error_rad']==0 and metrics['table_contact_counts']==[4,0,0]
    assert metrics['base_actual_initial_delta']==[0.,0.,0.] and metrics['handover_verdict']=='unavailable'
    for old,new in zip(before[:3],(r.d.qpos,r.sim.target,r.sim.base_target)):np.testing.assert_array_equal(old,new)
    assert r.d.time==before[3]
