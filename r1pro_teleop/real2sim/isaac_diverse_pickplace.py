"""Expert-only supported preparation for diverse episode-fixed Pick/Place.

Reuses the verified bilateral core. A single hand may move/turn a supported
tray before the bilateral lift. This module is not a model execution fallback.
"""
import math
import numpy as np
from scipy.spatial.transform import Rotation
from .isaac_fast_pickplace import FastPickPlace, smooth5
from .isaac_three_tray_observer import NativeTaskFault


def supported_arc_goal(start_center,target_center,tcp_start,delta,u,pitch_delta,pad_offset):
    """Rotate the pad center with the tray while changing wrist pitch about
    the pad normal. Do not rotate a TCP offset into the contact surface.
    """
    p,R=tcp_start
    rot=Rotation.from_euler('z',delta*u).as_matrix()
    orientation=rot@R@Rotation.from_euler('y',pitch_delta*u).as_matrix()
    center=np.asarray(start_center)+u*(np.asarray(target_center)-start_center)
    contact=center+rot@(p+R@pad_offset-start_center)
    return contact-orientation@pad_offset,orientation


def bounded_planar_correction(previous,error,limit_m=.02):
    """Leaky, bounded command correction, not an acceptance tolerance.

    No vertical correction and no accumulated demand beyond 2 cm. This
    prevents a stalled high-friction contact winding up a large TCP offset.
    """
    correction=.9*np.asarray(previous,float)+.35*np.asarray(error,float)
    correction=correction.copy();correction[2]=0.
    length=np.linalg.norm(correction[:2])
    if length>limit_m:correction*=limit_m/length
    return correction


def supported_center_for_yaw(center,vertices,yaw,table,tolerance=.05):
    """Project a reference center into the existing tabletop boundary gate.

    Uses actual collision vertices. No live pose or acceptance gate is changed.
    """
    table_R=Rotation.from_euler('z',float(table['yaw_world'])).as_matrix()[:2,:2]
    offset=(np.asarray(vertices)@Rotation.from_euler('z',yaw).as_matrix().T)[:,:2]@table_R
    half=np.asarray(table['dimensions_m'][:2])/2+tolerance
    low=-half-offset.min(0);high=half-offset.max(0)
    if np.any(low>high):raise NativeTaskFault('registered_supported_rotation_footprint_unavailable')
    local=(np.asarray(center[:2])-table['center_world'][:2])@table_R
    out=np.asarray(center,float).copy()
    out[:2]=np.asarray(table['center_world'][:2])+np.clip(local,low,high)@table_R.T
    return out


def supported_yaw_reference(actual,target,frame,max_lead=.12):
    """Ramp a bounded angular tracking demand to overcome static friction.

    This is a control reference, not a faster-than-physics pose update.
    """
    remaining=math.atan2(math.sin(target-actual),math.cos(target-actual))
    lead=min(max_lead,.01*max(1,frame))
    return actual+float(np.clip(remaining,-lead,lead)),remaining


def compliant_long_axis_center(target,actual,table):
    """Permit natural planar travel along the tabletop's longer dimension.

    Narrow-axis centering remains controlled; complete footprint projection
    is still applied afterwards with the unchanged boundary tolerance.
    """
    R=Rotation.from_euler('z',float(table['yaw_world'])).as_matrix()[:2,:2]
    origin=np.asarray(table['center_world'][:2]);local=(np.asarray(target[:2])-origin)@R
    measured=(np.asarray(actual[:2])-origin)@R
    axis=int(np.argmax(table['dimensions_m'][:2]));local[axis]=measured[axis]
    result=np.asarray(target,float).copy();result[:2]=origin+local@R.T
    return result


