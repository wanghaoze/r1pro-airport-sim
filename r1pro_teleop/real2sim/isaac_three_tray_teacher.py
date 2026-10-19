"""PhysX feedback teacher reusing the old opposed-long-rim IK/pose provider.

This class is expert collection only. It is never imported by policy execution.
All physical motion goes through NativeRuntime.tick, never a planning simulator.
"""
import math
import time
from types import SimpleNamespace
import numpy as np
from scipy.spatial.transform import Rotation, Slerp
from r1pro_teleop.single_tray_lab.control import SingleTrayController, ControlProfile
from r1pro_teleop.airport_fsm.rim_affordances import rim_pairs
from r1pro_teleop.airport_fsm.geometry import Geometry
from .isaac_three_tray_observer import NativeTaskFault
from .three_tray_migration import PROMPTS


def wrap(x):return float(np.arctan2(np.sin(x),np.cos(x)))


class NativeTeacher:
    def __init__(self,runtime,observer,*,place_flush_reserve_m=.042):
        self.r=runtime;self.o=observer;runtime.observer=observer
        self.held=set();self.active_tray=None;self.initial=runtime.command.copy()
        self.profile=ControlProfile()
        self.planner=SimpleNamespace(mj=runtime.mj,m=runtime.model,d=runtime.shadow,
            sim=SimpleNamespace(arms={s:[runtime.model.joint(f'{s}_arm_joint{i}').id for i in range(1,8)]
                for s in ('left','right')},target=runtime.command[:16].copy()),p=self.profile,holding_sides=self.held,
            private_incremental_command_prediction=True)
        self.g=Geometry(runtime.parent)
        self.mapping=None
        self.place_flush_reserve_m=float(place_flush_reserve_m)
        if not 0<=self.place_flush_reserve_m<=.05:raise ValueError('place_reserve_outside_authorized_position_tolerance')

    def obs(self):return self.r.observation()
    def tcp(self,side):
        self.r.sync_planner();site=self.r.shadow.site(side+'_tcp')
        return site.xpos.copy(),site.xmat.reshape(3,3).copy()

    def solve(self,goals,*,base_world=None):
        self.r.sync_planner();saved=self.r.shadow.qpos.copy()
        self.planner.sim.target=self.r.command[:16].copy()
        try:
            if base_world is not None:
                offsets=np.r_[np.asarray(base_world)[:2]-self.r.base_origin[:2],wrap(base_world[2]-self.r.base_origin[2])]
                for name,value in zip(('agent_base_x','agent_base_y','agent_base_yaw'),offsets):
                    self.r.shadow.qpos[self.r.model.jnt_qposadr[self.r.model.joint(name).id]]=self.r.source_base_q[name]+value
                self.r.mj.mj_forward(self.r.model,self.r.shadow)
            target=self.r.command.copy()
            for side,(position,rotation) in goals.items():
                found=SingleTrayController._ik_candidates(self.planner,side,position,rotation,warm_only=True)
                if not found:found=SingleTrayController._ik_candidates(self.planner,side,position,rotation)
                offset=0 if side=='left' else 8;target[offset:offset+7]=found[0][1]
            return target
        finally:self.r.shadow.qpos[:]=saved

    def hold(self,frames,*,require=()):
        result=None
        for _ in range(frames):
            result=self.r.tick()
            if require and any(result['finger_force'][self.active_tray,0 if s=='left' else 1]<=.5 for s in require):
                # Use the existing 0.3s transient window; do not fault on one sample.
                self.missing=getattr(self,'missing',0)+1
                if self.missing>6:raise NativeTaskFault('native_grasp_contact_lost_over_0p3s')
            else:self.missing=0
        return result

    def joints(self,target,*,minimum_frames=10,require=()):
        start=self.r.command.copy();target=np.asarray(target,float)
        count=max(minimum_frames,int(math.ceil(np.max(abs(target[:16]-start[:16]))/.035)))
        for u in np.linspace(1/count,1,count):
            smooth=u*u*(3-2*u);self.r.command=start+(target-start)*smooth;self.hold(1,require=require)
        return self.hold(3,require=require)

    def move(self,goals,*,openings=None,require=(),cartesian=True):
        if openings:
            self.r.command=self.r.command.copy()
            for side,value in openings.items():self.r.command[7 if side=='left' else 15]=value
        starts={s:self.tcp(s) for s in goals}
        distance=max(np.linalg.norm(np.asarray(p)-starts[s][0]) for s,(p,R) in goals.items())
        count=max(1,int(math.ceil(distance/.015))) if cartesian else 1
        interpolators={s:Slerp([0,1],Rotation.from_matrix(np.array([starts[s][1],R]))) for s,(p,R) in goals.items()}
        for u in np.linspace(1/count,1,count):
            sub={s:(starts[s][0]+u*(np.asarray(p)-starts[s][0]),interpolators[s]([u]).as_matrix()[0]) for s,(p,R) in goals.items()}
            target=self.solve(sub);self.joints(target,minimum_frames=3 if count>1 else 10,require=require)
        errors={s:float(np.linalg.norm(self.tcp(s)[0]-p)) for s,(p,R) in goals.items()}
        self.r.event('native_cartesian_endpoint',errors_m=errors,source='actual_joint_feedback_source_fk',live_pose_corrected=False)
        if max(errors.values())>.05:raise NativeTaskFault('native_tcp_tracking_error_over_authorized_5cm')
        return self.obs()

    def navigate(self,base_world,*,require=()):
        self.r.manipulating=False;start=self.obs();begin=np.r_[start['robot_position'][:2],start['robot_yaw']]
        end=np.asarray(base_world,float);delta=end-begin;delta[2]=wrap(delta[2])
        count=max(20,int(math.ceil(max(np.linalg.norm(delta[:2])/.12,abs(delta[2])/.24)*20)))
        old=self.r.command.copy()
        for u in np.linspace(1/count,1,count):
            smooth=u*u*(3-2*u);world=begin+smooth*delta
            self.r.command=old.copy();self.r.command[16:18]=world[:2]-self.r.base_origin[:2]
            self.r.command[18]=wrap(world[2]-self.r.base_origin[2]);self.hold(1,require=require)
        result=self.hold(10,require=require)
        error=np.linalg.norm(result['robot_position'][:2]-end[:2])
        if error>.05:raise NativeTaskFault('native_base_endpoint_error_over_5cm')
        self.r.event('native_navigation_complete',actual_position=result['robot_position'].tolist(),goal=end.tolist(),error_m=float(error))
        return result

    def goals(self,tray,face,*,pitch_deg=-30.):
        obs=self.obs();pose=obs['tray_pose'][tray];yaw=self.r.yaw(pose[3:])
        pair=next(p for p in rim_pairs(self.r.size[tray],yaw,face,inset=.01)
            if p.axis==('width' if self.r.size[tray,0]>=self.r.size[tray,1] else 'length'))
        center=pose[:3].copy()
        # Legacy successful source uses 75 mm at pickup; 96 mm belongs to
        # the separate pushing template. Do not conflate the two primitives.
        center[2]+=.096 if self.o.action and self.o.action['prompt']==PROMPTS[2] else .075
        return pair.goals(center,pitch_deg=pitch_deg,roll_deg=10.)

    def choose_station(self,tray,table,*,position=None,target=False):
        obs=self.obs();pose=obs['tray_pose'][tray];point=pose[:3] if position is None else np.asarray(position)
        face=math.pi if table['table_id']=='rear' else 0.
        goals=self.goals(tray,face)
        if position is not None:
            delta=point-pose[:3];goals={s:(p+delta,R) for s,(p,R) in goals.items()}
            if target:
                # Preserve the measured two-hand grasp through carry/descent.
                # A nominal rim template at carry height is not a preview of
                # the actual low placing path (demo05 exposed that mismatch).
                goals={s:(self.tcp(s)[0]+delta,self.tcp(s)[1]) for s in ('left','right')}
        failures=[]
        # Preserve the proven source/target stations before trying any fallback.
        distances=(.55,.52,.58,.50,.60,.62,.65) if target else (.58,.60,.55,.62,.65,.68)
        lateral_offsets=(-.10,-.08,-.12,0.) if target else (0.,.035,-.035)
        stations=[(distance,lateral,face,False) for distance in distances for lateral in lateral_offsets]
        if not target:
            tray_yaw=self.r.yaw(pose[3:])
            aligned=face+.5*wrap(2*(tray_yaw-face))
            stations += [(distance,lateral,angle,True)
                for angle in (aligned,face-.24,face+.24,face-.4,face+.4)
                for distance in (.55,.50,.60,.65,.45)
                for lateral in (0.,-.10,-.20,-.25,.10,.20)]
        for distance,lateral,angle,descent_check in stations:
            base=np.r_[point[:2]-distance*np.array([math.cos(face),math.sin(face)])+lateral*np.array([-math.sin(face),math.cos(face)]),angle]
            from r1pro_teleop.single_tray_3table.observer import table_front_region_violation
            if table_front_region_violation(table,np.r_[base[:2],0.]):continue
            try:
                self.solve(goals,base_world=base)
                if descent_check:
                    for height in np.linspace(.12,0.,9):
                        self.solve({side:(p+[0,0,height],R) for side,(p,R) in goals.items()},base_world=base)
                if target:
                    low=float(table['center_world'][2]+table['dimensions_m'][2]+.014)
                    for z in np.linspace(point[2],low,14):
                        dz=np.array([0.,0.,z-point[2]])
                        self.solve({s:(p+dz,R) for s,(p,R) in goals.items()},base_world=base)
                self.r.event('native_joint_station_selected',tray_id=f'tray_{tray}',table_id=table['table_id'],
                    base_world=base.tolist(),candidate_failures=failures,
                    measured_grasp_descent_knots=14 if target else (9 if descent_check else 0),
                    source_yaw_search_fallback=descent_check,
                    qualified='private_IK_only_actual_contact_required')
                return base,face
            except Exception as e:failures.append(dict(base=base.tolist(),error=str(e)))
        raise NativeTaskFault('registered_front_station_search_exhausted:'+str(failures[-3:]))

    def table_for(self,point):
        candidates=[]
        for t in self.r.tables:
            R=Rotation.from_euler('z',t['yaw_world']).as_matrix();local=R.T@(np.asarray(point)-np.asarray(t['center_world']))
            if np.all(abs(local[:2])<=np.asarray(t['dimensions_m'][:2])/2+.05):candidates.append(t)
        if not candidates:raise NativeTaskFault('native_tray_has_no_registered_table')
        return min(candidates,key=lambda t:np.linalg.norm(np.asarray(t['center_world'])[:2]-point[:2]))

    def acquire(self,sides,face):
        goals={s:g for s,g in self.goals(self.active_tray,face).items() if s in sides}
        opening=.1
        if tuple(sides)==('left',) and self.o.action and self.o.action['prompt']==PROMPTS[2]:
            opening=self.handover_opening(goals['left'])
        high={s:(p+np.array([0,0,.12]),R) for s,(p,R) in goals.items()}
        self.move(high,openings={s:opening for s in sides},cartesian=False,require=tuple(self.held))
        self.move(goals,require=tuple(self.held));self.r.manipulating=True
        for s in sides:self.r.command[7 if s=='left' else 15]=0.
        stable=0
        for _ in range(100):
            obs=self.hold(1,require=tuple(self.held))
            stable=stable+1 if all(obs['finger_force'][self.active_tray,0 if s=='left' else 1]>.5 for s in sides) else 0
            if stable>=3:
                self.held.update(sides);self.r.event('native_grasp_stable',sides=list(sides),tray_id=f'tray_{self.active_tray}',
                    measured_force=obs['finger_force'][self.active_tray].tolist(),long_edge_sign=obs['long_edge_sign'][self.active_tray].tolist())
                return obs
        raise NativeTaskFault('native_grasp_contact_not_acquired')

    def handover_opening(self,goal):
        """Keep the old rim/pose, avoid opening a finger into the next tray."""
        from .isaac_mobile import mobile_targets
        target=self.solve({'left':goal});self.r.sync_planner();saved=self.r.shadow.qpos.copy()
        neighbors={f'tray_{i}' for i in range(3) if i!=self.active_tray};candidates=[]
        try:
            for width in (.1,.04):
                self.r.shadow.qpos[:]=saved;candidate=target.copy();candidate[7]=width
                for name,value in mobile_targets(candidate).items():
                    self.r.shadow.qpos[self.r.model.jnt_qposadr[self.r.model.joint(name).id]]=value
                self.r.mj.mj_forward(self.r.model,self.r.shadow);depth=0.
                for contact in self.r.shadow.contact:
                    bodies=[self.r.model.body(int(self.r.model.geom_bodyid[g])).name for g in (contact.geom1,contact.geom2)]
                    if any(n.startswith('left_gripper') for n in bodies) and any(n in neighbors for n in bodies):
                        depth=max(depth,-float(contact.dist))
                candidates.append(dict(opening_m=width,predicted_neighbor_penetration_m=depth))
        finally:
            self.r.shadow.qpos[:]=saved;self.r.mj.mj_forward(self.r.model,self.r.shadow)
        selected=min(candidates,key=lambda c:c['predicted_neighbor_penetration_m'])
        self.r.event('native_left_handover_opening_selected',selected=selected,candidates=candidates,
            evidence='private_source_geometry_only_real_contact_still_required',grasp_edge_and_pose_unchanged=True)
        return selected['opening_m']

    def translate_held(self,delta,*,sides=None):
        sides=tuple(self.held) if sides is None else tuple(sides)
        goals={s:(self.tcp(s)[0]+np.asarray(delta),self.tcp(s)[1]) for s in sides}
        return self.move(goals,require=sides)

    def release(self,sides,*,require=(),opening=.1):
        for s in sides:self.r.command[7 if s=='left' else 15]=opening
        self.held.difference_update(sides);stable=0
        for _ in range(100):
            obs=self.hold(1,require=require)
            stable=stable+1 if all(obs['finger_force'][self.active_tray,0 if s=='left' else 1]<=.5 for s in sides) else 0
            if stable>=3:return obs
        raise NativeTaskFault('native_actual_grasp_release_unverified')

    def stable_support(self,*,loaded=False):
        stable=0;previous=self.obs()['tray_pose'][self.active_tray,:3].copy()
        for _ in range(200):
            obs=self.hold(1);position=obs['tray_pose'][self.active_tray,:3]
            speed=np.linalg.norm(position-previous)/.05;previous=position.copy()
            good=(obs['table_force'][self.active_tray]>.01 and speed<.01 and
                (not loaded or obs['payload_on_tray'][self.active_tray] and obs['payload_speed'][self.active_tray]<.01))
            stable=stable+1 if good else 0
            if stable>=10:return obs
        raise NativeTaskFault('native_final_support_not_stable')

    def pick(self,tray,cycle):
        self.active_tray=tray;self.o.begin(PROMPTS[0],self.r.frames,f'tray_{tray}',cycle)
        if cycle:
            # Do not sweep the open arms through the previously loaded tray
            # while tucking. Reuse Place's vertical withdrawal and front retreat
            # before changing arm posture. This remains Pick preparation.
            self.r.manipulating=True
            high={s:(self.tcp(s)[0]+[0,0,.12],self.tcp(s)[1]) for s in ('left','right')}
            self.r.event('native_pick_departure_begin',included_in_action=PROMPTS[0],
                previous_table=self.r.context['table_id'],live_pose_corrected=False)
            self.move(high,openings={'left':.1,'right':.1})
            observed=self.obs()
            self.navigate(np.r_[observed['robot_position'][:2]-.28*observed['robot_forward'][:2],observed['robot_yaw']])
            self.r.event('native_pick_departure_complete',included_in_action=PROMPTS[0])
        self.r.context=self.table_for(self.obs()['tray_pose'][tray,:3]);self.r.manipulating=False
        target=self.initial.copy();target[16:]=self.r.command[16:];self.joints(target)
        base,face=self.choose_station(tray,self.r.context)
        self.navigate(base);self.r.manipulating=True
        # The legacy successful case itself needed supported single-arm
        # separation before joining the second hand. This stays inside Pick.
        poses=self.obs()['tray_pose'];neighbors=[j for j in range(3) if j!=tray and
            np.linalg.norm(poses[j,:2]-poses[tray,:2])<.53]
        if neighbors:
            away=sum((poses[tray,:2]-poses[j,:2] for j in neighbors),np.zeros(2))
            lateral=np.array([-math.sin(face),math.cos(face)])
            signed=float(away@lateral)
            if abs(signed)<1e-6:raise NativeTaskFault('legacy_separation_direction_ambiguous')
            side='left' if signed>0 else 'right'
            self.r.event('legacy_supported_pick_preparation',side=side,neighbor_ids=neighbors,
                target_tray=f'tray_{tray}',included_in_action=PROMPTS[0],requested_displacement_m=.115)
            self.acquire((side,),face)
            start=self.obs()['tray_pose'][tray,:3].copy()
            self.translate_held(np.r_[lateral*(.115 if signed>0 else -.115),0.],sides=(side,))
            actual=self.obs()['tray_pose'][tray,:3]-start
            self.r.event('native_pick_preparation_actual_motion',tray_displacement_m=actual.tolist())
            other='right' if side=='left' else 'left'
            self.acquire((other,),face)
        else:self.acquire(('left','right'),face)
        self.translate_held([0,0,.18]);self.hold(10,require=('left','right'))
        self.o.finish(self.obs(),self.r.frames)

    def place(self,tray,slot,cycle):
        self.o.begin(PROMPTS[1],self.r.frames,f'tray_{tray}',cycle)
        obs=self.obs();source=self.r.context;forward=obs['robot_forward']
        self.r.manipulating=False
        self.navigate(np.r_[obs['robot_position'][:2]-.28*forward[:2],obs['robot_yaw']],require=('left','right'))
        goal=self.g.goals[slot].copy();goal[2]=.801;goal[1]-=self.place_flush_reserve_m
        self.r.event('native_place_push_space_reserved',slot=slot,nominal_goal=self.g.goals[slot].tolist(),
            placement_goal=goal.tolist(),reserve_m=self.place_flush_reserve_m,task_tolerance_changed=False)
        target_table=self.table_for(goal)
        # Turn in the aisle with the existing two-arm grip; no forced tray spin.
        current=self.obs();self.navigate(np.r_[current['robot_position'][:2],0.],require=('left','right'))
        observed=self.obs();target_center=goal.copy();target_center[2]=observed['tray_pose'][tray,2]
        self.r.context=target_table;base,_=self.choose_station(tray,target_table,position=target_center,target=True)
        self.navigate(base,require=('left','right'));self.r.manipulating=True
        delta=goal-self.obs()['tray_pose'][tray,:3];delta[2]=0.;self.translate_held(delta)
        while self.obs()['tray_pose'][tray,2]>.816:
            self.translate_held([0,0,-min(.012,self.obs()['tray_pose'][tray,2]-.814)])
            if self.obs()['table_force'][tray]>.01:break
        self.release(('left','right'));self.stable_support()
        high={s:(self.tcp(s)[0]+[0,0,.12],self.tcp(s)[1]) for s in ('left','right')};self.move(high)
        self.o.finish(self.obs(),self.r.frames,support_stable=True)

    def flush(self,tray,cycle):
        self.r.load_payload(tray,self.o,cycle)
        self.hold(20)  # Excluded environmental settling, before the Flush span.
        self.o.begin(PROMPTS[2],self.r.frames,f'tray_{tray}',cycle)
        self.flush_station(tray)
        self.acquire(('right',),0.);obs=self.obs();self.o.push_stage('right_push',obs,self.r.frames)
        for _ in range(24):
            obs=self.translate_held(obs['robot_left']*.008,sides=('right',))
            right=self.tcp('right')[0];lateral=float((right-obs['robot_position'])@obs['robot_left'])
            if lateral>=-.08 and self.o.cycle['right_actual_push']:break
        else:raise NativeTaskFault('native_right_workspace_handover_not_reached')
        self.o.push_stage('left_acquire',self.obs(),self.r.frames);self.acquire(('left',),0.)
        self.hold(3,require=('left','right'))
        if not self.o.cycle['left_stable_grasp']:raise NativeTaskFault('native_left_handover_unverified')
        self.o.push_stage('right_release',self.obs(),self.r.frames);self.release(('right',),require=('left',))
        self.o.push_stage('left_push',self.obs(),self.r.frames)
        # Retract the open right gripper before translating the left-held tray.
        p,R=self.tcp('right');self.move({'right':(p+np.array([0,-.035,.04]),R)},require=('left',))
        for _ in range(16):
            obs=self.translate_held(self.obs()['robot_left']*.008,sides=('left',))
            if self.o.cycle['actual_tray_left_displacement_m']>=.03:break
        else:raise NativeTaskFault('native_actual_left_tray_motion_below_3cm')
        self.o.push_stage('left_release',self.obs(),self.r.frames)
        # Open only enough to unclamp, withdraw vertically out of neighboring
        # rims, then verify actual release. A full-width opening at rim height
        # can trap the outside finger against another loaded tray (demo11).
        release_opening=min(.1,max(.04,float(self.obs()['state'][7])+.02))
        self.r.command[7]=release_opening;self.held.discard('left');self.hold(3)
        p,R=self.tcp('left');self.move({'left':(p+[0,0,.12],R)})
        self.release(('left',))
        self.r.event('native_flush_release_withdrawal',opening_before_withdrawal_m=release_opening,
            full_opening_after_clearance_m=.1,included_in_action=PROMPTS[2],
            actual_release_verified_after_withdrawal=True)
        self.stable_support(loaded=True);self.o.finish(self.obs(),self.r.frames,support_stable=True)

    def flush_station(self,tray):
        """Search the full right-hand descent, not just a Place endpoint."""
        obs=self.obs();point=obs['tray_pose'][tray,:3];failures=[]
        goals=self.goals(tray,0.)
        candidates=[]
        for distance in (.55,.52,.58,.50,.60,.62):
            # The handover soft bound remains -8 cm. Choose the front station
            # jointly with that bound, instead of consuming tabletop room with
            # avoidable right-hand travel (demo06 measured 5.61 cm).
            for lateral in (-.10,-.12,-.08,0.,-.04,.04):
                for yaw in (0.,-.12,.12,-.20,.20):
                    base=np.array([point[0]-distance,point[1]+lateral,yaw])
                    from r1pro_teleop.single_tray_3table.observer import table_front_region_violation
                    if table_front_region_violation(self.r.context,np.r_[base[:2],0.]):continue
                    left=np.array([-math.sin(yaw),math.cos(yaw)])
                    required=max(0.,-.08-float((goals['right'][0][:2]-base[:2])@left))
                    # A preference, not an additional completion/reachability
                    # gate: preserve proven straight stances when short, search
                    # yaw before consuming occupied neighboring tabletop space.
                    cost=required+.20*abs(yaw)+.1*abs(distance-.55)
                    if yaw==0. and required<=.05:cost=-1.+len(candidates)*1e-5
                    candidates.append((cost,len(candidates),base,required))
        for _,_,base,required in sorted(candidates,key=lambda c:c[:2]):
                previous_held=set(self.held)
                try:
                    # Include both long-rim hand poses and every descent knot.
                    self.solve(goals,base_world=base)
                    p,R=goals['right']
                    for height in np.linspace(.12,0.,13):
                        self.solve({'right':(p+[0,0,height],R)},base_world=base)
                    if base[2]!=0. or required>.05:
                        left=np.array([-math.sin(base[2]),math.cos(base[2]),0.])
                        shift=left*(required+.016)
                        self.held.add('right')
                        for u in np.linspace(0,1,8):self.solve({'right':(p+u*shift,R)},base_world=base)
                        both={s:(p+shift,R) for s,(p,R) in goals.items()}
                        self.solve(both,base_world=base)
                        self.held.discard('right');self.held.add('left')
                        for u in np.linspace(0,1,8):
                            self.solve({'right':(both['right'][0]+u*np.array([0,-.035,.04]),both['right'][1]),'left':both['left']},base_world=base)
                            self.solve({'left':(both['left'][0]+u*.04*left,both['left'][1])},base_world=base)
                    self.r.event('native_flush_station_path_selected',base_world=base.tolist(),
                        right_descent_knots=13,candidate_failures=failures,predicted_right_push_m=required,
                        qualification='private_kinematics_only_native_contact_still_required')
                except Exception as exc:
                    failures.append(dict(base_world=base.tolist(),error=str(exc)));continue
                finally:
                    self.held.clear();self.held.update(previous_held)
                self.navigate(base);self.r.manipulating=True;return
        raise NativeTaskFault('native_flush_front_path_search_exhausted:'+str(failures[-3:]))

    def run(self):
        self.hold(20);self.mapping=self.g.best_mapping(self.obs()['tray_pose'])
        self.r.event('legacy_slot_mapping_reused',slot_to_tray=list(map(int,self.mapping)))
        for slot,tray in enumerate(self.mapping):
            self.pick(int(tray),slot);self.place(int(tray),slot,slot);self.flush(int(tray),slot)
        self.hold(20);return self.obs()
