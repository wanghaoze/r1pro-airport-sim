"""Private teacher continuation on the SAME live three-table MuJoCo state.

Binding is bookkeeping only. This module is never a learned-policy fallback.
The initial bridge deliberately retains the inherited acquire geometry: callers
must supply a qualified long-rim adapter before the new forward-axis task runs.
"""
import math
import numpy as np
from dataclasses import asdict,dataclass,replace
from r1pro_teleop.single_tray_lab.control import SingleTrayController,ControlProfile
from r1pro_teleop.airport_fsm.contracts import Fault,State
from r1pro_teleop.airport_fsm.geometry import quat_yaw_tilt,wrap_angle,rectangle
from r1pro_teleop.airport_fsm.rim_affordances import rim_pairs

@dataclass(frozen=True)
class LoadedBridgeProfile(ControlProfile):
    source_collision_penetration_m: float=.003
    push_transient_boundary_extra_m: float=0.
    supported_boundary_margin_m: float=.005
    push_axis_feedback_enabled: bool=False
    push_axis_step_rad: float=math.radians(.5)
    push_axis_integral_limit_rad: float=.10
    loaded_goal_policy: str='table_left_edge'
    minimum_left_tray_motion_m: float=.03

    def validate(self):
        if self.loaded_goal_policy not in ('table_left_edge','handover_left_motion_then_release'):
            raise ValueError('bridge_unknown_loaded_goal_policy')
        if isinstance(self.minimum_left_tray_motion_m,bool) or not np.isfinite(self.minimum_left_tray_motion_m) or not 0<self.minimum_left_tray_motion_m<=.1:
            raise ValueError('bridge_left_tray_motion_requires_positive_bounded_distance')
        if isinstance(self.base_drift_m,bool) or not np.isfinite(self.base_drift_m) or not 0<self.base_drift_m<=.05:
            raise ValueError('bridge_base_drift_requires_positive_cap_up_to_5cm')
        if isinstance(self.supported_boundary_margin_m,bool) or not np.isfinite(self.supported_boundary_margin_m) or not 0<=self.supported_boundary_margin_m<=.05:
            raise ValueError('bridge_supported_boundary_total_margin_requires_0_to_5cm')
        if self.supported_boundary_margin_m+self.push_transient_boundary_extra_m>.05:
            raise ValueError('bridge_boundary_total_cannot_exceed_5cm')
        if type(self.push_axis_feedback_enabled) is not bool:raise ValueError('bridge_axis_feedback_boolean_required')
        if not np.isfinite(self.push_axis_step_rad) or not 0<self.push_axis_step_rad<=math.radians(.5):raise ValueError('bridge_axis_reference_step_bound')
        if not np.isfinite(self.push_axis_integral_limit_rad) or not 0<self.push_axis_integral_limit_rad<=.10:raise ValueError('bridge_axis_reference_antiwindup_bound')
        extra=self.push_transient_boundary_extra_m
        if isinstance(extra,bool) or not np.isfinite(extra) or not 0<=extra<=.001:
            raise ValueError('bridge_transient_boundary_extra_requires_0_to_1mm')
        if extra>0 and self.push_table_contact_grace_frames==0:
            raise ValueError('bridge_transient_boundary_requires_finite_support_grace')
        if not np.isfinite(self.source_collision_penetration_m) or not 0<self.source_collision_penetration_m<=.02:
            raise ValueError('bridge_source_collision_contract')
        if self.max_penetration_m!=self.source_collision_penetration_m:
            raise ValueError('bridge_collision_contract_mismatch')
        # Validate every original field against its original contract; only
        # this explicit new bridge restores the verified source's 20mm cap.
        surrogate=replace(self,max_penetration_m=min(self.max_penetration_m,.01),
            planning_gripper_preload_max_m=max(self.planning_gripper_preload_max_m,min(self.max_penetration_m,.01)))
        ControlProfile.validate(surrogate)
        if not self.max_penetration_m<=self.planning_gripper_preload_max_m<=.02:
            raise ValueError('bridge_preload_contract')
        return self


