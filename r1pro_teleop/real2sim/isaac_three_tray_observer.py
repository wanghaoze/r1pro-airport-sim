"""Measured-state task observer shared by native expert and pure-policy runs.

No commands, inverse kinematics, object reset or success-label override lives
here. A transition is rejected when its native evidence is absent.
"""
import numpy as np
from .three_tray_migration import PROFILE, RULE, PROMPTS


class NativeTaskFault(RuntimeError):
    pass


class ThreeTrayObserver:
    def __init__(self, *, contact_n=.5, stable_frames=3, support_frames=10, minimum_lift_m=.02):
        self.contact_n=contact_n;self.stable_frames=stable_frames;self.support_frames=support_frames
        self.minimum_lift_m=minimum_lift_m
        self.spans=[];self.loads=[];self.cycles=[];self.events=[];self.action=None
        self.stage='idle';self.cycle=None;self.stable=0;self.previous=None

    def event(self,name,frame,**data):
        self.events.append(dict(event=name,frame=int(frame),**data))

    def begin(self, prompt, frame, tray, cycle):
        if self.action is not None or prompt not in PROMPTS:
            raise NativeTaskFault('invalid_action_transition')
        if prompt==PROMPTS[0]:
            if self.cycle is not None:raise NativeTaskFault('previous_cycle_incomplete')
            self.cycle=dict(cycle_id=int(cycle),tray_id=tray,right_actual_push=False,
                left_stable_grasp=False,right_release_after_left_grasp=False,
                left_motion_after_right_release=False,actual_tray_left_displacement_m=0.)
        if self.cycle is None or self.cycle['tray_id']!=tray or self.cycle['cycle_id']!=cycle:
            raise NativeTaskFault('cycle_identity_changed')
        self.action=dict(prompt=prompt,start=int(frame),tray_id=tray,cycle_id=int(cycle))
        self.stable=0;self.event('action_start',frame,**self.action)

    def observe(self, obs, frame):
        if self.action is None:return
        i=int(self.action['tray_id'].split('_')[-1]);p=self.action['prompt'];c=self.cycle
        force=np.asarray(obs['finger_force'][i]);edges=np.asarray(obs['long_edge_sign'][i])
        opposed=bool(np.all(force>self.contact_n) and edges[0]*edges[1]==-1)
        if p==PROMPTS[0]:
            if obs['loaded'][i]:raise NativeTaskFault('pick_requires_empty_tray')
            self.stable=self.stable+1 if opposed else 0
            if self.stable>=self.stable_frames:
                c['opposed_long_edges_pick_place']=True;c['pick_bilateral_verified_frame']=int(frame)
        elif p==PROMPTS[1]:
            if obs['loaded'][i]:raise NativeTaskFault('place_requires_empty_tray')
            self.stable=self.stable+1 if opposed else 0
            if self.stable>=self.stable_frames:c['place_bilateral_verified_frame']=int(frame)
        if p==PROMPTS[2]:
            if not obs['loaded'][i]:raise NativeTaskFault('flush_requires_environment_load')
            if self.stage=='right_push':
                delta=float((obs['tray_pose'][i,:3]-self.right_origin)@self.left_axis)
                if delta>0:c['right_actual_push']=True;c['actual_right_tray_displacement_m']=delta
            elif self.stage=='left_acquire':
                good=bool(np.all(force>self.contact_n) and np.all(edges!=0))
                self.stable=self.stable+1 if good else 0
                if self.stable>=self.stable_frames:
                    c['left_stable_grasp']=True;c['left_stable_grasp_frame']=int(frame)
            elif self.stage=='right_release':
                # The controller already enforces the authorized 0.3 s contact
                # grace. A zero-force sample alone is not a new hard stop.
                if c['left_stable_grasp'] and force[0]>self.contact_n and force[1]<=self.contact_n and obs['command'][15]>=.1-1e-7:
                    c['right_release_after_left_grasp']=True;c['actual_right_release_frame']=int(frame)
            elif self.stage=='left_push':
                if not c['right_release_after_left_grasp']:raise NativeTaskFault('left_push_before_actual_right_release')
                delta=float((obs['tray_pose'][i,:3]-self.left_origin)@self.left_axis)
                c['actual_tray_left_displacement_m']=max(c['actual_tray_left_displacement_m'],delta)
                c['left_motion_after_right_release']=bool(delta>=.03)
        self.previous=obs

    def push_stage(self,stage,obs,frame):
        if stage not in ('right_push','left_acquire','right_release','left_push','left_release'):
            raise NativeTaskFault('unknown_push_stage')
        if self.action is None or self.action['prompt']!=PROMPTS[2]:raise NativeTaskFault('push_stage_outside_flush')
        i=int(self.action['tray_id'].split('_')[-1])
        if stage=='right_push':
            self.left_axis=np.asarray(obs['robot_left'],float).copy();self.right_origin=obs['tray_pose'][i,:3].copy()
        if stage=='right_release' and not self.cycle['left_stable_grasp']:
            raise NativeTaskFault('right_release_without_stable_left_grasp')
        if stage=='left_push':
            if not self.cycle.get('right_release_after_left_grasp'):raise NativeTaskFault('right_release_unverified')
            self.left_origin=obs['tray_pose'][i,:3].copy()
        self.stage=stage;self.stable=0;self.event('actual_push_stage_start',frame,stage=stage,tray_id=self.cycle['tray_id'])

    def loaded(self, frame, tray, cycle, *, protected_unchanged):
        if self.action is not None or self.cycle is None or tray!=self.cycle['tray_id'] or cycle!=self.cycle['cycle_id']:
            raise NativeTaskFault('environment_load_outside_place_flush_gap')
        if not protected_unchanged:raise NativeTaskFault('environment_load_modified_robot_or_trays')
        self.loads.append(dict(frame=int(frame),tray_id=tray,cycle_id=cycle,robot_and_all_trays_unchanged=True))
        self.event('passenger_load',frame,tray_id=tray,cycle_id=cycle,training_eligible=False)

    def finish(self,obs,frame,*,support_stable=False):
        if self.action is None or frame<=self.action['start']:raise NativeTaskFault('empty_or_missing_action')
        c=self.cycle;i=int(c['tray_id'].split('_')[-1]);prompt=self.action['prompt']
        c['front_region_manipulation']=bool(c.get('front_region_manipulation',True) and obs['front_region_ok'])
        if not c['front_region_manipulation']:raise NativeTaskFault('table_side_manipulation')
        if prompt==PROMPTS[0]:
            if (not c.get('opposed_long_edges_pick_place') or obs['loaded'][i] or
                    np.min(obs['finger_force'][i])<=self.contact_n or obs['long_edge_sign'][i,0]*obs['long_edge_sign'][i,1]!=-1 or
                    obs['table_force'][i]>.01 or obs['lift_clearance'][i]<self.minimum_lift_m):
                raise NativeTaskFault('native_empty_pick_endpoint_unverified')
            c['empty_pick_place']=True
        elif prompt==PROMPTS[1]:
            if (not c.get('place_bilateral_verified_frame') or obs['loaded'][i] or not support_stable or obs['table_force'][i]<=.01 or
                    np.max(obs['finger_force'][i])>self.contact_n or obs['axis_error_rad'][i]>np.deg2rad(15)):
                raise NativeTaskFault('native_empty_place_endpoint_unverified')
            c['long_axis_parallel_robot_forward']=True
            c['actual_place_axis_error_rad']=float(obs['axis_error_rad'][i])
        else:
            if (not all(c.get(key) for key in ('right_actual_push','left_stable_grasp',
                    'right_release_after_left_grasp','left_motion_after_right_release')) or
                    c['actual_tray_left_displacement_m']<.03 or not support_stable or
                    obs['table_force'][i]<=.01 or np.max(obs['finger_force'][i])>self.contact_n or
                    not obs['payload_on_tray'][i] or not obs['boundary_ok'][i]):
                raise NativeTaskFault('native_loaded_flush_endpoint_unverified')
            c.update(final_release=True,stable_table_support=True,all_three_payloads_on_tray=True)
            self.cycles.append(dict(c));self.cycle=None;self.stage='idle'
        self.spans.append(dict(self.action,end=int(frame)))
        self.event('action_complete',frame,**self.spans[-1]);self.action=None

    def qualification(self,episode_id,trace_sha256,final_obs):
        expected={'tray_0','tray_1','tray_2'}
        success=(self.action is None and self.cycle is None and {c['tray_id'] for c in self.cycles}==expected
            and bool(np.all(final_obs['payload_on_tray'])) and bool(np.all(final_obs['table_force']>.01))
            and bool(np.all(final_obs['finger_force']<=self.contact_n)) and bool(np.all(final_obs['boundary_ok']))
            and bool(np.all(final_obs.get('payload_speed',np.zeros(3))<.01)))
        return dict(schema='airport_isaac_task_qualification/1',engine='isaacsim',physics_backend='physx',
            profile=PROFILE,task_rule_revision=RULE,episode_id=episode_id,trace_sha256=trace_sha256,
            complete_task_success=bool(success),qualified_tray_ids=sorted({c['tray_id'] for c in self.cycles}),
            cycles=self.cycles,incomplete_cycle=dict(self.cycle) if self.cycle else None,incomplete_action=self.action,
            final_diagnostics={k:np.asarray(final_obs[k]).tolist() for k in
                ('tray_pose','table_force','finger_force','payload_on_tray','boundary_ok','axis_error_rad')},
            task_success_label_source='native_measured_state_observer',teacher_kinematics_used_as_success_evidence=False)
