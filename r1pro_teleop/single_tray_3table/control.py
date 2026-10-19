"""Thin teacher adapter to the existing opposed-grasp/lift/carry/place flow.

The first diagnostic stops after empty placement and cannot be training data.
No live object reset, weld, artificial force or VLA teacher fallback is added.
"""
from pathlib import Path
from dataclasses import replace
import json,time,traceback
import numpy as np
from ..airport_fsm.contracts import Config,Fault,State,atomic_json,wrap_angle
from ..airport_fsm.geometry import Geometry,Operation,quat_yaw_tilt
from ..airport_fsm.runtime import Runtime
from ..airport_fsm.machine import Machine
from ..airport_fsm.rim_affordances import rim_pairs, RimCandidate
from ..airport_recording import Evidence


def horizontal_axis_alignment_error(axis,forward):
    a=np.asarray(axis,float)[:2];b=np.asarray(forward,float)[:2]
    if not np.isfinite(np.r_[a,b]).all() or min(np.linalg.norm(a),np.linalg.norm(b))<1e-9:
        raise Fault('undefined_horizontal_alignment_axis')
    return float(np.arccos(np.clip(abs(a@b)/(np.linalg.norm(a)*np.linalg.norm(b)),0,1)))


class RigidTrayEvidence(Evidence):
    def row(self):
        s=self.sim;n=len(self.names);poses=np.zeros((n,7));forces=np.zeros((n,2))
        table=np.zeros(n);support=np.zeros(n);floor=np.zeros(n);bottom=np.zeros(n);bad=0;penetration=0.;flex_contacts=0
        for bid,i in self.ids.items():
            body=s.data.body(bid);poses[i]=np.r_[body.xpos,body.xquat]
            bottom[i]=(self.local_vertices[bid]@body.xmat.reshape(3,3).T+body.xpos)[:,2].min()
        for k,contact in enumerate(s.data.contact):
            # Flex has no rigid geom index; it must never masquerade as geom[-1].
            if min(contact.geom)<0:flex_contacts+=1;continue
            a,b=[int(s.model.geom_bodyid[g]) for g in contact.geom]
            force=np.zeros(6)
            import mujoco
            mujoco.mj_contactForce(s.model,s.data,k,force)
            if force[0]<=.05:continue
            if a in self.ids or b in self.ids:
                penetration=max(penetration,float(-contact.dist))
                for bid,other in ((a,b),(b,a)):
                    if bid not in self.ids:continue
                    i=self.ids[bid];name=s.model.body(other).name
                    for side,j in (('left',0),('right',1)):
                        if name.startswith(side+'_gripper_finger'):forces[i,j]+=force[0]
                    table[i]+=int(other in self.table_ids);support[i]+=int(other in self.table_ids or other in self.ids and poses[self.ids[other],2]<poses[i,2])
                    floor[i]+=int(other==0)
                    if name.startswith(('left_','right_','torso','base_')) and 'gripper_finger' not in name:bad+=1
            elif any(s.model.body(x).name.startswith(('left_','right_','torso')) for x in (a,b)):bad+=1
        return {'privileged/tray_pose':poses,'privileged/gripper_contact_force':forces,'privileged/table_contact':table,
            'privileged/support_contact':support,'privileged/floor_contact':floor,'privileged/min_z':bottom,
            'privileged/illegal_collision':np.int32(bad),'privileged/max_penetration':np.float64(penetration),
            'privileged/tcp':np.array([s.tcp(side)[0] for side in ('left','right')]),
            'privileged/registered_flex_contact_count':np.int32(flex_contacts)}


def teacher_config():
    root=Path(__file__).resolve().parents[2]
    base=Config.load(root/'configs/airport_approximate_completion_retry3.json')
    return replace(base,primitive_seconds=20.,max_episode_seconds=900.,
        max_attempt_wall_seconds=1800.,alternate_rim_enabled=False,substep_control_enabled=True,
        keep_place_contact=False,completion_supported_staging_enabled=False,
        completion_handoff_clearance_enabled=False,completion_yaw_deg=15.,
        rim_height_local_m=.096,rim_pitch_deg=-30.,pregrasp_clearance_m=.12,
        reachability_screen_enabled=False).validate()


