"""Native Isaac Sim scene import audit; never labels import as task success.

Run with the existing Isaac Sim Python environment. MuJoCo parses source
assets only; this PhysX probe uses no MuJoCo stepping or hardware commands.
"""
import argparse
import hashlib
import json
from pathlib import Path
import time
import traceback
import xml.etree.ElementTree as ET
import math


def source_inventory(path):
    """Resolve includes and inventory features that require conversion auditing."""
    files, tags, names = {}, {}, {}
    def visit(p):
        p = p.resolve()
        if str(p) in files:
            return
        raw = p.read_bytes()
        files[str(p)] = hashlib.sha256(raw).hexdigest()
        root = ET.fromstring(raw)
        for element in root.iter():
            tags[element.tag] = tags.get(element.tag, 0) + 1
            if element.get('name'):
                names.setdefault(element.tag, []).append(element.get('name'))
            if element.tag == 'include':
                visit(p.parent / element.attrib['file'])
    visit(Path(path))
    return dict(files=files, tags=tags, names=names)


def prepare_import_copy(source, output):
    """Translate parser-only options; never run this copy as a MuJoCo experiment."""
    source = Path(source).resolve()
    root = ET.parse(source).getroot()
    if list(root.iter('include')):
        raise ValueError('isaac_import_copy_nested_includes_require_expansion')
    changes = []
    for element in root.iter():
        if element.get('file'):
            element.set('file', str((source.parent / element.get('file')).resolve()))
        if element.tag == 'option' and element.get('integrator') == 'discrete':
            changes.append(dict(field='option.integrator', source='discrete',
                conversion_parse_only='implicitfast', native_physics='PhysX',
                equivalent_dynamics_claimed=False))
            element.set('integrator', 'implicitfast')
    path = Path(output) / 'import_only.xml'
    ET.ElementTree(root).write(path, encoding='utf-8', xml_declaration=True)
    (Path(output) / 'conversion_changes.json').write_text(json.dumps(changes, indent=2))
    return path


