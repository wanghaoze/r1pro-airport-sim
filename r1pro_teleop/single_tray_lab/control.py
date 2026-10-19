"""Independent single-tray simulation teacher with a contact-verified handover.

Robot execution changes actuator targets only. IK uses private MjData. Payload
initialization is an explicitly excluded passenger/environment phase; its hook
may not change the live robot, tray or simulation clock.
"""
from dataclasses import dataclass,fields
import math
import numpy as np
from itertools import product
from scipy.optimize import least_squares
from scipy.spatial.transform import Rotation
from r1pro_teleop.airport_fsm.contracts import Fault


ACTION_LABELS=('pick_empty','place_empty','push_loaded')
ACTION_PROMPTS={'pick_empty':'Pick up the tray','place_empty':'Place the tray','push_loaded':'Flush tray to the left'}


@dataclass(frozen=True)
class ControlProfile:
    tray_body: str='tray'
    table_bodies: tuple=('table',)
    payload_bodies: tuple=()
    payload_flexes: tuple=()
    tray_dimensions: tuple=(.56,.43,.105)
    table_center_xy: tuple=(.85,0.)
    table_half_sizes_xy: tuple=(.30,.60)
    tabletop_z: float=.8
    empty_place_position: tuple=(.85,-.24,.801)
    loaded_goal_position: tuple=(.85,.295,.801)
    front_normal: tuple=(-1.,0.,0.)
    robot_left: tuple=(0.,1.,0.)
    grasp_half_separation: float=.14
    grasp_mode: str='front_wall'
    rim_height: float=.082
    rim_inset: float=.01
    lift_distance: float=.12
    minimum_lift_clearance: float=.04
    lift_stop_margin_m: float=.005
    approach_clearance: float=.09
    open_command: float=.1
    close_command: float=0.
    contact_n: float=.5
    stable_contact_frames: int=3
    stable_support_frames: int=10
    push_step_m: float=.012
    push_command_reference: bool=False
    push_lead_frame: str='tray_anchor'
    push_right_outward_release: bool=False
    push_table_inboard_margin_m: float=.010
    push_forward_reference_step_m: float=.002
    push_forward_reference_lead_m: float=.020
    push_reference_lead_m: float=.04
    push_vertical_relief_m: float=0.
    push_table_contact_grace_frames: int=0
    push_table_contact_grace_gap_m: float=.001
    right_reach_lateral_m: float=-.08
    handover_left_tangent_m: float=-.06
    position_tolerance_m: float=.03
    tracking_tolerance_m: float=.006
    held_tracking_tolerance_m: float=.012
    place_release_clearance_m: float=.015
    place_inboard_slow_recipe: bool=False
    follow_tray_pose: bool=False
    held_private_ik_position_tolerance_m: float=.012
    held_private_ik_angle_tolerance_rad: float=.10
    max_penetration_m: float=.003
    soft_payload_penetration_m: float=.005
    planning_gripper_preload_max_m: float=.01
    base_drift_m: float=.005
    max_stage_steps: int=600
    fps: int=20

    @classmethod
    def from_scene(cls,scene):
        table=scene['table'];tray=scene['tray'];frame=scene['frame']
        if frame['base_mode']!='fixed_front' or frame.get('side_access_allowed'):
            raise ValueError('This controller only implements fixed-front base access')
        yaw=table['yaw'];size=np.asarray(table['size'][:2])/2
        axes=np.abs(np.array([[np.cos(yaw),-np.sin(yaw)],[np.sin(yaw),np.cos(yaw)]]))
        derived=cls(tray_body=tray['body'],table_bodies=(table['body'],),
            payload_bodies=tuple(p['name'] for p in scene['payloads'] if not p['flex']),
            payload_flexes=tuple(p['name'] for p in scene['payloads'] if p['flex']),
            tray_dimensions=tuple(tray['size']),table_center_xy=tuple(table['position'][:2]),
            table_half_sizes_xy=tuple(axes@size),tabletop_z=table['top_z'],
            empty_place_position=tuple(tray['position']),loaded_goal_position=tuple(tray['goal_position']),
            front_normal=tuple(-np.asarray(frame['robot_forward'])),robot_left=tuple(frame['robot_left']),
            rim_height=tray['rim_grasp_z'],lift_distance=scene['config']['lift_clearance']).validate()
        declaration=scene.get('control_profile')
        if declaration is None:return derived
        if not isinstance(declaration,dict) or set(declaration)!={f.name for f in fields(cls)}:
            raise ValueError('Scene requires complete known control_profile declaration')
        declared=cls(**declaration).validate()
        names=('tray_body','table_bodies','payload_bodies','payload_flexes')
        numeric=('tray_dimensions','table_center_xy','table_half_sizes_xy','tabletop_z',
            'empty_place_position','loaded_goal_position','front_normal','robot_left')
        for key in names:
            expected=getattr(derived,key);actual=getattr(declared,key)
            if (actual!=expected if isinstance(expected,str) else tuple(actual)!=expected):
                raise ValueError('Declared control_profile scene identity mismatch: '+key)
        for key in numeric:
            if not np.array_equal(np.asarray(getattr(declared,key),float),np.asarray(getattr(derived,key),float)):
                raise ValueError('Declared control_profile scene geometry mismatch: '+key)
        return declared

    def validate(self):
        if self.grasp_mode not in ('front_wall','wall_mid_taper'):raise ValueError('Unknown single-tray grasp mode')
        if type(self.follow_tray_pose) is not bool:raise ValueError('follow_tray_pose requires bool')
        if type(self.push_command_reference) is not bool:raise ValueError('push_command_reference requires bool')
        if self.push_lead_frame not in ('tray_anchor','measured_tcp'):raise ValueError('Unknown push lead frame')
        if self.push_lead_frame=='measured_tcp' and not self.push_command_reference:raise ValueError('Measured TCP lead requires explicit command reference')
        if type(self.push_right_outward_release) is not bool:raise ValueError('push_right_outward_release requires bool')
        if not all(np.isfinite(v) for v in (self.push_table_inboard_margin_m,self.push_forward_reference_step_m,self.push_forward_reference_lead_m)):
            raise ValueError('Finite push table reference limits required')
        if not 0<=self.push_table_inboard_margin_m<=.02 or not 0<self.push_forward_reference_step_m<=.002 or not 0<self.push_forward_reference_lead_m<=.02:
            raise ValueError('Invalid bounded push forward reference limits')
        if type(self.place_inboard_slow_recipe) is not bool:raise ValueError('place_inboard_slow_recipe requires bool')
        numeric=[self.tabletop_z,self.grasp_half_separation,self.rim_height,self.rim_inset,
            self.lift_distance,self.minimum_lift_clearance,self.lift_stop_margin_m,self.approach_clearance,self.open_command,
            self.close_command,self.contact_n,self.push_step_m,self.push_reference_lead_m,self.push_vertical_relief_m,self.push_table_contact_grace_gap_m,self.right_reach_lateral_m,self.handover_left_tangent_m,
            self.position_tolerance_m,self.tracking_tolerance_m,self.held_tracking_tolerance_m,self.place_release_clearance_m,self.max_penetration_m,self.soft_payload_penetration_m,self.planning_gripper_preload_max_m,self.held_private_ik_position_tolerance_m,self.held_private_ik_angle_tolerance_rad,self.base_drift_m]
        for value in (self.tray_dimensions,self.table_center_xy,self.table_half_sizes_xy,
                      self.empty_place_position,self.loaded_goal_position,self.front_normal,self.robot_left):
            numeric.extend(value)
        if not np.isfinite(numeric).all():raise ValueError('Nonfinite single-tray profile')
        if self.fps!=20 or self.open_command<=self.close_command or self.close_command<0:
            raise ValueError('Single-tray profile requires 20 Hz and ordered nonnegative jaw commands')
        if any(type(x) is not int or x<=0 for x in (self.stable_contact_frames,self.stable_support_frames,self.max_stage_steps)):
            raise ValueError('Positive integer frame budgets required')
        if min(self.tray_dimensions)<=0 or min(self.table_half_sizes_xy)<=0 or min(self.contact_n,self.push_step_m,self.max_penetration_m)<=0:
            raise ValueError('Positive physical dimensions and thresholds required')
        if self.tracking_tolerance_m<=0 or self.held_tracking_tolerance_m<=0:raise ValueError('Positive tracking tolerances required')
        if not 0<=self.place_release_clearance_m<=.02:raise ValueError('Release clearance must be within 2 cm')
        if not 0<=self.lift_stop_margin_m<=.02:raise ValueError('Lift endpoint margin must be within 2 cm')
        if not 0<self.soft_payload_penetration_m<=.01:raise ValueError('Soft payload compression threshold must be positive and at most 1 cm')
        if not 0<self.max_penetration_m<=.01:raise ValueError('Hard penetration threshold must be positive and at most 1 cm')
        if not self.max_penetration_m<=self.planning_gripper_preload_max_m<=.02:raise ValueError('Private gripper preload envelope must be between hard threshold and 2 cm')
        if not 0<self.held_private_ik_position_tolerance_m<=.02 or not 0<self.held_private_ik_angle_tolerance_rad<=.2:raise ValueError('Invalid held private IK residual tolerances')
        if not 0<self.push_reference_lead_m<=.1:raise ValueError('Push reference lead must be positive and at most 10 cm')
        if not 0<=self.push_vertical_relief_m<=.01:raise ValueError('Push vertical reference relief must be within 1 cm')
        if type(self.push_table_contact_grace_frames) is not int or not 0<=self.push_table_contact_grace_frames<=6:
            raise ValueError('Push table contact grace requires integer 0 to 6 frames')
        if not 0<self.push_table_contact_grace_gap_m<=.001:raise ValueError('Push contact grace gap must be positive and at most 1 mm')
        front=np.asarray(self.front_normal,float);left=np.asarray(self.robot_left,float)
        if abs(np.linalg.norm(front)-1)>1e-8 or abs(np.linalg.norm(left)-1)>1e-8 or abs(front@left)>1e-8 or abs(front[2])+abs(left[2])>1e-8:
            raise ValueError('Horizontal orthonormal front/left frame required')
        return self