class DiversePickPlace(FastPickPlace):
    def prepare_pick(self):
        self.preparation_start = None
        self.r.command[[7,15]]=.08
        self.hold(20)
        self.r.context=self.table_for(self.obs()['tray_pose'][0,:3])
        fixed=getattr(self,'fixed_base_world',None)
        direct_error=None
        if fixed is None:
            if not getattr(self,'search_front_stations',False):
                raise ValueError('diverse_collection_station_or_front_search_required')
            try:
                fixed,_=self.choose_station(0,self.r.context)
            except NativeTaskFault as exc:
                # Reuse the old acquisition station search for the supported
                # preparation; do not call finite direct-search exhaustion
                # global task unreachability.
                direct_error=str(exc)
                fixed=self.choose_supported_station()
            self.fixed_base_world=np.asarray(fixed,float).tolist()
        self.r.write('episode_station.json',dict(base_world=np.asarray(fixed,float).tolist(),
            initial_tray_pose=self.obs()['tray_pose'][0].tolist(),
            table_id=self.r.context['table_id'],selection_before_action=True,
            target_fixed_during_actions=True,private_direct_search_error=direct_error,
            model_executed=False))
        if getattr(self,'base_initialized_before_episode',False):
            observed=self.obs()
            actual=np.r_[observed['robot_position'][:2],observed['robot_yaw']]
            if not np.allclose(actual,np.asarray(fixed,float),atol=.05):
                raise NativeTaskFault('initialized_front_station_mismatch')
        else:
            self.navigate(np.asarray(fixed,float))
        self.r.manipulating=True
        try:
            self.choose_station(0,self.r.context)
        except NativeTaskFault as exc:
            if not str(exc).startswith('fixed_base_sample_path_unavailable:'):
                raise
            if getattr(self,'direct_grasp_only',False):
                raise
            self.preparation_start=self.r.frames
            self.o.action=dict(prompt='Pick up the tray',start=self.r.frames,tray_id='tray_0',cycle_id=0)
            self.r.event('diverse_supported_preadjustment_begin',included_in_action='Pick up the tray',
                         actual_initial_tray_pose=self.obs()['tray_pose'][0].tolist(),direct_grasp_error=str(exc))
            self.supported_preadjustment()
            if getattr(self,'reset_arms_after_preadjustment',False):
                self.reset_released_arms()
            # Actual resulting state, not the target or predicted pose.
            self.choose_station(0,self.r.context)
        goals=self.goals(0,float(self.fixed_base_world[2]))
        self.move({s:(p+[0,0,.12],R) for s,(p,R) in goals.items()},
                  openings=dict(left=.08,right=.08),cartesian=False)
        self.hold(5);self.pick_goals=goals

    def reset_released_arms(self):
        """Physical arm return only; preserve actual tray and base state."""
        if self.held:raise NativeTaskFault('arm_reset_requires_released_tray')
        self.stable_support()
        before=self.obs()['tray_pose'][0].copy();base=self.r.command[16:].copy()
        target=self.r.command.copy();target[:16]=self.initial[:16];target[[7,15]]=.08
        self.r.event('released_arm_reset_begin',included_in_action='Pick up the tray',
                     tray_pose=before.tolist(),base_command=base.tolist(),live_pose_reset=False)
        self.joints(target)
        if not np.array_equal(self.r.command[16:],base):
            raise NativeTaskFault('arm_reset_changed_base_command')
        self.stable_support()
        self.r.event('released_arm_reset_complete',actual_state=self.obs()['state'].tolist(),
                     actual_tray_pose=self.obs()['tray_pose'][0].tolist(),live_pose_reset=False)

    def choose_supported_station(self):
        """A preparation station needs one arm, not an already solved pair."""
        from r1pro_teleop.single_tray_3table.observer import table_front_region_violation
        pose=self.obs()['tray_pose'][0];table=self.r.context
        face=np.pi if table['table_id']=='rear' else 0.
        forward=np.array([np.cos(face),np.sin(face)]);left=np.array([-forward[1],forward[0]])
        registry=[];previous=getattr(self,'fixed_base_world',None)
        for distance in (.55,.58,.60,.50,.62,.65,.68):
            for lateral in (0.,-.035,.035,-.10,.10,-.20,.20):
                base=np.r_[pose[:2]-distance*forward+lateral*left,face]
                if table_front_region_violation(table,np.r_[base[:2],0.]):continue
                self.fixed_base_world=base.tolist()
                row=dict(base_world=base.tolist(),private_only=True)
                try:
                    sides=self.supported_preadjustment(plan_only=True,base_world=base)
                    row.update(path_available=True,candidate_sides=sides);registry.append(row)
                    self.r.write('supported_station_registry.json',registry)
                    return base
                except NativeTaskFault as exc:
                    row.update(path_available=False,error=str(exc));registry.append(row)
                    self.r.write('supported_station_registry.json',registry)
                finally:self.fixed_base_world=previous
        raise NativeTaskFault('registered_single_arm_preparation_station_candidates_exhausted')

    def supported_preadjustment(self,*,plan_only=False,base_world=None):
        initial=self.obs()['tray_pose'][0].copy()
        yaw=self.r.yaw(initial[3:]);face=float(self.fixed_base_world[2])
        # Rectangular symmetry: choose the nearest axis parallel to forward.
        delta=.5*math.atan2(math.sin(2*(face-yaw)),math.cos(2*(face-yaw)))
        if getattr(self,'reset_arms_after_preadjustment',False) and abs(delta)>np.deg2rad(15):
            # Aim inside the existing 15-degree final axis gate. This is a
            # reference, not a relaxed acceptance threshold or a pose reset.
            delta-=math.copysign(np.deg2rad(14),delta)
        # Keep the center at a proven forward reach distance, staying on the
        # registered table. This is a reference only; no live pose is written.
        forward=np.array([math.cos(face),math.sin(face),0.])
        target=initial[:3].copy()
        # Rotate near the initial center instead of translating toward an
        # arbitrary base-relative point while simultaneously turning.
        vertices=getattr(self.r,'boundary_footprints',{}).get('tray_0')
        if vertices is None:raise NativeTaskFault('native_collision_footprint_required_for_supported_plan')
        for angle in np.linspace(yaw,yaw+delta,61):
            target=supported_center_for_yaw(target,vertices,angle,self.r.context)
        candidates=[]; registry=[]
        original_pitch=self.grasp_pitch_degrees
        original_along=getattr(self,'contact_along_edge_offset_m',0.)
        try:
            # This finite geometry search changes neither long-edge identity
            # nor the fixed base. It removes an accidental midpoint-only and
            # single-wrist-pitch restriction from the preparation planner.
            for pitch in (-30.,0.,-10.):
                for along in (0.,.12,-.12):
                    self.grasp_pitch_degrees=pitch;self.contact_along_edge_offset_m=along
                    goals=self.goals(0,face)
                    offsets=next((e['offset_local_m'] for e in getattr(self.r,'events',[])
                                  if e.get('event')=='native_pad_center_to_tcp_translation'),None)
                    for side in ('left','right'):
                        p,R=goals[side]
                        row=dict(side=side,pitch_degrees=pitch,final_pitch_degrees=pitch,
                                 long_edge_offset_m=along,private_only=True,phase='approach')
                        try:
                            for h in np.linspace(.12,0.,9):self.solve({side:(p+[0,0,h],R)},base_world=base_world)
                            if offsets is None:raise NativeTaskFault('source_pad_offset_evidence_missing')
                            # A high-friction grasp transmits wrist pitch to the
                            # tray. Keep acquisition pitch during the planar arc;
                            # bilateral grasp is replanned after release.
                            pad_offset=np.asarray(offsets[side]);pitch_delta=0.
                            row['phase']='supported_arc'
                            for u in np.linspace(0.,1.,13):
                                center=supported_center_for_yaw(target,vertices,yaw+delta*u,self.r.context)
                                self.solve({side:supported_arc_goal(initial[:3],center,(p,R),delta*u,1.,pitch_delta,pad_offset)},base_world=base_world)
                            candidates.append((side,p.copy(),R.copy(),pitch_delta,pad_offset));row['path_available']=True
                        except Exception as exc:
                            row.update(path_available=False,error=str(exc))
                        registry.append(row)
                        if len(candidates)>=3:break
                    if len(candidates)>=3:break
                if len(candidates)>=3:break
        finally:
            self.grasp_pitch_degrees=original_pitch;self.contact_along_edge_offset_m=original_along
            self.r.write('preadjustment_private_candidate_registry.json',registry)
        if not candidates:raise NativeTaskFault('diverse_single_arm_preadjustment_paths_unavailable')
        if plan_only:return [c[0] for c in candidates]
        side,p,R,pitch_delta,pad_offset=candidates[0];index=0 if side=='left' else 1;opening_index=7 if side=='left' else 15
        self.r.event('diverse_preadjustment_registered_candidate',side=side,
            target_xy_m=target[:2].tolist(),requested_yaw_delta_rad=delta,
            candidate_sides=[c[0] for c in candidates],private_only=True)
        self.move({side:(p+[0,0,.12],R)},openings={side:.08},cartesian=False)
        self.move({side:(p,R)})
        start_width=float(self.r.command[opening_index])
        for k in range(1,9):
            self.r.command[opening_index]=start_width+(.008-start_width)*(k/8)
            self.hold(1)
        self.hold(2)
        observed=self.obs()
        if observed['finger_force'][0,index]<=.5 or observed['long_edge_sign'][0,index]==0:
            raise NativeTaskFault('diverse_single_arm_actual_long_edge_grasp_missing')
        self.held.add(side)
        actual_start=self.obs()['tray_pose'][0].copy();tcp_start=self.tcp(side)
        steps=max(80,math.ceil(abs(delta)/.01)*4)
        support_missing=0;centering_integral=np.zeros(3)
        for k in range(1,steps+21):
            current=self.obs()['tray_pose'][0]
            actual_yaw=self.r.yaw(current[3:])
            if getattr(self,'reset_arms_after_preadjustment',False) and k%5==0:
                # Use the existing Place axis gate and actual bilateral path,
                # not an unnecessarily exact zero-yaw preparation target.
                if self.obs()['axis_error_rad'][0]<=np.deg2rad(15):
                    try:self.choose_station(0,self.r.context)
                    except NativeTaskFault:pass
                    else:
                        self.r.event('preadjustment_actual_bilateral_path_ready',
                                     actual_tray_pose=current.tolist(),existing_axis_gate_degrees=15)
                        break
            next_yaw,remaining=supported_yaw_reference(actual_yaw,yaw+delta,k)
            desired_center=supported_center_for_yaw(
                compliant_long_axis_center(target,current[:3],self.r.context),
                vertices,next_yaw,self.r.context)
            # Real yaw controls reference progress; do not run the planned
            # circle ahead of a high-friction tray that has not yet rotated.
            angle=math.atan2(math.sin(next_yaw-self.r.yaw(actual_start[3:])),math.cos(next_yaw-self.r.yaw(actual_start[3:])))
            goal=supported_arc_goal(actual_start[:3],desired_center,tcp_start,angle,1.,0.,pad_offset)
            # Correct the *commanded* pad position from real tray feedback.
            # Never move/teleport the observed tray; vertical support is left
            # entirely to PhysX. The existing arm target rate limit applies.
            error=desired_center-self.obs()['tray_pose'][0,:3];error[2]=0.
            centering_integral=bounded_planar_correction(centering_integral,error)
            corrected=supported_center_for_yaw(desired_center+centering_integral,vertices,next_yaw,self.r.context)
            goal=(goal[0]+corrected-desired_center,goal[1])
            if k%10==0:self.r.event('diverse_actual_tray_center_feedback',
                desired_center_m=desired_center.tolist(),actual_center_m=self.obs()['tray_pose'][0,:3].tolist(),
                raw_integral_command_correction_m=centering_integral.tolist(),pose_reset=False,
                actual_yaw_rad=float(actual_yaw),next_reference_yaw_rad=float(next_yaw),remaining_yaw_rad=float(remaining))
            self.send_timed_target(self.solve({side:goal}))
            observed=self.hold(1,require=(side,))
            support_missing=0 if observed['table_force'][0]>.01 else support_missing+1
            if support_missing>6:raise NativeTaskFault('diverse_preadjustment_table_support_lost_over_0p3s')
            if not observed['boundary_ok'][0]:raise NativeTaskFault('diverse_preadjustment_boundary_failed')
            if abs(remaining)<.01 and np.linalg.norm(error[:2])<.005:break
        width=float(self.r.command[opening_index])
        for k in range(1,9):
            self.r.command[opening_index]=width+(.08-width)*(k/8);self.hold(1)
        self.held.discard(side);self.stable_support()
        self.move({side:(self.tcp(side)[0]+[0,0,.12],self.tcp(side)[1])})
        end=self.obs()['tray_pose'][0].copy()
        self.r.event('diverse_preadjustment_actual_outcome',side=side,
            actual_start_pose=actual_start.tolist(),actual_end_pose=end.tolist(),
            actual_translation_m=(end[:3]-actual_start[:3]).tolist(),
            actual_yaw_delta_rad=float(math.atan2(math.sin(self.r.yaw(end[3:])-self.r.yaw(actual_start[3:])),
                                                math.cos(self.r.yaw(end[3:])-self.r.yaw(actual_start[3:])))),
            live_pose_reset=False,requires_actual_bilateral_path_recheck=True)

    def begin_timed(self,prompt):
        self.core_start=self.r.frames
        start=super().begin_timed(prompt)
        return self.preparation_start if prompt=='Pick up the tray' and self.preparation_start is not None else start

    def finish_timed(self,prompt,start,passed,**evidence):
        evidence.update(core_motion_start=self.core_start,core_motion_frames=self.r.frames-self.core_start,
                        core_motion_seconds=(self.r.frames-self.core_start)/20,
                        includes_supported_preadjustment=prompt=='Pick up the tray' and self.preparation_start is not None)
        super().finish_timed(prompt,start,passed,**evidence)
