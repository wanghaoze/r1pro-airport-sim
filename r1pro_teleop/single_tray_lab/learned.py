"""Pure learned three-command DAG. Physics guards are never learned or bypassed."""
from pathlib import Path
import numpy as np
from r1pro_teleop.vla.policy import PolicyError,Pi05Policy
from .control import ACTION_LABELS, ACTION_PROMPTS
from .placement_clearance import grippers_clear_of_tray
from .grasp_contract import long_rim_contract,validate_long_rim_contract


class _CapturingClient:
    def __init__(self,client):self.client=client;self.reply=None
    def infer(self,observation):
        self.reply=self.client.infer(observation);return self.reply


class SingleTrayPolicy(Pi05Policy):
    """Explicit fixed-front serving protocol; preserve inactive raw predictions."""
    @classmethod
    def from_client(cls,client,contract):
        meta=client.get_server_metadata()
        expected=dict(checkpoint_id=contract.checkpoint_id,prompt_mode='single_tray_action3_v1',
            action_width=19,action_horizon=contract.action_horizon,control_hz=20,model='pi05',
            action_space='fixed_front_arm16_zero_padded19',base_mode='fixed_front',base_actuated=False,
            control_mask_applied=True,raw_action_output_field='raw_actions')
        mask=meta.get('model_action_mask') if isinstance(meta,dict) else None
        if not isinstance(meta,dict) or any(meta.get(k)!=v for k,v in expected.items()) or contract.action_width!=19 or contract.prompt_mode!='single_tray_action3_v1':
            raise PolicyError('single_tray_server_contract_mismatch')
        if meta['base_actuated'] is not False or meta['control_mask_applied'] is not True:
            raise PolicyError('single_tray_server_contract_mismatch')
        if not isinstance(mask,list) or len(mask)!=19 or any(type(x) is not bool for x in mask) or mask!=[True]*16+[False]*3:
            raise PolicyError('single_tray_server_mask_mismatch')
        if 'allowed_long_rim_contract' in meta:
            try:validate_long_rim_contract(meta['allowed_long_rim_contract'])
            except ValueError as exc:raise PolicyError('single_tray_server_rim_contract_mismatch') from exc
        return cls(_CapturingClient(client),contract)

    @classmethod
    def from_websocket(cls,host,port,contract):
        from openpi_client.websocket_client_policy import WebsocketClientPolicy
        return cls.from_client(WebsocketClientPolicy(host=host,port=port),contract)

    def infer(self,images,state,prompt):
        command=super().infer(images,state,prompt);reply=self.client.reply
        try:raw=np.asarray(reply.get('raw_actions'),dtype=np.float32)
        except (TypeError,ValueError) as exc:raise PolicyError('single_tray_invalid_raw_output') from exc
        if raw.shape!=command.shape or not np.isfinite(raw).all() or not np.array_equal(raw[:,:16],command[:,:16]):
            raise PolicyError('single_tray_raw_masked_output_mismatch')
        mask=reply.get('model_action_mask')
        if np.asarray(mask).dtype!=np.bool_ or not np.array_equal(mask,np.r_[np.ones(16,bool),np.zeros(3,bool)]) or np.any(command[:,16:]!=0):
            raise PolicyError('single_tray_reply_mask_mismatch')
        self.last_raw_actions=raw.copy();return command


def validate_chunk(actions, lower, upper):
    a=np.asarray(actions,dtype=float)
    # The serving contract emits float32. Compare against that same exact
    # representation (e.g. float32(.1)); no physical tolerance is introduced.
    lower=np.asarray(lower,dtype=np.float32).astype(float);upper=np.asarray(upper,dtype=np.float32).astype(float)
    if a.ndim!=2 or a.shape[1]!=19 or len(a)==0 or not np.isfinite(a).all():
        raise PolicyError('single_tray_invalid_policy_chunk')
    if np.any(a[:,16:]!=0):raise PolicyError('single_tray_policy_base_action_forbidden')
    if np.any(a[:,:16]<lower) or np.any(a[:,:16]>upper):
        raise PolicyError('single_tray_policy_outside_joint_limits')
    return a


def lateral_goal(obs,profile,on_table):
    corners=np.asarray(obs.get('tray_corners'),dtype=float)
    if not on_table or corners.shape!=(8,3) or not np.isfinite(corners).all():return False
    left=np.asarray(profile.robot_left,dtype=float)
    target=float(np.asarray(profile.loaded_goal_position)@left)+max(profile.tray_dimensions[:2])/2
    error=target-float(np.max(corners@left))
    return bool(np.isfinite(error) and abs(error)<=profile.position_tolerance_m)