class ThreeTableRuntime(Runtime):
    def __init__(self,manifest,cfg,*,approximate_planning=False,render=False):
        if type(render) is not bool:raise ValueError('render requires bool')
        if type(approximate_planning) is not bool:raise ValueError('approximate_planning requires bool')
        if approximate_planning and not cfg.approximate_completion_enabled:raise ValueError('Declared approximate profile required')
        self.manifest=manifest
        spec=manifest['legacy_spec']
        super().__init__(spec,manifest['xml'],cfg,geometry=Geometry(spec,expected_trays=1),render=render)
        self.evidence=RigidTrayEvidence(self.sim,self.g.ids)
        self.registered_flexes={int(self.mj.mj_name2id(self.m,self.mj.mjtObj.mjOBJ_FLEX,p['flex'] if isinstance(p['flex'],str) else p['name']))
            for p in manifest['payloads'] if p.get('flex')}
        self.registered_payload_bodies=set().union(*(self._descendants(self.m.body(p['name']).id)
            for p in manifest['payloads'] if not p.get('flex')))
        self.passenger_loaded=False
        self._approximate_planning_relaxed=approximate_planning

    def navigate(self,goal):
        return super().navigate(goal)

    def collision(self,data=None,*,planning=False,limit_override=None):
        """Original rigid checks, with explicit flex identity instead of geom[-1]."""
        d=self.d if data is None else data
        approximate=self.cfg.approximate_completion_enabled
        relaxed=approximate and planning and getattr(self,'_approximate_planning_relaxed',False)
        limit=(float(limit_override) if limit_override is not None else
            -float(self.cfg.completion_collision_penetration_m) if approximate and (not planning or relaxed)
            else self.cfg.planner_margin_m if planning else -.0002)
        for contact in d.contact:
            geoms=tuple(int(x) for x in contact.geom)
            if any(g<0 for g in geoms):
                flexes=[int(contact.flex[i]) for i,g in enumerate(geoms) if g<0]
                if any(f not in self.registered_flexes for f in flexes):return dict(geoms=['unregistered_flex'],distance_m=float(contact.dist))
                # Only the offstage floor pair is exempt while passengers are
                # absent; parked material touching the robot/table is not hidden.
                rigid=[g for g in geoms if g>=0]
                if not self.passenger_loaded and rigid and int(self.m.geom_bodyid[rigid[0]]) in self.registered_payload_bodies|{0}:continue
                if contact.dist<=limit:return dict(geoms=['registered_flex'],distance_m=float(contact.dist))
                continue
            if not np.isfinite(contact.dist):raise Fault('nonfinite_physics')
            if contact.dist<=limit and not self._pair_allowed(*geoms):
                return dict(geoms=[self.m.geom(g).name for g in geoms],distance_m=float(contact.dist))
        for g in self.robot_geoms:
            distances=np.linalg.norm(d.geom_xpos[self.table_geoms]-d.geom_xpos[g],axis=1)
            margin=max(.001,self.cfg.planner_margin_m) if planning else .001
            candidates=self.table_geoms[distances<self.m.geom_rbound[self.table_geoms]+self.m.geom_rbound[g]+margin]
            for other in candidates:
                if not ((self.m.geom_contype[g]&self.m.geom_conaffinity[other]) or (self.m.geom_contype[other]&self.m.geom_conaffinity[g])):continue
                distance=self.mj.mj_geomDistance(self.m,d,int(g),int(other),margin,None)
                if not np.isfinite(distance):raise Fault('nonfinite_physics')
                if distance<limit:return dict(geoms=[self.m.geom(int(g)).name,self.m.geom(int(other)).name],distance_m=float(distance))
        return None


