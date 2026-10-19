"""Existing geometric DAG scheduling with checkpoint-backed learned motion nodes."""
from dataclasses import asdict
import json,math
import numpy as np
from r1pro_teleop.airport_fsm.machine import Machine
from r1pro_teleop.airport_fsm.contracts import State,Fault,ARM_COLUMNS,atomic_json,wrap_angle
from r1pro_teleop.airport_fsm.geometry import quat_yaw_tilt,push_overhang_kwargs,Operation
from r1pro_teleop.airport_fsm.task_dag import build_task_dag
from .policy import Pi05Policy,PolicyContract,PolicyError
from .executor import VLAOperationExecutor,ActionBounds,ServoProjection,ReferenceRateLimiter,InitializerBaseHold,GraspBaseHold
from .data import language_prompt


def runtime_bounds(r):
    lower=np.empty(19);upper=np.empty(19)
    ranges=np.asarray(r.m.jnt_range[r.jids],float)
    lower[ARM_COLUMNS]=ranges[:,0]+r.cfg.joint_margin_rad
    upper[ARM_COLUMNS]=ranges[:,1]-r.cfg.joint_margin_rad
    for side,col in [('left',7),('right',15)]:
        ids=r.sim.fingers[side]
        if not all(r.m.jnt_limited[jid] for jid in ids):
            raise PolicyError('vla_unbounded_gripper_joint')
        mechanical=np.sum(r.m.jnt_range[ids],axis=0)
        # Recorded expert actions include opening=0. MuJoCo clamps the
        # corresponding half-opening ctrl to the finger actuator's range;
        # a closing servo reference is not a measured finger position.
        lower[col]=0.
        upper[col]=min(r.cfg.gripper_open_m+1e-6,mechanical[1])
    # Simulation workspace envelope, in the recorded initial-origin coordinates.
    # This is an explicit actuator envelope, independent of model normalization.
    lower[16:]=[-4.,-4.,-4*math.pi];upper[16:]=[4.,4.,4*math.pi]
    return ActionBounds(lower,upper)


def stable_evaluation(predicate,frames):
    count=0;last=None
    def check(r,op):
        nonlocal count,last
        step=r.steps
        if step==last:return count>=frames
        last=step
        count=count+1 if predicate(r,op) else 0
        check.stable_count=count
        return count>=frames
    check.stable_count=0
    check.required_frames=frames
    return check


def initial_posture_metrics(r):
    """Phase readiness only; strict audit and final task acceptance stay distinct."""
    errors=np.abs(np.asarray(r.sim.state(),float)-np.asarray(r.tucked,float))
    if errors.shape!=(16,):raise ValueError('Initialization requires measured mobile joint16 state')
    arm=float(getattr(getattr(r,'cfg',None),'vla_initialize_arm_tolerance_rad',.06))
    gripper=float(getattr(getattr(r,'cfg',None),'vla_initialize_gripper_tolerance_m',.005))
    thresholds=np.full(16,arm);thresholds[[7,15]]=gripper
    strict=np.full(16,.06);strict[[7,15]]=.005
    finite=bool(np.isfinite(errors).all())
    return dict(measured_absolute_errors=[float(v) if np.isfinite(v) else None for v in errors],
        arm_tolerance_rad=arm,gripper_tolerance_m=gripper,
        strict_arm_tolerance_rad=.06,strict_gripper_tolerance_m=.005,
        strict_passed=bool(finite and np.all(errors<=strict)),
        configured_passed=bool(finite and np.all(errors<=thresholds)),finite=finite,
        max_arm_error_rad=float(np.max(errors[ARM_COLUMNS])) if finite else None,
        max_gripper_error_m=float(np.max(errors[[7,15]])) if finite else None,
        qualification='initial_phase_readiness_only_not_control_improvement_or_final_task_acceptance')


def initial_posture_ready(r,op=None):
    return initial_posture_metrics(r)['configured_passed']


