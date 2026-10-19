"""Native PhysX execution/recording for the three-tray task.

Source MuJoCo objects are a private kinematic planner only. No mj_step, live
robot/object pose correction, grasp attachment, weld or external force is used.
"""
import hashlib
import json
from pathlib import Path
import subprocess
import time
from types import SimpleNamespace
import numpy as np
from .isaac_mobile import IsaacMobile19Backend, mobile_targets
from .isaac_three_tray_observer import NativeTaskFault
from .isaac_front_drift import FRONT_FIELDS,front_drift_check


def cpu(value):
    if hasattr(value,'detach'):return value.detach().cpu().numpy()
    if hasattr(value,'numpy'):return value.numpy()
    return np.asarray(value)


class NativeRuntime:
    def __init__(self, scene_root, output, *, seed, episode_id, record=True, initial_pose_overrides=None, interpolate_commands=False, restore_rubber_torsion=False, exact_collision_footprint=False, camera_resolutions=None, initial_base_world=None):
        import torch
        import mujoco
        import omni.usd
        from pxr import Usd, UsdPhysics, UsdGeom, UsdLux
        from isaacsim.core.api import World
        from isaacsim.core.prims import SingleArticulation, RigidPrim
        from isaacsim.core.simulation_manager import SimulationManager
        from isaacsim.core.experimental.prims import DeformablePrim
        from isaacsim.sensors.camera import Camera
        self.output=Path(output);self.root=Path(scene_root);self.seed=int(seed);self.episode_id=episode_id
        self.record=record;self.mj=mujoco;self.torch=torch;self.encoders={};self.cameras={}
        self.interpolate_commands=bool(interpolate_commands);self.previous_submitted_command=None
        self.frames=0;self.observer=None;self.context=None;self.manipulating=False;self.loaded=np.zeros(3,bool)
        self.events=[];self.raw_arrays={k:[] for k in ('time','state','raw_action','action','submitted_control',
            'tray_pose','finger_contact_force','table_force','payload_rigid_support','penetration','coat_positions',
            'rigid_pose','payload_loaded','long_edge_sign','payload_speed','payload_on_tray','boundary_ok','axis_error_rad','front_region_ok',*FRONT_FIELDS)}
        receipt=json.loads((self.root/'control/validation.json').read_text())
        wait=json.loads((self.root/'control_exit.json').read_text())
        if not receipt['passed'] or wait.get('returncode')!=0 or wait.get('actual_child_wait') is not True:
            raise NativeTaskFault('scene_specific_native_preflight_not_closed')
        scene=Path(receipt['scene_path']);scene_sha=hashlib.sha256(scene.read_bytes()).hexdigest()
        if scene_sha!=receipt['scene_sha256']:raise NativeTaskFault('validated_scene_changed')
        self.model=mujoco.MjModel.from_xml_path(str(self.root/'asset/import_only.xml'))
        self.shadow=mujoco.MjData(self.model)
        self.shadow.qpos[:]=self.model.key_qpos[0] if self.model.nkey else self.model.qpos0
        mujoco.mj_forward(self.model,self.shadow)
        self.source_base_q={n:float(self.shadow.qpos[self.model.jnt_qposadr[self.model.joint(n).id]])
            for n in ('agent_base_x','agent_base_y','agent_base_yaw')}
        inventory=json.loads((self.root/'preparation/legacy_inventory.json').read_text())
        self.scene_manifest_path=self.root/'source_scene.json'
        if not self.scene_manifest_path.exists():
            self.scene_manifest_path=next((self.root/'preparation/scenes/train').glob('*/scene.json'))
        self.scene_manifest=json.loads(self.scene_manifest_path.read_text())
        source=next(r for r in inventory['sources'] if r['parent_scene_id']==self.scene_manifest['parent_scene_id'])
        self.parent=json.loads(Path(source['legacy_source']['scene_json']).read_text())
        self.tables=self.parent['tables'];self.tray_ids=['tray_0','tray_1','tray_2']
        self.payload_specs=self.scene_manifest['payloads']
        self.size=np.array([t.get('dimensions_m',[.56,.43,.105]) for t in self.parent['trays']])
        if not omni.usd.get_context().open_stage(str(scene)):raise NativeTaskFault('native_task_stage_open_failed')
        self.stage=omni.usd.get_context().get_stage();self.stage.SetEditTarget(self.stage.GetSessionLayer())
        self.rubber_contact_report=None
        if restore_rubber_torsion:
            from .isaac_rubber_contacts import restore_soft_finger_contacts
            self.rubber_contact_report=restore_soft_finger_contacts(self.stage,self.model)
            self.write('rubber_pad_contact_translation.json',self.rubber_contact_report)
            self.stage.GetSessionLayer().Export(str(self.output/'rubber_contact_override.usda'))
        self.paths={p.GetName():str(p.GetPath()) for p in self.stage.Traverse() if p.HasAPI(UsdPhysics.RigidBodyAPI)}
        self.boundary_footprints={}
        if exact_collision_footprint:
            from .isaac_collision_footprint import native_mesh_footprint
            for name in self.tray_ids:
                row=native_mesh_footprint(self.stage,self.paths[name])
                row['validated_scene_sha256']=scene_sha
                self.boundary_footprints[name]=np.asarray(row['body_local_vertices_m'])
                self.write(name+'_collision_footprint.json',row)
        actor=self.paths['base_link']
        self.world=World(stage_units_in_meters=1.,physics_dt=.002,rendering_dt=.05,backend='torch',device='cuda:0')
        SimulationManager.set_device('cuda:0');self.world.get_physics_context().enable_gpu_dynamics(True)
        self.fingers=[f'{side}_gripper_finger_link{i}' for side in ('left','right') for i in (1,2)]
        payload_names=[p['name'] for p in self.payload_specs if not p['flex']]
        # Register views before reset/physics starts, including articulation links.
        self.sensor_names=self.fingers+self.tray_ids+payload_names
        robot_names=[n for n,path in self.paths.items() if path==actor or path.startswith(actor+'/')]
        self.sensor_names.extend(n for n in robot_names if n not in self.sensor_names)
        self.filter_paths=[self.paths[t] for t in self.tray_ids]
        self.filter_owner=list(self.tray_ids)
        table_roots=set()
        for table in self.tables:
            name=table['table_id']
            if name in self.paths:
                self.filter_paths.append(self.paths[name]);self.filter_owner.append(name);table_roots.add(name)
        for prim in Usd.PrimRange.Stage(self.stage,Usd.TraverseInstanceProxies()):
            if not prim.HasAPI(UsdPhysics.CollisionAPI) or not UsdPhysics.CollisionAPI(prim).GetCollisionEnabledAttr().Get():continue
            names=[str(prim.GetPath())]
            for table in self.tables:
                if '/'+table['table_id']+'/' in names[0]:
                    if table['table_id'] not in table_roots:
                        self.filter_paths.append(names[0]);self.filter_owner.append(table['table_id'])
                    break
        for name in payload_names:self.filter_paths.append(self.paths[name]);self.filter_owner.append(name)
        for name in robot_names:self.filter_paths.append(self.paths[name]);self.filter_owner.append(name)
        self.rigid=RigidPrim(prim_paths_expr=[self.paths[n] for n in self.sensor_names],name='task_contact_sensors',
            reset_xform_properties=False,track_contact_forces=True,
            contact_filter_prim_paths_expr=[self.filter_paths for _ in self.sensor_names],max_contact_count=32768)
        self.world.reset()
        self.robot=SingleArticulation(prim_path=actor,name='task_robot');self.robot.initialize()
        self.rigid.initialize()
        actual_paths=list(self.rigid.prim_paths)
        self.sensor_index={Path(p).name:i for i,p in enumerate(actual_paths)}
        if set(self.sensor_index)!=set(self.sensor_names):raise NativeTaskFault('native_contact_sensor_identity_mismatch')
        self.names=tuple(mobile_targets(np.zeros(19)))
        self.indices=self.gpu([self.robot.get_dof_index(n) for n in self.names],index=True)
        initial=[float(self.shadow.qpos[self.model.jnt_qposadr[self.model.joint(n).id]]) for n in self.names]
        self.robot.set_joint_positions(self.gpu(initial),joint_indices=self.indices)
        self.robot.set_joint_velocities(self.gpu(np.zeros(18)),joint_indices=self.indices)
        xyz,quat=[cpu(v) for v in self.robot.get_world_pose()];self.base_origin=np.r_[xyz[:2],self.yaw(quat)]
        mapping=json.loads((self.root/'control/mapping.json').read_text())
        self.backend=IsaacMobile19Backend(self.robot,self.stage.GetPrimAtPath(actor+'/agent_base_x'),
            mapping['native_d6_world_rotation'],self.base_origin,receipt,scene_sha256=scene_sha)
        if initial_base_world is not None:
            station=np.asarray(initial_base_world,float)
            if station.shape!=(3,) or not np.isfinite(station).all():
                raise ValueError('invalid_initial_base_world')
            # Episode initialization only, before any physical step. Keep the
            # original D6 origin so commands/planner use the validated mapping.
            self.robot.set_world_pose(position=self.gpu(np.r_[station[:2],xyz[2]]),
                orientation=self.gpu([np.cos(station[2]/2),0.,0.,np.sin(station[2]/2)]))
        self.command=self.backend.observe().copy();self.command[[7,15]]=.1
        self.fixed_episode_base_command=self.command[16:].copy() if initial_base_world is not None else None
        if initial_base_world is not None:
            self.backend.command(self.command)
            self.write('initial_base_station.json',dict(requested_world=station.tolist(),
                original_drive_origin=self.base_origin.tolist(),fixed_command=self.command[16:].tolist(),
                initialization_only_before_first_step=True))
        self.native_tray_indices=np.array([self.sensor_index[t] for t in self.tray_ids],int)
        # Object state initialization occurs exactly once, before the first step.
        poses,quats=self.rigid.get_world_poses();poses=cpu(poses).copy();quats=cpu(quats).copy()
        for name in self.tray_ids:
            i=self.sensor_index[name];body=self.shadow.body(name);poses[i]=body.xpos;quats[i]=body.xquat
        from scipy.spatial.transform import Rotation
        rng=np.random.default_rng(self.seed)
        for name in self.tray_ids:
            i=self.sensor_index[name];poses[i,:2]+=rng.uniform(-.003,.003,2)
            old=Rotation.from_quat(quats[i,[1,2,3,0]])
            quats[i]=(Rotation.from_euler('z',rng.uniform(-.005,.005))*old).as_quat()[[3,0,1,2]]
        for name,pose in (initial_pose_overrides or {}).items():
            pose=np.asarray(pose,float)
            if name not in self.tray_ids or pose.shape!=(7,) or not np.isfinite(pose).all() or not np.isclose(np.linalg.norm(pose[3:]),1.):
                raise ValueError('invalid_explicit_initial_tray_pose')
            i=self.sensor_index[name];poses[i]=pose[:3];quats[i]=pose[3:]
        self.initialization_record=dict(seed=self.seed,source='registered_parent_plus_small_random_xy_yaw',
            tray_ids=self.tray_ids,tray_poses=np.c_[poses[self.native_tray_indices],quats[self.native_tray_indices]].tolist(),
            source_target_tables_and_slots='registered_parent_scheduler',
            explicit_initial_pose_overrides=initial_pose_overrides or {},initialization_only_before_first_step=True)
        self.write('initialization.json',self.initialization_record)
        self.rigid.set_world_poses(positions=self.gpu(poses[self.native_tray_indices]),
            orientations=self.gpu(quats[self.native_tray_indices]),indices=self.gpu(self.native_tray_indices,index=True))
        self.rigid.set_velocities(self.gpu(np.zeros((3,6))),indices=self.gpu(self.native_tray_indices,index=True))
        conversions=json.loads((self.root/'control/coat_conversion.json').read_text())['coats']
        self.coats=[DeformablePrim(row['path'],deformable_type='surface') for row in conversions]
        self.coat_conversions=conversions
        for row in conversions:UsdGeom.Imageable(self.stage.GetPrimAtPath(row['path'])).MakeInvisible()
        self.initial_bottom=np.array([self.shadow.body(t).xpos[2] for t in self.tray_ids])
        self.filter_groups={name:np.array([i for i,n in enumerate(self.filter_owner) if n==name],int)
            for name in set(self.filter_owner)}
        self.table_filter=np.array([i for i,n in enumerate(self.filter_owner) if n in {t['table_id'] for t in self.tables}],int)
        if not len(self.table_filter):raise NativeTaskFault('native_table_contact_filters_missing')
        self._last_contact=None;self._last_obs=None
        self.write('native_mapping.json',dict(sensor_paths=actual_paths,filter_paths=self.filter_paths,
            filter_owner=self.filter_owner,scene_sha256=scene_sha,source_planner='private_mj_kinematics_no_mj_step',
            task_tables=self.tables,front_drift_limit_m=.05,front_station_search_remains_strict=True,
            source_mass_kg={n:float(self.model.body(n).mass[0]) for n in self.tray_ids},
            native_sensor_mass_kg=cpu(self.rigid.get_masses()).tolist(),live_pose_resets_after_initialization=False,
            rubber_contact_translation=self.rubber_contact_report))
        self.write('boundary_measurement.json',dict(
            mode='native_collision_vertices' if exact_collision_footprint else 'legacy_enclosing_rectangle',
            tolerance_m=.05,geometry_changed=False,old_labels_changed=False,
            collision_footprint_reports=[name+'_collision_footprint.json' for name in self.boundary_footprints]))
        masses=cpu(self.rigid.get_masses()).reshape(-1)
        mass_rows=[dict(body=n,source_mass_kg=float(self.model.body(n).mass[0]),native_mass_kg=float(masses[self.sensor_index[n]]))
            for n in self.tray_ids+payload_names]
        self.write('native_mass_validation.json',dict(rows=mass_rows,scope='source_translation_check_not_task_tolerance'))
        if any(not np.isclose(row['source_mass_kg'],row['native_mass_kg'],rtol=1e-4,atol=1e-6) for row in mass_rows):
            raise NativeTaskFault('native_object_mass_differs_from_source')
        if record:
            dome=UsdLux.DomeLight.Define(self.stage,'/TaskDomeLight');dome.CreateIntensityAttr(600.)
            for row in json.loads((self.root/'asset/camera_mapping.json').read_text()):
                name=row['name']
                if name not in ('head_left','head_right','left_wrist','right_wrist'):continue
                resolution=tuple((camera_resolutions or {}).get(name,row['resolution']))
                if len(resolution)!=2 or min(resolution)<=0 or not np.isclose(resolution[0]/resolution[1],row['resolution'][0]/row['resolution'][1]):
                    raise ValueError('native_camera_resolution_changes_aspect')
                camera=Camera(prim_path=row['path'],name=name,frequency=20,resolution=resolution)
                camera.initialize();self.cameras[name]=camera
                log=(self.output/(name+'_encoder.log')).open('wb');path=self.output/(name+'.mp4')
                cmd=['ffmpeg','-nostdin','-v','error','-n','-f','rawvideo','-pix_fmt','rgb24','-s',
                    f"{resolution[0]}x{resolution[1]}",'-r','20','-i','pipe:0','-an',
                    '-c:v','libx264','-preset','fast','-crf','18','-threads','2',str(path)]
                self.encoders[name]=(subprocess.Popen(cmd,stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=log),path,log)
            if len(self.cameras)!=4:raise NativeTaskFault('four_native_cameras_required')
            for _ in range(8):self.world.render()
        self.backend.command(self.command)

    def gpu(self,value,index=False):return self.torch.as_tensor(value,dtype=self.torch.int64 if index else self.torch.float32,device='cuda:0')
    @staticmethod
    def yaw(q):
        w,x,y,z=q;return float(np.arctan2(2*(w*z+x*y),1-2*(y*y+z*z)))
    def write(self,name,value):
        p=self.output/name;tmp=p.with_suffix(p.suffix+'.tmp');tmp.write_text(json.dumps(value,indent=2));tmp.replace(p)
    def event(self,name,**data):
        row=dict(event=name,frame=self.frames,sim_time=float(self.world.current_time),**data)
        self.events.append(row)
        with (self.output/'events.jsonl').open('a') as stream:stream.write(json.dumps(row)+'\n')

    def contact(self,*,detailed=True):
        f=cpu(self.rigid.get_contact_force_matrix(dt=.002))
        expected=(len(self.sensor_index),len(self.filter_paths),3)
        if f.shape!=expected:raise NativeTaskFault('native_force_matrix_shape:'+repr((f.shape,expected)))
        scalar=np.linalg.norm(f,axis=-1);finger=np.zeros((3,2));table=np.zeros(3);support=np.zeros((3,2));edges=np.zeros((3,2),int)
        for ti,tray in enumerate(self.tray_ids):
            cols=self.filter_groups[tray]
            for si,side in enumerate(('left','right')):
                ids=[self.sensor_index[f'{side}_gripper_finger_link{i}'] for i in (1,2)]
                finger[ti,si]=float(scalar[np.ix_(ids,cols)].sum())
            table[ti]=float(scalar[self.sensor_index[tray],self.table_filter].sum())
            for pi,kind in enumerate(('laptop','backpack')):
                name=f'{tray}_passenger_{kind}';support[ti,pi]=float(scalar[self.sensor_index[name],cols].sum())
        native=self.rigid.get_contact_force_data(dt=.002)
        counts,starts=[cpu(v) for v in native[4:]]
        counts=counts.reshape(len(self.sensor_index),-1);starts=starts.reshape(counts.shape)
        active=[]
        for row,col in np.argwhere(counts>0):
            a=int(starts[row,col]);b=a+int(counts[row,col]);active.extend(range(a,b))
        if not detailed:
            separations=native[3]
            if active and hasattr(separations,'detach'):
                index=self.torch.as_tensor(active,dtype=self.torch.int64,device=separations.device)
                depth=float(-separations[index].min().item())
            elif active:depth=float(-cpu(separations)[np.asarray(active,int)].min())
            else:depth=0.
            return finger,table,support,edges,max(0.,depth)
        forces,points,normals,separations=[cpu(v) for v in native[:4]]
        penetration=max(0.,float(-separations[np.asarray(active,int)].min())) if active else 0.
        self._last_contact=(scalar,points,forces,counts,starts,penetration,separations,normals)
        return finger,table,support,edges,penetration

    def front_ok(self,xyz):
        from r1pro_teleop.single_tray_3table.observer import table_front_region_violation
        contexts=[] if self.context is None else self.context if isinstance(self.context,list) else [self.context]
        if not self.manipulating or not contexts:
            self._front_anchor=None;self._front_allowance_logged=False
            self._front_diagnostics=dict(front_reference_xy=np.asarray(xyz)[:2].copy(),front_reference_table_index=-1,
                front_manipulating=False,front_reference_strict=False,
                front_actual_strict=any(not table_front_region_violation(t,xyz) for t in contexts),
                front_drift_m=0.,front_allowance_used=False)
            return True
        anchor=getattr(self,'_front_anchor',None)
        if anchor is None or anchor['table_id'] not in {t['table_id'] for t in contexts}:
            reference=self.base_origin[:2]+self.command[16:18]
            table=next((t for t in contexts if not table_front_region_violation(t,reference)),contexts[0])
            anchor=dict(table_id=table['table_id'],reference=reference.copy());self._front_anchor=anchor
        table=next(t for t in contexts if t['table_id']==anchor['table_id'])
        info=front_drift_check(table,xyz,anchor['reference']);allowed=info.pop('allowed')
        info.update(front_manipulating=True,front_reference_table_index=next(i for i,t in enumerate(self.tables) if t['table_id']==table['table_id']))
        self._front_diagnostics=info
        if info['front_allowance_used'] and not getattr(self,'_front_allowance_logged',False):
            self.event('native_authorized_front_base_drift',reference_xy=anchor['reference'].tolist(),
                actual_xy=np.asarray(xyz)[:2].tolist(),actual_drift_m=info['front_drift_m'],authorized_limit_m=.05,
                planned_reference_strict_front=info['front_reference_strict'])
        self._front_allowance_logged=info['front_allowance_used']
        return allowed

    def observation(self,*,force=False):
        # Private IK searches do not advance PhysX. Re-read only after an actual
        # step or explicit payload-state invalidation; never cache command intent.
        stamp=float(self.world.current_time)
        if not force and self._last_obs is not None and getattr(self,'_last_obs_time',None)==stamp:
            ok=self.front_ok(self._last_obs['robot_position'])
            return dict(self._last_obs,command=self.command.copy(),front_region_ok=ok,**self._front_diagnostics)
        from scipy.spatial.transform import Rotation
        positions,quats=[cpu(v) for v in self.rigid.get_world_poses()];velocities=cpu(self.rigid.get_velocities())
        tray_pose=np.c_[positions[self.native_tray_indices],quats[self.native_tray_indices]]
        state=self.backend.observe();xyz,quat=[cpu(v) for v in self.robot.get_world_pose()]
        yaw=self.yaw(quat);forward=np.array([np.cos(yaw),np.sin(yaw),0.]);left=np.array([-np.sin(yaw),np.cos(yaw),0.])
        finger,table,support,edges,penetration=self.contact();scalar,points,forces,counts,starts,_=self._last_contact[:6]
        boundary=np.ones(3,bool);angle=np.zeros(3);payload_ok=np.zeros(3,bool);nodes=[];payload_speed=np.zeros(3)
        for ti,tray in enumerate(self.tray_ids):
            R=Rotation.from_quat(tray_pose[ti,[4,5,6,3]]).as_matrix();origin=tray_pose[ti,:3];size=self.size[ti]
            axis=R[:,int(np.argmax(size[:2]))];angle[ti]=np.arccos(np.clip(abs(axis[:2]@forward[:2])/np.linalg.norm(axis[:2]),0,1))
            for si,side in enumerate(('left','right')):
                signs=[]
                for finger_name in [f'{side}_gripper_finger_link{i}' for i in (1,2)]:
                    row=self.sensor_index[finger_name]
                    for col in self.filter_groups[tray]:
                        a=int(starts[row,col]);b=a+int(counts[row,col])
                        for point,force in zip(points[a:b],forces[a:b]):
                            if abs(float(np.ravel(force)[0]))<=.01:continue
                            local=R.T@(point-origin);short=int(np.argmin(size[:2]));long=1-short
                            if abs(abs(local[short])-size[short]/2)<=.05 and abs(abs(local[short])-size[short]/2)<=abs(abs(local[long])-size[long]/2):
                                signs.append(int(np.sign(local[short])))
                if signs and len(set(signs))==1:edges[ti,si]=signs[0]
            # Evaluate support against the union of unchanged tabletop footprints.
            footprint=self.boundary_footprints.get(tray)
            if footprint is None:footprint=np.array([[x,y,0] for x in (-size[0]/2,size[0]/2) for y in (-size[1]/2,size[1]/2)])
            corners=footprint@R.T+origin
            if tray in self.boundary_footprints:
                from .isaac_collision_footprint import maximum_union_overhang
                boundary[ti]=maximum_union_overhang(corners,self.tables)<=.05
            else:
                for corner in corners:
                    valid=False
                    for t in self.tables:
                        rr=Rotation.from_euler('z',t['yaw_world']).as_matrix();local=rr.T@(corner-np.asarray(t['center_world']))
                        if np.all(abs(local[:2])<=np.array(t['dimensions_m'][:2])/2+.05):valid=True
                    if not valid:boundary[ti]=False
            native_nodes=cpu(self.coats[ti].get_nodal_positions()[0])[0];nodes.append(native_nodes)
            native_velocity=cpu(self.coats[ti].get_nodal_velocities())[0]
            payload_speed[ti]=float(np.linalg.norm(native_velocity,axis=-1).max())
            if self.loaded[ti]:
                local=(native_nodes-origin)@R
                cloth_inside=bool(np.all(abs(local[:,:2])<=size[:2]/2+.05) and
                    np.min(local[:,2])>=-.02 and np.max(local[:,2])<=.22)
                rigid_inside=True;connected=set()
                for kind in ('laptop','backpack'):
                    name=f'{tray}_passenger_{kind}';idx=self.sensor_index[name];pos=R.T@(positions[idx]-origin)
                    payload_speed[ti]=max(payload_speed[ti],float(np.linalg.norm(velocities[idx,:3])))
                    rigid_inside &= bool(np.all(abs(pos[:2])<size[:2]/2) and -.02<pos[2]<.3)
                    if scalar[idx,self.filter_groups[tray]].sum()>.01:connected.add(name)
                for _ in range(2):
                    for kind in ('laptop','backpack'):
                        name=f'{tray}_passenger_{kind}';idx=self.sensor_index[name]
                        if any(scalar[idx,self.filter_groups[n]].sum()>.01 for n in connected):connected.add(name)
                payload_ok[ti]=bool(cloth_inside and rigid_inside and len(connected)==2)
        front_ok=self.front_ok(xyz)
        obs=dict(state=state,command=self.command.copy(),tray_pose=tray_pose,finger_force=finger,table_force=table,
            payload_rigid_support=support,long_edge_sign=edges,loaded=self.loaded.copy(),payload_on_tray=payload_ok,
            boundary_ok=boundary,axis_error_rad=angle,lift_clearance=tray_pose[:,2]-self.initial_bottom,
            robot_position=xyz,robot_yaw=yaw,robot_forward=forward,robot_left=left,
            front_region_ok=front_ok,penetration_m=penetration,coat_positions=np.asarray(nodes),
            tray_velocity=velocities[self.native_tray_indices],rigid_pose=np.c_[positions,quats])
        obs['payload_speed']=payload_speed;obs.update(self._front_diagnostics)
        self._last_obs=obs;self._last_obs_time=stamp;return obs

    def sync_planner(self,obs=None):
        obs=self.observation() if obs is None else obs
        q=cpu(self.robot.get_joint_positions(joint_indices=self.indices))
        for name,value in zip(self.names,q):self.shadow.qpos[self.model.jnt_qposadr[self.model.joint(name).id]]=value
        for name,value in zip(('agent_base_x','agent_base_y','agent_base_yaw'),obs['state'][16:]):
            self.shadow.qpos[self.model.jnt_qposadr[self.model.joint(name).id]]=self.source_base_q[name]+value
        for i,tray in enumerate(self.tray_ids):
            jid=int(self.model.body(tray).jntadr[0]);adr=int(self.model.jnt_qposadr[jid]);self.shadow.qpos[adr:adr+7]=obs['tray_pose'][i]
        self.mj.mj_forward(self.model,self.shadow)

    def tick(self, command=None):
        command=self.command if command is None else np.asarray(command,float)
        if command.shape!=(19,) or not np.isfinite(command).all():raise NativeTaskFault('nonfinite_or_invalid_native_command')
        fixed=getattr(self,'fixed_episode_base_command',None)
        if fixed is not None and not np.array_equal(command[16:],fixed):
            raise NativeTaskFault('episode_fixed_base_command_changed')
        self.command=command.copy();before=self.observation()
        self.raw_arrays['time'].append(float(self.world.current_time));self.raw_arrays['state'].append(before['state'])
        self.raw_arrays['tray_pose'].append(before['tray_pose'])
        for key,value in [('rigid_pose',before['rigid_pose']),('payload_loaded',before['loaded']),('long_edge_sign',before['long_edge_sign'])]:
            self.raw_arrays[key].append(value.copy())
        for key in ('payload_speed','payload_on_tray','boundary_ok','axis_error_rad','front_region_ok',*FRONT_FIELDS):
            self.raw_arrays[key].append(np.asarray(before[key]).copy())
        self.record_contacts()
        if self.record:
            self.world.render()
            for name,camera in self.cameras.items():
                image=np.asarray(camera.get_rgba())
                if image.ndim!=3 or image.shape[-1]!=4:raise NativeTaskFault('invalid_native_camera_image:'+name)
                self.encoders[name][0].stdin.write(image[:,:,:3].astype(np.uint8).tobytes())
        from .isaac_command_timing import substep_commands
        previous=command if self.previous_submitted_command is None else self.previous_submitted_command
        commands=substep_commands(previous,command) if self.interpolate_commands else np.repeat(command[None],25,axis=0)
        submitted=None if self.interpolate_commands else self.backend.command(command)
        forces=[];tables=[];supports=[];penetration=[];controls=[]
        for subcommand in commands:
            if self.interpolate_commands:submitted=self.backend.command(subcommand)
            self.world.step(render=False);f,t,p,e,depth=self.contact(detailed=False)
            if self.frames<2 and len(forces)==0:
                full=self.contact()
                if any(not np.allclose(a,b,rtol=1e-6,atol=1e-6) for a,b in zip((f,t,p,depth),(full[0],full[1],full[2],full[4]))):
                    raise NativeTaskFault('sparse_native_contact_reduction_parity_failed')
                self.event('native_contact_sparse_full_parity',actual_force_and_depth_equal=True)
            forces.append(f);tables.append(t);supports.append(p);penetration.append(depth);controls.append(submitted['values'].copy())
            if not np.isfinite(np.r_[f.ravel(),t,depth]).all():raise NativeTaskFault('nonfinite_native_physics')
            if depth>.02:
                self.event('native_hard_penetration',measured_m=depth,existing_limit_m=.02)
                raise NativeTaskFault('native_hard_penetration_exceeded_2cm')
        self.previous_submitted_command=command.copy()
        for name,value in [('raw_action',command.copy()),('action',command.copy()),('submitted_control',controls),
                ('finger_contact_force',forces),('table_force',tables),('payload_rigid_support',supports),
                ('penetration',penetration),('coat_positions',before['coat_positions'])]:self.raw_arrays[name].append(value)
        self.frames+=1;after=self.observation()
        with (self.output/'native_steps.jsonl').open('a') as stream:
            stream.write(json.dumps(dict(frame=self.frames-1,completed_real_substeps=25,
                raw_action=command.tolist(),submitted_control=submitted['values'].tolist(),
                substep_command_constant=not self.interpolate_commands,
                interpolation='linear_500Hz' if self.interpolate_commands else 'zero_order_hold_20Hz',
                actual_first_substep_control=controls[0].tolist(),actual_last_substep_control=controls[-1].tolist(),
                measured_state=before['state'].tolist(),
                tray_pose=before['tray_pose'].tolist(),sim_time=float(self.world.current_time)))+'\n')
        if self.observer:self.observer.observe(after,self.frames)
        if self.manipulating and not after['front_region_ok']:
            if after['front_reference_strict'] and after['front_drift_m']>.05+1e-9:
                raise NativeTaskFault('native_base_drift_over_authorized_5cm')
            raise NativeTaskFault('native_table_side_manipulation')
        if self.frames%20==0:self.write('progress.json',dict(stage='native_task_running',frames=self.frames,
            sim_time=float(self.world.current_time),wall_unix=time.time(),action=self.observer.action if self.observer else None,
            tray_z=after['tray_pose'][:,2].tolist(),training_started=False))
        return after

    def record_contacts(self):
        scalar,points,forces,counts,starts,_,separations,normals=self._last_contact
        by_index={i:n for n,i in self.sensor_index.items()};rows=[]
        for row,col in np.argwhere(counts>0):
            a=int(starts[row,col]);b=a+int(counts[row,col])
            if not (row<len(by_index) and col<len(self.filter_owner)):raise NativeTaskFault('contact_index_outside_recorded_mapping')
            for i in range(a,b):
                force=float(np.ravel(forces[i])[0]);separation=float(np.ravel(separations[i])[0])
                if abs(force)<=.01 and separation>=0:continue
                rows.append(dict(sensor=by_index[int(row)],other=self.filter_owner[int(col)],
                    point_world=points[i].tolist(),normal_world=normals[i].tolist(),
                    normal_force_n=force,separation_m=separation))
        with (self.output/'native_contacts.jsonl').open('a') as stream:
            stream.write(json.dumps(dict(frame=self.frames,sim_time=float(self.world.current_time),contacts=rows))+'\n')

    def load_payload(self,tray,observer,cycle):
        from pxr import Usd, UsdGeom, UsdShade, Sdf
        from scipy.spatial.transform import Rotation
        import xml.etree.ElementTree as ET
        before=self.observation();protected=np.r_[before['state'],before['tray_pose'].ravel(),before['tray_velocity'].ravel()]
        pose=before['tray_pose'][tray];yaw=self.yaw(pose[3:]);delta=yaw-np.pi/2
        rotation=Rotation.from_euler('z',delta).as_matrix()
        heights={'laptop':.023,'backpack':.093,'coat':.018}
        updates=[]
        for item in self.payload_specs:
            if item['tray_id']!=f'tray_{tray}' or item['flex']:continue
            kind=item['kind'];offset=np.array([0.,-.13,heights[kind]])
            position=pose[:3]+rotation@offset;quat=np.array([np.cos(delta/2),0,0,np.sin(delta/2)])
            i=self.sensor_index[item['name']]
            self.rigid.set_world_poses(positions=self.gpu(position[None]),orientations=self.gpu(quat[None]),indices=self.gpu([i],index=True))
            self.rigid.set_velocities(self.gpu(np.zeros((1,6))),indices=self.gpu([i],index=True))
            updates.append(dict(name=item['name'],position_world=position.tolist(),orientation_wxyz=quat.tolist()))
            # Clone composed visual materials before revealing this payload only.
            subtree=self.stage.GetPrimAtPath(self.paths[item['name']]);flat=self.stage.Flatten();material_map={}
            UsdGeom.Scope.Define(self.stage,'/NativeLoadedMaterials')
            for prim in list(Usd.PrimRange(subtree,Usd.TraverseInstanceProxies())):
                if not prim.IsA(UsdGeom.Gprim):continue
                writable=prim
                while writable.IsInstanceProxy():writable=writable.GetParent()
                if writable.IsA(UsdGeom.Gprim):UsdGeom.Gprim(writable).CreateDisplayOpacityAttr([1.])
                material,_=UsdShade.MaterialBindingAPI(prim).ComputeBoundMaterial()
                if not material:continue
                old=material.GetPath()
                if str(old) not in material_map:
                    new=Sdf.Path('/NativeLoadedMaterials/'+item['name']+'_'+str(len(material_map)))
                    if not Sdf.CopySpec(flat,old,self.stage.GetSessionLayer(),new):raise NativeTaskFault('native_payload_visual_material_clone_failed')
                    for child in Usd.PrimRange(self.stage.GetPrimAtPath(new)):
                        for attr in child.GetAttributes():
                            connections=attr.GetConnections()
                            if connections:attr.SetConnections([p.ReplacePrefix(old,new) for p in connections])
                        if child.IsA(UsdShade.Shader):
                            shader=UsdShade.Shader(child);opacity=shader.GetInput('opacity')
                            if opacity:opacity.Set(1.)
                    material_map[str(old)]=new
                UsdShade.MaterialBindingAPI.Apply(writable).Bind(UsdShade.Material(self.stage.GetPrimAtPath(material_map[str(old)])),
                    bindingStrength=UsdShade.Tokens.strongerThanDescendants)
        element=next(e for e in ET.parse(self.root/'asset/import_only.xml').getroot().iter('flexcomp')
            if e.get('name')==f'tray_{tray}_passenger_coat')
        vertices=[]
        for line in Path(element.attrib['file']).read_text().splitlines():
            fields=line.split()
            if fields and fields[0]=='v':vertices.append(list(map(float,fields[1:4])))
        nodes=pose[:3]+(np.asarray(vertices)+np.array([0.,.13,heights['coat']]))@rotation.T
        self.coats[tray].set_nodal_positions(nodes[None]);self.coats[tray].set_nodal_velocities(np.zeros_like(nodes)[None])
        UsdGeom.Imageable(self.stage.GetPrimAtPath(self.coat_conversions[tray]['path'])).MakeVisible()
        self._last_obs=None
        after=self.observation();unchanged=np.array_equal(protected,np.r_[after['state'],after['tray_pose'].ravel(),after['tray_velocity'].ravel()])
        if not unchanged:raise NativeTaskFault('payload_load_changed_live_robot_or_trays')
        self.loaded[tray]=True;self._last_obs=None;observer.loaded(self.frames,f'tray_{tray}',cycle,protected_unchanged=True)
        self.event('passenger_payload_only_state_transition',tray_id=f'tray_{tray}',cycle_id=cycle,
            actual_tray_pose=pose.tolist(),rigid_updates=updates,coat_nodes_world=nodes.tolist(),
            robot_all_trays_unchanged=True,training_eligible=False)

    def close(self):
        exits={}
        for name,(encoder,path,log) in self.encoders.items():
            encoder.stdin.close();exits[name]=dict(returncode=encoder.wait(),path=str(path));log.close()
        self.write('encoder_exits.json',exits)
        if self.raw_arrays['state']:
            obs=self.observation();self.raw_arrays['time'].append(float(self.world.current_time))
            self.raw_arrays['state'].append(obs['state']);self.raw_arrays['tray_pose'].append(obs['tray_pose'])
            self.raw_arrays['rigid_pose'].append(obs['rigid_pose']);self.raw_arrays['payload_loaded'].append(obs['loaded'])
            self.raw_arrays['long_edge_sign'].append(obs['long_edge_sign'])
            for key in ('payload_speed','payload_on_tray','boundary_ok','axis_error_rad','front_region_ok',*FRONT_FIELDS):
                self.raw_arrays[key].append(np.asarray(obs[key]).copy())
            np.savez_compressed(self.output/'native_trace.npz',**{k:np.asarray(v) for k,v in self.raw_arrays.items()})
        return exits
