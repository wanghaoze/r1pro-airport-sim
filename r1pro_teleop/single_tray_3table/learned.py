"""Three-command mobile19 learned execution; no motion planner or fallback.

The model performs preparation, navigation, opposed pickup/place and loaded
handover. Privileged geometry/contact is used only for guards and completion.
"""
from pathlib import Path
from types import SimpleNamespace
import numpy as np
from ..vla.policy import Pi05Policy,PolicyError
from ..vla.executor import VLAOperationExecutor,ServoProjection
from ..vla.machine import runtime_bounds,runtime_rate_limiter,stable_evaluation
from ..vla.data_three_table_single_tray import (PROFILE,RULE_REVISION,
    FINAL_ORIENTATION_DEFINITION,TABLE_IDS,long_rim_codes,final_axis_error,table_geometry_values)
from ..airport_fsm.contracts import State
from ..airport_fsm.geometry import Operation
from ..single_tray_lab.learned import PhysicalHandover
from ..single_tray_lab.placement_clearance import grippers_clear_of_tray
from .observer import ThreeTableObserver,table_front_region_violation
from .loaded_bridge import LoadedBridgeController,derive_bridge_profile

PROMPTS=('Pick up the tray','Place the tray','Flush tray to the left')
LABELS=('pick_empty','place_empty','push_loaded')


class ThreeTablePolicy(Pi05Policy):
    @classmethod
    def from_client(cls,client,contract):
        meta=client.get_server_metadata()
        expected=dict(checkpoint_id=contract.checkpoint_id,prompt_mode=PROFILE,
            task_profile=PROFILE,task_rule_revision=RULE_REVISION,
            final_orientation_definition=FINAL_ORIENTATION_DEFINITION,
            model='pi05',control_hz=20,action_width=19,action_horizon=contract.action_horizon,
            action_space='mobile19_absolute_v1',base_mode='planar_mobile_table_front',
            base_actuated=True,control_mask_applied=False,raw_action_output_field='raw_actions')
        if (contract.prompt_mode!=PROFILE or contract.action_width!=19 or not isinstance(meta,dict)
            or any(meta.get(k)!=v for k,v in expected.items()) or meta.get('fine_tuned') is not True):
            raise PolicyError('three_table_server_contract_mismatch')
        mask=meta.get('model_action_mask')
        if not isinstance(mask,list) or len(mask)!=19 or any(x is not True for x in mask):
            raise PolicyError('three_table_active_mobile19_required')
        policy=cls(client,contract);policy.server_metadata=meta.copy();return policy

    @classmethod
    def from_websocket(cls,host,port,contract):
        from openpi_client.websocket_client_policy import WebsocketClientPolicy
        return cls.from_client(WebsocketClientPolicy(host=host,port=port),contract)

    def infer(self,images,state,prompt):
        # Official adapter's actions and raw_actions must be identical across
        # all 19 active channels. No base masking is permitted in this scope.
        class Capture:
            def __init__(self,client):self.client=client;self.reply=None
            def infer(self,obs):self.reply=self.client.infer(obs);return self.reply
        original=self.client;capture=Capture(original);self.client=capture
        try:actions=super().infer(images,state,prompt)
        finally:self.client=original
        reply=capture.reply;raw=np.asarray(reply.get('raw_actions'),dtype=np.float32)
        if raw.shape!=actions.shape or not np.isfinite(raw).all() or not np.array_equal(raw,actions):
            raise PolicyError('three_table_raw_action_identity_failed')
        mask=np.asarray(reply.get('model_action_mask'))
        if mask.shape!=(19,) or mask.dtype!=np.bool_ or not np.all(mask):
            raise PolicyError('three_table_reply_active_mobile19_required')
        return actions


def contact_snapshot(runtime,scene):
    """Read the public actual MuJoCo contact sampler without an observer hook."""
    sampler=ThreeTableObserver.__new__(ThreeTableObserver)
    sampler.r=runtime;sampler.scene=scene;sampler.capacity=256
    sampler.origin=np.zeros(3);sampler.manipulating=False;sampler.table=None
    sampler.confirmed=np.zeros(2,bool);sampler.push_stage=0
    return sampler.capture(include_environment=False)


def opposed_contact(snapshot,dimensions):
    codes=long_rim_codes(snapshot['gripper_tray_contact_points_local'][None],
        snapshot['gripper_tray_contact_normals_local'][None],
        snapshot['gripper_tray_contact_active'][None],dimensions,reject_invalid=False)[0]
    return bool(codes[0] in (-1,1) and codes[1]==-codes[0])


def actual_rim_codes(snapshot,dimensions):
    return long_rim_codes(snapshot['gripper_tray_contact_points_local'][None],
        snapshot['gripper_tray_contact_normals_local'][None],
        snapshot['gripper_tray_contact_active'][None],dimensions,reject_invalid=False)[0]


