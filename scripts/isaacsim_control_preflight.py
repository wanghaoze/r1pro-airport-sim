"""Native PhysX control calibration probe, never a task or training source."""
import argparse
import importlib.util
import json
from pathlib import Path
import sys
import time
import traceback


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--usd', required=True, type=Path)
    parser.add_argument('--xml', required=True, type=Path, help='Parser-compatible import copy')
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--native-coat', action='store_true')
    parser.add_argument('--coat-name', action='append', help='Explicit named coats in a new multi-tray scene')
    parser.add_argument('--restore-source-base-drives', action='store_true')
    parser.add_argument('--kinematic-audit', action='store_true')
    args = parser.parse_args()
    if args.coat_name and (not args.native_coat or len(set(args.coat_name)) != len(args.coat_name)):
        parser.error('Unique coat names require --native-coat')
    args.output.mkdir(parents=True, exist_ok=False)
    def save(name, data):
        (args.output / name).write_text(json.dumps(data, indent=2))
    def status(stage, **data):
        save('status.json', dict(stage=stage, unix=time.time(), **data))
    spec = importlib.util.spec_from_file_location('native_mobile', Path(__file__).with_name('isaac_mobile.py'))
    mobile = importlib.util.module_from_spec(spec); spec.loader.exec_module(mobile)
    import numpy as np
    from isaacsim import SimulationApp
    status('initializing_isaacsim')
    app = SimulationApp(dict(headless=True, active_gpu=0, physics_gpu=0, multi_gpu=False, fast_shutdown=True))
    exit_code = 0
    try:
        import omni.usd
        from pxr import UsdPhysics, UsdGeom, PhysxSchema, Gf
        from isaacsim.core.api import World
        from isaacsim.core.prims import SingleArticulation
        from isaacsim.core.utils.types import ArticulationAction
        import mujoco
        if not omni.usd.get_context().open_stage(str(args.usd)):
            raise RuntimeError('isaac_preflight_usd_open_failed')
        stage = omni.usd.get_context().get_stage()
        stage.SetEditTarget(stage.GetSessionLayer())
        roots = [p for p in stage.Traverse() if p.HasAPI(UsdPhysics.ArticulationRootAPI)]
        if len(roots) != 1:
            raise RuntimeError('isaac_preflight_one_robot_required')
        root = roots[0]
        joint = stage.GetPrimAtPath(root.GetPath().AppendChild('agent_base_x'))
        if not joint:
            raise RuntimeError('isaac_preflight_world_d6_missing')
        # Source model has exactly world X/Y/yaw, not a free six-axis chassis.
        for axis in ('transZ', 'rotX', 'rotY'):
            limit = UsdPhysics.LimitAPI.Apply(joint, axis)
            limit.CreateLowAttr(1.); limit.CreateHighAttr(-1.)
        validated_scene = args.output / 'validated_scene.usda'
        joint0 = UsdPhysics.Joint(joint)
        model = mujoco.MjModel.from_xml_path(str(args.xml))
        if args.restore_source_base_drives:
            drive_spec = importlib.util.spec_from_file_location('base_drives', Path(__file__).with_name('isaacsim_base_drives.py'))
            drive_module = importlib.util.module_from_spec(drive_spec); drive_spec.loader.exec_module(drive_module)
            save('base_drive_translation.json', drive_module.restore_missing(stage, joint, model))
        coat_conversions = []
        if args.native_coat:
            coat_spec = importlib.util.spec_from_file_location('native_coat', Path(__file__).with_name('isaacsim_deformable_coat.py'))
            coat_module = importlib.util.module_from_spec(coat_spec); coat_spec.loader.exec_module(coat_module)
            for name in args.coat_name or ['passenger_coat']:
                path = '/NativePassengerCoat' if name == 'passenger_coat' else '/NativePassengerCoat_' + name
                coat_conversions.append(coat_module.convert_coat(stage, args.xml, flex_name=name, native_path=path))
            save('coat_conversion.json', coat_conversions[0] if len(coat_conversions) == 1 else dict(coats=coat_conversions))
        local = joint0.GetLocalRot0Attr().Get()
        rotation = np.array(Gf.Matrix3d(local)).T
        # Body0 is the imported world root; include its world orientation.
        body0, = joint0.GetBody0Rel().GetTargets()
        transform = UsdGeom.Xformable(stage.GetPrimAtPath(body0)).ComputeLocalToWorldTransform(0.)
        rotation = np.array(transform.ExtractRotationMatrix()).T @ rotation
        mobile.d6_targets(np.zeros(3), rotation)
        drives = [UsdPhysics.DriveAPI.Get(joint, axis) for axis in ('transX', 'transY', 'rotZ')]
        if any(not drive for drive in drives):
            raise RuntimeError('isaac_preflight_d6_drives_missing')
        world = World(stage_units_in_meters=1., physics_dt=.002, rendering_dt=.05,
            backend='torch' if args.native_coat else 'numpy', device='cuda:0' if args.native_coat else 'cpu')
        if args.native_coat:
            from isaacsim.core.simulation_manager import SimulationManager
            SimulationManager.set_device('cuda:0')
            world.get_physics_context().enable_gpu_dynamics(True)
            scene_rows = []
            for prim in stage.Traverse():
                if prim.IsA(UsdPhysics.Scene):
                    api = PhysxSchema.PhysxSceneAPI.Apply(prim)
                    api.CreateEnableGPUDynamicsAttr(True)
                    api.CreateBroadphaseTypeAttr('GPU')
                    scene_rows.append(dict(path=str(prim.GetPath()),
                        gpu_dynamics=api.GetEnableGPUDynamicsAttr().Get()))
            save('physics_scenes.json', scene_rows)
        stage.Export(str(validated_scene))
        world.reset()
        coats = []
        if args.native_coat:
            from isaacsim.core.experimental.prims import DeformablePrim
            coats = [DeformablePrim(row['path'], deformable_type='surface') for row in coat_conversions]
        robot = SingleArticulation(prim_path=str(root.GetPath()), name='preflight_robot')
        robot.initialize()
        def numpy(value):
            return value.detach().cpu().numpy() if hasattr(value, 'detach') else np.asarray(value)
        def native(value, index=False):
            if args.native_coat:
                import torch
                return torch.as_tensor(value, dtype=torch.int64 if index else torch.float32, device='cuda:0')
            return np.asarray(value, dtype=int if index else float)
        names = tuple(mobile.mobile_targets(np.zeros(19)))
        indices = native([robot.get_dof_index(name) for name in names], index=True)
        q = model.key_qpos[0] if model.nkey else model.qpos0
        initial = np.array([q[model.jnt_qposadr[model.joint(name).id]] for name in names])
        robot.set_joint_positions(native(initial), joint_indices=indices)
        robot.set_joint_velocities(native(np.zeros(18)), joint_indices=indices)
        first_xyz, first_quat = [numpy(value) for value in robot.get_world_pose()]
        w, x, y, z = first_quat
        yaw0 = np.arctan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z))
        def observation():
            physical = dict(zip(names, numpy(robot.get_joint_positions(joint_indices=indices))))
            state = []
            for side in ('left', 'right'):
                state.extend(physical[f'{side}_arm_joint{i}'] for i in range(1, 8))
                state.append(sum(physical[f'{side}_gripper_finger_joint{i}'] for i in (1, 2)))
            xyz, quat = [numpy(value) for value in robot.get_world_pose()]; w, x, y, z = quat
            yaw = np.arctan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z))
            state.extend([xyz[0] - first_xyz[0], xyz[1] - first_xyz[1],
                np.arctan2(np.sin(yaw - yaw0), np.cos(yaw - yaw0))])
            return np.array(state), np.array(xyz)
        initial_state, _ = observation()
        def command(action):
            mapping = mobile.mobile_targets(action)
            targets = np.array([mapping[name] for name in names])
            robot.apply_action(ArticulationAction(joint_positions=native(targets), joint_indices=indices))
            for drive, value in zip(drives, mobile.d6_targets(action[16:], rotation)):
                drive.GetTargetPositionAttr().Set(float(value))
        targets = [('hold', initial_state.copy())]
        for name, index, delta in [('left_arm', 0, .04), ('right_arm', 8, .04),
                ('left_gripper', 7, -.01 if initial_state[7] >= .01 else .01),
                ('right_gripper', 15, -.01 if initial_state[15] >= .01 else .01),
                ('base_x', 16, .02), ('base_y', 17, .02), ('base_yaw', 18, .02)]:
            goal = initial_state.copy(); goal[index] += delta
            targets.append((name, goal))
        rows = []; trace = []
        for name, goal in targets:
            status('native_control_probe', probe=name)
            for _ in range(500):
                command(goal); world.step(render=False)
                state, xyz = observation()
                if not np.isfinite(np.r_[state, xyz]).all():
                    raise RuntimeError('isaac_preflight_nonfinite_physics')
                trace.append(np.r_[world.current_time, state, xyz])
            measured, xyz = observation()
            rows.append(dict(probe=name, target=goal.tolist(), measured=measured.tolist(),
                base_xyz=xyz.tolist(), error=(measured - goal).tolist()))
            physical=dict(zip(names,numpy(robot.get_joint_positions(joint_indices=indices))))
            rows[-1]['finger_positions_m']={side:[float(physical[f'{side}_gripper_finger_joint{i}']) for i in (1,2)]
                for side in ('left','right')}
            for side in ('left','right'):
                matches=[p for p in stage.Traverse() if p.IsA(UsdPhysics.Joint) and p.GetName()==f'{side}_gripper_finger_joint2']
                if len(matches)!=1:raise RuntimeError('native_finger_joint_identity_not_unique:'+side)
                finger=matches[0]
                if finger.HasAPI('NewtonMimicAPI'):
                    pair=rows[-1]['finger_positions_m'][side]
                    if abs(pair[0]-pair[1])>.001:
                        save('probe_results.json',rows)
                        raise RuntimeError('native_source_finger_coupling_not_reproduced:'+side)
            save('probe_results.json', rows)
        coat_probes = []
        for index, coat in enumerate(coats):
            positions, collision_positions, rest_positions = coat.get_nodal_positions()
            positions = positions.numpy()
            if not np.isfinite(positions).all():
                raise RuntimeError('isaac_native_coat_nonfinite')
            np.save(args.output / ('coat_native_positions.npy' if len(coats) == 1 else f'coat_{index}_native_positions.npy'), positions)
            coat_probes.append(dict(path=coat_conversions[index]['path'], shape=list(positions.shape),
                min_z=float(positions[..., 2].min()), max_z=float(positions[..., 2].max()),
                native_physics='physx_surface_deformable', material_equivalence_verified=False,
                task_success=None, training_eligible=False))
        if coat_probes:
            save('coat_native_probe.json', coat_probes[0] if len(coat_probes) == 1 else dict(coats=coat_probes))
        np.save(args.output / 'native_trace.npy', np.array(trace))
        if args.kinematic_audit:
            fk_spec=importlib.util.spec_from_file_location('fk_audit',Path(__file__).with_name('isaacsim_kinematic_audit.py'))
            fk_module=importlib.util.module_from_spec(fk_spec);fk_spec.loader.exec_module(fk_module)
            body_names=['base_link']+[f'{side}_{name}' for side in ('left','right')
                for name in ('arm_link7','gripper_link','gripper_finger_link1','gripper_finger_link2')]
            # Reuse the existing articulation view. Creating late rigid views
            # for articulation links is unsupported by the GPU tensor backend.
            view=robot._articulation_view
            transforms=numpy(view._physics_view.get_link_transforms())[0]
            link_indices={name:i for i,name in enumerate(view.body_names)}
            poses={}
            for name in body_names:
                pose=transforms[link_indices[name]]
                poses[name]=(pose[:3],pose[[6,3,4,5]])  # native tensor quaternion is XYZW
            measured=dict(zip(names,numpy(robot.get_joint_positions(joint_indices=indices))))
            save('source_fk_audit.json',fk_module.compare(model,measured,poses))
        save('mapping.json', dict(dof_names=names, indices=indices.tolist(),
            native_d6_world_rotation=rotation.tolist(), source_initial_q=initial.tolist()))
        # These are control-mapping diagnostic checks, not new task tolerances.
        arms = all(abs(row['error'][index]) < .02 for row, index in zip(rows[1:3], [0, 8]))
        grippers = all(abs(row['error'][index]) < .005 for row, index in zip(rows[3:5], [7, 15]))
        base = all(abs(row['error'][index]) < .01 and row['measured'][index] > .005
            for row, index in zip(rows[5:8], [16, 17, 18]))
        import hashlib
        result = dict(schema='airport_isaac_native_drive_validation/1', engine='isaacsim',
            physics_backend='physx', passed=bool(arms and grippers and base),
            arm_control_verified=bool(arms), gripper_control_verified=bool(grippers),
            base_control_verified=bool(base), scene_sha256=hashlib.sha256(validated_scene.read_bytes()).hexdigest(),
            scene_path=str(validated_scene), source_scene_sha256=hashlib.sha256(args.usd.read_bytes()).hexdigest(),
            initialization='source_MJCF_first_keyframe_scalar_joints_once_before_probe',
            tensor_backend='torch' if args.native_coat else 'numpy', device='cuda:0' if args.native_coat else 'cpu',
            task_success=None, training_eligible=False, probes=rows)
        save('validation.json', result)
        status('control_probe_complete', passed=result['passed'])
    except Exception:
        exit_code = 1; status('failed', error=traceback.format_exc()); raise
    finally:
        app.close(exit_code=exit_code)


if __name__ == '__main__':
    main()