def runtime_rate_limiter(r,directory):
    fraction=float(r.limits['fraction']);scale=r.cfg.vla_reference_rate_fraction
    v=np.concatenate((r.v,[r.cfg.base_speed*fraction/math.sqrt(2)]*2,[r.cfg.base_yaw_speed*fraction]))*scale
    a=np.concatenate((r.a,[r.cfg.base_acceleration*fraction/math.sqrt(2)]*2,[r.cfg.base_yaw_acceleration*fraction]))*scale
    # MuJoCo measurements may be inside a physical joint limit but outside
    # the conservative margin applied to NETWORK targets. Recover continuously
    # rather than jump-clipping measured state or rejecting a legal posture.
    target=runtime_bounds(r)
    lower=target.lower.copy();upper=target.upper.copy()
    ranges=np.asarray(r.m.jnt_range[r.jids],float)
    lower[ARM_COLUMNS]=ranges[:,0];upper[ARM_COLUMNS]=ranges[:,1]
    for side,col in [('left',7),('right',15)]:
        ids=r.sim.fingers[side]
        if not all(r.m.jnt_limited[jid] for jid in ids):
            raise PolicyError('vla_unbounded_gripper_joint')
        lower[col],upper[col]=np.sum(r.m.jnt_range[ids],axis=0)
        lower[col]=0.
    # Planar simulation joints are unbounded; retain the explicit workspace
    # envelope for intermediate references as well as network targets.
    physical=ActionBounds(lower,upper)
    limiter=ReferenceRateLimiter(v,a,directory,fps=r.cfg.fps,physical_bounds=physical)
    limiter.stats['reference_boundary_semantics']={
        'arms':'mechanical_joint_range',
        'grippers':'declared_zero_close_servo_reference_to_mechanical_opening_upper',
        'base':'explicit_simulation_workspace_envelope'}
    limiter.stats['gripper_measured_mechanical_ranges']={
        side:np.sum(r.m.jnt_range[r.sim.fingers[side]],axis=0).tolist()
        for side in ('left','right')}
    return limiter


