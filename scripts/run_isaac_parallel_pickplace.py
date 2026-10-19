"""Independent feedback teachers in one shared PhysX clock; no command replay."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import traceback
import threading
from types import SimpleNamespace

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from r1pro_teleop.real2sim.isaac_parallel_collection import (
    CAMERAS, BoundedVideoWriter, batched_joint_targets, room_origins, write_json)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=Path, required=True)
    args = parser.parse_args()
    cfg = json.loads(args.config.read_text())
    out = Path(cfg['output']); out.mkdir(parents=True, exist_ok=False)
    n = int(cfg['rooms'])
    policy_mode=cfg.get('execution_mode','teacher')=='policy'
    if policy_mode and not 1<=n<=32:raise ValueError('invalid_policy_room_count')
    grid_count=next(k for k in (1,4,8,16,32) if k>=n) if policy_mode else n
    origins=room_origins(grid_count)[:n]
    if cfg.get('execution_mode','teacher') not in ('teacher','policy'):raise ValueError('invalid_parallel_execution_mode')
    status = dict(scope='training_scene_native_closed_loop_diagnostic' if policy_mode else 'parallel_fixed_base_pickplace_collection', training_eligible=False,
                  model_executed=False, model_execution_requested=policy_mode, pid=os.getpid(), rooms=n, frames=0)
    def report(stage, **kw):
        status.update(stage=stage, heartbeat_unix=time.time(), **kw)
        write_json(out/'status.json', status)
    import resource
    soft,hard=resource.getrlimit(resource.RLIMIT_NOFILE)
    target=65536 if hard==resource.RLIM_INFINITY else min(hard,65536)
    if soft!=resource.RLIM_INFINITY and soft<target:resource.setrlimit(resource.RLIMIT_NOFILE,(target,hard))
    status['file_descriptor_limit']=dict(before_soft=soft,hard=hard,after_soft=resource.getrlimit(resource.RLIMIT_NOFILE)[0])
    report('initializing')
    from isaacsim import SimulationApp
    app = SimulationApp(dict(headless=True, active_gpu=0, physics_gpu=0,
                             multi_gpu=not policy_mode, max_gpu_count=1 if policy_mode else 2, fast_shutdown=True))
    writers = {}; closure = {}; error = None; rc = 1; runtimes=[]; threads=[]; overview=None
    try:
        import torch
        import mujoco
        import omni.usd
        from pxr import Usd, UsdGeom, UsdPhysics, UsdLux, Gf, Sdf
        from isaacsim.core.api import World
        from isaacsim.core.cloner import Cloner
        from isaacsim.core.prims import Articulation, RigidPrim
        from isaacsim.core.simulation_manager import SimulationManager
        from isaacsim.sensors.camera import Camera
        from r1pro_teleop.real2sim.isaac_lab_visuals import apply_lab_visuals
        from r1pro_teleop.real2sim.isaac_rubber_contacts import restore_soft_finger_contacts
        from r1pro_teleop.real2sim.isaac_mobile import d6_targets, mobile_targets
        def cpu(x): return x.detach().cpu().numpy() if hasattr(x, 'detach') else np.asarray(x)
        device = 'cpu' if policy_mode and cfg.get('runtime_profile')=='realtime' else 'cuda:0'
        def gpu(x, index=False):
            return torch.as_tensor(x, dtype=torch.int64 if index else torch.float32, device=device)
        root = Path(cfg['scene_root'])
        receipt = json.loads((root/'control/validation.json').read_text())
        wait=json.loads((root/'control_exit.json').read_text())
        if receipt.get('passed') is not True or wait.get('actual_child_wait') is not True or wait.get('returncode')!=0:raise ValueError('scene_specific_native_preflight_not_closed')
        source = Path(receipt['scene_path'])
        if hashlib.sha256(source.read_bytes()).hexdigest() != receipt['scene_sha256']:
            raise ValueError('parallel_source_identity_changed')
        context = omni.usd.get_context()
        if not context.open_stage(str(source)):
            raise ValueError('parallel_source_stage_open_failed')
        stage = context.get_stage(); stage.SetEditTarget(stage.GetSessionLayer())
        model = mujoco.MjModel.from_xml_path(str(root/'asset/import_only.xml'))
        write_json(out/'rubber_translation.json', restore_soft_finger_contacts(stage, model))
        visual_report=apply_lab_visuals(stage, cfg['lab_assets'], model)
        write_json(out/'visual_translation.json', visual_report)
        # This is an empty-tray Pick/Place-only derivative. Do not simulate
        # unused coats, passenger rigid bodies or the other two trays.
        removed = []
        removal_paths = []
        for prim in stage.Traverse():
            name = prim.GetName()
            if name in ('tray_1', 'tray_2') or '_passenger_' in name or 'deformable' in name.lower():
                if not prim.IsInstanceProxy():
                    removal_paths.append(str(prim.GetPath()))
        for path in sorted(removal_paths, key=len, reverse=True):
            prim = stage.GetPrimAtPath(path)
            if prim:
                prim.SetActive(False); removed.append(path)
        from r1pro_teleop.real2sim.isaac_collision_footprint import native_mesh_footprint
        source_paths={p.GetName():str(p.GetPath()) for p in stage.Traverse() if p.HasAPI(UsdPhysics.RigidBodyAPI)}
        footprint_report=native_mesh_footprint(stage,source_paths['tray_0'])
        footprint_report['validated_scene_sha256']=receipt['scene_sha256']
        inventory=json.loads((root/'preparation/legacy_inventory.json').read_text())
        manifest_path=root/'source_scene.json'
        if not manifest_path.exists():manifest_path=next((root/'preparation/scenes/train').glob('*/scene.json'))
        manifest=json.loads(manifest_path.read_text())
        parent_source=next(r for r in inventory['sources'] if r['parent_scene_id']==manifest['parent_scene_id'])
        parent=json.loads(Path(parent_source['legacy_source']['scene_json']).read_text())
        tables=parent['tables'];size=np.array(parent['trays'][0].get('dimensions_m',[.56,.43,.105]))
        table_roots={t['table_id'] for t in tables if t['table_id'] in source_paths}
        table_filters=[source_paths[t] for t in sorted(table_roots)];table_owners=sorted(table_roots)
        for prim in Usd.PrimRange.Stage(stage,Usd.TraverseInstanceProxies()):
            if not prim.HasAPI(UsdPhysics.CollisionAPI) or not UsdPhysics.CollisionAPI(prim).GetCollisionEnabledAttr().Get():continue
            for t in tables:
                if t['table_id'] not in table_roots and '/'+t['table_id']+'/' in str(prim.GetPath()):
                    table_filters.append(str(prim.GetPath()));table_owners.append(t['table_id']);break
        template = out/'room_source.usda'
        stage.Flatten().Export(str(template))
        report('source_derivative_prepared')
        source_default = str(stage.GetDefaultPrim().GetPath())
        # References to the physics root do not bring sibling laboratory
        # materials into that reference's namespace. Retarget visual bindings
        # explicitly inside the complete room before cloning its namespace.
        visual_bindings=[]
        for prim in Usd.PrimRange.Stage(stage,Usd.TraverseInstanceProxies()):
            path=str(prim.GetPath())
            if not path.startswith(source_default+'/'):continue
            for rel in prim.GetRelationships():
                targets=[str(p) for p in rel.GetTargets()]
                if rel.GetName().startswith('material:binding') and targets and all(p.startswith('/FastLabVisuals/') for p in targets):
                    visual_bindings.append((path,rel.GetName(),targets))
        camera_mapping = [r for r in json.loads((root/'asset/camera_mapping.json').read_text()) if r['name'] in CAMERAS]
        source_rigids = {p.GetName(): str(p.GetPath()) for p in stage.Traverse() if p.HasAPI(UsdPhysics.RigidBodyAPI)}
        robot_suffix = source_rigids['base_link']
        tray_suffix = source_rigids['tray_0']
        context.new_stage(); stage = context.get_stage()
        UsdGeom.Xform.Define(stage, '/World/envs/env_0')
        for source_path, dest in [(source_default, '/World/envs/env_0/Scene'),
                                  ('/FastLabVisuals', '/World/envs/env_0/Lab')]:
            stage.DefinePrim(dest, 'Xform').GetReferences().AddReference(str(template), source_path)
        for old,name,targets in visual_bindings:
            path='/World/envs/env_0/Scene'+old[len(source_default):]
            prim=stage.GetPrimAtPath(path)
            if not prim:raise ValueError('parallel_visual_relocation_missing')
            prim.CreateRelationship(name).SetTargets(['/World/envs/env_0/Lab'+p[len('/FastLabVisuals'):] for p in targets])
        cloner = Cloner(stage=stage); cloner.define_base_env('/World/envs')
        paths = cloner.generate_paths('/World/envs/env', n)
        cloner.clone(source_prim_path=paths[0], prim_paths=paths, positions=origins,
                     replicate_physics=False, copy_from_source=False)
        report('room_grid_cloned')
        def relocated(env, original):
            return paths[env]+'/Scene'+original[len(source_default):]
        robot_paths = [relocated(i, robot_suffix) for i in range(n)]
        tray_paths = [relocated(i, tray_suffix) for i in range(n)]
        # A world-attached D6's body0 frame is not a rigid body under the
        # room transform: explicitly shift its world anchor for each clone.
        mapping = json.loads((root/'control/mapping.json').read_text())
        drives = []
        for i in range(n):
            joint = UsdPhysics.Joint(stage.GetPrimAtPath(robot_paths[i]+'/agent_base_x'))
            body0 = joint.GetBody0Rel().GetTargets()
            if body0:
                if any(not str(p).startswith(paths[i]+'/') for p in body0):
                    raise ValueError('parallel_base_anchor_not_relocated:'+str(body0))
                # Imported static world body moves with its room; its local
                # joint anchor must remain unchanged.
            else:
                anchor = joint.GetLocalPos0Attr().Get()
                joint.GetLocalPos0Attr().Set(Gf.Vec3f(*(np.asarray(anchor)+origins[i])))
            drives.append([UsdPhysics.DriveAPI.Get(joint.GetPrim(), a) for a in ('transX','transY','rotZ')])
        world = World(stage_units_in_meters=1., physics_dt=.002, rendering_dt=.05,
                      backend='torch', device=device)
        SimulationManager.set_device(device)
        world.get_physics_context().enable_gpu_dynamics(device!='cpu')
        if policy_mode and cfg.get('runtime_profile')=='realtime':world.get_physics_context().enable_fabric(True)
        import carb
        write_json(out/'physics_runtime_settings.json',dict(physics_device=device,profile=cfg.get('runtime_profile','baseline'),fabric=SimulationManager.is_fabric_enabled(),updateToUsd=carb.settings.get_settings().get('/physics/updateToUsd'),physics_dt=.002,substeps=25))
        physics_scene = world.get_physics_context().prim_path
        cloner.filter_collisions(physics_scene, '/World/collision_groups', paths, [])
        robots = Articulation(prim_paths_expr=robot_paths, name='parallel_robots', reset_xform_properties=False)
        trays = RigidPrim(prim_paths_expr=tray_paths, name='parallel_trays', reset_xform_properties=False)
        world.scene.add(robots); world.scene.add(trays)
        from r1pro_teleop.real2sim.isaac_parallel_contacts import RoomContacts
        robot_names=[name for name,path in source_rigids.items() if path==robot_suffix or path.startswith(robot_suffix+'/')]
        sensor_names=list(dict.fromkeys([f'{side}_gripper_finger_link{k}' for side in ('left','right') for k in (1,2)]+['tray_0']+robot_names))
        filter_original=[tray_suffix]+table_filters+[source_rigids[name] for name in robot_names]
        filter_owners=['tray_0']+table_owners+robot_names
        contact_views=[]
        for i in range(n):
            filters=[relocated(i,p) for p in filter_original]
            view=RigidPrim(prim_paths_expr=[relocated(i,source_rigids[name]) for name in sensor_names],
                name=f'room_{i}_contacts',reset_xform_properties=False,track_contact_forces=True,
                contact_filter_prim_paths_expr=[filters for _ in sensor_names],max_contact_count=32768)
            world.scene.add(view);contact_views.append(view)
        dome=UsdLux.DomeLight.Define(stage,'/SharedDomeLight');dome.CreateIntensityAttr(600.)
        world.reset()
        physics_scenes=[str(p.GetPath()) for p in stage.Traverse() if p.IsA(UsdPhysics.Scene)]
        if len(physics_scenes)!=1:raise ValueError('parallel_requires_one_actual_physics_scene')
        report('native_views_initialized')
        from r1pro_teleop.real2sim.isaac_parallel_runtime import validate_actor_order
        actor_order=dict(robots=validate_actor_order(robot_paths,list(robots.prim_paths),kind='robots',native_actual=list(robots._physics_view.prim_paths)),trays=validate_actor_order(tray_paths,list(trays.prim_paths),kind='trays',native_actual=list(trays._physics_view.prim_paths)))
        write_json(out/'actor_order.json',actor_order)
        if robots.count != n or trays.count != n:
            raise ValueError('parallel_actor_count_mismatch')
        names = tuple(mobile_targets(np.zeros(19)))
        indices = gpu([robots.get_dof_index(name) for name in names], index=True)
        initial = np.asarray(mapping['source_initial_q'])
        robots.set_joint_positions(gpu(np.repeat(initial[None], n, axis=0)), joint_indices=indices)
        robots.set_joint_velocities(gpu(np.zeros((n, 18))), joint_indices=indices)
        cases=cfg['cases'][:n]
        if len(cases)!=n:raise ValueError('one_registered_case_per_room_required')
        from r1pro_teleop.real2sim.isaac_parallel_collection import validate_sources
        validate_sources(cases)
        if len({tuple(c['tray_pose']) for c in cases})!=n:raise ValueError('duplicate_room_initial_poses')
        base_pos,base_quat=[cpu(x).copy() for x in robots.get_world_poses()]
        base_origins=np.array([np.r_[p[:2]-o[:2],np.arctan2(2*(q[0]*q[3]+q[1]*q[2]),1-2*(q[2]**2+q[3]**2))] for p,q,o in zip(base_pos,base_quat,origins)])
        for i,c in enumerate(cases):
            station=np.asarray(c['initial_base_world'])
            if not np.array_equal(station,c['fixed_base_world']):raise ValueError('fixed_station_mismatch')
            base_pos[i,:2]=station[:2]+origins[i,:2]
            base_quat[i]=[np.cos(station[2]/2),0,0,np.sin(station[2]/2)]
        robots.set_world_poses(gpu(base_pos),gpu(base_quat))
        poses=np.asarray([c['tray_pose'] for c in cases])
        trays.set_world_poses(gpu(poses[:,:3]+origins),gpu(poses[:,3:]))
        trays.set_velocities(gpu(np.zeros((n,6))))
        readers=[RoomContacts(v,sensor_names,filter_owners,origins[i],size,tables,footprint_report['body_local_vertices_m']) for i,v in enumerate(contact_views)]
        (out/'rooms').mkdir()
        cameras = []; render_assignments = {}
        for i in range(n):
            d = out/'rooms'/f'room_{i:03d}'; d.mkdir()
            for row in camera_mapping:
                camera = Camera(prim_path=relocated(i,row['path']), name=f"room_{i}_{row['name']}",
                                frequency=20, resolution=CAMERAS[row['name']])
                camera.initialize(); cameras.append((i,row['name'],camera))
                if cfg.get('pin_render_products_to_gpus',False):
                    product=stage.GetPrimAtPath(camera.get_render_product_path())
                    assignment=[i%2]
                    product.CreateAttribute('deviceIds',Sdf.ValueTypeNames.UIntArray,custom=True).Set(assignment)
                    render_assignments[str(product.GetPath())]=list(product.GetAttribute('deviceIds').Get())
                writers[i,row['name']] = BoundedVideoWriter(d/(row['name']+'.mp4'), CAMERAS[row['name']])
        write_json(out/'render_product_assignments.json',dict(assignments=render_assignments,
            actual_gpu_workload_verified=False,method='USD RenderProduct deviceIds; workload verification required'))
        presentation=[]
        for i in range(n):
            path=f'/World/Presentation_{i}'
            prim=UsdGeom.Camera.Define(stage,path)
            prim.CreateHorizontalApertureAttr(36.);prim.CreateVerticalApertureAttr(20.25)
            prim.CreateFocalLengthAttr(23.);prim.CreateClippingRangeAttr(Gf.Vec2f(.03,30.))
            eye=np.array([2.4,-2.3,1.85])+origins[i];target=np.array([.3,0.,1.])+origins[i]
            matrix=Gf.Matrix4d().SetLookAt(Gf.Vec3d(*eye),Gf.Vec3d(*target),Gf.Vec3d(0,0,1)).GetInverse()
            UsdGeom.Xformable(prim).AddTransformOp().Set(matrix)
            camera=Camera(prim_path=path,name=f'overview_{i}',frequency=20,resolution=(320,180))
            camera.initialize();presentation.append(camera)
        columns=int(np.ceil(np.sqrt(n)));rows=int(np.ceil(n/columns))
        overview=BoundedVideoWriter(out/'global_overview.mp4',(columns*320,rows*180))
        stage.GetRootLayer().Export(str(out/'grid.usda'))
        for _ in range(8):world.render()
        def read_states():
            q=cpu(robots.get_joint_positions(joint_indices=indices)).copy()
            pos,quat=[cpu(x).copy() for x in robots.get_world_poses()]
            pos-=origins
            yaw=np.arctan2(2*(quat[:,0]*quat[:,3]+quat[:,1]*quat[:,2]),1-2*(quat[:,2]**2+quat[:,3]**2))
            states=np.c_[q[:,:7],q[:,7]+q[:,8],q[:,9:16],q[:,16]+q[:,17],pos[:,:2]-base_origins[:,:2],np.arctan2(np.sin(yaw-base_origins[:,2]),np.cos(yaw-base_origins[:,2]))]
            return states,q,np.c_[pos,quat]
        states,joints,base_poses=read_states()
        commands=states.copy();commands[:,[7,15]]=.08
        fixed_base=commands[:,16:].copy()
        base_targets=np.asarray([d6_targets(a,mapping['native_d6_world_rotation']) for a in fixed_base])
        for group,values in zip(drives,base_targets):
            for drive,value in zip(group,values):drive.GetTargetPositionAttr().Set(float(value))
        robots.set_joint_position_targets(gpu(batched_joint_targets(commands)),joint_indices=indices)
        shadow=mujoco.MjData(model);shadow.qpos[:]=model.key_qpos[0] if model.nkey else model.qpos0
        source_base_q={name:float(shadow.qpos[model.jnt_qposadr[model.joint(name).id]]) for name in ('agent_base_x','agent_base_y','agent_base_yaw')}
        from r1pro_teleop.real2sim.isaac_parallel_runtime import ParallelRoomRuntime
        if policy_mode:
            from r1pro_teleop.real2sim.isaac_policy_pickplace import run_policy_room as controller_target
            def policy_images(room):
                from PIL import Image
                result={}
                for ri,name,camera in cameras:
                    if ri!=room or name=='head_right':continue
                    image=Image.fromarray(np.asarray(camera.get_rgba())[:,:,:3].astype(np.uint8))
                    image.thumbnail((224,224),Image.Resampling.BILINEAR)
                    padded=Image.new('RGB',(224,224));padded.paste(image,((224-image.width)//2,(224-image.height)//2));result[name]=np.asarray(padded).copy()
                return result
        else:
            from r1pro_teleop.real2sim.isaac_parallel_runtime import run_room_controller as controller_target
        for i,c in enumerate(cases):
            d=out/'rooms'/f'room_{i:03d}'
            obs=readers[i].observation(states[i],commands[i],base_poses[i],poses[i,2]);obs['joint_position']=joints[i];obs['measured_wall_time']=time.time()
            if policy_mode:obs['policy_images']=policy_images(i)
            runtime=ParallelRoomRuntime(i,d,root/'asset/import_only.xml',parent,size[None],base_origins[i],source_base_q,obs,commands[i],boundary_footprints={'tray_0':np.asarray(footprint_report['body_local_vertices_m'])},initial_time=float(world.current_time))
            runtimes.append(runtime)
            runtime.write('initial_base_station.json',dict(requested_world=c['initial_base_world'],original_drive_origin=base_origins[i].tolist(),fixed_command=fixed_base[i].tolist(),initialization_only_before_first_step=True))
            runtime.write('initialization.json',dict(seed=c['seed'],parent_scene_id=c['parent_scene_id'],parent_split=c['parent_split'],tray_pose=c['tray_pose'],room_origin=origins[i].tolist(),initialization_only_before_first_step=True))
            runtime.write('tray_0_collision_footprint.json',footprint_report)
            runtime.write('visual_translation.json',visual_report)
            runtime.write('native_mapping.json',dict(sensor_paths=list(contact_views[i].prim_paths),filter_paths=[relocated(i,p) for p in filter_original],filter_owner=filter_owners,scene_sha256=receipt['scene_sha256'],task_tables=tables,room_origin=origins[i].tolist(),coordinate_frame='room_local',source_planner='private_mj_kinematics_no_mj_step',live_pose_resets_after_initialization=False))
        write_json(out/'identity.json',dict(source_scene=str(source),source_sha256=receipt['scene_sha256'],rooms=n,origins=origins.tolist(),robot_paths=robot_paths,tray_paths=tray_paths,requested_render_gpus=1 if policy_mode else 2,physics_gpu=0,physics_dt=.002,record_hz=20,global_substeps_per_frame=25,physics_scenes=physics_scenes,initial_simulation_time=float(world.current_time),source_type='learned_policy_native_physx' if policy_mode else 'independent_feedback_expert_native_physx',model_executed=False,model_execution_requested=policy_mode,room_cases=cases,training_eligible=False))
        live_started=time.monotonic()
        def publish_live(frame):
            if cfg.get('live_evaluation'):
                from r1pro_teleop.real2sim.studio_live_view import publish
                publish(out,cases,contact_views,readers,origins,cameras,presentation,states,frame,live_started,cpu)
        publish_live(0)
        for runtime,c in zip(runtimes,cases):
            thread=threading.Thread(target=controller_target,args=(runtime,c),daemon=True)
            threads.append(thread);thread.start()
        previous=commands.copy();frame=0;start=time.monotonic();last_report=0.;last_joint_feedback=0.
        timings=dict(planning_wait=0.,render=0.,readback_encode=0.,physics_contacts=0.,physics_step=0.,contact_read=0.,post_render=0.,live_publish=0.)
        report('running_independent_feedback_shared_clock',frames=0,active_rooms=n)
        while True:
            wait_start=time.monotonic()
            while True:
                pending=[r.pending_command() for r in runtimes]
                active=[i for i,r in enumerate(runtimes) if not r.exchange.done]
                if all(pending[i] is not None for i in active):break
                if policy_mode and time.monotonic()-last_joint_feedback>.1:
                    fresh_states,_,_=read_states()
                    for i in active:runtimes[i].refresh_joint_feedback(fresh_states[i],time.time())
                    last_joint_feedback=time.monotonic()
                if time.monotonic()-last_report>10:
                    report('planning_shared_clock_barrier',frames=frame,active_rooms=len(active),ready_rooms=sum(p is not None for p in pending),elapsed_seconds=time.monotonic()-start,timings=timings)
                    last_report=time.monotonic()
                time.sleep(.002)
            timings['planning_wait']+=time.monotonic()-wait_start
            if not active:break
            for i in active:
                commands[i]=pending[i]
                if not np.array_equal(commands[i,16:],fixed_base[i]):raise ValueError('parallel_fixed_base_command_changed')
                with (runtimes[i].output/'native_contacts.jsonl').open('a') as f:
                    f.write(json.dumps(dict(frame=runtimes[i].frames,global_frame=frame,sim_time=float(world.current_time),contacts=readers[i].contact_rows))+'\n')
            t=time.monotonic()
            # Policy mode already rendered this state after the previous physics tick.
            if not policy_mode:world.render()
            timings['render']+=time.monotonic()-t
            t=time.monotonic()
            for i,name,camera in cameras:
                if i in active:writers[i,name].put(np.asarray(camera.get_rgba())[:,:,:3].astype(np.uint8))
            grid=np.zeros((rows*180,columns*320,3),np.uint8)
            for i,camera in enumerate(presentation):
                row,col=divmod(i,columns);grid[row*180:(row+1)*180,col*320:(col+1)*320]=np.asarray(camera.get_rgba())[:,:,:3].astype(np.uint8)
            overview.put(grid);timings['readback_encode']+=time.monotonic()-t
            if policy_mode:
                with (out/'wall_clock_frames.jsonl').open('a') as clock_log:clock_log.write(json.dumps(dict(frame=frame,unix=time.time(),wall_seconds=time.monotonic()-start,simulation_seconds=frame/20))+chr(10))
            t=time.monotonic();records={i:dict(completed_real_substeps=25,submitted_control=[],finger_contact_force=[],table_force=[],payload_rigid_support=[],penetration=[]) for i in active}
            for sub in range(1,26):
                batch=previous+(commands-previous)*(sub/25.)
                target=batched_joint_targets(batch)
                robots.set_joint_position_targets(gpu(target),joint_indices=indices)
                step_started=time.monotonic();world.step(render=False);timings['physics_step']+=time.monotonic()-step_started
                contact_started=time.monotonic()
                for i in active:
                    fingers,table,support,depth=readers[i].contact()
                    rec=records[i];rec['submitted_control'].append(np.r_[target[i],base_targets[i]])
                    rec['finger_contact_force'].append(fingers);rec['table_force'].append(table)
                    rec['payload_rigid_support'].append(support);rec['penetration'].append(depth)
                            
                timings['contact_read']+=time.monotonic()-contact_started
            timings['physics_contacts']+=time.monotonic()-t
            states,joints,base_poses=read_states()
            post_started=time.monotonic()
            if policy_mode:world.render()
            timings['post_render']+=time.monotonic()-post_started
            for i in active:
                obs=readers[i].observation(states[i],commands[i],base_poses[i],poses[i,2]);obs['joint_position']=joints[i];obs['measured_wall_time']=time.time()
                if policy_mode:obs['policy_images']=policy_images(i)
                runtimes[i].complete_tick(obs,float(world.current_time),records[i])
            previous=commands.copy();frame+=1
            live_tick=time.monotonic();publish_live(frame);timings['live_publish']+=time.monotonic()-live_tick
            if cfg.get('realtime_pacing'):
                # Never accelerate physics to catch up after inference/render delays.
                time.sleep(max(0.,.05-(time.monotonic()-wait_start)))
            if frame%10==0:
                report('running_independent_feedback_shared_clock',frames=frame,active_rooms=len(active),global_real_substeps=frame*25,simulation_seconds=frame/20,elapsed_seconds=time.monotonic()-start,timings=timings)
                last_report=time.monotonic()
                import subprocess
                gpu_sample=subprocess.run(['nvidia-smi','--query-compute-apps=pid,gpu_uuid,used_gpu_memory','--format=csv,noheader'],capture_output=True,text=True)
                with (out/'gpu_samples.jsonl').open('a') as f:f.write(json.dumps(dict(unix=time.time(),native_pid=os.getpid(),stdout=gpu_sample.stdout,returncode=gpu_sample.returncode))+'\n')
        for thread in threads:thread.join()
        for runtime in runtimes:runtime.close_trace()
        rc=0
        report('physical_batch_closed_pending_media',frames=frame,global_real_substeps=frame*25,simulation_seconds=frame/20,elapsed_seconds=time.monotonic()-start,timings=timings,room_frames=[r.frames for r in runtimes])
    except BaseException as exc:
        error=dict(error=repr(exc),traceback=traceback.format_exc());write_json(out/'failure.json',error)
        for runtime in runtimes:runtime.abort(exc)
        for thread in threads:thread.join(timeout=5)
        for runtime in runtimes:
            if runtime.exchange.done:
                try:runtime.close_trace()
                except Exception:pass
    finally:
        for key,writer in writers.items():
            try:closure[f'{key[0]}_{key[1]}']=writer.close()
            except BaseException as exc:closure[f'{key[0]}_{key[1]}']=dict(error=repr(exc),returncode=1)
        if overview is not None:
            try:
                result=overview.close();result.update(global_start_frame=0,shared_world_render=True)
                write_json(out/'global_overview.json',result)
            except BaseException as exc:rc=1;write_json(out/'overview_failure.json',dict(error=repr(exc)))
        write_json(out/'media_exit.json',closure)
        for i,runtime in enumerate(runtimes):
            encoders={name:closure[f'{i}_{name}'] for name in CAMERAS if f'{i}_{name}' in closure}
            result=getattr(runtime,'worker_result',dict(passed=False,error=error,actions=[]))
            media_good=len(encoders)==4 and all(e.get('returncode')==0 and e.get('frames')==runtime.frames for e in encoders.values())
            result.update(case=cfg['cases'][i],native_encoders=encoders,video_demo_complete=bool(result.get('passed') and media_good),motion={},frames=runtime.frames,raw_fps=20,model_executed=result.get('model_executed',False) if policy_mode else False,training_eligible=False,scope='training_scene_native_closed_loop_diagnostic' if policy_mode else 'parallel_fixed_base_pickplace_candidate',shared_engine_receipt=str(out.parent/'native.exit.json'))
            runtime.write('result.json',result)
        report('parallel_batch_closed' if rc==0 else 'failed',error=error,actual_native_exit_intent=rc)
        app.close(wait_for_replicator=False,skip_cleanup=True,exit_code=rc)


if __name__=='__main__':main()