def completion(action, obs, profile, *, initial_bottom, on_table, handover, loaded_goal=None,withdrawn=False):
    forces=obs['gripper_contact_force'];opened=obs['gripper_openings']
    if action=='pick_empty':
        return not obs['payload_loaded'] and obs['table_contacts']==0 and obs['tray_bottom_z']-initial_bottom>=profile.minimum_lift_clearance and min(forces.values())>profile.contact_n
    released=max(forces.values())<=profile.contact_n and min(opened)>=.06
    if action=='place_empty':
        return not obs['payload_loaded'] and on_table and released and withdrawn
    if action=='push_loaded':
        reached=lateral_goal(obs,profile,on_table) if loaded_goal is None else loaded_goal
        return obs['payload_loaded'] and obs['payload_support_contacts']>0 and on_table and released and handover and reached
    raise PolicyError('single_tray_unknown_learned_action')


class PhysicalHandover:
    """Measured right push → stable bilateral → left-retained right release → left push."""
    def __init__(self, profile, position, *, goal_checker=None):
        self.p=profile;self.start=np.asarray(position).copy();self.stage='right_push';self.stable=0
        self.right_seen=False;self.left_start=None;self.verified=False
        self.goal_checker=goal_checker

    def update(self, obs):
        left=obs['gripper_contact_force']['left']>self.p.contact_n
        right=obs['gripper_contact_force']['right']>self.p.contact_n
        position=obs['tray_position'];axis=np.asarray(self.p.robot_left)
        if self.stage=='right_push':
            if left:raise PolicyError('single_tray_left_contact_before_right_push')
            self.right_seen|=right
            if self.right_seen and not right:raise PolicyError('single_tray_right_contact_lost_before_handover')
            if right and float((position-self.start)@axis)>=.001:self.stage='bilateral'
        elif self.stage=='bilateral':
            if not right:raise PolicyError('single_tray_right_release_before_bilateral_contact')
            self.stable=self.stable+1 if left else 0
            if self.stable>=self.p.stable_contact_frames:self.stage='right_release'
        elif self.stage=='right_release':
            if not left:raise PolicyError('single_tray_handover_left_contact_lost')
            if not right:self.stage='left_push';self.left_start=np.asarray(position).copy()
        elif self.stage=='left_push':
            if right:raise PolicyError('single_tray_right_recontact_after_handover')
            if not left:raise PolicyError('single_tray_left_contact_lost_before_left_push')
            if float((position-self.left_start)@axis)>=.001:self.stage='left_transport';self.verified=True
        elif self.stage=='left_transport':
            if right:raise PolicyError('single_tray_right_recontact_after_handover')
            at_goal=self.goal_checker(obs) if self.goal_checker is not None else lateral_goal(obs,self.p,obs['table_contacts']>0)
            if not left and not at_goal:raise PolicyError('single_tray_left_release_before_goal')
        return self.verified


class NativePolicyImages:
    """Source XML camera poses, native sizes, isolated renderer lifetime."""
    def __init__(self, controller, scene, names):
        from r1pro_teleop.airport_fsm.contracts import camera_shapes
        self.c=controller;self.shapes=camera_shapes(scene);self.names=names;self.renderers={}
        if any(n not in self.shapes for n in names):raise PolicyError('single_tray_missing_native_camera')

    def __call__(self):
        import mujoco
        images={}
        for n in self.names:
            h,w,_=self.shapes[n]
            if n not in self.renderers:self.renderers[n]=mujoco.Renderer(self.c.m,height=h,width=w)
            r=self.renderers[n];r.update_scene(self.c.d,camera=n,scene_option=self.c.sim.options)
            image=r.render().copy()
            if image.shape!=(h,w,3) or image.dtype!=np.uint8:raise PolicyError('single_tray_bad_native_rgb')
            images[n]=image
        return images

    def close(self):
        for r in self.renderers.values():r.close()
        self.renderers.clear()