class ThreeTableMachine(Machine):
    def __init__(self,runtime,directory,manifest,*,grasp_stagger=0.):
        if grasp_stagger not in (0.,.12,.16):raise ValueError('Supported grasp stagger values: 0/.12/.16 m')
        super().__init__(runtime,directory,seed=manifest['seed'])
        self.manifest=manifest
        self.grasp_stagger=grasp_stagger
        self.scheduler.mapping=(0,)

    def separate_if_needed(self,tray):
        if len(self.g.ids)==1:return None
        return super().separate_if_needed(tray)

    def carry_place(self,operation,placement_proposal=None,*,skip_placement_screen=False):
        # This task includes a later loaded left-hand endpoint. Empty Place
        # reach alone must not choose a standing pose that cannot execute it.
        push_target=self.manifest.get('loaded_push_target',{})
        if (placement_proposal is None and push_target and
                push_target.get('target')!='handover_left_motion_then_release'):
            from .placement_scope import select_joint_station
            placement_proposal=select_joint_station(self,operation)
        return super().carry_place(operation,placement_proposal,
            skip_placement_screen=skip_placement_screen)

    def _screen_candidate_list(self,tray,candidates):
        # The generic screen may append alternate short-edge candidates after
        # _candidate_list. Normalize that entire pool to the actual opposed
        # long-edge geometry before it can earn a private qualification.
        from .observer import table_front_region_violation
        pose=self._poses()[tray]
        table=self.g.tables[self.g.support_table(pose[:3])]
        yaw,_=quat_yaw_tilt(pose[3:])
        wanted='width' if self.g.sizes[tray,0]>=self.g.sizes[tray,1] else 'length'
        qualified=[];seen=set()
        for base,face,offset in candidates:
            if table_front_region_violation(table,base):continue
            pair=next(p for p in rim_pairs(self.g.sizes[tray],yaw,face,
                inset=self.c.rim_inset_m) if p.axis==wanted)
            if abs(offset)>pair.edge_half_length:continue
            key=tuple(np.round(np.r_[base,pair.face,offset],8))
            if key in seen:continue
            seen.add(key)
            qualified.append(RimCandidate(np.asarray(base).copy(),pair.face,offset,pair))
        return qualified

    def _candidate_list(self,tray):
        # Reuse the old joint position/heading/rim search. Both the initial
        # live list and the expanded private screen share this exact filter.
        return self._screen_candidate_list(tray,super()._candidate_list(tray))

    def _grasp_goals(self,center,face,*,x_offset=0.,sides=('left','right')):
        pose=self._poses()[0];yaw,_=quat_yaw_tilt(pose[3:])
        pairs=rim_pairs(self.g.sizes[0],yaw,face,inset=self.c.rim_inset_m)
        wanted='width' if self.g.sizes[0,0]>=self.g.sizes[0,1] else 'length'
        pair=getattr(self,'grasp_rim_pair',None)
        if pair is not None and pair.axis!=wanted:
            raise Fault('three_table_private_live_grasp_geometry_mismatch')
        if pair is None:pair=next(p for p in pairs if p.axis==wanted)
        self.grasp_rim_pair=pair
        # Actual legacy Runtime geometry/orientation implementation, unchanged.
        sign=1. if np.cos(pair.face-yaw)>0 else -1.
        goals={}
        for side in sides:
            tangent=x_offset+(self.grasp_stagger if side=='left' else -self.grasp_stagger)*sign
            goals.update(self.r.grasp_goals(center,pair.face,rim_pair=pair,x_offset=tangent,sides=(side,)))
        return goals