def place_completion(numeric,obs,scene,*,opposed_seen,released,front_violation):
    """The same declared support/50mm/horizontal-axis endpoint as source QA.

    No withdrawal-distance gate is introduced. Carrying between tables does
    not certify placement, nor is it treated as side-of-table manipulation.
    """
    index=TABLE_IDS.index(scene['target_table'])
    if not opposed_seen or not released or front_violation or numeric['table_contact_counts'][index]<=0:return False
    margin=scene.get('loaded_push_target',{}).get('supported_boundary_margin_m',.005)
    if type(margin) not in (int,float) or not np.isfinite(margin) or not 0<=margin<=.05:
        raise PolicyError('three_table_declared_support_margin_invalid')
    excess,_=table_geometry_values(numeric['tray_corners_world'],scene['tables'])
    aligned=float(final_axis_error(numeric['tray_long_axis_world'],numeric['robot_forward_world']))<=np.deg2rad(15)
    return bool(excess[index]<=margin and aligned and np.asarray(obs['floor_contact'])[0]==0)


class LearnedThreeTable:
    def __init__(self,runtime,scene,policy,*,output,push_reference_profile,
                 execute_steps=5,max_action_steps=6000,actuator_saturation=False,reference_rate_limit=False):
        if policy.contract.prompt_mode!=PROFILE or policy.contract.action_width!=19:
            raise PolicyError('three_table_learned_mobile19_contract_required')
        self.r=runtime;self.scene=scene;self.policy=policy;self.output=Path(output)
        self.output.mkdir(parents=True,exist_ok=False);self.reference=push_reference_profile
        self.bridge=None;self.spans=[];self.action=None;self.opposed_seen=False;self.handover=None
        self.grasp_contact_ticks=np.zeros(2,dtype=int);self.grasp_sample_step=None
        self.initial_bottom=float(runtime.observation()['min_z'][0])
        # New model files explicitly start their planar joint coordinates at
        # zero. Reject a different origin instead of silently masking/subtracting.
        self.base_origin=np.asarray(runtime.sim.base_joint_state()).copy()
        if np.any(self.base_origin!=0):raise PolicyError('three_table_nonzero_initial_joint_origin')
        projection=ServoProjection(self.output/'projection',mode='actuator_saturation') if actuator_saturation else None
        limiter=runtime_rate_limiter(runtime,self.output/'rate') if reference_rate_limit else None
        def record(payload):
            path=self.output/f'decision_{runtime.steps:08d}.npz'
            with path.open('xb') as stream:
                np.savez_compressed(stream,state=payload['state'],actions=payload['actions'],
                    servo_actions=payload['servo_actions'],prompt=np.asarray(payload['prompt']),
                    checkpoint_id=np.asarray(policy.contract.checkpoint_id),
                    **{'image_'+k:v for k,v in payload['images'].items()})
        self.executor=VLAOperationExecutor(runtime,policy,runtime_bounds(runtime),execute_steps=execute_steps,
            max_operation_steps=max_action_steps,projection=projection,rate_limiter=limiter,on_decision=record)

    def endpoint(self,r,operation):
        numeric=contact_snapshot(r,self.scene);obs=r.observation();force=np.asarray(obs['gripper_contact_force'])[0]
        opposed=opposed_contact(numeric,self.scene['tray']['size'])
        if self.action in ('pick_empty','place_empty'):
            codes=actual_rim_codes(numeric,self.scene['tray']['size'])
            active=np.asarray(numeric['gripper_tray_contact_active']).any(axis=1)
            actual_force=np.asarray(numeric['gripper_contact_force'])
            contact=active & (actual_force>r.cfg.criteria.contact_n)
            # The source confirms grasp after 150ms of real contact. Merely
            # approaching, touching once or preparing with one legal arm is
            # not a completed dual grasp. Repeated reads never advance time.
            if self.grasp_sample_step!=r.steps:
                self.grasp_contact_ticks=np.where(contact,self.grasp_contact_ticks+1,0)
                self.grasp_sample_step=r.steps
            confirmed=self.grasp_contact_ticks>=max(1,int(round(.15*r.cfg.fps)))
            if np.any(confirmed & (codes==2)):
                raise PolicyError('three_table_actual_short_or_ambiguous_rim_grasp')
            if np.all(confirmed) and not opposed:
                raise PolicyError('three_table_actual_opposed_long_rims_required')
            lifted=obs['table_contact'][0]==0 and obs['min_z'][0]-self.initial_bottom>=r.cfg.criteria.lifted_m
            if lifted and not (np.all(contact) and opposed):
                raise PolicyError('three_table_lift_requires_actual_opposed_long_rims')
            self.opposed_seen|=bool(np.all(confirmed) and opposed)
        if np.all(force>r.cfg.criteria.contact_n):
            # Whole Place includes carrying. The source observer does not
            # apply target-table manipulation bounds while travelling.
            manipulating=(self.action=='pick_empty' or self.action=='place_empty' and
                numeric['table_contact_counts'][TABLE_IDS.index(self.scene['target_table'])]>0)
            if manipulating:
                table=r.g.tables[self.scene['source_table'] if self.action=='pick_empty' else self.scene['target_table']]
                if table_front_region_violation(table,r.d.body('base_link').xpos):
                    raise PolicyError('three_table_manipulation_outside_table_front')
        if self.action=='pick_empty':
            return bool(self.opposed_seen and np.all(force>r.cfg.criteria.contact_n) and
                obs['table_contact'][0]==0 and obs['min_z'][0]-self.initial_bottom>=r.cfg.criteria.lifted_m)
        if self.action=='place_empty':
            table_index=TABLE_IDS.index(self.scene['target_table'])
            release=bool(np.all(force<=r.cfg.criteria.contact_n) and np.all(r.sim.target[[7,15]]>=np.float32(r.cfg.gripper_open_m)))
            target_contact=numeric['table_contact_counts'][table_index]>0
            front_violation=(table_front_region_violation(r.g.tables[self.scene['target_table']],r.d.body('base_link').xpos)
                if target_contact else False)
            return place_completion(numeric,obs,self.scene,opposed_seen=self.opposed_seen,
                released=release,front_violation=front_violation)
        measured=self.bridge.observation();previous_stage=self.handover.stage;self.handover.update(measured)
        if previous_stage=='right_release' and self.handover.stage=='left_push' and self.bridge.left_motion_origin is None:
            self.bridge.left_motion_origin=np.asarray(measured['tray_position']).copy()
            self.bridge.left_motion_axis=np.asarray(self.bridge.p.robot_left).copy()
            self.r.trace.event('actual_model_left_motion_origin_after_right_release',actual_tray_position=self.bridge.left_motion_origin.tolist(),actual_robot_left=self.bridge.left_motion_axis.tolist(),evidence_source='actual_measured_handover')
        self.bridge.handover_verified=bool(self.handover.verified)
        self.bridge.left_reference_captured=bool(self.handover.verified)
        self.bridge._capture_actual_left_origin(measured)
        released=max(measured['gripper_contact_force'].values())<=self.bridge.p.contact_n
        return bool(self.handover.verified and released and self.bridge.loaded_goal_reached(measured) and
            measured['payload_floor_contacts']==0 and measured['payload_mass_kg']>=measured['payload_total_mass_kg']-1e-6)

    def run_action(self,label,prompt):
        r=self.r;self.action=label;self.opposed_seen=False;start=r.trace.count
        r.fsm_state=State.GRASP_TRAY if label=='pick_empty' else State.PLACE_TRAY if label=='place_empty' else State.ADJUST_TRAY
        r.phase='vla_'+label;r.allowed_tray=0;r.target_slot=0
        r.trace.event('action_start',action_label=label,prompt=prompt,controller_source='vla_generated')
        stable=stable_evaluation(self.endpoint,3 if label!='push_loaded' else self.bridge.p.stable_support_frames)
        operation=Operation(0,0,np.asarray(self.scene['place_target']['position_world']),float(self.scene['place_target']['yaw_world']))
        self.executor.execute_operation(operation,prompt,stable)
        # Record the measured endpoint with the last model command held; this
        # is not a teacher trajectory or an invented/padded observation.
        r.tick()
        if not self.endpoint(r,operation):raise PolicyError('three_table_endpoint_changed_during_recorded_hold')
        span=dict(action_label=label,start_frame=start,end_frame=r.trace.count,verified=True,
            measured_endpoint_frame=r.trace.count-1,controller_source='vla_generated')
        self.spans.append(span);r.trace.event('action_complete',**span)

    def run(self):
        self.run_action(LABELS[0],PROMPTS[0]);self.run_action(LABELS[1],PROMPTS[1])
        from ..single_tray_lab.three_table_scene import passenger_load_three_table
        profile=derive_bridge_profile(self.r,self.scene,self.reference)
        self.bridge=LoadedBridgeController.bind(self.r,profile,
            passenger_loader=lambda sim:passenger_load_three_table(sim,self.scene))
        # Only the external passenger-loading phase uses held model targets.
        # No acquire/move/push/teacher primitive is invoked.
        self.bridge.passenger_load()
        self.bridge.action='push_loaded';self.bridge.phase='vla_push_loaded'
        original_guard=self.r.guard
        def guarded():original_guard();self.bridge.guard()
        self.r.guard=guarded
        self.bridge.right_motion_origin=np.asarray(self.bridge.observation()['tray_position']).copy()
        self.handover=PhysicalHandover(profile,self.bridge.observation()['tray_position'],
            goal_checker=self.bridge.loaded_goal_reached)
        self.run_action(LABELS[2],PROMPTS[2])
        if self.r.id_calls!=0:raise PolicyError('three_table_inverse_solver_used_by_learned_execution')
        return dict(task_completed=True,physics_success=True,actual_handover_verified=self.handover.verified,
            action_spans=self.spans,inverse_solver_calls=int(self.r.id_calls),teacher_fallback_calls=0)