class LearnedSingleTray:
    def __init__(self, controller, policy, images, *, output, execute_steps=5, max_steps=1200):
        if type(execute_steps) is not int or type(max_steps) is not int or not 1<=execute_steps<=policy.contract.action_horizon or max_steps<1:
            raise PolicyError('single_tray_invalid_policy_budget')
        if policy.contract.prompt_mode!='single_tray_action3_v1':raise PolicyError('single_tray_wrong_policy_prompt_mode')
        self.c,self.policy,self.images=controller,policy,images;self.execute_steps=execute_steps;self.max_steps=max_steps
        self.output=Path(output);self.output.mkdir(parents=True,exist_ok=False)
        self.lower=np.empty(16);self.upper=np.empty(16)
        for side,offset in [('left',0),('right',8)]:
            ids=controller.sim.arms[side]
            if not all(controller.m.jnt_limited[j] for j in ids):raise PolicyError('single_tray_unbounded_joint')
            self.lower[offset:offset+7],self.upper[offset:offset+7]=controller.m.jnt_range[ids].T
            fingers=controller.sim.fingers[side]
            if not all(controller.m.jnt_limited[j] for j in fingers):raise PolicyError('single_tray_unbounded_gripper')
            # This is an opening *command*, not a measured finger position.
            # apply_target retains its existing per-finger physical clamps.
            self.lower[offset+7],self.upper[offset+7]=0.,.1
        self.rate=np.array([.025]*7+[.002]+[.025]*7+[.002]);self.decisions=0

    def execute(self, action):
        c=self.c;c.action=action;c.phase='learned_policy';start=c.frames;initial=c.observation()['tray_bottom_z']
        stable=0;handover=False;previous=None
        contact_sequence=PhysicalHandover(c.p,c.observation()['tray_position'],goal_checker=c.loaded_goal_reached) if action=='push_loaded' else None
        c.event('learned_action_start',checkpoint_id=self.policy.contract.checkpoint_id,language_prompt=ACTION_PROMPTS[action],allowed_long_rim_contract=long_rim_contract())
        while c.frames-start<self.max_steps:
            state=np.r_[c.sim.state(),(c.sim.base_state()-c.base_origin)]
            images=self.images();raw=validate_chunk(self.policy.infer(images,state,ACTION_PROMPTS[action]),self.lower,self.upper)
            np.savez_compressed(self.output/f'decision_{self.decisions:06d}.npz',state=state,raw_actions=raw,
                raw_model_actions=getattr(self.policy,'last_raw_actions',raw),model_action_mask=np.r_[np.ones(16,bool),np.zeros(3,bool)],frame=c.frames)
            self.decisions+=1
            for a in raw[:min(self.execute_steps,self.max_steps-(c.frames-start))]:
                c.sim.target=c.sim.target+np.clip(a[:16]-c.sim.target,-self.rate,self.rate)
                obs=c.tick();forces=obs['gripper_contact_force']
                if action=='push_loaded':
                    prior=contact_sequence.stage;handover=contact_sequence.update(obs)
                    if prior!=contact_sequence.stage:c.event('learned_measured_handover_stage',previous=prior,stage=contact_sequence.stage,force_n=forces)
                    c.handover_verified=handover
                done=completion(action,obs,c.p,initial_bottom=initial,on_table=c._on_table(obs),handover=handover,
                    loaded_goal=c.loaded_goal_reached(obs) if action=='push_loaded' else None,
                    withdrawn=grippers_clear_of_tray(c,obs) if action=='place_empty' else False)
                stationary=previous is not None and np.linalg.norm(obs['tray_position']-previous)<.0005
                previous=obs['tray_position'].copy();stable=stable+1 if done and stationary else 0
                if stable>=c.p.stable_support_frames:
                    c.holding_sides={'left','right'} if action=='pick_empty' else set()
                    span=dict(action_label=action,start_frame=start,end_frame_exclusive=c.frames,verified=True,payload_loaded=c.loaded)
                    c.actions.append(span);c.event('learned_action_complete',**{k:v for k,v in span.items() if k!='action_label'});return
        raise PolicyError('single_tray_learned_action_budget_exhausted:'+action)

    def run(self):
        self.execute('pick_empty');self.execute('place_empty')
        # This explicit external passenger hook cannot move robot/tray/clock.
        self.c.passenger_load()
        self.execute('push_loaded')
        return dict(task_completed=True,physics_success=True,inverse_solver_calls=0,teacher_fallback_calls=0,
                    checkpoint_id=self.policy.contract.checkpoint_id,action_spans=self.c.actions,
                    environment_phase_excluded=True,allowed_long_rim_contract=long_rim_contract(),source='simulation/program_generated')
