"""Three-second physical Pick/Place benchmark, separate from full-task BC.

Station selection and arm preposition are recorded and timed separately.
The timed intervals always use real 20Hz commands and 25 native substeps.
"""
import numpy as np
from .isaac_three_tray_teacher import NativeTeacher
from .isaac_three_tray_observer import NativeTaskFault


def smooth5(u):return u*u*u*(10.+u*(-15.+6.*u))


def episode_front_stations(point,tray_yaw,table):
    """Reuse aisle-facing station offsets and add legal yaw-aligned offsets.

    Positions are filtered against the original table front, not a front
    redefined by the robot's yaw. These are private planning proposals only.
    """
    from r1pro_teleop.single_tray_3table.observer import table_front_region_violation
    face=np.pi if table['table_id']=='rear' else 0.
    aligned=face+.5*np.arctan2(np.sin(2*(tray_yaw-face)),np.cos(2*(tray_yaw-face)))
    seen=set()
    for angle in (aligned,aligned-np.deg2rad(15),aligned+np.deg2rad(15)):
        for distance in (.55,.58,.60,.50,.62,.65,.68):
            for lateral in (0.,.035,-.035,-.10,.10,-.20,.20):
                for offset_face in (face,angle):
                    forward=np.array([np.cos(offset_face),np.sin(offset_face)])
                    left=np.array([-forward[1],forward[0]])
                    base=np.r_[np.asarray(point)[:2]-distance*forward+lateral*left,angle]
                    key=tuple(np.round(base,9))
                    if key in seen:continue
                    seen.add(key)
                    if not table_front_region_violation(table,np.r_[base[:2],0.]):yield base


def aligned_pad_rotation(face,side,pitch_degrees=-30.):
    from scipy.spatial.transform import Rotation
    return (Rotation.from_euler('z',face).as_matrix() @
            Rotation.from_euler('x',-10. if side=='left' else 10.,degrees=True).as_matrix() @
            Rotation.from_euler('y',pitch_degrees,degrees=True).as_matrix())


