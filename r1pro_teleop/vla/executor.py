"""Receding-horizon position-servo execution, without IK/inverse dynamics.

DAG selection and privileged completion/safety tests remain the caller's job.
They are not included in the observation passed to the learned policy.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Callable
import hashlib
from pathlib import Path
import numpy as np
from .policy import Pi05Policy, PolicyError
from .observations import render_model_observation


@dataclass(frozen=True)
class ActionBounds:
    lower: np.ndarray
    upper: np.ndarray

    def __post_init__(self):
        lower, upper = np.asarray(self.lower, dtype=float), np.asarray(self.upper, dtype=float)
        if lower.shape != (19,) or upper.shape != (19,) or not np.isfinite([lower, upper]).all() or np.any(lower >= upper):
            raise PolicyError('vla_invalid_action_bounds')
        object.__setattr__(self, 'lower', lower.copy())
        object.__setattr__(self, 'upper', upper.copy())

    @classmethod
    def from_runtime(cls, runtime):
        lower, upper = np.empty(19), np.empty(19)
        columns = list(range(7)) + list(range(8, 15))
        for col, jid in zip(columns, runtime.jids):
            if not runtime.m.jnt_limited[jid]:
                raise PolicyError('vla_unbounded_arm_joint')
            lower[col], upper[col] = runtime.m.jnt_range[jid]
        # Opening is the sum of two finger joint positions, in metres.
        for side, col in [('left', 7), ('right', 15)]:
            ids = runtime.sim.fingers[side]
            if not all(runtime.m.jnt_limited[jid] for jid in ids):
                raise PolicyError('vla_unbounded_gripper_joint')
            lower[col], upper[col] = np.sum(runtime.m.jnt_range[ids], axis=0)
        for col, jid in zip(range(16, 19), runtime.base_joints):
            if not runtime.m.jnt_limited[jid]:
                raise PolicyError('vla_unbounded_base_requires_explicit_bounds')
            lower[col], upper[col] = runtime.m.jnt_range[jid]
        return cls(lower, upper)

    def validate(self, actions):
        value = np.asarray(actions, dtype=float)
        if value.ndim != 2 or value.shape[1] != 19 or not np.isfinite(value).all():
            raise PolicyError('vla_invalid_mobile19_actions')
        if np.any(value < self.lower) or np.any(value > self.upper):
            raise PolicyError('vla_action_outside_joint_limits')


@dataclass(frozen=True)
class ServoProjection:
    """Explicit admissible raw prediction errors, in physical robot units.

    This is an actuator reference projection, never a replacement planner.
    The complete predicted chunk must fit inside these bounded envelopes.
    """
    artifact_directory: Path
    arm_tolerance_rad: float = .03
    gripper_tolerance_m: float = .002
    base_xy_tolerance_m: float = .02
    base_yaw_tolerance_rad: float = .05
    mode: str = 'bounded'

    def __post_init__(self):
        if self.mode not in ('bounded','actuator_saturation'):
            raise PolicyError('vla_invalid_servo_projection_mode')
        values=(self.arm_tolerance_rad,self.gripper_tolerance_m,
                self.base_xy_tolerance_m,self.base_yaw_tolerance_rad)
        caps=(.03,.002,.02,.05)
        if any(isinstance(v,bool) or not np.isfinite(v) or v<0 or v>cap for v,cap in zip(values,caps)):
            raise PolicyError('vla_invalid_servo_projection_envelope')
        object.__setattr__(self,'artifact_directory',Path(self.artifact_directory).resolve())

    def project(self,raw,bounds):
        raw=np.asarray(raw,dtype=np.float32)
        if raw.ndim!=2 or raw.shape[1]!=19 or len(raw)==0 or not np.isfinite(raw).all():
            raise PolicyError('vla_invalid_mobile19_actions')
        tolerance=np.full(19,self.arm_tolerance_rad)
        tolerance[[7,15]]=self.gripper_tolerance_m
        tolerance[16:18]=self.base_xy_tolerance_m
        tolerance[18]=self.base_yaw_tolerance_rad
        if self.mode=='bounded' and (np.any(raw<bounds.lower-tolerance) or np.any(raw>bounds.upper+tolerance)):
            raise PolicyError('vla_action_outside_projection_envelope')
        projected=np.clip(raw,bounds.lower,bounds.upper).astype(np.float32)
        # Float32 conversion may round a nonrepresentable boundary outwards.
        # Move the command one float32 ULP inward rather than widen the bounds.
        for col in range(19):
            projected[:,col]=np.where(projected[:,col]<bounds.lower[col],
                np.nextafter(projected[:,col],np.float32(np.inf)),projected[:,col])
            projected[:,col]=np.where(projected[:,col]>bounds.upper[col],
                np.nextafter(projected[:,col],np.float32(-np.inf)),projected[:,col])
        bounds.validate(projected)
        return projected,projected!=raw


class ReferenceRateLimiter:
    """Limit servo references, with measured-state continuous initialization.

    ``physical_bounds`` is the intermediate REFERENCE domain: arm mechanical
    limits, declared gripper opening command limits, and base workspace limits.
    Gripper opening zero is a legal command even when each MuJoCo finger joint
    has a positive minimum. Servo opening/2 is saturated by the existing
    actuator ctrlrange; commanded opening and measured finger separation are
    distinct quantities. This class does not change ctrlrange or live qpos.
    Model target changes may be crossed while braking. This inertia is bounded
    by the stopping distance at the change, and is recorded. Physical command
    bounds remain hard. This filters references, not measured robot velocities.
    """
    def __init__(self,velocity_caps,acceleration_caps,artifact_directory,*,fps=20,physical_bounds=None):
        self.velocity_caps=np.asarray(velocity_caps,dtype=float).copy()
        self.acceleration_caps=np.asarray(acceleration_caps,dtype=float).copy()
        if (fps!=20 or self.velocity_caps.shape!=(19,) or self.acceleration_caps.shape!=(19,) or
                not np.isfinite([self.velocity_caps,self.acceleration_caps]).all() or
                np.any(self.velocity_caps<=0) or np.any(self.acceleration_caps<=0)):
            raise PolicyError('vla_invalid_reference_rate_caps')
        self.dt=1./fps;self.directory=Path(artifact_directory).resolve()
        if physical_bounds is not None and not isinstance(physical_bounds,ActionBounds):
            raise PolicyError('vla_invalid_rate_physical_bounds')
        self.physical_bounds=physical_bounds
        # Reserve one percent for float32 actuator target quantization. Report
        # both requested and effective caps; no hardware limits are changed.
        self.vmax=self.velocity_caps*.99;self.amax=self.acceleration_caps*.99
        self.position=None;self.velocity=np.zeros(19);self.goal=None
        self.stats={'enabled':True,'submitted_rows':0,'executed_rows':0,'changed_rows':0,
                    'max_abs_delta_by_channel':[0.]*19,'max_reference_velocity_by_channel':[0.]*19,
                    'max_reference_acceleration_by_channel':[0.]*19,'max_target_overshoot_by_channel':[0.]*19,
                    'max_stopping_distance_by_channel':[0.]*19,'raw_policy_unmodified':True,
                    'velocity_caps':self.velocity_caps.tolist(),'acceleration_caps':self.acceleration_caps.tolist(),
                    'effective_velocity_caps':self.vmax.tolist(),'effective_acceleration_caps':self.amax.tolist(),
                    'dt_s':self.dt,'caps_scope':'command_reference_only_actual_physics_guard_unchanged'}
        self.stats['reference_bounds_semantics']='arm_mechanical_gripper_declared_opening_command_base_workspace'
        if physical_bounds is not None:
            self.stats.update(physical_lower=physical_bounds.lower.tolist(),physical_upper=physical_bounds.upper.tolist())

    def contract(self):
        result={key:list(self.stats[key]) if isinstance(self.stats[key],list) else self.stats[key]
                for key in ('velocity_caps','acceleration_caps','effective_velocity_caps',
                            'effective_acceleration_caps','dt_s','caps_scope','reference_bounds_semantics')}
        if self.physical_bounds is not None:
            result.update(physical_lower=self.physical_bounds.lower.tolist(),physical_upper=self.physical_bounds.upper.tolist())
        return result

    def _stop_distance(self,speed):
        speed=np.abs(speed);dv=self.amax*self.dt
        n=np.maximum(np.ceil(speed/dv)-1,0)
        return self.dt*((n+1)*speed-dv*n*(n+1)/2)

    def _safe_speed(self,distance):
        lo=np.zeros(19);hi=self.vmax.copy()
        for _ in range(48):
            mid=(lo+hi)/2;safe=self._stop_distance(mid)<=np.maximum(distance,0.)
            lo=np.where(safe,mid,lo);hi=np.where(safe,hi,mid)
        return lo

    def submit(self,raw,pre_rate,measured,bounds,*,step,checkpoint_id):
        raw=np.asarray(raw,dtype=np.float32);target=np.asarray(pre_rate,dtype=float)
        measured=np.asarray(measured,dtype=float)
        if (raw.shape!=(19,) or target.shape!=(19,) or measured.shape!=(19,) or
                not np.isfinite([raw,target,measured]).all()):
            raise PolicyError('vla_invalid_rate_reference')
        bounds.validate(target[None,:])
        physical=self.physical_bounds or bounds
        if np.any(bounds.lower<physical.lower) or np.any(bounds.upper>physical.upper):
            raise PolicyError('vla_target_bounds_outside_physical_bounds')
        if self.position is None:
            physical.validate(measured[None,:])
            self.position=measured.copy();self.stats['initial_measured_state']=measured.tolist()
            deficit=np.maximum(np.maximum(bounds.lower-measured,measured-bounds.upper),0.)
            self.stats.update(initial_reference=measured.tolist(),initial_command_margin_deficit=deficit.tolist(),
                              margin_recovery_steps=0,margin_recovery_complete=not bool(np.any(deficit)))
        current=self.position;old_v=self.velocity
        delta=target-current;desired=np.sign(delta)*self._safe_speed(np.abs(delta))
        opposing=old_v*delta<0
        # A reversal first decelerates to a sampled zero before accelerating in
        # the other direction. Never silently reset velocity at a new DAG node.
        desired=np.where(opposing,0.,desired)
        velocity=np.clip(desired,old_v-self.amax*self.dt,old_v+self.amax*self.dt)
        velocity=np.clip(velocity,-self.vmax,self.vmax)
        safe_positive=self._safe_speed(physical.upper-current)
        safe_negative=self._safe_speed(current-physical.lower)
        velocity=np.clip(velocity,-safe_negative,safe_positive)
        if np.any(np.abs(velocity-old_v)>self.acceleration_caps*self.dt+1e-10):
            raise PolicyError('vla_reference_physical_braking_infeasible')
        command=(current+velocity*self.dt).astype(np.float32)
        for col in range(19):
            if command[col]<physical.lower[col]:command[col]=np.nextafter(command[col],np.float32(np.inf))
            if command[col]>physical.upper[col]:command[col]=np.nextafter(command[col],np.float32(-np.inf))
        # Eliminate a quantization-sized goal crossing when stopping exactly
        # there fits the declared acceleration. A close *new* moving target
        # that cannot be reached without abrupt braking retains bounded inertia.
        crossed=(target-current)*(command.astype(float)-target)>=0
        goal_v=(target-current)/self.dt
        stop_allowed=(np.abs(goal_v)<=self.amax*self.dt)&(np.abs((goal_v-old_v)/self.dt)<=self.acceleration_caps)
        command=np.where(crossed&stop_allowed,target.astype(np.float32),command)
        physical.validate(command[None,:])
        actual_v=(command.astype(float)-current)/self.dt
        actual_a=(actual_v-old_v)/self.dt
        if (np.any(np.abs(actual_v)>self.velocity_caps+1e-9) or
                np.any(np.abs(actual_a)>self.acceleration_caps+1e-9)):
            raise PolicyError('vla_reference_quantization_cap_violation')
        deficit=np.maximum(np.maximum(bounds.lower-command,command-bounds.upper),0.)
        if self.stats['submitted_rows']==0:
            self.stats.update(first_command=command.tolist(),first_command_measured_velocity=((command-measured)/self.dt).tolist(),
                              first_command_measured_acceleration=((command-measured)/self.dt**2).tolist())
        if not self.stats['margin_recovery_complete']:
            self.stats['margin_recovery_steps']+=1
            self.stats['margin_recovery_complete']=not bool(np.any(deficit))
        self.stats['command_margin_deficit']=deficit.tolist()
        changed=np.ones(19,dtype=bool) if self.goal is None else target!=self.goal
        if self.goal is None:
            self.goal_origin=current.copy();self.goal_direction=np.zeros(19);self.goal_stop_budget=np.zeros(19)
        self.goal_origin=np.where(changed,current,self.goal_origin)
        direction=np.where(old_v!=0,np.sign(old_v),np.sign(delta))
        self.goal_direction=np.where(changed,direction,self.goal_direction)
        self.goal_stop_budget=np.where(changed,self._stop_distance(old_v),self.goal_stop_budget)
        ahead=self.goal_direction*(target-self.goal_origin)>=0
        origin=np.where(ahead,target,self.goal_origin)
        overshoot=np.maximum(self.goal_direction*(command-origin),0.)
        # A new target can lie inside current braking distance. That permissible
        # reference inertia is measured, never converted into an episode fault.
        stopping=self._stop_distance(old_v)
        self.directory.mkdir(parents=True,exist_ok=True)
        sequence=self.stats['submitted_rows'];path=self.directory/f'step_{sequence:06d}.npz'
        with path.open('xb') as stream:
            np.savez_compressed(stream,raw_action=raw,pre_rate_action=target,rate_limited_action=command,
                measured_state=measured,reference_velocity=actual_v,reference_acceleration=actual_a,
                command_margin_deficit=deficit,physical_lower=physical.lower,physical_upper=physical.upper,
                target_overshoot=overshoot,stopping_distance=stopping,target_change_stopping_budget=self.goal_stop_budget,
                step=np.int64(step),dt=np.float64(self.dt),checkpoint_id=np.asarray(checkpoint_id))
        digest=hashlib.sha256(path.read_bytes()).hexdigest();difference=np.abs(command-target)
        self.position=command.astype(float);self.velocity=actual_v;self.goal=target.copy()
        self.stats['submitted_rows']+=1;self.stats['changed_rows']+=int(np.any(difference>0))
        for key,value in (('max_abs_delta_by_channel',difference),('max_reference_velocity_by_channel',np.abs(actual_v)),
                          ('max_reference_acceleration_by_channel',np.abs(actual_a)),
                          ('max_target_overshoot_by_channel',overshoot),('max_stopping_distance_by_channel',stopping)):
            self.stats[key]=np.maximum(self.stats[key],value).tolist()
        if np.any(difference>0):self.stats['raw_policy_unmodified']=False
        return command,{'event':'vla_reference_rate_limit','step':int(step),'rate_artifact':str(path),
                        'rate_sha256':digest,'rate_changed_channels':int(np.count_nonzero(difference)),
                        'max_reference_velocity':float(np.max(np.abs(actual_v))),
                        'max_reference_acceleration':float(np.max(np.abs(actual_a))),
                        'target_overshoot_by_channel':overshoot.tolist(),'stopping_distance_by_channel':stopping.tolist()}


class InitializerBaseHold:
    """Operation-local measured base reference; never alters model observations."""
    def __init__(self,directory,*,skill='initialize_posture'):
        if skill not in ('initialize_posture','grasp_lift_tray'):raise PolicyError('vla_invalid_base_hold_skill')
        self.skill=skill
        self.kind='initializer_only_base_hold' if skill=='initialize_posture' else 'grasp_only_base_hold'
        self.event='vla_initializer_base_hold' if skill=='initialize_posture' else 'vla_grasp_base_hold'
        self.directory=Path(directory).resolve();self.target=None
        self.checkpoint_id=None
        self.stats=dict(enabled=True,kind=self.kind,skill=skill,capture_count=0,chunks=0,
            submitted_rows=0,executed_rows=0,max_measured_base_drift=[0.]*3,
            max_constrained_base_delta=[0.]*3,raw_policy_unmodified=True,raw_model_actions_retained=True,servo_reference_modified=False,
            executed_rows_semantics='Runtime.tick_returned_with_guards_passed_failed_tick_may_advance_physics',
            qualification=('declared_initializer_reference_constraint_not_IK_teacher_or_qpos_reset' if skill=='initialize_posture' else
                           'declared_grasp_reference_constraint_not_IK_teacher_or_qpos_reset'))

    def begin(self,measured,bounds,step):
        value=np.asarray(measured,float)
        if self.target is not None:raise PolicyError('vla_base_hold_already_captured')
        if value.shape!=(19,) or not np.isfinite(value).all():raise PolicyError('vla_invalid_base_hold_measurement')
        base=value[16:].astype(np.float32)
        # Preserve the measured value up to normal command dtype precision.
        # A physical workspace violation cannot be hidden by this constraint.
        if np.any(value[16:]<bounds.lower[16:]) or np.any(value[16:]>bounds.upper[16:]):
            raise PolicyError('vla_base_hold_outside_workspace')
        for col in range(3):
            if base[col]<bounds.lower[16+col]:base[col]=np.nextafter(base[col],np.float32(np.inf))
            if base[col]>bounds.upper[16+col]:base[col]=np.nextafter(base[col],np.float32(-np.inf))
        self.target=base.copy();self.stats.update(capture_count=1,capture_step=int(step),
            captured_measured_mobile19=value.tolist(),held_base_reference=base.tolist())

    def apply(self,raw,prehold,bounds,step,checkpoint_id):
        if self.target is None:raise PolicyError('vla_base_hold_not_captured')
        bounds.validate(prehold);result=prehold.copy();result[:,16:]=self.target
        self.checkpoint_id=checkpoint_id
        bounds.validate(result);delta=result.astype(float)-prehold
        self.directory.mkdir(parents=True,exist_ok=True);path=self.directory/f'chunk_{self.stats["chunks"]:06d}.npz'
        with path.open('xb') as stream:
            np.savez_compressed(stream,raw_actions=raw,prehold_servo_actions=prehold,constrained_actions=result,
                constraint_delta=delta,held_base_reference=self.target,step=np.int64(step),
                checkpoint_id=np.asarray(checkpoint_id),constraint_kind=np.asarray(self.kind),skill=np.asarray(self.skill),stage=np.asarray('post_projection_base_hold_pre_rate_not_executed_chunk'))
        self.stats['chunks']+=1
        if np.any(delta):self.stats['servo_reference_modified']=True
        self.stats['max_constrained_base_delta']=np.maximum(self.stats['max_constrained_base_delta'],np.max(np.abs(delta[:,16:]),axis=0)).tolist()
        return result,dict(event=self.event,constraint_kind=self.kind,constraint_skill=self.skill,checkpoint_id=checkpoint_id,step=int(step),constraint_artifact=str(path),
            constraint_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),held_base_reference=self.target.tolist(),
            constrained_stage='post_projection_pre_rate_not_executed_chunk')

    def record_tick(self,before,after,command,step,*,executed,error=None):
        path=self.directory/f'tick_{self.stats["submitted_rows"]:06d}.npz'
        before=np.asarray(before,float);after=np.asarray(after,float)
        with path.open('xb') as stream:
            np.savez_compressed(stream,measured_before=before,measured_after=after,actual_submitted_reference=command,
                held_base_reference=self.target,measured_base_drift=after[16:]-self.target,
                step=np.int64(step),executed=np.asarray(executed),error=np.asarray(error or ''),
                checkpoint_id=np.asarray(self.checkpoint_id or ''),constraint_kind=np.asarray(self.kind),skill=np.asarray(self.skill))
        self.stats['submitted_rows']+=1;self.stats['executed_rows']+=int(executed)
        finite=np.isfinite(after[16:])
        self.stats['max_measured_base_drift']=np.maximum(self.stats['max_measured_base_drift'],
            np.where(finite,np.abs(after[16:]-self.target),0.)).tolist()
        return dict(event=self.event+'_tick',constraint_kind=self.kind,constraint_skill=self.skill,checkpoint_id=self.checkpoint_id,step=int(step),executed=bool(executed),
            constraint_tick_artifact=str(path),constraint_tick_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            measured_base_drift=[float(v) if np.isfinite(v) else None for v in after[16:]-self.target])


class GraspBaseHold(InitializerBaseHold):
    """Optional grasp-node base reference constraint, independent of initializer."""
    def __init__(self,directory):super().__init__(directory,skill='grasp_lift_tray')


class VLAOperationExecutor:
    """Execute at most ``execute_steps`` actions, observe again, infer again.

    The entire returned chunk is validated before the first physical tick.
    ``completed(runtime, operation)`` must be a pure evaluation callback.
    Runtime.tick retains native recording, finite/collision/camera/contact guards.
    Model or guard failure is propagated; no recovery/teacher is implicit here.
    """
    def __init__(self, runtime, policy: Pi05Policy, bounds: ActionBounds,
                 *, execute_steps: int = 10, max_operation_steps: int = 2400,
                 on_chunk: Callable | None = None, on_decision: Callable | None = None,
                 projection: ServoProjection | None = None,rate_limiter: ReferenceRateLimiter | None = None):
        if runtime.cfg.fps != 20 or policy.contract.fps != runtime.cfg.fps:
            raise PolicyError('vla_runtime_sampling_mismatch')
        if any(isinstance(x, bool) or not isinstance(x, int) or x < 1
               for x in (execute_steps, max_operation_steps)) or execute_steps > policy.contract.action_horizon:
            raise PolicyError('vla_invalid_execution_budget')
        self.runtime, self.policy, self.bounds = runtime, policy, bounds
        self.execute_steps, self.max_operation_steps = execute_steps, max_operation_steps
        self.on_chunk = on_chunk
        self.on_decision = on_decision
        if projection is not None and not isinstance(projection,ServoProjection):
            raise PolicyError('vla_invalid_servo_projection')
        self.projection=projection
        if rate_limiter is not None and not isinstance(rate_limiter,ReferenceRateLimiter):
            raise PolicyError('vla_invalid_reference_rate_limiter')
        self.rate_limiter=rate_limiter
        self.rate_limit_stats=rate_limiter.stats if rate_limiter is not None else {'enabled':False}
        self.reference_constraint_stats=[]
        self.projection_stats={'enabled':projection is not None,'chunks':0,'projected_chunks':0,
                               'projected_action_rows':0,'projected_channels':0,
                               'submitted_projected_rows':0,'executed_projected_rows':0,
                               'max_abs_delta_by_channel':[0.]*19,
                               'raw_policy_unmodified':True}
        self.projection_stats.update(mode=projection.mode if projection is not None else 'disabled',
                                     total_action_rows=0,total_channels=0,saturated_channel_fraction=0.,saturated_row_fraction=0.,
                                     max_normalized_severity_by_channel=[0.]*19)
        if projection is not None and projection.mode=='actuator_saturation' and rate_limiter is None:
            raise PolicyError('vla_actuator_saturation_requires_rate_limiter')

    def _project_chunk(self,raw,step):
        if self.projection is None:
            self.bounds.validate(raw)
            return raw,np.zeros_like(raw,dtype=bool),{}
        try:
            projected,mask=self.projection.project(raw,self.bounds)
        except PolicyError as exc:
            directory=self.projection.artifact_directory
            directory.mkdir(parents=True,exist_ok=True)
            path=directory/f'rejected_chunk_{self.projection_stats["chunks"]:06d}.npz'
            with path.open('xb') as stream:
                np.savez_compressed(stream,raw_actions=raw,target_lower=self.bounds.lower,target_upper=self.bounds.upper,
                    step=np.int64(step),checkpoint_id=np.asarray(self.policy.contract.checkpoint_id),
                    rejection_code=np.asarray(str(exc)))
            self.projection_stats.update(rejected_chunk_artifact=str(path),
                rejected_chunk_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),rejected_chunk_code=str(exc))
            raise
        stats=self.projection_stats;sequence=stats['chunks']
        directory=self.projection.artifact_directory
        directory.mkdir(parents=True,exist_ok=True)
        path=directory/f'chunk_{sequence:06d}.npz'
        # Exclusive creation prevents evidence overwrite when a run is reused.
        with path.open('xb') as stream:
            np.savez_compressed(stream,raw_actions=raw,servo_actions=projected,projection_mask=mask,
                saturated_actions=projected,mode=np.asarray(self.projection.mode),
                normalized_saturation_severity=np.abs(projected.astype(float)-raw)/(self.bounds.upper-self.bounds.lower),
                servo_actions_stage=np.asarray('bounded_projection_pre_rate'),
                step=np.int64(step),checkpoint_id=np.asarray(self.policy.contract.checkpoint_id))
        digest=hashlib.sha256(path.read_bytes()).hexdigest()
        count=int(mask.sum());rows=int(np.any(mask,axis=1).sum())
        maxima=np.max(np.abs(projected-raw),axis=0)
        stats['chunks']+=1;stats['projected_chunks']+=int(count>0)
        stats['total_action_rows']+=len(raw);stats['total_channels']+=raw.size
        stats['projected_action_rows']+=rows;stats['projected_channels']+=count
        stats['max_abs_delta_by_channel']=np.maximum(stats['max_abs_delta_by_channel'],maxima).tolist()
        stats['saturated_channel_fraction']=stats['projected_channels']/stats['total_channels']
        stats['saturated_row_fraction']=stats['projected_action_rows']/stats['total_action_rows']
        stats['max_normalized_severity_by_channel']=np.maximum(stats['max_normalized_severity_by_channel'],
            maxima/(self.bounds.upper-self.bounds.lower)).tolist()
        if count:stats['raw_policy_unmodified']=False
        detail={'projection_enabled':True,'projection_artifact':str(path),'projection_sha256':digest,
                'projection_mode':self.projection.mode,'saturated_channel_fraction':count/raw.size,
                'saturated_row_fraction':rows/len(raw),
                'normalized_severity_by_channel':(maxima/(self.bounds.upper-self.bounds.lower)).tolist(),
                'projection_channels':count,'projection_action_rows':rows,
                'projection_max_abs_delta_by_channel':maxima.tolist()}
        return projected,mask,detail

    def execute_operation(self, operation, prompt: str, completed: Callable, *, reference_constraint=None) -> bool:
        r = self.runtime
        if reference_constraint is not None:
            if not isinstance(reference_constraint,InitializerBaseHold):raise PolicyError('vla_invalid_reference_constraint')
            if self.rate_limiter is None:raise PolicyError('vla_base_hold_requires_reference_rate_limiter')
            reference_constraint.begin(np.concatenate((r.sim.state(),r.sim.base_joint_state())),self.bounds,r.steps)
            self.reference_constraint_stats.append(reference_constraint.stats)
        r.allowed_tray, r.target_slot = operation.tray, operation.slot
        if completed(r, operation):
            return True
        used = 0
        while used < self.max_operation_steps:
            # No privileged tray poses, contact forces, goal coordinates, or
            # IK seed enter the network. Prompt is provided by the DAG caller.
            state = np.concatenate((r.sim.state(), r.sim.base_joint_state()))
            images = {name: render_model_observation(r.sim, name, getattr(r.cfg, 'vla_model_render_max_dim', 0))
                      for name in self.policy.contract.camera_names}
            observation_render = dict(max_dim=getattr(r.cfg, 'vla_model_render_max_dim', 0),
                                      profile='native' if getattr(r.cfg, 'vla_model_render_max_dim', 0)==0 else 'policy_same_aspect',
                                      rgb_shapes={name:list(image.shape) for name,image in images.items()})
            actions = self.policy.infer(images, state, prompt)
            servo_actions,projection_mask,projection_detail=self._project_chunk(actions,int(r.steps))
            constrained_actions=servo_actions;constraint_detail=None
            if reference_constraint is not None:
                constrained_actions,constraint_detail=reference_constraint.apply(actions,servo_actions,self.bounds,int(r.steps),self.policy.contract.checkpoint_id)
            if self.on_decision is not None:
                # A private expert observer receives copies, never buffers that
                # it can mutate into teacher actions on the live learner.
                self.on_decision(dict(step=int(r.steps), images={name: value.copy() for name,value in images.items()},
                                      state=state.copy(), prompt=prompt, actions=actions.copy(),
                                      observation_render=observation_render,
                                      servo_actions=servo_actions.copy(),
                                      servo_actions_stage='bounded_projection_pre_rate_not_executed_chunk',
                                      constrained_actions=constrained_actions.copy(),
                                      constrained_actions_stage='post_projection_constraint_pre_rate_not_executed_chunk',
                                      reference_constraint=dict(kind=reference_constraint.kind,skill=reference_constraint.skill,held_base_reference=reference_constraint.target.tolist()) if reference_constraint is not None else None,
                                      rate_limit_contract=self.rate_limiter.contract() if self.rate_limiter is not None else None))
            count = min(self.execute_steps, self.max_operation_steps-used)
            if self.on_chunk is not None:
                self.on_chunk(dict(step=int(r.steps), checkpoint_id=self.policy.contract.checkpoint_id,
                                   executed_actions=count, chunk_actions=len(actions), observation_render=observation_render))
                if projection_detail:
                    self.on_chunk(dict(step=int(r.steps),checkpoint_id=self.policy.contract.checkpoint_id,
                                       event='vla_servo_projection',**projection_detail))
                if constraint_detail:self.on_chunk(constraint_detail)
            for row_index,target in enumerate(constrained_actions[:count]):
                if self.rate_limiter is not None:
                    target,rate_detail=self.rate_limiter.submit(actions[row_index],target,
                        np.concatenate((r.sim.state(),r.sim.base_joint_state())),self.bounds,
                        step=int(r.steps),checkpoint_id=self.policy.contract.checkpoint_id)
                    if self.on_chunk is not None:self.on_chunk(rate_detail)
                r.sim.target = target[:16].astype(np.float32).copy()
                # These are initial-origin joint coordinates, not world coords.
                r.sim.base_target = target[16:].astype(np.float32).copy()
                if np.any(projection_mask[row_index]):self.projection_stats['submitted_projected_rows']+=1
                if reference_constraint is None:r.tick()
                else:
                    before=np.concatenate((r.sim.state(),r.sim.base_joint_state()));step=int(r.steps)
                    error=None;executed=False
                    try:r.tick();executed=True
                    except BaseException as exc:error=repr(exc);raise
                    finally:
                        after=np.concatenate((r.sim.state(),r.sim.base_joint_state()))
                        detail=reference_constraint.record_tick(before,after,target,step,executed=executed,error=error)
                        if self.on_chunk is not None:self.on_chunk(detail)
                if self.rate_limiter is not None:self.rate_limit_stats['executed_rows']+=1
                if np.any(projection_mask[row_index]):self.projection_stats['executed_projected_rows']+=1
                used += 1
                if completed(r, operation):
                    return True
        raise PolicyError('vla_operation_step_budget_exhausted')