def derive_bridge_profile(runtime,manifest,reference_profile):
    """Keep the explicit source push controller settings; derive only geometry.

    loaded_goal_position is a NOMINAL reference whose +half-long-side edge
    defines the target. Completion uses actual rotated eight-corner max edge,
    so the new forward-axis tray is not forced to old yaw90 centre Y=.295.
    """
    reference_profile.validate()
    target=runtime.g.tables[manifest['target_table']]
    R=runtime.d.body('base_link').xmat.reshape(3,3)
    forward=R[:,0].copy();forward[2]=0.;forward/=np.linalg.norm(forward)
    left=np.array([-forward[1],forward[0],0.])
    table_corners=rectangle(target['center_world'],target.get('yaw_world',0.),target['dimensions_m'])
    boundary=manifest.get('loaded_push_target',{})
    edge=float(np.max(table_corners@left[:2]))-boundary.get('table_edge_margin_m',.025)
    actual=runtime.d.body('tray').xpos.copy()
    nominal=actual+(edge-max(runtime.g.sizes[0,:2])/2-float(actual@left))*left
    half=np.array([np.ptp(table_corners[:,0]),np.ptp(table_corners[:,1])])/2
    values=asdict(reference_profile)
    if boundary.get('final_boundary_extra_m',0.)!=0.:
        raise ValueError('bridge_final_boundary_predicate_must_remain_unchanged')
    for key,expected in (('existing_boundary_numeric_margin_m',.005),
                         ('transient_support_grace_s',reference_profile.push_table_contact_grace_frames/reference_profile.fps),
                         ('transient_lowest_corner_gap_m',reference_profile.push_table_contact_grace_gap_m)):
        if key in boundary and boundary[key]!=expected:
            raise ValueError('bridge_scene_grace_contract_mismatch:'+key)
    values.update(tray_body='tray',table_bodies=tuple(runtime.g.tables),
        payload_bodies=tuple(p['name'] for p in manifest['payloads'] if not p.get('flex')),
        payload_flexes=tuple(p['name'] for p in manifest['payloads'] if p.get('flex')),
        tray_dimensions=tuple(runtime.g.sizes[0]),table_center_xy=tuple(target['center_world'][:2]),
        table_half_sizes_xy=tuple(half),tabletop_z=float(target['dimensions_m'][2]),
        empty_place_position=tuple(actual),loaded_goal_position=tuple(nominal),
        front_normal=tuple(-forward),robot_left=tuple(left),
        rim_height=runtime.cfg.rim_height_local_m,rim_inset=runtime.cfg.rim_inset_m,
        max_penetration_m=runtime.cfg.completion_collision_penetration_m,
        push_transient_boundary_extra_m=boundary.get('transient_boundary_extra_m',0.),
        supported_boundary_margin_m=boundary.get('supported_boundary_margin_m',.005),
        position_tolerance_m=boundary.get('goal_edge_tolerance_m',reference_profile.position_tolerance_m),
        base_drift_m=boundary.get('base_drift_m',reference_profile.base_drift_m),
        push_axis_feedback_enabled=boundary.get('push_axis_feedback_enabled',False),
        push_axis_step_rad=boundary.get('push_axis_step_rad',math.radians(.5)),
        push_axis_integral_limit_rad=boundary.get('push_axis_integral_limit_rad',.10),
        loaded_goal_policy=boundary.get('target','table_left_edge'),
        minimum_left_tray_motion_m=boundary.get('minimum_left_tray_motion_m',.03),
        source_collision_penetration_m=runtime.cfg.completion_collision_penetration_m,
        planning_gripper_preload_max_m=max(reference_profile.planning_gripper_preload_max_m,runtime.cfg.completion_collision_penetration_m))
    return LoadedBridgeProfile(**values).validate()