class FastPickPlace(NativeTeacher):
    def __init__(self,runtime,observer):
        super().__init__(runtime,observer);self.spans=[];self.active_tray=0

    def goals(self,tray,face):
        goals=super().goals(tray,face,pitch_deg=getattr(self,'grasp_pitch_degrees',-30.))
        if getattr(self,'align_pad_normal',False):
            # Pitch about the already aligned pad normal. The old Ry @ Rx
            # composition introduces an along-rim component into the pad normal
            # and makes the box corner, rather than its face, contact the wall.
            across=goals['left'][0]-goals['right'][0]
            selected_face=float(np.arctan2(-across[0],across[1]))
            goals={side:(p,aligned_pad_rotation(selected_face,side,getattr(self,'grasp_pitch_degrees',-30.)))
                   for side,(p,R) in goals.items()}
        # The long-rim provider describes the desired pad contact center.
        # Use the actual source pad geometry rather than treating the TCP as
        # that center. Both hands retain the original long-rim orientation.
        self.r.sync_planner();saved=self.r.shadow.qpos.copy();offsets={}
        try:
            for side in goals:
                for k in (1,2):
                    jid=self.r.model.joint(f'{side}_gripper_finger_joint{k}').id
                    self.r.shadow.qpos[self.r.model.jnt_qposadr[jid]]=.006
            self.r.mj.mj_forward(self.r.model,self.r.shadow)
            for side in goals:
                names={f'{side}_gripper_finger_link{k}' for k in (1,2)}
                gids=[i for i in range(self.r.model.ngeom)
                      if self.r.model.body(self.r.model.geom_bodyid[i]).name in names and
                      (self.r.model.geom_contype[i] or self.r.model.geom_conaffinity[i])]
                if len(gids)!=2:raise ValueError('two_source_pad_collision_centers_required')
                center=np.mean([self.r.shadow.geom(i).xpos for i in gids],axis=0)
                tcp=self.r.shadow.site(side+'_tcp');offsets[side]=tcp.xmat.reshape(3,3).T@(center-tcp.xpos)
        finally:
            self.r.shadow.qpos[:]=saved;self.r.mj.mj_forward(self.r.model,self.r.shadow)
        if not getattr(self,'pad_frame_recorded',False):
            self.r.event('native_pad_center_to_tcp_translation',offset_local_m={s:p.tolist() for s,p in offsets.items()},
                         source='unchanged_source_collision_geometry',grasp_edges_unchanged=True,
                         registered_grasp_pitch_degrees=getattr(self,'grasp_pitch_degrees',-30.))
            self.pad_frame_recorded=True
        offset=float(getattr(self,'contact_along_edge_offset_m',0.))
        if abs(offset)>max(self.r.size[tray,:2])/2-.01:raise ValueError('contact_offset_outside_existing_long_edge')
        yaw=self.r.yaw(self.obs()['tray_pose'][tray,3:])+(0. if self.r.size[tray,0]>=self.r.size[tray,1] else np.pi/2)
        along=offset*np.array([np.cos(yaw),np.sin(yaw),0.])
        return {side:(p+along-R@offsets[side],R) for side,(p,R) in goals.items()}

    def choose_station(self,tray,table,**unused):
        from r1pro_teleop.single_tray_3table.observer import table_front_region_violation
        obs=self.obs();point=obs['tray_pose'][tray,:3];yaw=.5*np.arctan2(np.sin(2*self.r.yaw(obs['tray_pose'][tray,3:])),np.cos(2*self.r.yaw(obs['tray_pose'][tray,3:])))
        from scipy.spatial.transform import Rotation
        yaw_rotation=Rotation.from_euler('z',yaw).as_matrix()
        goals=self.goals(tray,0.);failed=[]
        fixed=getattr(self,'fixed_base_world',None)
        candidates=[np.asarray(fixed,float)] if fixed is not None else []
        if fixed is None and getattr(self,'search_front_stations',False):
            candidates=list(episode_front_stations(point,yaw,table))
        elif fixed is None:
            for distance in (.55,.60,.50,.65):
                for lateral in (0.,-.10,.10,-.20,.20):
                    forward=np.array([np.cos(yaw),np.sin(yaw)]);left=np.array([-forward[1],forward[0]])
                    candidates.append(np.r_[point[:2]-distance*forward+lateral*left,yaw])
        lift=float(getattr(self,'lift_height_m',.18))
        for base in candidates:
            if base.shape!=(3,) or not np.isfinite(base).all():raise ValueError('invalid_fixed_base_pose')
            if table_front_region_violation(table,np.r_[base[:2],0.]):continue
            try:
                if getattr(self,'search_front_stations',False):goals=self.goals(tray,float(base[2]))
                for u in np.linspace(0.,1.,13):
                    self.solve({s:(p+[0,0,.12*u],R) for s,(p,R) in goals.items()},base_world=base)
                    correction=np.eye(3)
                    self.solve({s:(point+[0,0,lift*u]+correction@(p-point),correction@R) for s,(p,R) in goals.items()},base_world=base)
                    correction=np.eye(3)
                    self.solve({s:(point+[0,0,lift-(lift-.004)*u]+correction@(p-point),correction@R) for s,(p,R) in goals.items()},base_world=base)
                self.r.event('fast_joint_front_station_selected',base_world=base.tolist(),tray_yaw_rad=float(yaw),full_lift_precheck_knots=13,approach_and_compensated_lift_and_place_checked=True,private_only=True,candidate_failures=failed)
                return base,float(base[2]) if getattr(self,'search_front_stations',False) else 0.
            except Exception as exc:failed.append(dict(base=base.tolist(),error=str(exc)))
        raise NativeTaskFault(('fixed_base_sample_path_unavailable:' if fixed is not None else 'fast_registered_front_station_candidates_exhausted:')+str(failed[-3:]))

    def timed_move(self,goals,frames,*,require=()):
        starts={s:self.tcp(s) for s in goals}
        for k in range(1,frames+1):
            u=smooth5(k/frames)
            targets={s:(starts[s][0]+u*(np.asarray(p)-starts[s][0]),R) for s,(p,R) in goals.items()}
            self.send_timed_target(self.solve(targets));self.hold(1,require=require)

    def send_timed_target(self,target):
        target=np.asarray(target,float);previous=self.r.command.copy();limited=target.copy();arms=np.r_[0:7,8:15]
        delta=target[arms]-previous[arms];scale=min(1.,.075/max(float(abs(delta).max()),1e-12))
        limited[arms]=previous[arms]+scale*delta
        if not np.allclose(target[arms],limited[arms],atol=1e-10):
            self.r.event('fast_joint_target_rate_limited',raw_ik_target=target.tolist(),submitted_mobile19=limited.tolist(),
                reference_real_client_velocity_rad_s=1.5,control_dt=.05,coordinated_arm_progress=scale)
        self.r.command=limited

    def tray_motion(self,target_z,frames,*,stop_on_support=False):
        from scipy.spatial.transform import Rotation
        initial=self.obs()['tray_pose'][0].copy();start=initial[:3];target=start.copy();target[2]=target_z
        yaw=Rotation.from_euler('z',self.r.yaw(initial[3:])).as_matrix();supported=False
        starts={side:self.tcp(side) for side in ('left','right')}
        self.r.event('fast_continuous_pose_reference',lift_pitch_compensation_rad=0.,
            compensation_source='removed_unstable_fixed_pitch_feedforward',joint_command_velocity_reference_rad_s=1.5)
        for k in range(1,frames+1):
            if not supported:
                u=smooth5(k/frames);correction=np.eye(3)
                center=start+u*(target-start)
                goals={side:(center+correction@(p-start),correction@R) for side,(p,R) in starts.items()}
                self.send_timed_target(self.solve(goals))
            obs=self.hold(1,require=('left','right'))
            if stop_on_support:
                table_z=float(self.r.context['center_world'][2]+self.r.context['dimensions_m'][2])
                supported=supported or (obs['table_force'][0]>.01 and obs['tray_pose'][0,2]-table_z<=.02)

    def begin_timed(self,prompt):
        self.o.action=dict(prompt=prompt,start=self.r.frames,tray_id='tray_0',cycle_id=0)
        self.r.event('fast_action_start',**self.o.action)
        return self.r.frames

    def finish_timed(self,prompt,start,passed,**evidence):
        span=dict(prompt=prompt,start=start,end=self.r.frames,frames=self.r.frames-start,
            simulation_seconds=(self.r.frames-start)/20,target_seconds=3.,passed=bool(passed),**evidence)
        self.spans.append(span);self.r.event('fast_action_endpoint',**span);self.o.action=None
        self.r.write('fast_actions.json',self.spans)
        if not passed:raise NativeTaskFault('fast_physical_endpoint_failed:'+prompt)

    def run(self):
        self.prepare_pick()
        self.pick()
        self.place()
        return self.obs()

    def prepare_pick(self):
        self.r.command[[7,15]]=.08
        self.hold(20);self.r.context=self.table_for(self.obs()['tray_pose'][0,:3])
        start_preparation=self.r.frames;base,face=self.choose_station(0,self.r.context)
        self.navigate(base);self.r.manipulating=True
        goals=self.goals(0,face)
        self.move({s:(p+[0,0,.12],R) for s,(p,R) in goals.items()},openings=dict(left=.08,right=.08),cartesian=False)
        self.hold(5);self.r.event('fast_preposition_complete',frames=self.r.frames-start_preparation,
            simulation_seconds=(self.r.frames-start_preparation)/20,excluded_from_three_second_motion=True,
            includes_base_station_and_ready_arm_approach=True,base_world=base.tolist())
        self.pick_goals=goals

    def pick(self):
        goals=self.pick_goals
        bottom=float(self.obs()['tray_pose'][0,2]);start=self.begin_timed('Pick up the tray')
        self.timed_move(goals,20)
        # A bounded ramp avoids the old 80mm -> zero step and maintains a
        # modest preload on the existing high-friction pads instead of crushing.
        opening=self.r.command[[7,15]].copy()
        preload=float(getattr(self,'gripper_preload_target_m',.012))
        if not 0<=preload<=.08:raise ValueError('preload_outside_existing_gripper_range')
        for k in range(1,9):
            self.r.command[[7,15]]=opening+(np.array([preload,preload])-opening)*(k/8)
            self.hold(1)
        settling=2 if getattr(self,'align_pad_normal',False) else 0
        if settling:self.hold(settling)
        self.r.event('fast_gripper_preload',target_opening_m=preload,closing_frames=8,settling_frames=settling,
            actual_opening_m=self.obs()['state'][[7,15]].tolist(),finger_force_n=self.obs()['finger_force'][0].tolist(),
            source_pad_friction=1.2,real_material_calibration=False)
        contact=self.obs();opposed=bool(np.all(contact['finger_force'][0]>.5) and np.prod(contact['long_edge_sign'][0])==-1)
        if not opposed:raise NativeTaskFault('fast_opposed_long_edges_not_acquired')
        self.held.update(('left','right'))
        self.tray_motion(self.obs()['tray_pose'][0,2]+float(getattr(self,'lift_height_m',.18)),26)
        self.hold(6-settling,require=('left','right'));obs=self.obs();lift=float(obs['tray_pose'][0,2]-bottom)
        passed=(np.all(obs['finger_force'][0]>.5) and np.prod(obs['long_edge_sign'][0])==-1 and obs['table_force'][0]<=.01 and lift>=.02)
        self.finish_timed('Pick up the tray',start,passed,actual_lift_m=lift,opposed_long_edges=bool(np.prod(obs['long_edge_sign'][0])==-1),
            measured_finger_force_n=obs['finger_force'][0].tolist(),table_force_n=float(obs['table_force'][0]))
    def place(self):
        # This method consumes live feedback. It never substitutes a canonical
        # held posture or resets a tray to an airborne pose.
        obs=self.obs()
        if not (np.all(obs['finger_force'][0]>.5) and np.prod(obs['long_edge_sign'][0])==-1 and obs['table_force'][0]<=.01):
            raise NativeTaskFault('place_initial_actual_opposed_hold_missing')
        self.held.update(('left','right'))
        self.r.write('place_initial_state.json',dict(frame=self.r.frames,state=obs['state'].tolist(),
            tray_pose=obs['tray_pose'][0].tolist(),finger_force_n=obs['finger_force'][0].tolist(),
            table_force_n=float(obs['table_force'][0]),source='preceding_expert_pick_physical_continuation',
            reset_between_pick_and_place=False,model_executed=False))
        start=self.begin_timed('Place the tray');height=float(self.r.context['center_world'][2]+self.r.context['dimensions_m'][2])
        self.tray_motion(height+.004,28,stop_on_support=True)
        gap=float(self.obs()['tray_pose'][0,2]-height)
        if gap>.02:raise NativeTaskFault('fast_release_above_authorized_2cm')
        opening=self.r.command[[7,15]].copy();self.held.clear()
        for k in range(1,9):
            self.r.command[[7,15]]=opening+(np.array([.08,.08])-opening)*(k/8)
            self.hold(1)
        self.timed_move({s:(self.tcp(s)[0]+[0,0,.12],self.tcp(s)[1]) for s in ('left','right')},14)
        stable=0;previous=self.obs()['tray_pose'][0,:3].copy()
        for _ in range(10):
            obs=self.hold(1);speed=float(np.linalg.norm(obs['tray_pose'][0,:3]-previous)*20);previous=obs['tray_pose'][0,:3].copy()
            stable=stable+1 if obs['table_force'][0]>.01 and speed<.01 and np.all(obs['finger_force'][0]<=.5) else 0
        passed=(stable>=10 and obs['boundary_ok'][0] and obs['axis_error_rad'][0]<=np.deg2rad(15))
        self.finish_timed('Place the tray',start,passed,actual_release_gap_m=gap,stable_support_frames=stable,
            measured_finger_force_n=obs['finger_force'][0].tolist(),table_force_n=float(obs['table_force'][0]),
            actual_place_axis_error_rad=float(obs['axis_error_rad'][0]))
        return self.obs()