def empty_motion_diagnostic(manifest,directory,cfg=None,*,grasp_stagger=0.,approximate_planning=False,continuation=None,record_substeps=False):
    """Execute original physics; explicitly not a complete three-action source."""
    r=ThreeTableRuntime(manifest,cfg or teacher_config(),approximate_planning=approximate_planning)
    machine=ThreeTableMachine(r,directory,manifest,grasp_stagger=grasp_stagger)
    if record_substeps:
        r.record_ctrl_substeps=True
        machine.log.file.attrs['schema']='airport_fsm_raw/2'
        metadata=json.loads(machine.log.file.attrs['metadata_json'])
        metadata['recorded_substep_controls_without_interpolation']=not r.cfg.substep_control_enabled
        machine.log.file.attrs['metadata_json']=json.dumps(metadata,allow_nan=False)
    machine.log.file.attrs['three_table_controller_profile_json']=json.dumps(dict(grasp_stagger_m=grasp_stagger,
        approximate_private_planning=approximate_planning,private_collision_limit_m=r.cfg.completion_collision_penetration_m,
        target_station_hint=manifest['target_robot_pose'],planner_station_override=False))
    result=dict(schema='airport_three_table_empty_motion_diagnostic/1',task_completed=False,
        training_eligible=False,diagnostic=True,source='simulation/program_generated',
        grasp_stagger_m=grasp_stagger,
        approximate_private_planning=approximate_planning,
        reused_primitives=['Machine.prepare_pick','Machine.grasp','primitives.lift','Machine.carry_place','primitives.place'],
        empty_pick_completed=False,empty_place_completed=False)
    started=time.monotonic()
    try:
        r.allowed_tray=0;r.target_slot=0
        machine.transition(State.ALIGN_BASE,'initial_posture',tray=0,slot=0)
        r.joints(r.tucked,minimum_seconds=.3)
        face,offset=machine.prepare_pick(0,0);machine.grasp(0,face,offset)
        result['empty_pick_completed']=True;result['pick_end_frame']=r.steps
        place=manifest['place_target'];position=np.asarray(place['position_world'],float)
        # The latest task aligns the tray long axis to the actual robot forward
        # axis, matching the original airport place orientation. The declared
        # goal comes from the scene; no additional held rotation is inserted.
        yaw=float(place['yaw_world']);machine.g.goals[0]=position;machine.g.goal_yaw[0]=yaw
        operation=Operation(0,0,position,yaw)
        machine.carry_place(operation)
        obs=r.observation();actual_yaw,_=quat_yaw_tilt(obs['tray_pose'][0,3:])
        forward=r.d.body('base_link').xmat.reshape(3,3)[:,0]
        long_axis=r.d.body('tray').xmat.reshape(3,3)[:,int(np.argmax(r.g.sizes[0,:2]))]
        alignment=horizontal_axis_alignment_error(long_axis,forward)
        result.update(empty_place_completed=bool(obs['support_contact'][0]>0 and np.all(obs['gripper_contact_force'][0]<=.5)
            and alignment<=np.deg2rad(15)),place_end_frame=r.steps,actual_yaw=actual_yaw,
            alignment_reference='actual_robot_forward',actual_long_axis_alignment_error_rad=alignment)
        if continuation is not None:
            if not result['empty_place_completed']:raise Fault('three_table_empty_place_endpoint_unverified')
            result.update(schema='airport_three_table_full_motion_candidate/1',
                loaded_continuation=continuation(r,machine,manifest))
            result['task_completed']=bool(result['loaded_continuation'].get('push_loaded_completed',False))
    except Exception as exc:
        result.update(error_code=getattr(exc,'code',type(exc).__name__),error=str(exc))
        (Path(directory)/'exception.txt').write_text(traceback.format_exc())
    finally:
        if hasattr(r,'loaded_bridge'):result['loaded_guard_statistics']=r.loaded_bridge.statistics()
        result.update(frames=r.steps,completed_intervals=r.steps,recorded_frames=machine.log.count,
            terminal_partial_interval=bool(machine.log.count>r.steps),
            sim_seconds=float(r.d.time),wall_seconds=time.monotonic()-started,
            final_observation=r.observation(),inverse_calls=r.id_calls,physical_episode_started=True,
            actual_grasp_relative_transforms=r.grasp_rel,holding=r.holding,final_base_state=r.sim.base_state())
        machine.log.file.attrs['terminal_snapshot_json']=json.dumps(dict(qpos=r.d.qpos.tolist(),qvel=r.d.qvel.tolist(),time=float(r.d.time)))
        machine.log.close();r.sim.close();atomic_json(Path(directory)/'diagnostic_result.json',result)
    return result