def restore_cameras(stage, xml):
    """MJCF and USD optical frames both look along -Z with +Y up."""
    import mujoco
    from pxr import UsdGeom, UsdPhysics, Gf
    model = mujoco.MjModel.from_xml_path(str(xml))
    rigid = {}
    for prim in stage.Traverse():
        if prim.HasAPI(UsdPhysics.RigidBodyAPI):
            rigid.setdefault(prim.GetName(), []).append(prim)
    rows = []
    for index in range(model.ncam):
        name = model.camera(index).name
        body = model.body(int(model.cam_bodyid[index])).name
        if int(model.cam_mode[index]) != 0:
            raise ValueError('isaac_camera_nonfixed_mode_requires_adapter')
        parents = rigid.get(body, [])
        if int(model.cam_bodyid[index]) == 0:
            parents = [UsdGeom.Xform.Define(stage, '/TaskWorldCameras').GetPrim()]
        if len(parents) != 1:
            raise ValueError('isaac_camera_parent_missing_or_ambiguous:' + body)
        camera = UsdGeom.Camera.Define(stage, parents[0].GetPath().AppendChild(name))
        xyz = [float(x) for x in model.cam_pos[index]]
        w, x, y, z = [float(x) for x in model.cam_quat[index]]
        xf = UsdGeom.Xformable(camera.GetPrim())
        xf.ClearXformOpOrder()
        xf.AddTranslateOp().Set(Gf.Vec3d(*xyz))
        xf.AddOrientOp().Set(Gf.Quatf(w, Gf.Vec3f(x, y, z)))
        resolution = [int(x) for x in model.cam_resolution[index]]
        if min(resolution) <= 0:
            raise ValueError('isaac_camera_missing_source_resolution:' + name)
        vertical = 24.
        camera.CreateVerticalApertureAttr(vertical)
        camera.CreateHorizontalApertureAttr(vertical * resolution[0] / resolution[1])
        camera.CreateFocalLengthAttr(vertical / (2 * math.tan(math.radians(float(model.cam_fovy[index])) / 2)))
        camera.CreateClippingRangeAttr(Gf.Vec2f(.01, 1000.))
        rows.append(dict(name=name, path=str(camera.GetPath()), source_body=body,
            position_m=xyz, quaternion_wxyz=[w, x, y, z], resolution=resolution,
            fovy_degrees=float(model.cam_fovy[index]), optical_axis='-Z', up_axis='+Y'))
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--xml', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--steps', type=int, default=100)
    parser.add_argument('--usd', type=Path, help='Reuse an immutable previously converted USD')
    parser.add_argument('--capture', action='store_true', help='Render four diagnostic camera PNGs, not training data')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    def status(stage, **fields):
        data = dict(stage=stage, unix=time.time(), **fields)
        temp = args.output / 'status.tmp'
        temp.write_text(json.dumps(data, indent=2))
        temp.replace(args.output / 'status.json')
    source = source_inventory(args.xml)
    (args.output / 'source_inventory.json').write_text(json.dumps(source, indent=2))
    app = None
    exit_code = 0
    try:
        status('initializing_isaacsim')
        from isaacsim import SimulationApp
        app = SimulationApp(dict(headless=True, active_gpu=0, physics_gpu=0, fast_shutdown=True,
                                 multi_gpu=False, width=640, height=480))
        from isaacsim.core.utils.extensions import enable_extension
        enable_extension('isaacsim.asset.importer.mjcf')
        import omni.kit.commands
        import omni.usd
        from pxr import UsdGeom, UsdPhysics
        from isaacsim.core.api import World
        status('importing_scene')
        omni.usd.get_context().new_stage()
        import isaacsim.asset.importer.mjcf as mjcf
        if args.usd:
            import_xml = prepare_import_copy(args.xml, args.output)
            usd_path = args.usd.resolve()
            result = str(usd_path)
        elif hasattr(mjcf, 'MJCFImporterConfig'):
            # Isaac 6 uses a native Python conversion pipeline, not the 5.x command.
            import_xml = prepare_import_copy(args.xml, args.output)
            config = mjcf.MJCFImporterConfig(mjcf_path=str(import_xml),
                usd_path=str(args.output / 'converted'), import_scene=True,
                collision_from_visuals=False, allow_self_collision=True,
                fix_base=None, debug_mode=True)
            result = mjcf.MJCFImporter(config).import_mjcf()
            usd_path = Path(result)
        else:
            ok, config = omni.kit.commands.execute('MJCFCreateImportConfig')
            if not ok:
                raise RuntimeError('isaac_mjcf_config_failed')
            config.set_fix_base(False)
            config.set_make_default_prim(True)
            usd_path = args.output / 'imported.usd'
            ok, result = omni.kit.commands.execute('MJCFCreateAsset',
                mjcf_path=str(args.xml.resolve()), import_config=config,
                prim_path='/Airport', dest_path=str(usd_path))
            if not ok:
                raise RuntimeError('isaac_mjcf_import_failed')
        # Importer's destination stage is explicitly opened before simulation.
        if not omni.usd.get_context().open_stage(str(usd_path)):
            raise RuntimeError('isaac_usd_open_failed')
        stage = omni.usd.get_context().get_stage()
        # Session edits keep a reused USD immutable; export this run's layer later.
        stage.SetEditTarget(stage.GetSessionLayer())
        UsdGeom.SetStageMetersPerUnit(stage, 1.)
        if hasattr(mjcf, 'MJCFImporterConfig'):
            cameras = restore_cameras(stage, import_xml)
            (args.output / 'camera_mapping.json').write_text(json.dumps(cameras, indent=2))
        rows = []
        for prim in stage.Traverse():
            if prim.IsA(UsdPhysics.Joint) or prim.HasAPI(UsdPhysics.RigidBodyAPI) or prim.IsA(UsdGeom.Camera):
                rows.append(dict(path=str(prim.GetPath()), type=prim.GetTypeName(),
                    schemas=list(prim.GetAppliedSchemas())))
        (args.output / 'usd_inventory.json').write_text(json.dumps(rows, indent=2))
        stage.Export(str(args.output / 'airport_scene.usda'))
        status('physics_smoke', imported_objects=len(rows), completed_steps=0)
        world = World(stage_units_in_meters=1., physics_dt=.002, rendering_dt=.05)
        world.reset()
        from isaacsim.core.prims import SingleArticulation
        import numpy as np
        roots = [p for p in stage.Traverse() if p.HasAPI(UsdPhysics.ArticulationRootAPI)]
        articulation_rows = []
        for index, prim in enumerate(roots):
            robot = SingleArticulation(prim_path=str(prim.GetPath()), name=f'audit_{index}')
            robot.initialize()
            q = np.asarray(robot.get_joint_positions())
            if not np.isfinite(q).all():
                raise RuntimeError('isaac_nonfinite_initial_joint_state')
            articulation_rows.append(dict(path=str(prim.GetPath()),
                dof_names=list(robot.dof_names), initial_positions=q.tolist()))
        (args.output / 'articulation_mapping.json').write_text(json.dumps(articulation_rows, indent=2))
        for step in range(args.steps):
            world.step(render=False)
            if (step + 1) % 20 == 0:
                status('physics_smoke', completed_steps=step + 1)
        if args.capture:
            status('rendering_diagnostic_cameras')
            from isaacsim.sensors.camera import Camera
            from pxr import UsdLux
            from PIL import Image
            light = UsdLux.DomeLight.Define(stage, '/DiagnosticDomeLight')
            light.CreateIntensityAttr(600.)
            sensors = []
            for row in cameras:
                if row['name'] in ['head_left', 'head_right', 'left_wrist', 'right_wrist']:
                    sensor = Camera(prim_path=row['path'], name=row['name'],
                                    frequency=20, resolution=tuple(row['resolution']))
                    sensor.initialize()
                    sensors.append((row, sensor))
            for _ in range(8):
                world.step(render=True)
            captures = []
            for row, sensor in sensors:
                rgba = np.asarray(sensor.get_rgba())
                if rgba.shape != (row['resolution'][1], row['resolution'][0], 4):
                    raise RuntimeError('isaac_camera_empty_or_wrong_resolution:' + row['name'])
                path = args.output / (row['name'] + '.png')
                Image.fromarray(rgba[:, :, :3].astype('uint8')).save(path)
                captures.append(dict(camera=row['name'], path=str(path),
                    shape=list(rgba.shape), pixel_mean=float(rgba[:, :, :3].mean()),
                    sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                    simulation_time=float(world.current_time), diagnostic_lighting=True,
                    training_eligible=False))
            (args.output / 'camera_captures.json').write_text(json.dumps(captures, indent=2))
        gaps = ['joint_drive_mapping_not_validated', 'native_camera_alignment_not_validated',
                'model_closed_loop_not_run', 'contact_equivalence_not_validated']
        if source['tags'].get('flexcomp') or source['tags'].get('flex'):
            gaps.append('mujoco_flex_requires_native_physx_deformable_conversion')
        report = dict(engine='isaacsim', scope='native_import_physics_smoke',
            steps=args.steps, physics_dt=.002, task_success=None,
            migration_complete=False, training_eligible=False, gaps=gaps,
            imported_objects=len(rows), importer_result=str(result))
        (args.output / 'report.json').write_text(json.dumps(report, indent=2))
        status('smoke_completed_migration_pending', **report)
    except Exception:
        exit_code = 1
        status('failed', error=traceback.format_exc())
        raise
    finally:
        if app is not None:
            import inspect
            if 'exit_code' in inspect.signature(app.close).parameters:
                app.close(exit_code=exit_code)
            else:
                app.close()


if __name__ == '__main__':
    main()