class LoadedBridgeController(SingleTrayController):
    @classmethod
    def bind(cls,runtime,profile,*,passenger_loader,on_event=None,observer=None):
        profile.validate()
        if profile.max_penetration_m!=runtime.cfg.completion_collision_penetration_m:
            raise ValueError('bridge_actual_source_collision_contract_mismatch')
        if profile.rim_height!=runtime.cfg.rim_height_local_m or profile.rim_inset!=runtime.cfg.rim_inset_m:
            raise ValueError('bridge_actual_source_rim_geometry_mismatch')
        if profile.fps!=runtime.cfg.fps:raise ValueError('bridge_fps_mismatch')
        self=cls.__new__(cls)
        self.runtime=runtime;self.p=profile
        runtime.loaded_bridge=self
        self.sim=runtime.sim;self.m=runtime.m;self.d=runtime.d;self.mj=runtime.mj
        if self.sim.model is not self.m or self.sim.data is not self.d:
            raise ValueError('bridge_live_model_data_identity')
        self.passenger_loader=passenger_loader;self.on_frame=None;self.on_event=on_event
        self.observer=observer
        self.frames=runtime.steps;self.phase='passenger_load';self.action='environment';self.loaded=False
        self.events=[];self.actions=[];self.holding_sides=set();self.handover_verified=False
        self.rim_outward_local={}
        self.axis_references={};self.pending_axis_proposal=None;self.private_axis_prediction=None
        self.left_motion_origin=None;self.left_motion_axis=None;self.left_reference_captured=False
        self.right_motion_origin=None
        self.observed_hard_penetration_peak_m=0.;self.observed_soft_payload_penetration_peak_m=0.;self.guarded_substeps=0
        self.robot_payload_contact_statistics()
        self.strict_continuous_push_table_contact_gate=True
        self.push_table_contact_grace_episodes=0;self.push_table_contact_grace_recoveries=0
        self.push_table_contact_max_absent_duration_s=0.;self.push_table_contact_max_gap_m=0.
        self._push_table_missing_since=None;self._push_table_missing_frame=None
        self._push_table_missing_logged=False;self._push_table_last_log_frame=None
        self.observed_boundary_extra_peak_m=0.;self.strict_push_footprint_gate_passed=True
        self.boundary_grace_episodes=0;self.boundary_grace_recoveries=0
        self.boundary_grace_max_duration_s=0.;self._boundary_missing_since=None
        self._boundary_last_logged_frame=None
        self.robot=self._descendants(self.m.body('base_link').id)
        self.tray=self._descendants(self.m.body(profile.tray_body).id)
        self.tables=set().union(*(self._descendants(self.m.body(name).id) for name in profile.table_bodies))
        self.payload=set().union(*(self._descendants(self.m.body(name).id) for name in profile.payload_bodies))
        self.flexes={int(self.mj.mj_name2id(self.m,self.mj.mjtObj.mjOBJ_FLEX,name)) for name in profile.payload_flexes}
        if -1 in self.flexes:raise ValueError('bridge_missing_payload_flex')
        # Fixed-front guard origin is local to this stage, NOT the model's raw
        # mobile19 origin or actuator reference. Neither is rewritten.
        self.base_origin=self.sim.base_state().astype(float)
        self.observed_base_drift_peak_m=0.;self.observed_base_yaw_drift_peak_rad=0.
        self.strict_base_5mm_gate_passed=True;self._base_strict_deviation_logged=False
        self.integration_spec=runtime.integration_spec;self.integration_size=runtime.integration_size
        self._protected_qpos=self._body_qpos(self.robot|self.tray)
        self._protected_dofs=self._body_dofs(self.robot|self.tray)
        return self

    def _capture_push_reference(self,side):
        reference=super()._capture_push_reference(side)
        if side=='right' and self.p.loaded_goal_policy=='handover_left_motion_then_release':
            self.right_motion_origin=np.asarray(self.observation()['tray_position']).copy()
        if side=='left' and self.p.loaded_goal_policy=='handover_left_motion_then_release':
            self.left_reference_captured=True
            self._capture_actual_left_origin(self.observation())
        if self.p.push_axis_feedback_enabled:
            from .axis_feedback import PushAxisReference
            obs=self.observation();_,origin,tcp,R=self.push_anchor
            state=PushAxisReference(origin,obs['tray_rotation'],tcp,R,-np.asarray(self.p.front_normal))
            self.axis_references[side]=state;self.pending_axis_proposal=None
            self.event('coupled_push_material_reference_captured',side=side,material_point=state.material_point.tolist(),
                relative_tool_rotation=state.relative_tool.tolist(),goal_yaw_reference_rad=state.goal_yaw,
                actual_robot_forward=(-np.asarray(self.p.front_normal)).tolist(),capture_scope='commanded FK once; force-lead origin retained')
        return reference

    def _capture_actual_left_origin(self,obs):
        right_move=(float((np.asarray(obs['tray_position'])-self.right_motion_origin)@np.asarray(self.p.robot_left))
            if self.right_motion_origin is not None else 0.)
        if (self.left_motion_origin is None and self.left_reference_captured and self.handover_verified
                and obs['gripper_contact_force']['right']<=self.p.contact_n
                and obs['gripper_contact_force']['left']>self.p.contact_n and right_move>=.001):
            self.left_motion_origin=np.asarray(obs['tray_position']).copy()
            self.left_motion_axis=np.asarray(self.p.robot_left).copy()
            self.event('actual_left_motion_origin_after_right_release',actual_tray_position=self.left_motion_origin.tolist(),
                actual_robot_left=self.left_motion_axis.tolist(),actual_forces=obs['gripper_contact_force'],
                minimum_left_tray_motion_m=self.p.minimum_left_tray_motion_m,actual_right_push_distance_m=right_move)

    def loaded_goal_remaining(self,obs):
        if self.p.loaded_goal_policy!='handover_left_motion_then_release':return super().loaded_goal_remaining(obs)
        self._capture_actual_left_origin(obs)
        if self.left_motion_origin is None:return self.p.position_tolerance_m+self.p.minimum_left_tray_motion_m
        moved=float((np.asarray(obs['tray_position'])-self.left_motion_origin)@self.left_motion_axis)
        gap=self.p.minimum_left_tray_motion_m-moved
        # Original loop's `remaining <= position_tolerance` must not stop
        # before the newly required measured motion has actually occurred.
        return 0. if gap<=0 else gap+self.p.position_tolerance_m

    def loaded_goal_reached(self,obs):
        if self.p.loaded_goal_policy!='handover_left_motion_then_release':return super().loaded_goal_reached(obs)
        self._capture_actual_left_origin(obs)
        return bool(self.left_motion_origin is not None and self.handover_verified and self._on_table(obs)
            and float((np.asarray(obs['tray_position'])-self.left_motion_origin)@self.left_motion_axis)>=self.p.minimum_left_tray_motion_m)

    def _next_tcp_push_reference(self,reference,side,remaining):
        if not self.p.push_axis_feedback_enabled:return super()._next_tcp_push_reference(reference,side,remaining)
        state=self.axis_references[side];obs=self.observation()
        proposal=state.propose(obs,self.sim.tcp(side)[0],self.p,remaining)
        _,origin,anchor,_=self.push_anchor
        proxy=origin+proposal.tcp_reference-anchor
        self.pending_axis_proposal=(side,proxy.copy(),proposal)
        self.event('coupled_push_reference_proposed',side=side,yaw_error_rad=proposal.yaw_error,
            yaw_reference_delta_rad=proposal.yaw_delta,command_yaw_rad=proposal.command_yaw,
            tcp_reference=proposal.tcp_reference.tolist(),body_reference=proposal.body_reference.tolist(),
            tool_rotation=proposal.tool_rotation.tolist(),forward_clearance_m=proposal.clearance,
            y_force_lead_paused=proposal.paused_y,submitted=False,
            qualification='Coupled reference only; no live state update or final acceptance change')
        return proxy,proposal.tcp_reference.copy()

    def _push_reference_move(self,position,side):
        if not self.p.push_axis_feedback_enabled:return super()._push_reference_move(position,side)
        from .axis_feedback import AxisProposal
        from ..airport_fsm.geometry import rz
        state=self.axis_references[side];_,origin,anchor,_=self.push_anchor
        pending=self.pending_axis_proposal
        if pending is not None and pending[0]==side and np.allclose(position,pending[1],rtol=0,atol=1e-10):
            proposal=pending[2]
        else:
            # Original right-reach neutralization discards the unsubmitted
            # proposal. Keep committed yaw/material and only neutralize its Y.
            command_R=rz(state.command_yaw-state.initial_yaw)@state.capture_rotation
            tcp=anchor+np.asarray(position)-origin;body=tcp-command_R@state.material_point
            proposal=AxisProposal(body,tcp,command_R@state.relative_tool,state.command_yaw,0.,
                body-state.body_reference,state.previous_clearance or 0.,True,0.)
        self.pending_axis_proposal=None
        self.private_axis_prediction=(proposal.body_delta.copy(),proposal.yaw_delta)
        self.private_incremental_command_prediction=True
        try:
            result=self.move({side:(proposal.tcp_reference,proposal.tool_rotation)},minimum_seconds=.25,
                tracking_tolerance=self.p.held_tracking_tolerance_m,finish_on_reference_submitted=True,
                predicate=lambda obs:obs['gripper_contact_force'][side]>self.p.contact_n)
            state.commit(proposal);self.push_last_reference_position=np.asarray(position).copy()
            self.event('coupled_push_reference_submitted',side=side,command_yaw_rad=state.command_yaw,
                body_delta=proposal.body_delta.tolist(),yaw_delta_rad=proposal.yaw_delta,
                original_force_lead_cap_m=self.p.push_reference_lead_m,
                qualification='Real servo interpolation completed; actual tray dynamics and guards remain authoritative')
            return result
        finally:
            self.private_axis_prediction=None;self.private_incremental_command_prediction=False

    def endpoint_reachable(self,side,position,rotation):
        pending=self.pending_axis_proposal
        if (self.p.push_axis_feedback_enabled and pending is not None and pending[0]==side
                and np.allclose(position,pending[2].tcp_reference,rtol=0,atol=1e-10)):
            rotation=pending[2].tool_rotation
        return super().endpoint_reachable(side,position,rotation)

    def _joint_path_clear(self,start,end,*,samples=51):
        if not self.p.push_axis_feedback_enabled or self.private_axis_prediction is None:
            return super()._joint_path_clear(start,end,samples=samples)
        from .axis_feedback import predict_shadow_pose
        shadow=self.mj.MjData(self.m);original=self.d.qpos.copy()
        delta,dyaw=self.private_axis_prediction
        for u in np.linspace(0,1,samples):
            shadow.qpos[:]=original
            q=start+(end-self.sim.target.astype(float))*u
            for hand,offset in (('left',0),('right',8)):
                ids=[self.m.jnt_qposadr[j] for j in self.sim.arms[hand]]
                shadow.qpos[ids]=q[offset:offset+7]
            predict_shadow_pose(self,shadow,u*delta,u*dyaw)
            self.mj.mj_forward(self.m,shadow);contacts=self._contacts(shadow)
            if contacts['illegal_contacts'] or self._penetration_exceeds(contacts,
                    planning_preload=getattr(self,'private_allow_held_preload',False)):
                self.last_private_path_rejection=dict(fraction=float(u),illegal_contacts=contacts['illegal_contacts'],
                    max_penetration=contacts['max_penetration'],hard_max_penetration=contacts['hard_max_penetration'],
                    soft_payload_max_penetration=contacts['soft_payload_max_penetration'],prediction_mode='private_coupled_rigid_yaw_translation',
                    robot_payload_contacts=contacts.get('robot_payload_contacts',[]),
                    robot_payload_contact_scope='private_predicted_path_not_actual_guard')
                return False
        return True

    def statistics(self):
        return dict(guarded_substeps=self.guarded_substeps,
            robot_payload_contact_statistics=self.robot_payload_contact_statistics(),
            hard_penetration_peak_m=self.observed_hard_penetration_peak_m,
            soft_payload_penetration_peak_m=self.observed_soft_payload_penetration_peak_m,
            authorized_boundary_extra_m=self.p.push_transient_boundary_extra_m,
            selected_supported_boundary_total_margin_m=self.p.supported_boundary_margin_m,
            selected_goal_edge_tolerance_m=self.p.position_tolerance_m,
            observed_boundary_extra_peak_m=self.observed_boundary_extra_peak_m,
            strict_push_footprint_gate_passed=self.strict_push_footprint_gate_passed,
            boundary_grace_episodes=self.boundary_grace_episodes,boundary_grace_recoveries=self.boundary_grace_recoveries,
            boundary_grace_max_duration_s=self.boundary_grace_max_duration_s,
            strict_continuous_push_table_contact_gate=self.strict_continuous_push_table_contact_gate,
            push_support_max_absent_duration_s=self.push_table_contact_max_absent_duration_s,
            boundary_duration_scope='outside_old_5mm_geometry; actual contact absence timer separate',
            coverage='every_live_bridge_guard_substep',final_on_table_predicate_unchanged=self.p.supported_boundary_margin_m==.005,
            controller_axis_feedback_enabled=self.p.push_axis_feedback_enabled,
            selected_base_drift_cap_m=self.p.base_drift_m,original_base_drift_cap_m=.005,
            observed_base_drift_peak_m=self.observed_base_drift_peak_m,
            observed_base_yaw_drift_peak_rad=self.observed_base_yaw_drift_peak_rad,
            selected_base_yaw_drift_cap_rad=.01,strict_base_5mm_gate_passed=self.strict_base_5mm_gate_passed,
            base_stage_origin=self.base_origin.tolist(),loaded_goal_policy=self.p.loaded_goal_policy,
            minimum_left_tray_motion_m=self.p.minimum_left_tray_motion_m,
            actual_left_motion_origin=None if self.left_motion_origin is None else self.left_motion_origin.tolist(),
            actual_left_tray_motion_m=None if self.left_motion_origin is None else float(
                (self.d.body(self.p.tray_body).xpos-self.left_motion_origin)@self.left_motion_axis))

    def guard(self):
        # Live measurements only, including the substep that can fault. Neither
        # the held base actuator reference nor the original .01-rad yaw gate
        # is changed by the explicit translational tolerance profile.
        base=self.sim.base_state().astype(float)
        drift=float(np.linalg.norm(base[:2]-self.base_origin[:2]))
        yaw=abs(float(base[2]-self.base_origin[2]))
        self.observed_base_drift_peak_m=max(self.observed_base_drift_peak_m,drift)
        self.observed_base_yaw_drift_peak_rad=max(self.observed_base_yaw_drift_peak_rad,yaw)
        if self.action=='push_loaded':
            from .observer import table_front_region_violation
            name=self.runtime.manifest['target_table'];table=dict(self.runtime.g.tables[name])
            body=self.d.body(name);R=body.xmat.reshape(3,3)
            table.update(table_id=name,center_world=body.xpos.tolist(),yaw_world=float(np.arctan2(R[1,0],R[0,0])))
            if table_front_region_violation(table,base):
                raise Fault('bridge_actual_base_outside_target_table_front',dict(actual_base=base.tolist(),target_table=name))
        if drift>.005:
            self.strict_base_5mm_gate_passed=False
            if not self._base_strict_deviation_logged:
                self._base_strict_deviation_logged=True
                self.event('loaded_mobile_base_strict_5mm_exceeded',actual_drift_m=drift,
                    selected_cap_m=self.p.base_drift_m,stage_base_origin=self.base_origin.tolist(),
                    actual_base=base.tolist(),base_action_reference=self.sim.base_target.tolist(),
                    qualification='Explicit passive-drift acceptance profile; no active base move added')
        return super().guard()

    def _on_table(self,obs):
        relative=np.asarray(obs['tray_corners'])[:,:2]-self.p.table_center_xy
        return bool(obs['table_contacts']>0 and np.isfinite(relative).all()
            and np.all(np.abs(relative)<=np.asarray(self.p.table_half_sizes_xy)+self.p.supported_boundary_margin_m))

    def _boundary_geometry(self,obs):
        xy=np.asarray(obs['tray_corners'],float)[:,:2]
        finite=np.isfinite(xy).all()
        extra=float(max(0.,np.max(np.abs(xy-self.p.table_center_xy)-np.asarray(self.p.table_half_sizes_xy)-.005))) if finite else float('inf')
        return finite,extra

    def observation(self):
        obs=super().observation();finite,extra=self._boundary_geometry(obs)
        gap=float(obs['tray_bottom_z'])-self.p.tabletop_z
        selected_inside=finite and np.all(np.abs(np.asarray(obs['tray_corners'])[:,:2]-self.p.table_center_xy)
            <=np.asarray(self.p.table_half_sizes_xy)+self.p.supported_boundary_margin_m)
        obs.update(strict_table_footprint_inside=bool(finite and extra<=0.),
            selected_table_footprint_inside=bool(selected_inside),
            authorized_boundary_grace_geometry=bool(self._in_push_contact_domain() and finite
                and extra<=self.p.supported_boundary_margin_m-.005+self.p.push_transient_boundary_extra_m and np.isfinite(gap)
                and abs(gap)<=self.p.push_table_contact_grace_gap_m),
            boundary_extra_beyond_original_margin_m=extra)
        return obs

    def _finish_action(self,start):
        if self.action=='push_loaded':
            obs=self.observation()
            if obs['payload_floor_contacts'] or obs['payload_mass_kg']<obs['payload_total_mass_kg']-1e-6:
                raise Fault('bridge_final_payload_not_all_supported_on_tray',dict(
                    actual_on_tray_mass_kg=obs['payload_mass_kg'],actual_total_mass_kg=obs['payload_total_mass_kg']))
            if max(obs['gripper_contact_force'].values())>self.p.contact_n:
                raise Fault('bridge_final_grippers_not_released',obs['gripper_contact_force'])
            if not self.loaded_goal_reached(obs):raise Fault('single_tray_loaded_goal_incomplete',obs)
            self.final_gate_evidence=dict(actual_on_tray_mass_kg=obs['payload_mass_kg'],actual_total_mass_kg=obs['payload_total_mass_kg'],
                actual_floor_contacts=obs['payload_floor_contacts'],actual_table_contacts=obs['table_contacts'],
                strict_original_5mm_on_table=SingleTrayController._on_table(self,obs),
                actual_goal_edge_error_m=abs(self.loaded_goal_remaining(obs)),
                strict_old_30mm_edge_error_passed=abs(self.loaded_goal_remaining(obs))<=.03,
                selected_goal_edge_tolerance_m=self.p.position_tolerance_m,
                selected_boundary_total_margin_m=self.p.supported_boundary_margin_m,
                actual_gripper_contact_force=obs['gripper_contact_force'])
            if self.p.loaded_goal_policy=='handover_left_motion_then_release':
                self.final_gate_evidence.pop('actual_goal_edge_error_m',None)
                self.final_gate_evidence.pop('strict_old_30mm_edge_error_passed',None)
                self.final_gate_evidence.update(loaded_goal_policy=self.p.loaded_goal_policy,
                    actual_left_motion_origin=self.left_motion_origin.tolist(),
                    actual_left_motion_axis=self.left_motion_axis.tolist(),
                    actual_left_tray_motion_m=float((np.asarray(obs['tray_position'])-self.left_motion_origin)@self.left_motion_axis),
                    minimum_left_tray_motion_m=self.p.minimum_left_tray_motion_m,
                    table_left_endpoint_required=False)
        return super()._finish_action(start)

    def _push_missing_support_geometry(self,obs):
        gap=float(obs['tray_bottom_z'])-self.p.tabletop_z
        corners=np.asarray(obs['tray_corners'])
        inside=np.isfinite(corners).all() and np.all(np.abs(corners[:,:2]-self.p.table_center_xy)
            <=np.asarray(self.p.table_half_sizes_xy)+self.p.supported_boundary_margin_m+self.p.push_transient_boundary_extra_m)
        return bool(inside and np.isfinite(gap)
            and abs(gap)<=self.p.push_table_contact_grace_gap_m),gap

    def _observe_push_table_support(self,obs):
        # Called only from the live substep guard. Private planning and read-only
        # observations cannot contaminate measured violation/timing statistics.
        if self._in_push_contact_domain():
            finite,extra=self._boundary_geometry(obs)
            self.observed_boundary_extra_peak_m=max(self.observed_boundary_extra_peak_m,extra)
            if not finite or extra>0:
                self.strict_push_footprint_gate_passed=False
                if self._boundary_missing_since is None:
                    self._boundary_missing_since=float(self.d.time);self.boundary_grace_episodes+=1
                    if self._boundary_last_logged_frame!=self.frames:
                        self._boundary_last_logged_frame=self.frames
                        self.event('transient_boundary_original_gate_exceeded',actual_extra_m=extra,
                            authorized_extra_m=self.p.push_transient_boundary_extra_m,
                            selected_supported_margin_m=self.p.supported_boundary_margin_m,
                            original_margin_m=.005,grace_limit_s=self.p.push_table_contact_grace_frames/self.p.fps,
                            qualification='Explicit boundary acceptance profile; physical support, payload, release gates retained')
                self.boundary_grace_max_duration_s=max(self.boundary_grace_max_duration_s,
                    float(self.d.time)-self._boundary_missing_since)
            elif self._boundary_missing_since is not None:
                duration=float(self.d.time)-self._boundary_missing_since
                self.boundary_grace_max_duration_s=max(self.boundary_grace_max_duration_s,duration)
                self.boundary_grace_recoveries+=1;self._boundary_missing_since=None
        return super()._observe_push_table_support(obs)

    def event(self,name,**details):
        if name=='passenger_payload_initialized':
            if not self.loaded:raise Fault('bridge_payload_initialization_order')
            self.runtime.passenger_loaded=True
        super().event(name,**details)
        row=self.events[-1]
        if self.runtime.trace is not None:
            self.runtime.trace.event(name,**{k:v for k,v in row.items() if k not in ('event','frame')})
        o=self.observer
        if o is not None:
            if name=='action_start':o.begin_action(self.action,table_id=self.runtime.manifest['target_table'],manipulating=True)
            elif name=='grasp_contact_verified':
                o.confirm_grasp(details['sides'],stable_frames=details['stable_frames'],contact_n=self.p.contact_n)
            elif name=='passenger_payload_initialized':o.environment_event(details['environment_evidence'])
            elif name=='left_handover_contact_verified':o.set_push_stage(2)
            elif name=='right_released_after_left_contact':o.set_push_stage(3)
            elif name=='action_complete':
                o.complete_action(verified=True,measured_endpoint_frame=details['measured_endpoint_frame'],
                    actual_handover_verified=self.handover_verified)
        return row

    def release(self,sides,*,predicate=None):
        result=super().release(sides,predicate=predicate)
        if self.observer is not None:self.observer.release_grasp(sides)
        self.event('actual_grasp_release_command_completed',sides=list(sides),
            force_n=self.observation()['gripper_contact_force'],commanded_opening_m=self.sim.target[[7,15]].tolist(),
            measured_opening_m=self.sim.state()[[7,15]].tolist())
        return result

    def _grasp_goals(self):
        """Reuse actual legacy opposed-long-rim tool poses, not f40 yaw90.

        A right→left takeover may acquire the opposite long rim. No tray/base
        reorientation or material-point assignment is applied to live state.
        """
        r=self.runtime;obs=r.observation();pose=obs['tray_pose'][0]
        yaw,_=quat_yaw_tilt(pose[3:]);base_heading=float(self.sim.base_state()[2])
        face=base_heading+float(wrap_angle(yaw-base_heading,np.pi))
        pairs=rim_pairs(r.g.sizes[0],yaw,face,inset=r.cfg.rim_inset_m)
        wanted='width' if r.g.sizes[0,0]>=r.g.sizes[0,1] else 'length'
        pair=next(p for p in pairs if p.axis==wanted)
        center=pose[:3].copy();center[2]+=r.cfg.rim_height_local_m
        return r.grasp_goals(center,pair.face,rim_pair=pair,x_offset=0.,sides=('left','right'))

    def acquire(self,sides,*,prefix=''):
        goals={side:goal for side,goal in self._grasp_goals().items() if side in sides}
        tray=self.d.body(self.p.tray_body);tray_R=tray.xmat.reshape(3,3)
        for side,(position,_) in goals.items():
            local=tray_R.T@(position-tray.xpos)
            normal=np.zeros(3);normal[int(np.argmin(self.p.tray_dimensions[:2]))]=np.sign(local[int(np.argmin(self.p.tray_dimensions[:2]))])
            self.rim_outward_local[side]=normal
        high={side:(position+np.array([0,0,self.p.approach_clearance]),R) for side,(position,R) in goals.items()}
        self.phase=prefix+'approach';self.move(high,openings={s:self.p.open_command for s in sides})
        self.phase=prefix+'contact';self.move(goals,openings={s:self.p.open_command for s in sides},minimum_seconds=.5)
        self.phase=prefix+'close';stable=0
        for _ in range(self.p.max_stage_steps):
            self._opening(sides,self.p.close_command);obs=self.tick()
            stable=stable+1 if all(obs['gripper_contact_force'][s]>self.p.contact_n for s in sides) else 0
            if stable>=self.p.stable_contact_frames and all(abs(self.sim.target[7 if s=='left' else 15]-self.p.close_command)<1e-6 for s in sides):
                self.holding_sides.update(sides)
                if self.p.follow_tray_pose:self._capture_held_tools(sides,obs)
                self.event('grasp_contact_verified',sides=list(sides),force_n=obs['gripper_contact_force'],
                    grasp_provider='legacy_opposed_long_rim_tools',stable_frames=stable)
                return obs
        raise Fault('single_tray_missing_grasp_contact',dict(sides=sides,force_n=obs['gripper_contact_force']))

    def _release_right_outward(self,*,predicate):
        if not self.handover_verified or self.observation()['gripper_contact_force']['left']<=self.p.contact_n:
            raise Fault('single_tray_right_release_before_left_contact')
        if not self.p.push_command_reference:raise Fault('single_tray_outward_release_without_command_reference')
        _,origin,anchor,R=self.push_anchor
        reference=anchor+self.push_last_reference_position-origin
        initial=float(self.sim.state()[15])
        normal=self.d.body(self.p.tray_body).xmat.reshape(3,3)@self.rim_outward_local['right']
        self.event('right_outward_open_start',initial_opening_m=initial,
            outward_direction=normal.tolist(),direction_source='actual_registered_long_rim_normal',
            base_station_unchanged=True)
        for _ in range(math.ceil(self.p.open_command/.002)+2):
            opening=min(self.p.open_command,float(self.sim.target[15])+.002)
            outward=.005+.5*max(0.,opening-initial)
            self.move({'right':(reference+outward*normal,R)},openings={'right':opening},minimum_seconds=.25,
                tracking_tolerance=self.p.held_tracking_tolerance_m,finish_on_reference_submitted=True,
                predicate=lambda obs:obs['gripper_contact_force']['left']>self.p.contact_n and (predicate is None or predicate(obs)))
            if opening>=self.p.open_command:break
        else:raise Fault('single_tray_right_outward_release_budget_exhausted')
        self.holding_sides.discard('right')
        self.event('right_outward_open_complete',actual_opening_m=float(self.sim.state()[15]),
            force_n=self.observation()['gripper_contact_force'],outward_reference_m=outward)

    def tick(self):
        r=self.runtime
        if r.sim is not self.sim or r.d is not self.d or r.m is not self.m:
            raise Fault('bridge_live_identity_changed')
        original_guard=r.guard
        def both_guards():
            original_guard()  # finite, warnings, collision, camera, limits
            self.guard()      # actual load, table/grace, fixed front, hand state
        r.guard=both_guards
        r.phase=self.phase
        r.fsm_state=State.ADJUST_TRAY if self.action=='push_loaded' else State.PLACE_TRAY
        if self.observer is not None:
            if self.phase=='right_push' and self.observer.push_stage==0:self.observer.set_push_stage(1)
            elif self.phase=='left_push' and self.observer.push_stage==3:self.observer.set_push_stage(4)
        try:
            # Original runtime journals actual global base_action/base_state
            # and each submitted actuator ctrl; f40's fixed-base zero padding
            # is never used here.
            r.tick()
        finally:
            r.guard=original_guard
            self.frames=r.trace.count if r.trace is not None else r.steps
        return self.observation()
