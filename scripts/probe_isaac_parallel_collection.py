"""One-engine grid integration probe, never a qualified training collection.

Replays recorded expert *commands* into fresh PhysX rooms. Observed poses are
only initialized before stepping. No recorded object pose is replayed live.
This probe validates batching, timing and cameras before adaptive collection.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import traceback

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
    n = int(cfg['rooms']); origins = room_origins(n)
    status = dict(scope='parallel_engine_integration_probe', training_eligible=False,
                  model_executed=False, pid=os.getpid(), rooms=n, frames=0)
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
                             multi_gpu=True, max_gpu_count=2, fast_shutdown=True))
    writers = {}; closure = {}; error = None; rc = 1
    try:
        import torch
        import mujoco
        import omni.usd
        from pxr import Usd, UsdGeom, UsdPhysics, Gf, Sdf
        from isaacsim.core.api import World
        from isaacsim.core.cloner import Cloner
        from isaacsim.core.prims import Articulation, RigidPrim
        from isaacsim.core.simulation_manager import SimulationManager
        from isaacsim.sensors.camera import Camera
        from r1pro_teleop.real2sim.isaac_lab_visuals import apply_lab_visuals
        from r1pro_teleop.real2sim.isaac_rubber_contacts import restore_soft_finger_contacts
        from r1pro_teleop.real2sim.isaac_mobile import d6_targets, mobile_targets
        def cpu(x): return x.detach().cpu().numpy() if hasattr(x, 'detach') else np.asarray(x)
        device = 'cuda:0'
        def gpu(x, index=False):
            return torch.as_tensor(x, dtype=torch.int64 if index else torch.float32, device=device)
        root = Path(cfg['scene_root'])
        receipt = json.loads((root/'control/validation.json').read_text())
        source = Path(receipt['scene_path'])
        if hashlib.sha256(source.read_bytes()).hexdigest() != receipt['scene_sha256']:
            raise ValueError('parallel_source_identity_changed')
        context = omni.usd.get_context()
        if not context.open_stage(str(source)):
            raise ValueError('parallel_source_stage_open_failed')
        stage = context.get_stage(); stage.SetEditTarget(stage.GetSessionLayer())
        model = mujoco.MjModel.from_xml_path(str(root/'asset/import_only.xml'))
        write_json(out/'rubber_translation.json', restore_soft_finger_contacts(stage, model))
        write_json(out/'visual_translation.json', apply_lab_visuals(stage, cfg['lab_assets'], model))
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
        world.get_physics_context().enable_gpu_dynamics(True)
        physics_scene = world.get_physics_context().prim_path
        cloner.filter_collisions(physics_scene, '/World/collision_groups', paths, [])
        robots = Articulation(prim_paths_expr=robot_paths, name='parallel_robots', reset_xform_properties=False)
        trays = RigidPrim(prim_paths_expr=tray_paths, name='parallel_trays', reset_xform_properties=False)
        world.scene.add(robots); world.scene.add(trays)
        world.reset()
        physics_scenes=[str(p.GetPath()) for p in stage.Traverse() if p.IsA(UsdPhysics.Scene)]
        if len(physics_scenes)!=1:raise ValueError('parallel_requires_one_actual_physics_scene')
        report('native_views_initialized')
        if robots.count != n or trays.count != n:
            raise ValueError('parallel_actor_count_mismatch')
        names = tuple(mobile_targets(np.zeros(19)))
        indices = gpu([robots.get_dof_index(name) for name in names], index=True)
        initial = np.asarray(mapping['source_initial_q'])
        robots.set_joint_positions(gpu(np.repeat(initial[None], n, axis=0)), joint_indices=indices)
        robots.set_joint_velocities(gpu(np.zeros((n, 18))), joint_indices=indices)
        source_case = Path(cfg['command_source'])
        source_cfg = json.loads((source_case.parent/'case_000.config.json').read_text())
        pose = np.asarray(source_cfg['tray_pose'])
        trays.set_world_poses(gpu(pose[None,:3]+origins), gpu(np.repeat(pose[None,3:], n, axis=0)))
        trays.set_velocities(gpu(np.zeros((n, 6))))
        cameras = []; render_assignments = {}
        for i in range(n):
            d = out/f'room_{i:03d}'; d.mkdir()
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
        stage.GetRootLayer().Export(str(out/'grid.usda'))
        for _ in range(8):world.render()
        with np.load(source_case/'native_trace.npz') as trace:
            commands = trace['raw_action'].copy()
        frames = min(len(commands), int(cfg.get('frames', len(commands))))
        write_json(out/'identity.json', dict(source_scene=str(source), source_sha256=receipt['scene_sha256'],
            command_source=str(source_case), command_trace_sha256=hashlib.sha256((source_case/'native_trace.npz').read_bytes()).hexdigest(),
            rooms=n, origins=origins.tolist(), robot_paths=robot_paths, tray_paths=tray_paths,
            requested_render_gpus=2, actual_renderer_gpu_usage='requires_process_device_evidence',
            physics_gpu=0, physics_dt=.002, record_hz=20, global_substeps_per_frame=25,physics_scenes=physics_scenes,
            relocated_visual_material_bindings=len(visual_bindings),
            removed_inactive_scope_objects=removed, camera_resolution=CAMERAS,
            source_type='recorded_expert_commands_fresh_native_physics_not_VLA', training_eligible=False))
        previous = commands[0].copy(); observations=[]; tray_observations=[]; submitted=[]; robot_poses=[]
        start = time.monotonic(); timings=dict(render=0.,readback_encode=0.,physics=0.,state_readback=0.)
        report('running_native_shared_clock')
        for frame in range(frames):
            t=time.monotonic()
            q=cpu(robots.get_joint_positions(joint_indices=indices)).copy()
            pos, quat = [cpu(x).copy() for x in trays.get_world_poses()]
            observations.append(q);tray_observations.append(np.c_[pos-origins,quat])
            base_pos,base_quat=[cpu(x).copy() for x in robots.get_world_poses()]
            robot_poses.append(np.c_[base_pos-origins,base_quat])
            timings['state_readback']+=time.monotonic()-t
            t=time.monotonic();world.render();timings['render']+=time.monotonic()-t
            t=time.monotonic()
            for i,name,camera in cameras:
                rgba=np.asarray(camera.get_rgba())
                writers[i,name].put(rgba[:,:,:3].astype(np.uint8))
            timings['readback_encode']+=time.monotonic()-t
            t=time.monotonic();controls=[]
            for sub in range(1,26):
                action=previous+(commands[frame]-previous)*(sub/25.)
                batch=np.repeat(action[None],n,axis=0)
                target=batched_joint_targets(batch)
                robots.set_joint_position_targets(gpu(target), joint_indices=indices)
                base=d6_targets(action[16:],mapping['native_d6_world_rotation'])
                for group in drives:
                    for drive,value in zip(group,base):drive.GetTargetPositionAttr().Set(float(value))
                world.step(render=False)  # ONE global step, not one per room.
                controls.append(target)
            submitted.append(controls);previous=commands[frame].copy()
            timings['physics']+=time.monotonic()-t
            if frame%10==0:
                report('running_native_shared_clock',frames=frame+1,global_real_substeps=(frame+1)*25,
                       simulation_seconds=(frame+1)/20,elapsed_seconds=time.monotonic()-start,timings=timings)
        observations.append(cpu(robots.get_joint_positions(joint_indices=indices)).copy())
        pos,quat=[cpu(x).copy() for x in trays.get_world_poses()]
        tray_observations.append(np.c_[pos-origins,quat])
        base_pos,base_quat=[cpu(x).copy() for x in robots.get_world_poses()]
        robot_poses.append(np.c_[base_pos-origins,base_quat])
        np.savez_compressed(out/'probe_trace.npz',joint_position=np.asarray(observations),
            tray_pose=np.asarray(tray_observations),submitted_control=np.asarray(submitted),
            raw_action=np.repeat(commands[:frames,None,:],n,axis=1),origins=origins,
            robot_pose=np.asarray(robot_poses))
        if not np.isfinite(observations).all() or not np.isfinite(tray_observations).all():
            raise ValueError('parallel_nonfinite_physics')
        rc=0
        report('native_probe_complete_pending_media',frames=frames,global_real_substeps=frames*25,
               simulation_seconds=frames/20,elapsed_seconds=time.monotonic()-start,timings=timings,
               complete_task_passed=False,adaptive_controller_implemented=False,
               camera_isolation_audited=False)
    except BaseException as exc:
        error=dict(error=repr(exc),traceback=traceback.format_exc())
        write_json(out/'failure.json',error)
    finally:
        for key,writer in writers.items():
            try:closure[f'{key[0]}_{key[1]}']=writer.close()
            except BaseException as exc:closure[str(key)]=dict(error=repr(exc),returncode=1)
        if any(r.get('returncode')!=0 for r in closure.values()):rc=1
        write_json(out/'media_exit.json',closure)
        report('integration_probe_closed' if rc==0 else 'failed',error=error,actual_native_exit_intent=rc)
        # All trace writes and encoder waits above are already closed. Avoid
        # Kit's stage-close teardown crash with many multi-GPU render products;
        # this is the installed SDK's supported immediate shutdown path.
        app.close(wait_for_replicator=False,skip_cleanup=True,exit_code=rc)


if __name__=='__main__':main()
