"""Re-execute a registered historical expert reference in native PhysX.

This migration diagnostic records NEW physics and four native cameras. It
never inherits historical success and cannot enter training without a separate
native task observer/qualification. No MuJoCo stepping or runtime IK is used.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import time
import traceback


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--frames', type=int, help='Explicit shorter diagnostic, never full-task data')
    args = parser.parse_args(); root = args.root
    args.output.mkdir(parents=True, exist_ok=False)
    def save(name, data):
        (args.output / name).write_text(json.dumps(data, indent=2))
    def status(stage, **data):
        save('status.json', dict(stage=stage, unix=time.time(), training_started=False, **data))
    receipt = json.loads((root / 'control/validation.json').read_text())
    exit_receipt = json.loads((root / 'control_exit.json').read_text())
    if not receipt['passed'] or exit_receipt.get('returncode') != 0 or not exit_receipt.get('actual_child_wait'):
        raise ValueError('Native case-specific control validation must close first')
    scene = Path(receipt['scene_path'])
    if hashlib.sha256(scene.read_bytes()).hexdigest() != receipt['scene_sha256']:
        raise ValueError('Native validated scene changed')
    spec = importlib.util.spec_from_file_location('native_mobile', Path(__file__).with_name('isaac_mobile.py'))
    mobile = importlib.util.module_from_spec(spec); spec.loader.exec_module(mobile)
    import numpy as np
    import torch
    reference = np.load(root / 'teacher_reference.npz', allow_pickle=False)
    source = json.loads((root / 'source_provenance.json').read_text())
    segments = json.loads((root / 'source_segments.json').read_text())
    runtime_metadata = json.loads((root / 'source_runtime_metadata.json').read_text())
    scene_metadata = runtime_metadata['scene']
    load_indices = np.flatnonzero(np.diff(reference['payload_loaded'].reshape(-1)) != 0) + 1
    if len(load_indices) != 1:
        raise ValueError('Exactly one source environmental loading event required')
    load_frame = int(load_indices[0])
    count = len(reference['action']) if args.frames is None else min(args.frames, len(reference['action']))
    status('initializing_native_reference', frames=count, execution_mode='reference_reexecution_diagnostic')
    from isaacsim import SimulationApp
    app = SimulationApp(dict(headless=True, active_gpu=0, physics_gpu=0, multi_gpu=False, fast_shutdown=True))
    code = 0; encoders = {}; arrays = {}; completed = 0
    def numpy(value):
        if hasattr(value, 'detach'):
            return value.detach().cpu().numpy()
        if hasattr(value, 'numpy'):
            return value.numpy()
        return np.asarray(value)
    def gpu(value, index=False):
        return torch.as_tensor(value, dtype=torch.int64 if index else torch.float32, device='cuda:0')
    try:
        import omni.usd
        from pxr import UsdPhysics, UsdLux, UsdGeom, UsdShade, Usd
        from isaacsim.core.api import World
        from isaacsim.core.prims import SingleArticulation, SingleRigidPrim, RigidPrim
        from isaacsim.core.experimental.prims import DeformablePrim
        from isaacsim.core.simulation_manager import SimulationManager
        from isaacsim.sensors.camera import Camera
        if not omni.usd.get_context().open_stage(str(scene)):
            raise RuntimeError('isaac_reference_scene_open_failed')
        stage = omni.usd.get_context().get_stage(); stage.SetEditTarget(stage.GetSessionLayer())
        bodies = {prim.GetName(): str(prim.GetPath()) for prim in stage.Traverse() if prim.HasAPI(UsdPhysics.RigidBodyAPI)}
        actor_path = bodies['base_link']; tray_path = bodies['tray']
        finger_paths = [bodies[f'{side}_gripper_finger_link{i}'] for side in ('left', 'right') for i in (1, 2)]
        world = World(stage_units_in_meters=1., physics_dt=.002, rendering_dt=.05, backend='torch', device='cuda:0')
        SimulationManager.set_device('cuda:0')
        contact = RigidPrim(prim_paths_expr=finger_paths, name='finger_contacts',
            reset_xform_properties=False, track_contact_forces=True,
            contact_filter_prim_paths_expr=[[tray_path] for _ in finger_paths], max_contact_count=512)
        light = UsdLux.DomeLight.Define(stage, '/NativeEpisodeDomeLight')
        light.CreateIntensityAttr(600.)
        save('lighting.json', dict(type='dome', intensity=600, calibrated_real_lighting=False))
        world.reset()
        robot = SingleArticulation(prim_path=actor_path, name='native_robot'); robot.initialize()
        names = tuple(mobile.mobile_targets(np.zeros(19)))
        indices = gpu([robot.get_dof_index(name) for name in names], index=True)
        initial = mobile.mobile_targets(reference['state'][0])
        robot.set_joint_positions(gpu([initial[name] for name in names]), joint_indices=indices)
        robot.set_joint_velocities(gpu(np.zeros(18)), joint_indices=indices)
        xyz, quat = [numpy(value) for value in robot.get_world_pose()]
        w, x, y, z = quat
        base_origin = [float(xyz[0]), float(xyz[1]), float(np.arctan2(2 * (w*z+x*y), 1-2*(y*y+z*z)))]
        mapping = json.loads((root / 'control/mapping.json').read_text())
        base_joint = stage.GetPrimAtPath(actor_path + '/agent_base_x')
        backend = mobile.IsaacMobile19Backend(robot, base_joint, mapping['native_d6_world_rotation'],
            base_origin, receipt, scene_sha256=receipt['scene_sha256'])
        tray = SingleRigidPrim(prim_path=tray_path, name='native_tray'); tray.initialize()
        initial_tray = reference['tray_pose'][0].reshape(-1, 7)[0]
        tray.set_world_pose(position=gpu(initial_tray[:3]), orientation=gpu(initial_tray[3:]))
        tray.set_linear_velocity(gpu([0, 0, 0])); tray.set_angular_velocity(gpu([0, 0, 0]))
        payloads = {}
        for item in scene_metadata['payloads']:
            if not item['flex']:
                entity = SingleRigidPrim(prim_path=bodies[item['name']], name=item['name']); entity.initialize()
                payloads[item['kind']] = entity
        coat = DeformablePrim('/NativePassengerCoat', deformable_type='surface')
        contact.initialize()
        cameras = {}
        for row in json.loads((root / 'asset02/camera_mapping.json').read_text()):
            if row['name'] not in ('head_left', 'head_right', 'left_wrist', 'right_wrist'):
                continue
            sensor = Camera(prim_path=row['path'], name=row['name'], frequency=20, resolution=tuple(row['resolution']))
            sensor.initialize(); cameras[row['name']] = (sensor, row)
            path = args.output / (row['name'] + '.mp4')
            log = open(args.output / (row['name'] + '_encoder.log'), 'wb')
            command = ['ffmpeg', '-nostdin', '-v', 'error', '-n', '-f', 'rawvideo', '-pix_fmt', 'rgb24',
                '-s', f"{row['resolution'][0]}x{row['resolution'][1]}", '-r', '20', '-i', 'pipe:0',
                '-an', '-c:v', 'libx264', '-preset', 'fast', '-crf', '18', '-threads', '2', str(path)]
            encoders[row['name']] = (subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=log), path)
        # Camera warmup never advances the physical simulation.
        backend.command(reference['action'][0])
        for _ in range(8):
            world.render()
        arrays = {name: [] for name in ['time', 'state', 'raw_action', 'action', 'submitted_control',
            'tray_pose', 'finger_contact_force', 'coat_positions']}
        events = []
        def tray_pose():
            position, orientation = [numpy(value) for value in tray.get_world_pose()]
            return np.r_[position, orientation]
        def load_payload():
            before = np.r_[backend.observe(), tray_pose()]
            actual = tray_pose(); w, x, y, z = actual[3:]
            yaw = np.arctan2(2*(w*z+x*y), 1-2*(y*y+z*z)); delta = yaw - np.pi/2
            rotation = np.array([[np.cos(delta), -np.sin(delta), 0], [np.sin(delta), np.cos(delta), 0], [0, 0, 1]])
            layout = scene_metadata['passenger_layout']
            for kind, entity in payloads.items():
                offset = np.array(layout['offsets_world_m'][kind], float)
                offset[2] += layout['heights_above_tray_origin_m'][kind]
                entity.set_world_pose(position=gpu(actual[:3] + rotation @ offset),
                    orientation=gpu([np.cos(delta/2), 0, 0, np.sin(delta/2)]))
                entity.set_linear_velocity(gpu([0, 0, 0])); entity.set_angular_velocity(gpu([0, 0, 0]))
                for prim in Usd.PrimRange(stage.GetPrimAtPath(bodies['passenger_' + kind])):
                    if prim.IsA(UsdGeom.Gprim):
                        UsdGeom.Gprim(prim).CreateDisplayOpacityAttr([1.])
                    material, _ = UsdShade.MaterialBindingAPI(prim).ComputeBoundMaterial()
                    if material:
                        for shader_prim in Usd.PrimRange(material.GetPrim()):
                            if shader_prim.IsA(UsdShade.Shader):
                                opacity = UsdShade.Shader(shader_prim).GetInput('opacity')
                                if opacity:
                                    opacity.Set(1.)
            coat_meta = json.loads((root / 'control/coat_conversion.json').read_text())
            import xml.etree.ElementTree as ET
            element = next(e for e in ET.parse(root / 'asset02/import_only.xml').getroot().iter('flexcomp') if e.get('name') == 'passenger_coat')
            coat_spec = importlib.util.spec_from_file_location('coat_source', Path(__file__).with_name('isaacsim_deformable_coat.py'))
            coat_module = importlib.util.module_from_spec(coat_spec); coat_spec.loader.exec_module(coat_module)
            vertices, _ = coat_module.read_obj(element.attrib['file'])
            offset = np.array(layout['offsets_world_m']['coat']); offset[2] += layout['heights_above_tray_origin_m']['coat']
            positions = actual[:3] + (np.asarray(vertices) + offset) @ rotation.T
            coat.set_nodal_positions(positions[None]); coat.set_nodal_velocities(np.zeros_like(positions)[None])
            after = np.r_[backend.observe(), tray_pose()]
            if not np.array_equal(before, after):
                raise RuntimeError('native_payload_loading_changed_robot_or_tray')
            return dict(event='passenger_load', frame=load_frame, sim_time=float(world.current_time),
                robot_tray_unchanged=True, training_eligible=False, actual_tray_pose=actual.tolist())
        for frame in range(count):
            if frame == load_frame:
                events.append(load_payload()); save('events.json', events)
            state = backend.observe(); pose = tray_pose()
            arrays['time'].append(float(world.current_time)); arrays['state'].append(state); arrays['tray_pose'].append(pose)
            for name, (sensor, row) in cameras.items():
                world.render() if name == 'head_left' else None
                image = np.asarray(sensor.get_rgba())
                if image.shape != (row['resolution'][1], row['resolution'][0], 4):
                    raise RuntimeError('native_reference_camera_frame_invalid:' + name)
                encoders[name][0].stdin.write(image[:, :, :3].astype(np.uint8).tobytes())
            raw = np.asarray(reference['action'][frame])
            control = backend.command(raw)
            arrays['raw_action'].append(raw.copy()); arrays['action'].append(raw.copy())
            controls, forces = [], []
            for _ in range(25):
                world.step(render=False)
                controls.append(control['values'].copy())
                forces.append(numpy(contact.get_contact_force_matrix(dt=.002)).reshape(4, -1, 3).sum(axis=1))
            arrays['submitted_control'].append(controls); arrays['finger_contact_force'].append(forces)
            positions, _, _ = coat.get_nodal_positions(); arrays['coat_positions'].append(numpy(positions)[0])
            completed = frame + 1
            if frame % 20 == 0:
                status('native_reference_running', completed_frames=completed, total_frames=count,
                    tray_z=float(pose[2]), current_action='pick' if frame < 224 else 'place' if frame < 611 else 'load' if frame < 651 else 'flush')
        arrays['time'].append(float(world.current_time)); arrays['state'].append(backend.observe()); arrays['tray_pose'].append(tray_pose())
        save('diagnostic_result.json', dict(engine='isaacsim', physics_backend='physx',
            execution_mode='reference_reexecution_diagnostic', frames=completed,
            expert_reference_engine='mujoco', old_success_inherited=False,
            task_success=None, training_eligible=False, model_executed=False,
            initial_tray=initial_tray.tolist(), final_tray=tray_pose().tolist(),
            max_tray_z=float(np.asarray(arrays['tray_pose'])[:, 2].max()),
            qualification='native_complete_task_observer_not_yet_implemented'))
        status('native_reference_recorded_validation_pending', completed_frames=completed, total_frames=count)
    except Exception:
        code = 1; status('failed', completed_frames=completed, error=traceback.format_exc()); raise
    finally:
        if arrays:
            np.savez_compressed(args.output / 'native_trace_partial_or_complete.npz',
                **{name: np.asarray(values) for name, values in arrays.items()})
        exits = {}
        for name, (encoder, path) in encoders.items():
            encoder.stdin.close(); exits[name] = dict(returncode=encoder.wait(), path=str(path))
        save('encoder_exits.json', exits)
        if any(row['returncode'] != 0 for row in exits.values()):
            code = 1
        app.close(exit_code=code)


if __name__ == '__main__':
    main()