def long_front_goals(position,rotation,profile,*,left_tangent=None):
    """Both hands on one long front rim; jaw Y closes across its wall."""
    profile.validate();size=np.asarray(profile.tray_dimensions);R=np.asarray(rotation)
    long=int(np.argmax(size[:2]));short=1-long
    normal=np.asarray(profile.front_normal);local=R.T@normal
    if abs(local[short])<.95:raise Fault('tray_long_rim_not_facing_robot')
    if profile.grasp_half_separation>=size[long]/2-.02:raise ValueError('Grasp points extend beyond long rim')
    tangent_sign=1 if R[:,long]@profile.robot_left>0 else -1
    up=np.array([0.,0.,1.])
    goals={}
    for side,sign in (('left',1),('right',-1)):
        jaw=normal if side=='right' else -normal
        tool=np.column_stack((np.cross(jaw,up),jaw,up))
        offset=np.zeros(3);offset[short]=np.sign(local[short])*(size[short]/2-profile.rim_inset)
        if profile.grasp_mode=='wall_mid_taper':
            if not np.array_equal(size,np.array([.56,.43,.105])) or long!=0:
                raise ValueError('Wall taper profile requires the original measured tray')
            # Original tray_contact_004 OBJ wall planes, in metres:
            # outer y=.19753 at z=.008 -> .215 at z=.105;
            # inner y=.18753 at z=.012 -> .205 at z=.105.
            slope=.01747/.097;angle=math.atan(slope);pad_z=profile.rim_height+.00811*math.cos(angle)
            outer=.19753+(pad_z-.008)*slope;inner=.18753+(pad_z-.012)*(.01747/.093)
            front_sign=np.sign(local[short])
            offset[short]=front_sign*((outer+inner)/2-.00811*math.sin(angle))
            wall_normal=np.zeros(3);wall_normal[short]=front_sign*math.cos(angle);wall_normal[2]=-math.sin(angle)
            wall_up=np.zeros(3);wall_up[short]=front_sign*math.sin(angle);wall_up[2]=math.cos(angle)
            wall_normal=R@wall_normal;wall_up=R@wall_up
            jaw=wall_normal if side=='right' else -wall_normal
            tool=np.column_stack((np.cross(jaw,wall_up),jaw,wall_up))
        tangent=(profile.grasp_half_separation if side=='left' else -profile.grasp_half_separation)
        if side=='left' and left_tangent is not None:
            if not np.isfinite(left_tangent) or abs(left_tangent)>=size[long]/2-.02:raise ValueError('Handover point outside front long rim')
            tangent=left_tangent
        offset[long]=tangent*tangent_sign;offset[2]=profile.rim_height
        goals[side]=(np.asarray(position)+R@offset,tool.copy())
    return goals


