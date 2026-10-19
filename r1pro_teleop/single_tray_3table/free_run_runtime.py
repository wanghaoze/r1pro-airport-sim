"""Diagnostic-only uninterrupted physics; never a formal task executor.

Targets go directly to the existing simulation servo. Numerical state is checked
each physics substep. Expensive original task guards and extra task predicates
are sampled at 20 Hz and recorded, not used to finish or stop the trajectory.
"""
from pathlib import Path
import json
import math
import time
import numpy as np
from .control import ThreeTableRuntime
from ..airport_fsm.contracts import Fault,json_default


class FreeRunRuntime(ThreeTableRuntime):
    RUN_SCOPE='free_run_diagnostic'
    TASK_CHECK_COVERAGE='frame_endpoint_20hz'

    def __init__(self,scene,cfg,*,render=True,diagnostic_directory=None,on_diagnostic=None):
        if cfg.fps!=20:raise ValueError('free_run_diagnostic_requires_20hz')
        super().__init__(scene,cfg,render=render)
        self.record_ctrl_substeps=True
        self._setup_diagnostics(diagnostic_directory,on_diagnostic)
        base=self.d.body('base_link');R=base.xmat.reshape(3,3)
        self.diagnostic_initial_base_world=np.r_[base.xpos[:2],math.atan2(R[1,0],R[0,0])]
        self.diagnostic_initial_base_joints=np.asarray(self.sim.base_joint_state()).copy()

    def _setup_diagnostics(self,directory=None,callback=None):
        self.diagnostic_callback=callback;self.diagnostic_checks={};self.diagnostic_stream=None
        if directory is not None:
            folder=Path(directory);folder.mkdir(parents=True,exist_ok=True)
            self.diagnostic_stream=(folder/'free_run_guard_diagnostics.jsonl').open('x',encoding='utf-8')
        self.diagnostic_count=0;self.diagnostic_fault_count=0;self.diagnostic_last_frame=[]
        self.diagnostic_peak_penetration_m=0.;self._diagnostic_substep=-1
        self.last_model_raw_action19=None
        self.diagnostic_metrics=None

    def register_diagnostic_check(self,name,check):
        if not isinstance(name,str) or not name or name in self.diagnostic_checks or not callable(check):
            raise ValueError('unique_callable_diagnostic_check_required')
        self.diagnostic_checks[name]=check

    def apply_model_target(self,raw_action19):
        raw=np.asarray(raw_action19)
        if raw.shape!=(19,) or not np.isfinite(raw).all():raise Fault('nonfinite_or_invalid_model_target')
        with np.errstate(over='ignore',invalid='ignore'):target=raw.astype(np.float32)
        if not np.isfinite(target).all():raise Fault('nonfinite_model_servo_representation')
        self.last_model_raw_action19=raw.copy()
        self.sim.target=target[:16].copy();self.sim.base_target=target[16:].copy()

    def _finite_physics(self):
        fields=('qpos','qvel','qacc','ctrl','actuator_force','actuator_velocity')
        if not np.isfinite(self.d.time) or any(not np.isfinite(getattr(self.d,k)).all() for k in fields):
            raise Fault('nonfinite_physics')

    def _record_diagnostic(self,checks,*,coverage,metrics=None):
        row=dict(frame=int(self.steps),physics_step=int(self.physics_step_count),
            substep=int(self._diagnostic_substep),sim_time=float(self.d.time),coverage=coverage,
            checks=checks,task_completed=False,training_eligible=False,formal_evaluation=False)
        if metrics is not None:row['diagnostic_metrics']=metrics
        self.diagnostic_count+=1;self.diagnostic_fault_count+=sum(x.get('passed') is False for x in checks)
        self.diagnostic_last_frame.append(row)
        if self.diagnostic_stream is not None:
            self.diagnostic_stream.write(json.dumps(row,default=json_default,allow_nan=False)+'\n')
        if self.diagnostic_callback is not None:self.diagnostic_callback(row)
        return row

    def _measured_metrics(self):
        """Read actual contacts/FK; never infer completion or change a target."""
        try:
            from .learned import contact_snapshot,actual_rim_codes
            from .observer import table_front_region_violation
            from ..vla.data_three_table_single_tray import table_geometry_values,final_axis_error,TABLE_IDS
            from ..airport_fsm.geometry import quat_yaw_tilt
            scene=self.manifest;snapshot=contact_snapshot(self,scene)
            active=np.asarray(snapshot['gripper_tray_contact_active'],bool)
            codes=actual_rim_codes(snapshot,scene['tray']['size'])
            base=self.d.body('base_link');R=base.xmat.reshape(3,3)
            actual_base=np.r_[base.xpos[:2],math.atan2(R[1,0],R[0,0])]
            delta=actual_base-self.diagnostic_initial_base_world
            delta[2]=math.atan2(math.sin(delta[2]),math.cos(delta[2]))
            excess,gap=table_geometry_values(snapshot['tray_corners_world'],scene['tables'])
            axis_error=None;axis_unavailable=None
            try:axis_error=float(final_axis_error(snapshot['tray_long_axis_world'],snapshot['robot_forward_world']))
            except ValueError as error:axis_unavailable=str(error)
            tray=self.d.body('tray')
            return dict(available=True,coverage='actual_frame_endpoint_20hz',
                contact_semantics='actual_mujoco_finger_tray_contacts_existing_0.05N_sampler',
                actual_rim_codes=codes.tolist(),actual_gripper_contact_force_n=snapshot['gripper_contact_force'].tolist(),
                contact_active=active.tolist(),actual_contact_points_local=[snapshot['gripper_tray_contact_points_local'][i][active[i]].tolist() for i in range(2)],
                actual_contact_normals_local=[snapshot['gripper_tray_contact_normals_local'][i][active[i]].tolist() for i in range(2)],
                opposed_long_rims=bool(codes[0] in (-1,1) and codes[1]==-codes[0]),
                tray_long_axis_world=snapshot['tray_long_axis_world'].tolist(),robot_forward_world=snapshot['robot_forward_world'].tolist(),
                tray_axis_robot_forward_error_rad=axis_error,axis_error_unavailable=axis_unavailable,
                tray_tilt_rad=float(quat_yaw_tilt(tray.xquat)[1]),tray_position_world=tray.xpos.tolist(),
                table_ids=list(TABLE_IDS),table_contact_counts=snapshot['table_contact_counts'].tolist(),
                tray_footprint_on_table=snapshot['tray_footprint_on_table'].tolist(),table_footprint_excess_m=excess.tolist(),table_corner_gap_m=gap.tolist(),
                base_actual_world=actual_base.tolist(),base_initial_world=self.diagnostic_initial_base_world.tolist(),
                base_actual_initial_delta=delta.tolist(),base_xy_drift_m=float(np.linalg.norm(delta[:2])),
                base_joint_initial_delta=(np.asarray(self.sim.base_joint_state())-self.diagnostic_initial_base_joints).tolist(),
                source_front_violation=bool(table_front_region_violation(self.g.tables[scene['source_table']],base.xpos)),
                target_front_violation=bool(table_front_region_violation(self.g.tables[scene['target_table']],base.xpos)),
                passenger_loaded_environment_applied=bool(self.passenger_loaded),payload_support_verdict='unavailable',
                handover_verdict='unavailable',task_success_verdict='not_evaluated_diagnostic_only')
        except Exception as error:
            return dict(available=False,coverage='actual_frame_endpoint_20hz',reason=repr(error),
                payload_support_verdict='unavailable',handover_verdict='unavailable',task_success_verdict='not_evaluated_diagnostic_only')

    def _task_check(self,name,check):
        try:
            value=check()
            return dict(name=name,passed=bool(value) if isinstance(value,(bool,np.bool_)) else True)
        except Fault as error:
            if error.code=='nonfinite_physics':raise
            return dict(name=name,passed=False,code=error.code,detail=str(error.detail))
        except Exception as error:
            return dict(name=name,passed=False,code='diagnostic_check_unavailable',detail=repr(error))

    def guard(self):
        """Original guards are diagnostic observations, not termination gates."""
        self._finite_physics()
        checks=[self._task_check('original_runtime_guard',lambda:super(FreeRunRuntime,self).guard()),
                self._task_check('retained_contact',self.check_retained_contact),
                self._task_check('retained_integer_clock',self.validate_retained_clock_state)]
        e=self.observation()
        for key in ('tray_pose','min_z','gripper_contact_force','max_penetration'):
            if not np.isfinite(e[key]).all():raise Fault('nonfinite_physics')
        # Independent measured checks still appear when the original ordered
        # guard raises at its first task fault. No check corrects any target.
        checks.extend([
            dict(name='tray_floor_contact',passed=not bool(np.any(e['floor_contact']))),
            dict(name='strict_contact_penetration',passed=float(e['max_penetration'])<=self.cfg.criteria.penetration_m),
            dict(name='selected_contact_penetration',passed=float(e['max_penetration'])<=self.cfg.completion_collision_penetration_m),
            dict(name='finite_task_observation',passed=True)])
        sides=[side for j,side in enumerate(('left','right')) if np.any(e['gripper_contact_force'][:,j]>.5)]
        checks.extend([
            self._task_check('selected_collision',lambda:not bool(self.collision())),
            self._task_check('wrist_camera_front_guard',lambda:not sides or self.camera_guard(contact_sides=sides)),
            self._task_check('measured_arm_speed',lambda:self._check_measured_arm_speed(
                np.abs(self.d.qvel[self.dofs]),np.abs(self.d.qvel[self.dofs])/self.actual_velocity_cap)),
            dict(name='measured_base_speed',passed=bool(np.linalg.norm(self.d.qvel[self.base_dofs][:2])<=self.cfg.base_speed*self.cfg.limit_fraction+1e-5 and
                abs(self.d.qvel[self.base_dofs][2])<=self.cfg.base_yaw_speed*self.cfg.limit_fraction+1e-5)),
            dict(name='mechanical_power_cap',passed=self.power_cap is None or float(np.sum(np.abs(self.d.actuator_force*self.d.actuator_velocity)))<=self.power_cap),
            dict(name='primitive_deadline',passed=getattr(self,'primitive_deadline_step',None) is None or self.steps<self.primitive_deadline_step),
            dict(name='episode_simulation_budget',passed=self.steps<round(self.cfg.max_episode_seconds*self.cfg.fps)),
            dict(name='episode_wall_budget',passed=time.monotonic()-self.wall_start<=self.cfg.max_attempt_wall_seconds)])
        if self.holding is not None:
            t=self.holding
            from ..airport_fsm.geometry import quat_yaw_tilt
            checks.extend([dict(name='bilateral_holding_contact',passed=bool(np.all(e['gripper_contact_force'][t]>.5))),
                dict(name='carried_tray_tilt',passed=quat_yaw_tilt(e['tray_pose'][t,3:])[1]<=np.deg2rad(20)),
                dict(name='carried_payload_support_contact',passed=e['support_contact'][t]==0)])
        for name,check in self.diagnostic_checks.items():checks.append(self._task_check(name,lambda f=check:f(self)))
        self.diagnostic_metrics=self._measured_metrics()
        self._record_diagnostic(checks,coverage=self.TASK_CHECK_COVERAGE,metrics=self.diagnostic_metrics)
        return e

    def tick(self,*,substep_targets=None):
        if substep_targets is not None:raise ValueError('free_run_model_targets_only_no_interpolation')
        self._finite_physics();self.diagnostic_last_frame=[];self.diagnostic_metrics=None
        if not np.isfinite(self.sim.target).all() or not np.isfinite(self.sim.base_target).all():
            raise Fault('nonfinite_model_target')
        self.sim.target=np.asarray(self.sim.target,np.float32);self.sim.base_target=np.asarray(self.sim.base_target,np.float32)
        e=self.observation();integration=np.empty(self.integration_size,np.float64)
        self.mj.mj_getState(self.m,self.d,integration,self.integration_spec)
        row=dict(integration_state=integration,ctrl=self.d.ctrl.copy(),timestamp=np.float64(self.steps/self.cfg.fps),
            sim_time=np.float64(self.d.time),qpos=self.d.qpos.copy(),qvel=self.d.qvel.copy(),
            qacc_warmstart=self.d.qacc_warmstart.copy(),act=self.d.act.copy(),state=self.sim.state(),
            action=self.sim.target.copy(),base_action=self.sim.base_target.copy(),base_state=self.sim.base_state(),
            fsm_state=self.fsm_state.value,phase=self.phase,target_tray=np.int32(-1 if self.allowed_tray is None else self.allowed_tray),
            target_slot=np.int32(self.target_slot),recovery=np.bool_(self.recovery),wrist_violation=np.bool_(False),
            transition_completed=np.bool_(False),**e)
        n=self.sim.nstep
        row.update(ctrl_substeps=np.zeros((n,self.m.nu),np.float64),effective_ctrl_substeps=np.zeros((n,self.m.nu),np.float64),executed_substeps=np.int32(0),
            diagnostic_contact_penetration_substeps=np.zeros(n,np.float64),
            diagnostic_warning_numbers_substeps=np.zeros((n,len(self.d.warning)),np.int32))
        t0=float(self.d.time);self.sim.apply_target()
        try:
            for k in range(n):
                self._diagnostic_substep=k;row['ctrl_substeps'][k]=self.d.ctrl
                # Diagnostic view of MuJoCo's existing actuator input limit.
                # It is never written back to d.ctrl or the model reference.
                limited=np.asarray(self.m.actuator_ctrllimited,dtype=bool)
                row['effective_ctrl_substeps'][k]=np.where(limited,
                    np.clip(self.d.ctrl,self.m.actuator_ctrlrange[:,0],self.m.actuator_ctrlrange[:,1]),self.d.ctrl)
                try:self.mj.mj_step(self.m,self.d);self.mj.mj_forward(self.m,self.d)
                except Exception as error:raise Fault('free_run_physics_cannot_continue',repr(error)) from error
                self.physics_step_count+=1;row['executed_substeps']=np.int32(k+1)
                self._finite_physics()
                if not math.isclose(float(self.d.time),t0+(k+1)*float(self.m.opt.timestep),abs_tol=1e-9):
                    raise Fault('physics_time_reset_or_drift')
                warnings=np.array([w.number for w in self.d.warning],np.int32)
                row['diagnostic_warning_numbers_substeps'][k]=warnings
                distances=np.asarray(self.d.contact.dist)
                if not np.isfinite(distances).all():raise Fault('nonfinite_physics')
                penetration=max(0.,-float(np.min(distances))) if len(distances) else 0.
                row['diagnostic_contact_penetration_substeps'][k]=penetration
                self.diagnostic_peak_penetration_m=max(self.diagnostic_peak_penetration_m,penetration)
                violations=[]
                if np.any(warnings):violations.append(dict(name='mujoco_warning',passed=False,numbers=warnings.tolist()))
                if penetration>self.cfg.completion_collision_penetration_m:
                    violations.append(dict(name='selected_contact_penetration',passed=False,measured_m=penetration))
                if violations:self._record_diagnostic(violations,coverage='actual_physics_substep_warning_and_contact_peak')
            if not math.isclose(float(self.d.time)-t0,1/self.cfg.fps,abs_tol=1e-9):
                raise Fault('physics_time_reset_or_drift')
            self._diagnostic_substep=-1;self.guard()
            row['transition_completed']=np.bool_(True)
        finally:
            row['diagnostic_metrics_json']=json.dumps(self.diagnostic_metrics or dict(available=False,
                coverage='not_reached_numerical_partial_interval'),default=json_default,allow_nan=False)
            if self.trace:self.trace.append(row)
            if self.diagnostic_stream is not None:self.diagnostic_stream.flush()
        self.steps+=1
        self.sim.workspace_rotation=self.d.body('base_link').xmat.reshape(3,3).copy()
        from ..core import XR_TO_ROBOT
        self.sim.xr_to_world=self.sim.workspace_rotation@XR_TO_ROBOT

    def close_diagnostics(self):
        if self.diagnostic_stream is not None:self.diagnostic_stream.close();self.diagnostic_stream=None