class VLAMachine(Machine):
    def __init__(self,runtime,directory,*,attempt=0,seed=0,policy=None):
        c=runtime.cfg
        contract=PolicyContract(c.vla_checkpoint_id,action_horizon=c.vla_action_horizon,action_width=19,prompt_mode=getattr(c,'vla_prompt_mode','legacy'))
        policy=policy or Pi05Policy.from_websocket(c.vla_host,c.vla_port,contract)
        bounds=runtime_bounds(runtime)
        super().__init__(runtime,directory,attempt=attempt,seed=seed)
        self.executor=VLAOperationExecutor(runtime,policy,bounds,execute_steps=c.vla_execute_steps,
            max_operation_steps=c.vla_max_skill_steps,on_chunk=self._chunk,
            projection=ServoProjection(self.directory/'vla_projection',mode=c.vla_servo_projection_mode)
                if c.vla_servo_projection_enabled else None,
            rate_limiter=runtime_rate_limiter(runtime,self.directory/'vla_rate_limit') if c.vla_reference_rate_limit_enabled else None)
        self.current_skill=None
        metadata=json.loads(self.log.file.attrs['metadata_json'])
        metadata.update(controller_source='vla_generated',motion_backend='pi05',privileged_teacher=False,
            policy_uses_privileged_state=False,policy_observation_keys=['state','RGB','prompt'],
            high_level_scheduler_uses_privileged_state=True,checkpoint_id=contract.checkpoint_id,
            prompt_mode=contract.prompt_mode,action_semantics='absolute_mobile19',base_action_envelope={'lower':bounds.lower[16:].tolist(),'upper':bounds.upper[16:].tolist()})
        self.log.file.attrs['metadata_json']=json.dumps(metadata)
        dag=build_task_dag(c.max_operations,c.max_local_retries)
        dag['motion_executor']='pi05_finetuned_vla';dag['teacher_fallback_enabled']=False
        atomic_json(self.directory/'task_dag.json',dag)

    def _chunk(self,detail):
        detail=dict(detail)
        event=detail.pop('event','vla_action_chunk')
        self.log.event(event,skill=self.current_skill,**detail)

    def _node(self,op,skill,state,predicate,stable_frames=2):
        self.current_skill=skill
        self.current_operation=op
        self.transition(state,'vla_'+skill,tray=op.tray,slot=op.slot)
        segment={'skill':skill,'phase':'vla_'+skill,'target_tray_id':self.g.ids[op.tray],
            'target_slot_id':None if op.slot<0 else self.g.spec['slots'][op.slot]['slot_id']}
        try:
            prompt=language_prompt(segment,asdict(op),prompt_mode=getattr(self.c,'vla_prompt_mode','legacy'))
        except ValueError as exc:
            self.log.event('vla_unsupported_action_goal',skill=skill,operation=asdict(op),
                prompt_mode=getattr(self.c,'vla_prompt_mode','legacy'),reason=str(exc),
                teacher_fallback_enabled=False)
            code='vla_unsupported_temporary_carry' if skill=='carry_tray' and op.temporary else 'vla_unsupported_action_prompt'
            raise PolicyError(code) from exc
        self.log.event('vla_skill_started',skill=skill,prompt=prompt,operation_index=self.operations)
        kwargs={}
        if skill=='initialize_posture' and getattr(self.c,'vla_initializer_base_hold_enabled',False):
            kwargs['reference_constraint']=InitializerBaseHold(self.directory/'vla_initializer_base_hold')
        elif skill=='grasp_lift_tray' and getattr(self.c,'vla_grasp_base_hold_enabled',False):
            node=getattr(self,'grasp_base_hold_nodes',0);self.grasp_base_hold_nodes=node+1
            kwargs['reference_constraint']=GraspBaseHold(self.directory/('vla_grasp_base_hold_node_'+str(node).zfill(3)))
        check=stable_evaluation(predicate,stable_frames)
        navigation=getattr(predicate,'__func__',None) is VLAMachine._navigation_ready
        if navigation:self.navigation_latest_metrics=None
        completed=False
        try:
            self.executor.execute_operation(op,prompt,check,**kwargs)
            completed=True
        finally:
            if navigation:
                record=dict(operation_index=self.operations,target_tray_id=self.g.ids[op.tray],
                    completed=completed,required_stable_ticks=stable_frames,actual_stable_ticks=check.stable_count,
                    actual_steps=getattr(self.r,'steps',None),metrics=self.navigation_latest_metrics,
                    qualification='DAG_stage_readiness_only_not_reachability_or_final_task_acceptance')
                if not hasattr(self,'navigation_handoffs'):self.navigation_handoffs=[]
                self.navigation_handoffs.append(record)
                self.log.event('vla_navigation_handoff_evaluated',**record)
        detail={}
        if skill=='initialize_posture':
            self.initial_posture_completion_metrics=initial_posture_metrics(self.r)
            detail['initial_posture']=self.initial_posture_completion_metrics
        self.log.event('vla_skill_completed',skill=skill,qualification='actual_physics_predicate_not_model_claim',**detail)

    def _navigation_ready(self,r,op):
        pose=r.observation()['tray_pose'][op.tray]
        base=r.sim.base_state();distance=float(np.linalg.norm(base[:2]-pose[:2]))
        inward=self._inward_yaw(pose[:3]);yaw=float(quat_yaw_tilt(pose[3:])[0])
        face=inward+float(wrap_angle(yaw-inward,np.pi))
        offsets=(0.,np.pi/2,-np.pi/2) if r.cfg.alternate_rim_enabled else (0.,)
        error=min(abs(float(wrap_angle(base[2]-heading-offset)))
            for heading in (face,inward) for offset in offsets)
        velocity=np.asarray(r.d.qvel[r.base_dofs])
        delta=pose[:2]-base[:2];c,s=np.cos(base[2]),np.sin(base[2])
        forward=float(c*delta[0]+s*delta[1]);lateral=float(-s*delta[0]+c*delta[1])
        bearing=float(np.arctan2(lateral,forward));speed=float(np.linalg.norm(velocity[:2]));yaw_speed=float(abs(velocity[2]))
        finite=bool(np.isfinite([distance,error,forward,lateral,bearing,speed,yaw_speed]).all())
        legacy=bool(finite and .4<=distance<=.75 and error<=.6 and speed<=.03 and yaw_speed<=.08)
        cfg=r.cfg;mode=cfg.vla_navigation_readiness_mode
        cone=bool(finite and abs(bearing)<=cfg.vla_navigation_target_bearing_max_rad
            and abs(lateral)<=cfg.vla_navigation_target_lateral_max_m and forward>=cfg.vla_navigation_target_forward_min_m)
        selected=legacy and (mode=='legacy' or cone)
        values=dict(distance_m=distance,legacy_heading_error_rad=error,target_forward_m=forward,
            target_lateral_m=lateral,target_bearing_rad=bearing,base_xy_speed_m_s=speed,base_yaw_speed_rad_s=yaw_speed)
        reasons=[]
        if not finite:reasons.append('nonfinite_navigation_geometry_or_velocity')
        if not .4<=distance<=.75:reasons.append('legacy_distance')
        if not error<=.6:reasons.append('legacy_heading')
        if not speed<=.03:reasons.append('legacy_xy_velocity')
        if not yaw_speed<=.08:reasons.append('legacy_yaw_velocity')
        if mode!='legacy':
            if not abs(bearing)<=cfg.vla_navigation_target_bearing_max_rad:reasons.append('target_bearing')
            if not abs(lateral)<=cfg.vla_navigation_target_lateral_max_m:reasons.append('target_lateral')
            if not forward>=cfg.vla_navigation_target_forward_min_m:reasons.append('target_forward')
        self.navigation_latest_metrics=dict(mode=mode,finite=finite,legacy_ready=legacy,
            target_cone_ready=cone,selected_ready=bool(selected),reasons=reasons,
            evaluated_step=getattr(r,'steps',None),
            thresholds=dict(target_bearing_max_rad=cfg.vla_navigation_target_bearing_max_rad,
                target_lateral_max_m=cfg.vla_navigation_target_lateral_max_m,target_forward_min_m=cfg.vla_navigation_target_forward_min_m),
            actual={k:v if np.isfinite(v) else None for k,v in values.items()})
        return bool(selected)

    def _released(self,r,op):
        e=r.observation();t=op.tray
        return bool(e['table_contact'][t]>0 and np.max(e['gripper_contact_force'][t])<=.5
            and np.min(r.sim.state()[[7,15]])>=.06)

    def _placed(self,r,op):
        if not self._released(r,op):return False
        if op.slot>=0 and not op.temporary:return self._operation_geometry_ready(op)
        e=r.observation();yaw,tilt=quat_yaw_tilt(e['tray_pose'][op.tray,3:])
        return bool(np.linalg.norm(e['tray_pose'][op.tray,:2]-op.destination[:2])<=.1
            and abs(float(wrap_angle(yaw-op.yaw,self.g.period)))<=np.deg2rad(15)
            and tilt<=np.deg2rad(5))

    def _execute_dag_operation(self,op):
        r=self.r;t=op.tray
        self._node(op,'navigate_to_tray',State.ALIGN_BASE,self._navigation_ready,self.c.vla_navigation_stable_frames)
        pose=self._poses()
        if self.g.push_possible(pose,t,op.destination,op.yaw,self.c.push_max_distance_m,
                np.deg2rad(self.c.push_max_yaw_deg),**push_overhang_kwargs(self.c)):
            self._node(op,'push_adjust_tray',State.ADJUST_TRAY,self._placed,20)
            return
        def lifted(runtime,operation):
            e=runtime.observation();tray=operation.tray
            return bool(np.min(e['gripper_contact_force'][tray])>.5 and
                e['min_z'][tray]-runtime.initial_bottom[tray]>=self.c.completion_lift_min_m)
        self._node(op,'grasp_lift_tray',State.GRASP_TRAY,lifted)
        r.remember_grasp(t)  # measured contact bookkeeping, no IK or attachment.
        self._node(op,'carry_tray',State.TRANSPORT_TRAY,
            lambda runtime,operation: np.linalg.norm(runtime.observation()['tray_pose'][t,:2]-operation.destination[:2])<=.18)
        self._node(op,'place_release_tray',State.PLACE_TRAY,self._released,4)
        r.holding=None;r.grasp_rel=None;r.retained_contact=None
        if not self._placed(r,op):
            self._node(op,'push_adjust_tray',State.ADJUST_TRAY,self._placed,20)

    def run(self):
        r=self.r
        self.transition(State.SEARCH_TARGET,'unknown');r.wait(2.)
        r.initial_bottom=r.observation()['min_z'].copy()
        first_pose=self._poses()[0]
        initialize=Operation(0,-1,first_pose[:3].copy(),float(quat_yaw_tilt(first_pose[3:])[0]))
        self._node(initialize,'initialize_posture',State.SEARCH_TARGET,
            initial_posture_ready,3)
        for _ in range(self.c.max_operations):
            self.transition(State.SEARCH_TARGET,'unknown')
            if self.operations:
                valid,report=self._profile_final_acceptance()
                if valid:
                    self.transition(State.TASK_COMPLETE,'verified');r.tick();return report
            op=self.scheduler.choose(self._poses())
            if op is None:
                self.transition(State.VERIFY_PLACEMENT,'verified');r.wait(self.c.criteria.stable_s+.15)
                valid,report=self._profile_final_acceptance()
                if valid:
                    self.transition(State.TASK_COMPLETE,'verified');r.tick();return report
                raise Fault('final_physical_acceptance_failed',report)
            if getattr(self.c,'release_preflight_enabled',False):
                from r1pro_teleop.airport_fsm.scheduler import release_prerequisite
                requested=op
                op,prerequisite=release_prerequisite(self.g,self._poses(),op,self.scheduler.mapping,
                    self.verified_final_trays,self.c)
                if prerequisite:self.log.event('release_prerequisite_selected',requested=asdict(requested),**prerequisite)
            self.operations+=1
            self.log.event('operation_selected',operation=asdict(op),operation_index=self.operations)
            # Pure VLA failures never invoke Machine.recover, IK or a teacher.
            self._execute_dag_operation(op)
            if op.slot>=0 and not op.temporary:self.verified_final_trays.add(op.tray)
        raise Fault('operation_budget_exhausted')

    def finish(self,success,acceptance=None,error=None):
        if isinstance(error,PolicyError):
            error=Fault(str(error).split(':',1)[0],{'policy_error':str(error)},recoverable=False)
        result=super().finish(success,acceptance,error)
        result.update(controller_source='vla_generated',privileged_teacher=False,motion_backend='pi05',
            checkpoint_id=self.c.vla_checkpoint_id,policy_uses_privileged_state=False,training_candidate=False)
        if hasattr(self,'r'):
            result['vla_initial_posture_at_finish']=initial_posture_metrics(self.r)
            result['vla_initial_posture_completed']=getattr(self,'initial_posture_completion_metrics',None)
        result['vla_reference_constraints']=getattr(self.executor,'reference_constraint_stats',[]) if hasattr(self,'executor') else []
        result['vla_navigation_handoffs']=getattr(self,'navigation_handoffs',[])
        atomic_json(self.directory/'result.json',result)
        return result