class SingleTrayController:
    @classmethod
    def from_scene(cls,scene,**kwargs):
        from .scene import passenger_load
        return cls(scene['xml'],ControlProfile.from_scene(scene),
            passenger_loader=lambda simulation:passenger_load(simulation,scene),**kwargs)

    def __init__(self,xml,profile,*,passenger_loader=None,on_frame=None,on_event=None):
        import mujoco
        from r1pro_teleop.airport_recording import AirportSimulation
        self.p=profile.validate();self.sim=AirportSimulation(xml,fps=profile.fps,render=False)
        self.m,self.d,self.mj=self.sim.model,self.sim.data,mujoco
        self.passenger_loader=passenger_loader;self.on_frame=on_frame;self.on_event=on_event
        self.frames=0;self.phase='initial_settle';self.action='environment';self.loaded=False
        self.events=[];self.actions=[];self.holding_sides=set();self.handover_verified=False
        self.observed_hard_penetration_peak_m=0.
        self.observed_soft_payload_penetration_peak_m=0.
        self.guarded_substeps=0
        self.strict_continuous_push_table_contact_gate=True
        self.push_table_contact_grace_episodes=0;self.push_table_contact_grace_recoveries=0
        self.push_table_contact_max_absent_duration_s=0.;self.push_table_contact_max_gap_m=0.
        self._push_table_missing_since=None;self._push_table_missing_frame=None
        self._push_table_missing_logged=False;self._push_table_last_log_frame=None
        self.robot=self._descendants(self.m.body('base_link').id)
        self.tray=self._descendants(self.m.body(self.p.tray_body).id)
        self.tables=set().union(*(self._descendants(self.m.body(name).id) for name in self.p.table_bodies))
        self.payload=set().union(*(self._descendants(self.m.body(name).id) for name in self.p.payload_bodies)) if self.p.payload_bodies else set()
        self.flexes={int(mujoco.mj_name2id(self.m,mujoco.mjtObj.mjOBJ_FLEX,name)) for name in self.p.payload_flexes}
        if -1 in self.flexes:raise ValueError('Declared payload flex missing from scene')
        self.base_origin=self.sim.base_state().astype(float)
        self.integration_spec=mujoco.mjtState.mjSTATE_INTEGRATION
        self.integration_size=mujoco.mj_stateSize(self.m,self.integration_spec)
        self._protected_qpos=self._body_qpos(self.robot|self.tray)
        self._protected_dofs=self._body_dofs(self.robot|self.tray)

    def _descendants(self,root):
        result=set()
        for body in range(1,self.m.nbody):
            node=body
            while node and node!=root:node=int(self.m.body_parentid[node])
            if node==root:result.add(body)
        return result

    def _body_qpos(self,bodies):
        indices=[]
        for joint,body in enumerate(self.m.jnt_bodyid):
            if int(body) in bodies:
                width=7 if self.m.jnt_type[joint]==0 else 4 if self.m.jnt_type[joint]==1 else 1
                indices.extend(range(int(self.m.jnt_qposadr[joint]),int(self.m.jnt_qposadr[joint])+width))
        return np.array(indices,int)

    def _body_dofs(self,bodies):
        return np.flatnonzero(np.isin(self.m.dof_bodyid,list(bodies)))

    def event(self,name,**details):
        row=dict(event=name,frame=self.frames,phase=self.phase,action_label=self.action,
            payload_loaded=self.loaded,source='simulation/program_generated',**details)
        self.events.append(row)
        if self.on_event:self.on_event(row)

    def _entity(self,contact,index):
        geom=int(contact.geom[index])
        if geom>=0:return int(self.m.geom_bodyid[geom]),self.m.geom(geom).name
        flex=int(contact.flex[index])
        if flex in self.flexes:return 'payload_flex','flex:'+self.mj.mj_id2name(self.m,self.mj.mjtObj.mjOBJ_FLEX,flex)
        return 'unknown_flex','unregistered_flex:'+str(flex)

    def _contacts(self,data=None):
        d=self.d if data is None else data
        forces={'left':0.,'right':0.};table=0;payload_support=0;payload_floor=0;bad=[];penetration=0.
        supported=set();links={};parked_penetration=0.;hard_penetration=0.;soft_penetration=0.;non_preload_hard=0.;held_preload=0.
        robot_payload_contacts=[]
        for index,contact in enumerate(d.contact):
            a,an=self._entity(contact,0);b,bn=self._entity(contact,1)
            if not np.isfinite(contact.dist):raise Fault('single_tray_nonfinite_contact')
            normal=np.zeros(6)
            self.mj.mj_contactForce(self.m,d,index,normal);force=abs(float(normal[0]))
            is_payload=lambda body:body=='payload_flex' or body in self.payload
            if (a in self.robot and is_payload(b)) or (b in self.robot and is_payload(a)):
                # Passenger objects may touch the robot. This is still a real
                # hard-domain collision measurement, never grasp/support proof
                # and never exempt from the existing penetration ceiling.
                robot_payload_contacts.append(dict(entities=[an,bn],distance_m=float(contact.dist),
                    penetration_m=max(0.,-float(contact.dist)),normal_force_n=force))
            parked_environment=(not self.loaded and (is_payload(a) or is_payload(b)) and
                a not in self.robot|self.tray|self.tables and b not in self.robot|self.tray|self.tables)
            if parked_environment:parked_penetration=max(parked_penetration,-float(contact.dist))
            else:
                depth=max(0.,-float(contact.dist));penetration=max(penetration,depth)
                if self._is_soft_payload_pair(a,b):soft_penetration=max(soft_penetration,depth)
                else:
                    hard_penetration=max(hard_penetration,depth)
                    if self._is_held_finger_pair(a,b):held_preload=max(held_preload,depth)
                    else:non_preload_hard=max(non_preload_hard,depth)
            if self.loaded and ((is_payload(a) and b==0) or (is_payload(b) and a==0)):payload_floor+=1
            if (a in self.tray and b in self.tables) or (b in self.tray and a in self.tables):table+=1
            if (is_payload(a) and b in self.tray|self.tables) or (is_payload(b) and a in self.tray|self.tables):payload_support+=1
            if force>.01:
                if is_payload(a) and b in self.tray:supported.add(a)
                if is_payload(b) and a in self.tray:supported.add(b)
                if is_payload(a) and is_payload(b):
                    links.setdefault(a,set()).add(b);links.setdefault(b,set()).add(a)
            for body,other in ((a,b),(b,a)):
                if body in self.robot and other in self.tray:
                    name=self.m.body(body).name
                    for side in ('left','right'):
                        if name.startswith(side+'_gripper_finger'):forces[side]+=force
            if contact.dist>=-.0002:continue
            permitted=False
            if a in self.tray and b in self.tables or b in self.tray and a in self.tables:permitted=True
            elif is_payload(a) or is_payload(b):
                other=b if is_payload(a) else a
                permitted=(other in self.tray|self.tables|self.robot or is_payload(other) or not self.loaded and other==0)
            elif a in self.robot or b in self.robot:
                robot=a if a in self.robot else b;other=b if a in self.robot else a
                name=self.m.body(robot).name
                permitted=(other in self.tray and '_gripper_finger' in name) or (other==0 and name.startswith(('wheel_','steer_','base_link')))
            else:permitted=not (a in self.tray or b in self.tray) and a!='unknown_flex' and b!='unknown_flex'
            if not permitted:bad.append(dict(entities=[an,bn],distance_m=float(contact.dist)))
        for _ in range(len(self.payload)+len(self.flexes)+1):
            expanded=supported|set().union(*(links.get(body,set()) for body in supported)) if supported else set()
            if expanded==supported:break
            supported=expanded
        return dict(gripper_contact_force=forces,table_contacts=table,payload_support_contacts=payload_support,
                    supported_payload_entities=supported,
                    payload_floor_contacts=payload_floor,illegal_contacts=bad,max_penetration=penetration,
                    robot_payload_contacts=robot_payload_contacts,
                    hard_max_penetration=hard_penetration,soft_payload_max_penetration=soft_penetration,
                    non_preload_hard_max_penetration=non_preload_hard,held_finger_tray_max_penetration=held_preload,
                    parked_environment_max_penetration=parked_penetration)

    def _is_soft_payload_pair(self,a,b):
        # Only _entity's registered flex token can enter the soft domain;
        # robot, unknown flex, floor and arbitrary room contacts remain hard.
        allowed=lambda other:other in self.payload|self.tray|self.tables or other=='payload_flex'
        return (a=='payload_flex' and allowed(b)) or (b=='payload_flex' and allowed(a))

    def robot_payload_contact_statistics(self):
        """Bounded actual-guard diagnostics; private planners never update these."""
        if not hasattr(self,'_robot_payload_contact_stats'):
            self._robot_payload_contact_stats=dict(schema='airport_actual_robot_payload_contacts/1',
                scope='actual_live_guard_substeps_only_private_predictions_excluded',guard_checks=0,
                guard_checks_with_contacts=0,contact_point_observations=0,penetration_peak_m=0.,normal_force_peak_n=0.,
                pair_observation_limit=64,event_limit=32,events_written=0,event_limit_reached=False,
                overflow_pair_observations=0,pairs={},first_contact=None,last_contact=None)
        import copy
        return copy.deepcopy(self._robot_payload_contact_stats)

    def _record_actual_robot_payload_contacts(self,obs):
        if not hasattr(self,'_robot_payload_contact_stats'):self.robot_payload_contact_statistics()
        stats=self._robot_payload_contact_stats;stats['guard_checks']+=1
        contacts=obs.get('robot_payload_contacts',[])
        if not contacts:return
        stats['guard_checks_with_contacts']+=1;stats['contact_point_observations']+=len(contacts)
        stamp=dict(frame=int(self.frames),sim_time=float(self.d.time),phase=self.phase,action=self.action)
        for contact in contacts:
            depth=float(contact['penetration_m']);force=float(contact['normal_force_n'])
            stats['penetration_peak_m']=max(stats['penetration_peak_m'],depth)
            stats['normal_force_peak_n']=max(stats['normal_force_peak_n'],force)
            record=dict(stamp,**contact)
            if stats['first_contact'] is None:stats['first_contact']=record
            stats['last_contact']=record
            key=' | '.join(sorted(contact['entities']))
            if key not in stats['pairs'] and len(stats['pairs'])>=stats['pair_observation_limit']:
                stats['overflow_pair_observations']+=1;continue
            pair=stats['pairs'].setdefault(key,dict(entities=contact['entities'],contact_point_observations=0,
                penetration_peak_m=0.,normal_force_peak_n=0.,first_sim_time=stamp['sim_time'],last_sim_time=stamp['sim_time']))
            pair['contact_point_observations']+=1;pair['penetration_peak_m']=max(pair['penetration_peak_m'],depth)
            pair['normal_force_peak_n']=max(pair['normal_force_peak_n'],force);pair['last_sim_time']=stamp['sim_time']
        phase=(self.action,self.phase)
        due=(stats['events_written']==0 or phase!=getattr(self,'_robot_payload_last_logged_phase',None)
            or stamp['sim_time']-getattr(self,'_robot_payload_last_logged_time',0.)>=1.)
        if due and stats['events_written']<stats['event_limit']:
            self.event('actual_robot_payload_contact_observed',scope=stats['scope'],
                observed_contacts=sorted(contacts,key=lambda c:c['penetration_m'],reverse=True)[:4],
                actual_contact_points=len(contacts),cumulative_contact_point_observations=stats['contact_point_observations'],
                penetration_peak_m=stats['penetration_peak_m'],normal_force_peak_n=stats['normal_force_peak_n'],
                hard_penetration_limit_m=self.p.max_penetration_m,contact_permission_not_grasp_or_support=True)
            stats['events_written']+=1;self._robot_payload_last_logged_phase=phase;self._robot_payload_last_logged_time=stamp['sim_time']
        elif due:stats['event_limit_reached']=True

    def _is_held_finger_pair(self,a,b):
        if a in self.tray and b in self.robot:robot=b
        elif b in self.tray and a in self.robot:robot=a
        else:return False
        name=self.m.body(robot).name
        return any(name.startswith(side+'_gripper_finger') for side in self.holding_sides)

    def _penetration_exceeds(self,contacts,*,planning_preload=False):
        hard=contacts.get('hard_max_penetration',contacts['max_penetration'])
        if planning_preload:
            hard=contacts.get('non_preload_hard_max_penetration',hard)
            if contacts.get('held_finger_tray_max_penetration',0.)>self.p.planning_gripper_preload_max_m:return True
        return (hard>self.p.max_penetration_m or
            contacts.get('soft_payload_max_penetration',0.)>self.p.soft_payload_penetration_m)

    def observation(self):
        body=self.d.body(self.p.tray_body);R=body.xmat.reshape(3,3).copy();position=body.xpos.copy()
        size=np.asarray(self.p.tray_dimensions);corners=np.array([[x,y,z] for x in (-size[0]/2,size[0]/2) for y in (-size[1]/2,size[1]/2) for z in (0,size[2])])@R.T+position
        contacts=self._contacts()
        mass=float(np.sum(self.m.body_mass[list(self.payload)]));on_tray=float(np.sum(self.m.body_mass[
            [body for body in self.payload if body in contacts['supported_payload_entities']]]))
        for flex in self.flexes:
            start=int(self.m.flex_vertadr[flex]);count=int(self.m.flex_vertnum[flex])
            bodies=set(int(x) for x in self.m.flex_vertbodyid[start:start+count])-self.payload
            flex_mass=float(np.sum(self.m.body_mass[list(bodies)]));mass+=flex_mass
            if 'payload_flex' in contacts['supported_payload_entities']:on_tray+=flex_mass
        contacts.pop('supported_payload_entities')
        return dict(tray_position=position,tray_rotation=R,tray_bottom_z=float(corners[:,2].min()),
            tray_corners=corners,gripper_openings=self.sim.state()[[7,15]].copy(),
            payload_mass_kg=on_tray,payload_total_mass_kg=mass,payload_loaded=self.loaded and on_tray>0,
            base=self.sim.base_state().copy(),**contacts)

    def guard(self):
        if not np.isfinite(np.r_[self.d.qpos,self.d.qvel,self.d.ctrl]).all():raise Fault('single_tray_nonfinite_physics')
        obs=self.observation()
        self.guarded_substeps+=1
        self._record_actual_robot_payload_contacts(obs)
        self.observed_hard_penetration_peak_m=max(self.observed_hard_penetration_peak_m,float(obs['hard_max_penetration']))
        self.observed_soft_payload_penetration_peak_m=max(self.observed_soft_payload_penetration_peak_m,float(obs['soft_payload_max_penetration']))
        support_fault=self._observe_push_table_support(obs)
        if np.linalg.norm(obs['base'][:2]-self.base_origin[:2])>self.p.base_drift_m or abs(obs['base'][2]-self.base_origin[2])>.01:
            raise Fault('single_tray_fixed_base_drift',obs['base'].tolist())
        if obs['illegal_contacts']:raise Fault('single_tray_illegal_collision',obs['illegal_contacts'])
        if obs['payload_floor_contacts']:raise Fault('single_tray_payload_on_floor')
        if self.action=='push_loaded' and obs['payload_mass_kg']<=0:raise Fault('single_tray_push_payload_support_lost')
        if self._penetration_exceeds(obs):raise Fault('single_tray_excess_penetration',dict(
            global_max_penetration_m=obs['max_penetration'],hard_max_penetration_m=obs['hard_max_penetration'],
            soft_payload_max_penetration_m=obs['soft_payload_max_penetration'],
            hard_limit_m=self.p.max_penetration_m,soft_payload_limit_m=self.p.soft_payload_penetration_m))
        if obs['tray_bottom_z']<self.p.tabletop_z-.03:raise Fault('single_tray_tray_below_table',obs['tray_bottom_z'])
        if support_fault is not None:raise support_fault
        return obs

    def tick(self):
        before=np.empty(self.integration_size);self.mj.mj_getState(self.m,self.d,before,self.integration_spec)
        before_measurement=self.observation();self.sim.target=self.sim.target.astype(np.float32)
        base_offsets=(self.sim.base_state()-self.base_origin).astype(np.float32)
        row=dict(integration_state=before,qpos=self.d.qpos.copy(),qvel=self.d.qvel.copy(),
            sim_time=float(self.d.time),state=self.sim.state().copy(),state19=np.r_[self.sim.state(),base_offsets],
            action=self.sim.target.copy(),action19=np.r_[self.sim.target,np.zeros(3,dtype=np.float32)],
            base_action=np.zeros(3,dtype=np.float32),base_state=self.sim.base_state().copy(),
            measurement_before=before_measurement,phase=self.phase,action_label=self.action,
            payload_loaded=self.loaded,training_segment=self.action in ACTION_LABELS)
        journal=np.zeros((self.sim.nstep,self.m.nu));executed=0;error=None
        self.sim.apply_target()
        try:
            for substep in range(self.sim.nstep):
                journal[substep]=self.d.ctrl;self.mj.mj_step(self.m,self.d);executed+=1;self.guard()
        except Exception as exc:error=exc
        measured=self.observation()
        row.update(ctrl_substeps=journal,executed_substeps=executed,transition_completed=error is None,
                   measured=measured,payload_loaded=measured['payload_loaded'],payload_mass_kg=measured['payload_mass_kg'],
                   payload_total_mass_kg=measured['payload_total_mass_kg'],holding_sides=tuple(sorted(self.holding_sides)))
        if self.on_frame:self.on_frame(row)
        self.frames+=1
        if error:
            self.event('control_failed',reason=getattr(error,'code',type(error).__name__),detail=str(error));raise error
        return row['measured']

    def hold(self,frames,predicate=None):
        for _ in range(frames):
            obs=self.tick()
            if predicate is not None and not predicate(obs):raise Fault('single_tray_contact_lost',obs['gripper_contact_force'])
        return self.observation()

    def _opening(self,sides,value):
        for side in sides:
            column=7 if side=='left' else 15
            self.sim.target[column]+=np.clip(value-self.sim.target[column],-.002,.002)

    def _ik_candidates(self,side,position,rotation,*,warm_only=False):
        """Deterministic multistart IK in independent data, with exact pose checks."""
        offset=0 if side=='left' else 8;ids=self.sim.arms[side]
        qids=np.array([self.m.jnt_qposadr[j] for j in ids]);limits=self.m.jnt_range[ids]
        lower,upper=limits[:,0]+.01,limits[:,1]-.01
        original=self.sim.target[offset:offset+7].astype(float).copy()
        shadow=self.mj.MjData(self.m);shadow.qpos[:]=self.d.qpos
        site=self.m.site(side+'_tcp').id;position=np.asarray(position);rotation=np.asarray(rotation)
        def residual(q):
            shadow.qpos[qids]=q;self.mj.mj_kinematics(self.m,shadow)
            return np.r_[shadow.site_xpos[site]-position,
                .2*Rotation.from_matrix(rotation@shadow.site_xmat[site].reshape(3,3).T).as_rotvec(),
                .0002*(q-original)]
        rng=np.random.default_rng(20261006+(0 if side=='left' else 1))
        seeds=[original]
        for abduction in (.35,.65,1.):
            seed=original.copy();seed[1]=abduction if side=='left' else -abduction
            seed[2]=-.9 if side=='left' else .9;seed[5]=.65;seed[6]=-1.4 if side=='left' else 1.4
            seeds.append(seed)
        seeds.extend(rng.uniform(lower,upper) for _ in range(12))
        solutions=[]
        held_feedback=getattr(self,'private_incremental_command_prediction',False) and side in self.holding_sides
        position_tolerance=self.p.held_private_ik_position_tolerance_m if held_feedback else .002
        angle_tolerance=self.p.held_private_ik_angle_tolerance_rad if held_feedback else .02
        for seed in seeds[:1] if warm_only else seeds:
            fit=least_squares(residual,np.clip(seed,lower,upper),bounds=(lower,upper),max_nfev=180)
            errors=residual(fit.x);pos=float(np.linalg.norm(errors[:3]));angle=float(np.linalg.norm(errors[3:6])/.2)
            if pos<position_tolerance and angle<angle_tolerance and not any(np.linalg.norm(fit.x-old[1])<.04 for old in solutions):
                solutions.append((float(np.linalg.norm(fit.x-original)),fit.x.copy(),pos,angle))
        solutions.sort(key=lambda item:item[0])
        if not solutions and not warm_only:raise Fault('single_tray_private_ik_unreachable',dict(side=side,position=position.tolist()))
        return solutions[:8]

    def _joint_path_clear(self,start,end,*,samples=51):
        shadow=self.mj.MjData(self.m);shadow.qpos[:]=self.d.qpos
        original=self.d.qpos.copy();predicted=getattr(self,'private_held_translation',None)
        for u in np.linspace(0,1,samples):
            shadow.qpos[:]=original
            q=start+(end-start)*u
            if getattr(self,'private_incremental_command_prediction',False):
                # A loaded servo's measured pose differs from its legal
                # reference through contact compliance. Predict the *new*
                # reference increment from that measured pose, rather than
                # replaying its existing preload as an instantaneous reset.
                q=start+(end-self.sim.target.astype(float))*u
            for side,offset in (('left',0),('right',8)):
                qids=[self.m.jnt_qposadr[j] for j in self.sim.arms[side]]
                shadow.qpos[qids]=q[offset:offset+7]
            if predicted is not None:
                # Only the independent planning data predicts contact-held
                # object translation. Live objects remain fully dynamic.
                moved=self.tray|(self.payload if self.loaded else set())
                for joint,body in enumerate(self.m.jnt_bodyid):
                    if int(body) in moved and self.m.jnt_type[joint]==0:
                        adr=int(self.m.jnt_qposadr[joint]);shadow.qpos[adr:adr+3]+=u*predicted
                if self.loaded:
                    for flex in self.flexes:
                        adr=int(self.m.flex_vertadr[flex]);count=int(self.m.flex_vertnum[flex])
                        for body in set(int(b) for b in self.m.flex_vertbodyid[adr:adr+count]):
                            for joint in range(self.m.body_jntadr[body],self.m.body_jntadr[body]+self.m.body_jntnum[body]):
                                if self.m.jnt_type[joint]==2:
                                    shadow.qpos[int(self.m.jnt_qposadr[joint])]+=float(self.m.jnt_axis[joint]@(u*predicted))
            self.mj.mj_forward(self.m,shadow);contacts=self._contacts(shadow)
            if contacts['illegal_contacts'] or self._penetration_exceeds(contacts,
                    planning_preload=getattr(self,'private_allow_held_preload',False)):
                self.last_private_path_rejection=dict(fraction=float(u),
                    illegal_contacts=contacts['illegal_contacts'],max_penetration=contacts['max_penetration'],
                    hard_max_penetration=contacts['hard_max_penetration'],
                    soft_payload_max_penetration=contacts['soft_payload_max_penetration'],
                    robot_payload_contacts=contacts.get('robot_payload_contacts',[]),
                    robot_payload_contact_scope='private_predicted_path_not_actual_guard')
                return False
        return True

    def plan_joint_goal(self,goals,*,reference_step_rad=None):
        if reference_step_rad is not None and (not np.isfinite(reference_step_rad) or reference_step_rad<=0):raise ValueError('Positive reference joint step required')
        start=self.sim.state().astype(float).copy();start[[7,15]]=self.sim.target[[7,15]];sides=list(goals)
        for robust in (False,True):
            choices=[self._ik_candidates(side,*goals[side],warm_only=not robust) for side in sides]
            combinations=sorted(product(*choices),key=lambda combo:sum(item[0] for item in combo))
            for combination in combinations:
                target=(self.sim.target.astype(float).copy() if getattr(self,'private_incremental_command_prediction',False) else start.copy())
                for side,item in zip(sides,combination):
                    offset=0 if side=='left' else 8
                    target[offset:offset+7]=(item[1] if reference_step_rad is None else
                        self.sim.target[offset:offset+7]+np.clip(item[1]-self.sim.target[offset:offset+7],-reference_step_rad,reference_step_rad))
                if self._joint_path_clear(start,target):
                    self.event('private_multistart_joint_path_verified',sides=sides,warm_start_only=not robust,
                        max_position_error_m=max(item[2] for item in combination),
                        max_angle_error_rad=max(item[3] for item in combination),path_samples=51,
                        reference_step_rad=reference_step_rad,pose_error_scope='IK endpoint before explicit reference step limit',
                        strict_2mm_ik_passed=max(item[2] for item in combination)<.002,
                        strict_20mrad_ik_passed=max(item[3] for item in combination)<.02,
                        planning_preload_allowed=getattr(self,'private_allow_held_preload',False),
                        planning_preload_max_m=self.p.planning_gripper_preload_max_m,
                        actual_hard_penetration_max_m=self.p.max_penetration_m,
                        prediction_mode=('measured_plus_reference_increment' if getattr(self,'private_incremental_command_prediction',False)
                            else 'measured_to_absolute_reference'))
                    return target
        raise Fault('single_tray_private_joint_path_collision',dict(sides=sides,candidates=len(combinations),
            last_rejection=getattr(self,'last_private_path_rejection',None)))

    def move(self,goals,*,openings=None,predicate=None,minimum_seconds=.5,tracking_tolerance=None,finish_predicate=None,allow_one_hand_recovery=False,finish_on_reference_submitted=False):
        if allow_one_hand_recovery and self.action!='place_empty':raise ValueError('One-hand recovery is restricted to empty place')
        if finish_on_reference_submitted and (self.action!='push_loaded' or not self.p.push_command_reference):
            raise ValueError('Reference-lead completion is restricted to explicit loaded push')
        active_sides=set(goals)
        tolerance=self.p.tracking_tolerance_m if tracking_tolerance is None else tracking_tolerance
        target=self.plan_joint_goal(goals);start=self.sim.target.astype(float).copy()
        duration=max(minimum_seconds,1.875*float(np.max(np.abs(target-start)))/.45)
        motion_frames=math.ceil(duration*self.p.fps)
        if motion_frames>=self.p.max_stage_steps:raise Fault('single_tray_reference_budget_exhausted')
        for step in range(self.p.max_stage_steps):
            u=min(1.,(step+1)/motion_frames);smooth=u*u*u*(10-15*u+6*u*u)
            reference=start+(target-start)*smooth
            for side in active_sides:
                offset=0 if side=='left' else 8
                self.sim.target[offset:offset+7]=reference[offset:offset+7]
            for side,value in (openings or {}).items():self._opening((side,),value)
            obs=self.tick()
            if predicate is not None and not predicate(obs):
                surviving={s for s in active_sides if obs['gripper_contact_force'][s]>self.p.contact_n}
                if not allow_one_hand_recovery or not surviving:
                    raise Fault('single_tray_contact_lost',obs['gripper_contact_force'])
                lost=active_sides-surviving
                if lost:
                    frozen={s:self.sim.target[0 if s=='left' else 8:(0 if s=='left' else 8)+7].tolist() for s in lost}
                    self.event('empty_place_one_hand_recovery',lost_sides=sorted(lost),remaining_sides=sorted(surviving),
                        frozen_arm_references=frozen,force_n=obs['gripper_contact_force'],
                        lowest_corner_gap_m=float(obs['tray_bottom_z'])-self.p.tabletop_z,
                        qualification='Remaining measured grasp only; no object reset or release above configured height')
                    self.holding_sides.difference_update(lost);active_sides=surviving
            if finish_predicate is not None and finish_predicate(obs):
                self.event('measured_motion_endpoint_reached',reference_held=True,
                    qualification='Stopped at actual task endpoint; current actuator reference retained, no state reset')
                return obs
            errors=[np.linalg.norm(self.sim.tcp(side)[0]-goals[side][0]) for side in active_sides]
            angles=[np.linalg.norm(Rotation.from_matrix(goals[side][1]@self.sim.tcp(side)[1].T).as_rotvec()) for side in active_sides]
            jaw_ok=all(abs(self.sim.target[7 if side=='left' else 15]-value)<1e-6 for side,value in (openings or {}).items())
            if finish_on_reference_submitted and step+1>=motion_frames and jaw_ok:
                self.event('push_reference_ramp_submitted',actual_ticks=step+1,
                    position_errors_m=[float(x) for x in errors],angle_errors_rad=[float(x) for x in angles],
                    selected_tracking_tolerance_m=tolerance,strict_6mm_passed=bool(max(errors,default=0)<.006),
                    qualification='Reference interpolation executed; finite servo lead supplies contact force. Not object motion or action completion')
                return obs
            if step+1>=motion_frames and max(errors,default=0)<tolerance and max(angles,default=0)<.10 and jaw_ok:
                self.event('motion_tracking_evaluated',position_errors_m=[float(x) for x in errors],
                    angle_errors_rad=[float(x) for x in angles],selected_tolerance_m=tolerance,
                    strict_6mm_passed=max(errors,default=0)<.006,
                    qualification='Intermediate tracking tolerance only; original contact/collision/task completion gates unchanged')
                return obs
        raise Fault('single_tray_motion_budget_exhausted',dict(phase=self.phase,position_errors=errors,angle_errors=angles))

    def _grasp_goals(self):
        obs=self.observation();return long_front_goals(obs['tray_position'],obs['tray_rotation'],self.p)

    def acquire(self,sides,*,prefix=''):
        if self.loaded and tuple(sides)==('left',):
            obs=self.observation();all_goals=long_front_goals(obs['tray_position'],obs['tray_rotation'],self.p,
                left_tangent=self.p.handover_left_tangent_m)
        else:all_goals=self._grasp_goals()
        goals={side:goal for side,goal in all_goals.items() if side in sides}
        high={side:(position+np.array([0,0,self.p.approach_clearance]),R) for side,(position,R) in goals.items()}
        self.phase=prefix+'approach';self.move(high,openings={s:self.p.open_command for s in sides})
        self.phase=prefix+'contact';self.move(goals)
        self.phase=prefix+'close';stable=0
        for _ in range(self.p.max_stage_steps):
            self._opening(sides,self.p.close_command);obs=self.tick()
            stable=stable+1 if all(obs['gripper_contact_force'][s]>self.p.contact_n for s in sides) else 0
            if stable>=self.p.stable_contact_frames and all(abs(self.sim.target[7 if s=='left' else 15]-self.p.close_command)<1e-6 for s in sides):
                self.holding_sides.update(sides)
                if self.p.follow_tray_pose:self._capture_held_tools(sides,obs)
                self.event('grasp_contact_verified',sides=list(sides),force_n=obs['gripper_contact_force']);return obs
        raise Fault('single_tray_missing_grasp_contact',dict(sides=sides,force_n=obs['gripper_contact_force']))

    def _held_move(self,position,sides,*,finish_predicate=None,allow_one_hand_recovery=False):
        if self.p.follow_tray_pose:
            return self._held_pose_follow_move(position,sides,finish_predicate=finish_predicate,
                allow_one_hand_recovery=allow_one_hand_recovery)
        obs=self.observation();delta=np.asarray(position)-obs['tray_position']
        shadow=self.mj.MjData(self.m);shadow.qpos[:]=self.d.qpos
        for side,offset in (('left',0),('right',8)):
            cols=[self.m.jnt_qposadr[j] for j in self.sim.arms[side]]
            shadow.qpos[cols]=self.sim.target[offset:offset+7]
        self.mj.mj_kinematics(self.m,shadow)
        starts={side:self.sim.tcp(side)[0] for side in sides}
        rotations={side:shadow.site(side+'_tcp').xmat.reshape(3,3).copy() for side in sides}
        self.event('held_command_reference',sides=list(sides),delta=delta.tolist(),
            qualification='Measured TCP translation with legal command orientation; private Cartesian continuation, no object attachment/reset')
        count=max(1,math.ceil(float(np.linalg.norm(delta))/.0075))
        for u in np.linspace(1/count,1,count):
            if allow_one_hand_recovery:
                sides=tuple(s for s in sides if s in self.holding_sides)
                if not sides:raise Fault('single_tray_contact_lost',self.observation()['gripper_contact_force'])
            goals={side:(starts[side]+u*delta,rotations[side]) for side in sides}
            self.private_held_translation=np.mean([goals[side][0]-self.sim.tcp(side)[0] for side in sides],axis=0)
            self.event('private_held_translation_prediction',delta=self.private_held_translation.tolist(),
                qualification='Shadow MjData only; actual tray/payload qpos never assigned during robot action')
            try:
                obs=self.move(goals,minimum_seconds=.25,tracking_tolerance=self.p.held_tracking_tolerance_m,
                    predicate=lambda o:all(o['gripper_contact_force'][s]>self.p.contact_n for s in sides),
                    finish_predicate=finish_predicate,allow_one_hand_recovery=allow_one_hand_recovery)
            finally:self.private_held_translation=None
            if finish_predicate is not None and finish_predicate(obs):return obs
        return obs

    def _capture_held_tools(self,sides,obs):
        """Command FK preserves the measured grasp's servo preload in tray frame."""
        shadow=self.mj.MjData(self.m);shadow.qpos[:]=self.d.qpos
        for side,offset in (('left',0),('right',8)):
            qids=[self.m.jnt_qposadr[j] for j in self.sim.arms[side]]
            shadow.qpos[qids]=self.sim.target[offset:offset+7]
        self.mj.mj_kinematics(self.m,shadow)
        if not hasattr(self,'held_relative_tools'):self.held_relative_tools={}
        R=obs['tray_rotation']
        for side in sides:
            site=shadow.site(side+'_tcp')
            self.held_relative_tools[side]=(R.T@(site.xpos-obs['tray_position']),R.T@site.xmat.reshape(3,3))
        self.event('held_tray_frame_tools_captured',sides=list(sides),
            relative_tools={s:{'position':self.held_relative_tools[s][0].tolist(),
                'rotation':self.held_relative_tools[s][1].tolist()} for s in sides},
            qualification='Private command FK only; servo preload retained, no live object assignment')

    def _held_pose_follow_move(self,position,sides,*,finish_predicate=None,allow_one_hand_recovery=False):
        if allow_one_hand_recovery and self.action!='place_empty':raise ValueError('One-hand recovery is restricted to empty place')
        if any(s not in getattr(self,'held_relative_tools',{}) for s in sides):raise Fault('single_tray_held_pose_reference_missing')
        position=np.asarray(position,float);active=set(sides)
        translation_reference=self.observation()['tray_position'].copy()
        for step in range(self.p.max_stage_steps):
            obs=self.observation()
            surviving={s for s in active if obs['gripper_contact_force'][s]>self.p.contact_n}
            if surviving!=active:
                if not allow_one_hand_recovery or not surviving:raise Fault('single_tray_contact_lost',obs['gripper_contact_force'])
                self.event('empty_place_one_hand_recovery',lost_sides=sorted(active-surviving),remaining_sides=sorted(surviving),
                    frozen_arm_references={s:self.sim.target[(0 if s=='left' else 8):(7 if s=='left' else 15)].tolist() for s in active-surviving},
                    force_n=obs['gripper_contact_force'],lowest_corner_gap_m=float(obs['tray_bottom_z'])-self.p.tabletop_z)
                self.holding_sides.difference_update(active-surviving);active=surviving
            if finish_predicate is not None and finish_predicate(obs):return obs
            remaining=position-obs['tray_position'];error=float(np.linalg.norm(remaining))
            advance=position-translation_reference
            advance*=min(1.,.0025/max(float(np.linalg.norm(advance)),1e-12))
            proposal=translation_reference+advance
            lag=proposal-obs['tray_position'];lag_norm=float(np.linalg.norm(lag))
            # Accumulate a real actuator translation reference so gravity
            # need not be overcome by a perpetually reset 2.5 mm error.
            # Bound its distance from actual object feedback to 20 mm.
            if lag_norm>.02:proposal=obs['tray_position']+lag*.02/lag_norm
            delta=proposal-translation_reference
            delta*=min(1.,.0025/max(float(np.linalg.norm(delta)),1e-12))
            translation_reference+=delta
            R=obs['tray_rotation'];goals={s:(translation_reference+R@self.held_relative_tools[s][0],
                R@self.held_relative_tools[s][1]) for s in active}
            self.private_held_translation=delta.copy()
            self.private_incremental_command_prediction=True
            self.private_allow_held_preload=(active=={'left','right'})
            try:planned=self.plan_joint_goal(goals,reference_step_rad=.45/self.p.fps)
            finally:
                self.private_held_translation=None;self.private_incremental_command_prediction=False;self.private_allow_held_preload=False
            before=self.sim.target.copy()
            for side in active:
                offset=0 if side=='left' else 8
                self.sim.target[offset:offset+7]+=np.clip(planned[offset:offset+7]-before[offset:offset+7],-.45/self.p.fps,.45/self.p.fps)
            obs=self.tick()
            if step%20==0:self.event('held_pose_feedback',sides=sorted(active),remaining_position_error_m=error,
                reference_translation_step_m=delta.tolist(),joint_reference_speed_cap_rad_s=.45,
                translation_reference=translation_reference.tolist(),reference_lag_target_m=.02,
                actual_translation_lag_m=float(np.linalg.norm(translation_reference-obs['tray_position'])),
                tray_rotation=R.tolist(),qualification='Actual pose feedback through actuator targets; no attachment or external force')
            contact_retained=all(obs['gripper_contact_force'][s]>self.p.contact_n for s in active)
            if contact_retained and finish_predicate is not None and finish_predicate(obs):return obs
            if contact_retained and error<self.p.held_tracking_tolerance_m:return obs
        raise Fault('single_tray_held_pose_feedback_budget_exhausted',dict(position_error_m=error,sides=sorted(active)))

    def endpoint_reachable(self,side,position,rotation):
        """Private FK/IK endpoint check, never a live object or robot reset."""
        from r1pro_teleop.airport_arrange import solve
        offset=0 if side=='left' else 8
        _,error=solve(self.sim,side,np.asarray(position),np.asarray(rotation),self.sim.target[offset:offset+7])
        return bool(np.isfinite(error) and error<.02)

    def release(self,sides,*,predicate=None):
        if self.action=='push_loaded' and tuple(sides)==('right',) and not self.handover_verified:
            raise Fault('single_tray_right_release_before_left_contact')
        if self.action=='push_loaded' and tuple(sides)==('right',) and self.p.push_right_outward_release:
            return self._release_right_outward(predicate=predicate)
        for _ in range(math.ceil(self.p.open_command/.002)+2):
            self._opening(sides,self.p.open_command);obs=self.tick()
            if predicate is not None and not predicate(obs):raise Fault('single_tray_handover_left_contact_lost')
        self.holding_sides.difference_update(sides)

    def _release_right_outward(self,*,predicate):
        if not self.handover_verified or self.observation()['gripper_contact_force']['left']<=self.p.contact_n:
            raise Fault('single_tray_right_release_before_left_contact')
        if not self.p.push_command_reference:raise Fault('single_tray_outward_release_without_command_reference')
        _,origin,anchor,R=self.push_anchor
        reference=anchor+self.push_last_reference_position-origin
        initial_opening=float(self.sim.state()[15]);normal=np.asarray(self.p.front_normal)
        self.event('right_outward_open_start',initial_opening_m=initial_opening,
            commanded_tcp_reference=reference.tolist(),outward_direction=normal.tolist(),
            qualification='Left grasp already verified; gradual front retreat offsets inward-finger opening, original payload contact guard retained')
        for _ in range(math.ceil(self.p.open_command/.002)+2):
            opening=min(self.p.open_command,float(self.sim.target[15])+.002)
            outward=.005+.5*max(0.,opening-initial_opening)
            self.move({'right':(reference+outward*normal,R)},openings={'right':opening},minimum_seconds=.25,
                tracking_tolerance=self.p.held_tracking_tolerance_m,finish_on_reference_submitted=True,
                predicate=lambda o:o['gripper_contact_force']['left']>self.p.contact_n and (predicate is None or predicate(o)))
            if opening>=self.p.open_command:break
        else:raise Fault('single_tray_right_outward_release_budget_exhausted')
        self.holding_sides.discard('right')
        self.event('right_outward_open_complete',actual_opening_m=float(self.sim.state()[15]),
            force_n=self.observation()['gripper_contact_force'],outward_reference_m=outward)

    def _on_table(self,obs):
        relative=obs['tray_corners'][:,:2]-self.p.table_center_xy
        return bool(obs['table_contacts']>0 and np.all(np.abs(relative)<=np.asarray(self.p.table_half_sizes_xy)+.005))

    def loaded_goal_reached(self,obs):
        """Actual leftmost tray edge, including its actual yaw and tilt."""
        error=self.loaded_goal_remaining(obs)
        return bool(np.isfinite(error) and self._on_table(obs) and abs(error)<=self.p.position_tolerance_m)

    def loaded_goal_remaining(self,obs):
        left=np.asarray(self.p.robot_left)
        target=float(np.asarray(self.p.loaded_goal_position)@left)+max(self.p.tray_dimensions[:2])/2
        corners=np.asarray(obs['tray_corners'],float)
        return target-float(np.max(corners@left))

    def _in_push_contact_domain(self):
        return self.action=='push_loaded' and self.phase in ('right_push','left_push','vla_push_loaded')

    def _push_missing_support_geometry(self,obs):
        corners=np.asarray(obs['tray_corners'],float);gap=float(obs['tray_bottom_z'])-self.p.tabletop_z
        inside=np.isfinite(corners).all() and np.all(np.abs(corners[:,:2]-self.p.table_center_xy)<=np.asarray(self.p.table_half_sizes_xy)+.005)
        return bool(inside and np.isfinite(gap) and abs(gap)<=self.p.push_table_contact_grace_gap_m),gap

    def _observe_push_table_support(self,obs):
        supported=self._on_table(obs)
        if supported:
            if self._push_table_missing_since is not None:
                duration=float(self.d.time)-self._push_table_missing_since
                self.push_table_contact_max_absent_duration_s=max(self.push_table_contact_max_absent_duration_s,duration)
                self.push_table_contact_grace_recoveries+=1
                if self._push_table_missing_logged:self.event('push_table_contact_restored',
                    missing_start_frame=self._push_table_missing_frame,missing_start_sim_time=self._push_table_missing_since,
                    absent_duration_s=duration,table_contacts=int(obs['table_contacts']))
                self._push_table_missing_since=None;self._push_table_missing_frame=None;self._push_table_missing_logged=False
            return None
        if not self._in_push_contact_domain():return None
        self.strict_continuous_push_table_contact_gate=False
        valid,gap=self._push_missing_support_geometry(obs)
        self.push_table_contact_max_gap_m=max(self.push_table_contact_max_gap_m,abs(gap))
        if self._push_table_missing_since is None:
            self._push_table_missing_since=float(self.d.time);self._push_table_missing_frame=self.frames
            self.push_table_contact_grace_episodes+=1
            # At most one paired episode log per rendered frame. Counters
            # retain every substep episode, including unlogged micro-bounces.
            self._push_table_missing_logged=self._push_table_last_log_frame!=self.frames
            if self._push_table_missing_logged:
                self._push_table_last_log_frame=self.frames
                self.event('push_table_contact_missing',missing_start_frame=self.frames,
                    missing_start_sim_time=float(self.d.time),lowest_corner_gap_m=gap,
                    grace_frames=self.p.push_table_contact_grace_frames,grace_gap_cap_m=self.p.push_table_contact_grace_gap_m,
                    qualification='Explicit bounded numeric-contact grace; strict continuous support flag is false')
        duration=float(self.d.time)-self._push_table_missing_since
        self.push_table_contact_max_absent_duration_s=max(self.push_table_contact_max_absent_duration_s,duration)
        if self.p.push_table_contact_grace_frames==0:return None  # preserve historic runtime gates
        if not valid:return Fault('single_tray_push_missing_support_outside_grace_geometry',
            dict(lowest_corner_gap_m=gap,gap_cap_m=self.p.push_table_contact_grace_gap_m,full_footprint_inside_required=True))
        limit=self.p.push_table_contact_grace_frames/self.p.fps
        if duration>limit+1e-9:return Fault('single_tray_push_table_contact_grace_exhausted',
            dict(absent_duration_s=duration,grace_limit_s=limit,missing_start_frame=self._push_table_missing_frame))
        return None

    def _push_table_supported(self,obs):
        if self._on_table(obs):return True
        if not self._in_push_contact_domain() or self.p.push_table_contact_grace_frames==0 or self._push_table_missing_since is None:return False
        valid,_=self._push_missing_support_geometry(obs)
        return bool(valid and float(self.d.time)-self._push_table_missing_since<=self.p.push_table_contact_grace_frames/self.p.fps+1e-9)

    def _place_release_ready(self,obs):
        corners=np.asarray(obs['tray_corners'],float)
        relative=corners[:,:2]-self.p.table_center_xy
        gap=float(obs['tray_bottom_z'])-self.p.tabletop_z
        return bool(np.isfinite(corners).all() and np.isfinite(gap) and
            -self.p.max_penetration_m<=gap<=self.p.place_release_clearance_m and
            np.all(np.abs(relative)<=np.asarray(self.p.table_half_sizes_xy)))

    def _finish_action(self,start):
        # An actual extra held interval journals the measured success endpoint;
        # this is not duplicated/padded trajectory data.
        endpoint=self.frames;self.tick();end=self.frames
        row=dict(action_label=self.action,start_frame=start,end_frame_exclusive=end,
            measured_endpoint_frame=endpoint,payload_loaded=self.loaded,verified=True)
        self.actions.append(row)
        # event() binds action/payload identity from this same live controller;
        # do not pass a second copy of its reserved keyword arguments.
        self.event('action_complete',**{k:v for k,v in row.items() if k not in ('action_label','payload_loaded')})

    def pick_empty(self):
        if self.loaded:raise Fault('single_tray_pick_requires_empty')
        self.action='pick_empty';start=self.frames;self.event('action_start')
        self.phase='robot_prepare';self.hold(40)
        initial=self.observation()['tray_bottom_z'];self.acquire(('left','right'))
        self.phase='lift';position=self.observation()['tray_position'];position[2]+=self.p.lift_distance
        lifted=lambda o:(o['table_contacts']==0 and o['tray_bottom_z']-initial>=self.p.minimum_lift_clearance
            and all(o['gripper_contact_force'][s]>self.p.contact_n for s in ('left','right')))
        stop_ready=lambda o:(lifted(o) and o['tray_bottom_z']-initial>=
            self.p.minimum_lift_clearance+self.p.lift_stop_margin_m)
        self._held_move(position,('left','right'),finish_predicate=stop_ready)
        self.event('lift_reference_stopped',actual_clearance_m=float(self.observation()['tray_bottom_z'])-initial,
            endpoint_margin_m=self.p.lift_stop_margin_m,required_stable_clearance_m=self.p.minimum_lift_clearance)
        self.phase='stabilize'
        for stable_frame in range(self.p.stable_support_frames):
            obs=self.tick()
            if not all(obs['gripper_contact_force'][s]>self.p.contact_n for s in ('left','right')):
                raise Fault('single_tray_contact_lost',obs['gripper_contact_force'])
            if not lifted(obs):
                raise Fault('single_tray_empty_lift_not_stable',dict(actual_clearance_m=float(obs['tray_bottom_z'])-initial,
                    table_contacts=obs['table_contacts'],force_n=obs['gripper_contact_force'],
                    stable_frames_completed=stable_frame,required_stable_frames=self.p.stable_support_frames,
                    required_clearance_m=self.p.minimum_lift_clearance,endpoint_margin_m=self.p.lift_stop_margin_m))
        if obs['table_contacts'] or obs['tray_bottom_z']-initial<self.p.minimum_lift_clearance:
            raise Fault('single_tray_empty_lift_incomplete',dict(clearance_m=obs['tray_bottom_z']-initial,table_contacts=obs['table_contacts']))
        self._finish_action(start)

    def place_empty(self):
        if self.p.place_inboard_slow_recipe:
            from .placement_recipe import PlacementRecipe,place_empty_recipe
            return place_empty_recipe(self,PlacementRecipe(withdraw=True))
        if self.loaded or self.holding_sides!={'left','right'}:raise Fault('single_tray_empty_place_without_grasp')
        self.action='place_empty';start=self.frames;self.event('action_start');self.phase='lower'
        # Correct the actual footprint while still held, never relax the
        # tabletop bounds to accommodate a tipped tray's outward corner.
        obs=self.observation();xy=np.asarray(obs['tray_corners'])[:,:2]
        lo=np.asarray(self.p.table_center_xy)-self.p.table_half_sizes_xy
        hi=np.asarray(self.p.table_center_xy)+self.p.table_half_sizes_xy
        correction=np.maximum(lo+.01-xy.min(axis=0),0)-np.maximum(xy.max(axis=0)-(hi-.01),0)
        if np.any(np.abs(correction)>.04):raise Fault('single_tray_place_footprint_recovery_unreachable',correction.tolist())
        if np.any(np.abs(correction)>1e-6):
            self.phase='place_inward_recovery';position=obs['tray_position'].copy();position[:2]+=correction
            self.event('empty_place_footprint_correction',translation_xy=correction.tolist(),tray_corners_xy=xy.tolist())
            self._held_move(position,tuple(sorted(self.holding_sides)),allow_one_hand_recovery=True)
        self.phase='lower'
        for _ in range(self.p.max_stage_steps):
            obs=self.observation()
            if self._place_release_ready(obs):break
            gap=float(obs['tray_bottom_z'])-self.p.tabletop_z
            if gap<=self.p.place_release_clearance_m:
                raise Fault('single_tray_place_release_footprint_unsafe')
            # Lower the actual lowest corner, rather than driving a tilted
            # tray's nominal origin through the tabletop in the shadow plan.
            position=obs['tray_position'].copy()
            position[2]-=min(.0075,max(.001,gap-self.p.place_release_clearance_m*.5))
            self._held_move(position,tuple(sorted(self.holding_sides)),finish_predicate=self._place_release_ready,
                allow_one_hand_recovery=True)
        else:raise Fault('single_tray_place_lowering_budget_exhausted')
        obs=self.observation()
        if not self._place_release_ready(obs):raise Fault('single_tray_place_release_not_ready')
        self.event('place_release_geometry_verified',lowest_corner_gap_m=float(obs['tray_bottom_z'])-self.p.tabletop_z,
            allowed_release_clearance_m=self.p.place_release_clearance_m,
            tray_corners_xy=np.asarray(obs['tray_corners'])[:,:2].tolist(),
            table_contact_before_release=bool(obs['table_contacts']),
            qualification='Low-height release; real gravity, table support and complete gripper release still required')
        self.phase='open';self.release(('left','right'))
        self.phase='withdraw';self.move({s:(self.sim.tcp(s)[0]+np.array([0,0,.10]),self.sim.tcp(s)[1]) for s in ('left','right')})
        self.phase='settle';obs=self.hold(self.p.stable_support_frames)
        if not self._on_table(obs) or max(obs['gripper_contact_force'].values())>self.p.contact_n or min(obs['gripper_openings'])<.06:
            raise Fault('single_tray_empty_place_not_released')
        self._finish_action(start)

    def passenger_load(self):
        if self.passenger_loader is None:raise Fault('single_tray_passenger_loader_missing')
        self.action='environment';self.phase='passenger_load';before_q=self.d.qpos[self._protected_qpos].copy();before_v=self.d.qvel[self._protected_dofs].copy()
        before_time=float(self.d.time);before_target=self.sim.target.copy()
        self.event('passenger_load_start',training_segment=False)
        evidence=self.passenger_loader(self.sim)
        if (not np.array_equal(before_q,self.d.qpos[self._protected_qpos]) or not np.array_equal(before_v,self.d.qvel[self._protected_dofs]) or
            before_time!=float(self.d.time) or not np.array_equal(before_target,self.sim.target)):
            raise Fault('single_tray_environment_modified_robot_or_tray')
        self.mj.mj_forward(self.m,self.d);self.loaded=True
        self.event('passenger_payload_initialized',training_segment=False,environment_evidence=evidence)
        self.phase='passenger_settle';obs=self.hold(40)
        if obs['payload_mass_kg']<=0 or obs['payload_support_contacts']<=0 or not self._on_table(obs):
            raise Fault('single_tray_payload_not_physically_supported',obs)

    def _handover(self):
        if 'right' not in self.holding_sides:raise Fault('single_tray_handover_without_right_grasp')
        if self.p.push_lead_frame=='measured_tcp':self._neutralize_right_push_reference()
        right_reference=self.sim.target[8:16].copy();self.phase='right_reach_stop';self.hold(self.p.stable_contact_frames)
        self.event('right_reach_stopped',right_joint_reference=right_reference.tolist())
        self.phase='left_approach';self.acquire(('left',),prefix='left_')
        if not np.array_equal(right_reference,self.sim.target[8:16]):raise Fault('single_tray_handover_moved_right_reference')
        self.phase='left_contact_verify'
        obs=self.hold(self.p.stable_contact_frames,lambda o:o['gripper_contact_force']['left']>self.p.contact_n and o['gripper_contact_force']['right']>self.p.contact_n)
        self.handover_verified=True;self.event('left_handover_contact_verified',force_n=obs['gripper_contact_force'])
        self.phase='right_release';self.release(('right',),predicate=lambda o:o['gripper_contact_force']['left']>self.p.contact_n)
        self.event('right_released_after_left_contact',contact_verified=True)
        self.move({'right':(self.sim.tcp('right')[0]+np.array([0,0,.10]),self.sim.tcp('right')[1])},
            predicate=lambda o:o['gripper_contact_force']['left']>self.p.contact_n)

    def _neutralize_right_push_reference(self):
        _,origin,anchor,R=self.push_anchor;left=np.asarray(self.p.robot_left)
        reference=anchor+self.push_last_reference_position-origin;actual=self.sim.tcp('right')[0]
        neutral=reference-float((reference-actual)@left)*left
        self.phase='right_reach_stop'
        self.event('right_push_reference_neutralization',previous_reference=reference.tolist(),neutral_reference=neutral.tolist(),
            actual_tcp_position=actual.tolist(),qualification='Only left-axis target neutralized; command X/Z/orientation preload retained')
        self._push_reference_move(origin+neutral-anchor,'right')
        previous=self.observation();previous_tcp=self.sim.tcp('right')[0].copy();stable=0
        for _ in range(self.p.max_stage_steps):
            obs=self.tick();tcp=self.sim.tcp('right')[0].copy()
            if obs['gripper_contact_force']['right']<=self.p.contact_n:raise Fault('single_tray_right_push_neutralization_contact_lost')
            tray_speed=float(np.linalg.norm(obs['tray_position']-previous['tray_position'])*self.p.fps)
            tcp_speed=float(np.linalg.norm(tcp-previous_tcp)*self.p.fps)
            stable=stable+1 if self._on_table(obs) and obs['gripper_contact_force']['right']>self.p.contact_n and tray_speed<.01 and tcp_speed<.02 else 0
            previous=obs;previous_tcp=tcp
            if stable>=3:
                self.event('right_push_reference_physically_stable',stable_frames=stable,tray_speed_m_s=tray_speed,
                    tcp_speed_m_s=tcp_speed,actual_tray_position=obs['tray_position'].tolist())
                return
        raise Fault('single_tray_right_push_neutralization_budget_exhausted')

    def _capture_push_reference(self,side):
        obs=self.observation()
        if not self.loaded or obs['payload_mass_kg']<=0 or side not in self.holding_sides or obs['gripper_contact_force'][side]<=self.p.contact_n:
            raise Fault('single_tray_push_reference_without_live_loaded_grasp')
        shadow=self.mj.MjData(self.m);shadow.qpos[:]=self.d.qpos
        for hand,offset in (('left',0),('right',8)):
            qids=[self.m.jnt_qposadr[j] for j in self.sim.arms[hand]]
            shadow.qpos[qids]=self.sim.target[offset:offset+7]
        self.mj.mj_kinematics(self.m,shadow)
        site=shadow.site(side+'_tcp')
        original_tcp=site.xpos.copy();anchor_tcp=original_tcp+np.array([0.,0.,self.p.push_vertical_relief_m])
        self.push_anchor=(side,obs['tray_position'].copy(),anchor_tcp,site.xmat.reshape(3,3).copy())
        self.push_last_reference_position=obs['tray_position'].copy()
        self.event('loaded_push_command_reference_captured',side=side,
            actual_tray_position=self.push_anchor[1].tolist(),commanded_tcp_position=original_tcp.tolist(),
            push_tcp_anchor_position=anchor_tcp.tolist(),vertical_reference_relief_m=self.p.push_vertical_relief_m,
            commanded_tcp_rotation=self.push_anchor[3].tolist(),force_n=obs['gripper_contact_force'][side],
            qualification='Private FK captures existing servo reference with explicit bounded vertical relief; robot/tray state unchanged')
        return obs['tray_position'].copy()

    def _push_reference_move(self,position,side):
        hand,origin,tcp,R=self.push_anchor
        if hand!=side:raise Fault('single_tray_push_reference_holder_mismatch')
        position=np.asarray(position,float);obs=self.observation()
        previous=getattr(self,'push_last_reference_position',origin)
        self.private_held_translation=position-previous
        self.event('private_push_increment_prediction',reference_increment=self.private_held_translation.tolist(),
            actual_force_lead=(position-obs['tray_position']).tolist(),
            qualification='Shadow predicts this newly submitted increment, never treats cumulative servo force-lead as instantaneous tray movement')
        self.private_incremental_command_prediction=True
        try:
            result=self.move({side:(tcp+position-origin,R)},minimum_seconds=.25,
                tracking_tolerance=self.p.held_tracking_tolerance_m,
                finish_on_reference_submitted=True,
                predicate=lambda o:o['gripper_contact_force'][side]>self.p.contact_n)
            self.push_last_reference_position=position.copy()
            return result
        finally:
            self.private_held_translation=None;self.private_incremental_command_prediction=False

    def _next_tcp_push_reference(self,reference,side,remaining):
        _,origin,anchor,R=self.push_anchor;left=np.asarray(self.p.robot_left);obs=self.observation()
        previous=anchor+reference-origin;actual=self.sim.tcp(side)[0]
        lead=float((previous-actual)@left)
        increment=min(self.p.push_step_m,max(0.,remaining),self.p.push_reference_lead_m-lead)
        desired=previous+increment*left
        forward=-np.asarray(self.p.front_normal);corners=np.asarray(obs['tray_corners'])@forward
        centre=float(np.r_[self.p.table_center_xy,0.]@forward)
        half=float(np.asarray(self.p.table_half_sizes_xy)@np.abs(forward[:2]))
        lower=centre-half+self.p.push_table_inboard_margin_m;upper=centre+half-self.p.push_table_inboard_margin_m
        below=lower-float(np.min(corners));above=float(np.max(corners))-upper
        error=((below-above)/2 if below>0 and above>0 else below if below>0 else -above if above>0 else 0.)
        correction=float(np.clip(error,-self.p.push_forward_reference_step_m,self.p.push_forward_reference_step_m))
        desired=desired+correction*forward
        forward_lead=float((desired-actual)@forward)
        desired=desired+(float(np.clip(forward_lead,-self.p.push_forward_reference_lead_m,self.p.push_forward_reference_lead_m))-forward_lead)*forward
        long=int(np.argmax(self.p.tray_dimensions[:2]));limit=max(self.p.tray_dimensions[:2])/2-.02
        for scope,point in (('measured',actual),('reference',desired)):
            local=obs['tray_rotation'].T@(point-obs['tray_position'])
            if not np.isfinite(local).all() or abs(float(local[long]))>limit:
                raise Fault('single_tray_push_long_rim_tracking_boundary',dict(scope=scope,local_position=local.tolist(),tangent_limit_m=limit))
        self.event('loaded_push_measured_tcp_reference',side=side,actual_tcp_position=actual.tolist(),
            previous_tcp_reference=previous.tolist(),submitted_tcp_reference=desired.tolist(),
            measured_tracking_lead_m=float((desired-actual)@left),lead_cap_m=self.p.push_reference_lead_m,
            reference_increment_m=increment,actual_tray_position=obs['tray_position'].tolist(),
            forward_corner_min_m=float(np.min(corners)),forward_corner_max_m=float(np.max(corners)),
            forward_inboard_target_interval_m=[lower,upper],forward_reference_correction_m=correction,
            forward_tracking_lead_m=float((desired-actual)@forward),forward_lead_cap_m=self.p.push_forward_reference_lead_m)
        return origin+desired-anchor,desired

    def push_loaded(self):
        obs=self.observation()
        if not self.loaded or obs['payload_mass_kg']<=0 or obs['payload_support_contacts']<=0:raise Fault('single_tray_push_requires_real_load')
        self.action='push_loaded';start=self.frames;self.event('action_start');self.acquire(('right',),prefix='right_')
        side='right';left=np.asarray(self.p.robot_left);goal=np.asarray(self.p.loaded_goal_position)
        reference=self._capture_push_reference(side) if self.p.push_command_reference else None
        for _ in range(self.p.max_stage_steps):
            obs=self.observation();remaining=self.loaded_goal_remaining(obs)
            if remaining<=self.p.position_tolerance_m:break
            next_delta=min(self.p.push_step_m,remaining)*left
            proposed=None
            if self.p.push_lead_frame=='measured_tcp':proposed=self._next_tcp_push_reference(reference,side,remaining)
            right_at_limit=(side=='right' and (
                float((self.sim.tcp('right')[0]-np.r_[self.base_origin[:2],0.])@left)>=self.p.right_reach_lateral_m or
                (proposed is not None and float((proposed[1]-np.r_[self.base_origin[:2],0.])@left)>=self.p.right_reach_lateral_m) or
                not self.endpoint_reachable('right',proposed[1] if proposed is not None else self.sim.tcp('right')[0]+next_delta,
                    self.push_anchor[3] if proposed is not None else self.sim.tcp('right')[1])))
            if right_at_limit:
                self._handover();side='left'
                if self.p.push_command_reference:reference=self._capture_push_reference(side)
                if self.p.push_lead_frame=='measured_tcp':proposed=self._next_tcp_push_reference(reference,side,self.loaded_goal_remaining(self.observation()))
            self.phase=side+'_push';position=obs['tray_position']+min(self.p.push_step_m,remaining)*left
            if self.p.push_command_reference:
                obs=self.observation();lead=float((reference-obs['tray_position'])@left)
                reference=(proposed[0] if proposed is not None else reference+min(self.p.push_step_m,remaining,max(0.,self.p.push_reference_lead_m-lead))*left)
                tray_offset=float((reference-obs['tray_position'])@left)
                selected_lead=(float((self.push_anchor[2]+reference-self.push_anchor[1]-self.sim.tcp(side)[0])@left)
                    if self.p.push_lead_frame=='measured_tcp' else tray_offset)
                self.event('loaded_push_absolute_reference',side=side,reference_position=reference.tolist(),
                    actual_tray_position=obs['tray_position'].tolist(),reference_lead_m=selected_lead,
                    lead_frame=self.p.push_lead_frame,tray_reference_offset_m=tray_offset,
                    lead_limit_m=self.p.push_reference_lead_m,
                    qualification='Persistent command FK origin; no per-segment measured TCP reset')
                self._push_reference_move(reference,side)
            else:self._held_move(position,(side,))
            if not self._push_table_supported(self.observation()):raise Fault('single_tray_push_lost_table_support')
        else:raise Fault('single_tray_push_budget_exhausted')
        if not self.handover_verified:raise Fault('single_tray_required_handover_not_executed')
        self.phase='open';self.release(('left',));self.phase='withdraw'
        self.move({'left':(self.sim.tcp('left')[0]+np.array([0,0,.10]),self.sim.tcp('left')[1])})
        self.phase='settle';obs=self.hold(self.p.stable_support_frames)
        if not self.loaded_goal_reached(obs) or obs['payload_support_contacts']<=0:
            raise Fault('single_tray_loaded_goal_incomplete',obs)
        self._finish_action(start)

    def run(self):
        self.pick_empty();self.place_empty();self.passenger_load();self.push_loaded()
        return dict(task_completed=True,source='simulation/program_generated',actions=self.actions,
            environment_phase_excluded=True,actual_handover_verified=self.handover_verified,frames=self.frames)

    def close(self):self.sim.close()
