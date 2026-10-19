"""Translate the source flex surface to a native PhysX surface-deformable body.

This is an asset translation, not a task-success or material-calibration claim.
Imports happen after SimulationApp has initialized.
"""
from pathlib import Path
import xml.etree.ElementTree as ET


def read_obj(path):
    points, triangles = [], []
    for line in Path(path).read_text().splitlines():
        parts = line.split()
        if not parts:
            continue
        if parts[0] == 'v':
            points.append([float(x) for x in parts[1:4]])
        elif parts[0] == 'f':
            face = [int(x.split('/')[0]) - 1 for x in parts[1:]]
            if len(face) != 3 or min(face) < 0:
                raise ValueError('isaac_coat_triangular_positive_obj_indices_required')
            triangles.append(face)
    if not points or not triangles or max(max(row) for row in triangles) >= len(points):
        raise ValueError('isaac_invalid_coat_mesh')
    return points, triangles


def convert_coat(stage, xml, *, flex_name='passenger_coat', native_path='/NativePassengerCoat'):
    import numpy as np
    from pxr import UsdGeom, UsdPhysics, PhysxSchema, Gf
    from omni.physx.scripts import deformableUtils, physicsUtils
    source = Path(xml)
    flexes = list(ET.parse(source).getroot().iter('flexcomp'))
    flex, = [element for element in flexes if element.get('name') == flex_name]
    if flex.get('dim') != '2' or flex.get('type') != 'mesh':
        raise ValueError('isaac_source_surface_coat_required')
    points, triangles = read_obj(source.parent / flex.attrib['file'])
    disabled = []
    # Remove imported uncoupled flex-node bodies from this NEW variant only.
    node_paths = [str(prim.GetPath()) for prim in stage.Traverse()
        if prim.GetName().startswith(flex_name + '_') and prim.HasAPI(UsdPhysics.RigidBodyAPI)]
    for node_path in node_paths:
        stage.GetPrimAtPath(node_path).SetActive(False)
        disabled.append(node_path)
    path = native_path
    body = UsdGeom.Xform.Define(stage, path)
    position = list(map(float, flex.attrib['pos'].split()))
    body.AddTranslateOp().Set(Gf.Vec3d(*position))
    mesh = UsdGeom.Mesh.Define(stage, path + '/skin')
    mesh.CreatePointsAttr([Gf.Vec3f(*p) for p in points])
    mesh.CreateFaceVertexCountsAttr([3] * len(triangles))
    mesh.CreateFaceVertexIndicesAttr(np.asarray(triangles).ravel().tolist())
    mesh.CreateSubdivisionSchemeAttr('none')
    mesh.CreateDoubleSidedAttr(True)
    rgba = list(map(float, flex.attrib['rgba'].split()))
    mesh.CreateDisplayColorAttr([Gf.Vec3f(*rgba[:3])])
    deformableUtils.create_auto_surface_deformable_hierarchy(stage,
        root_prim_path=path, simulation_mesh_path=path + '/simMesh',
        cooking_src_mesh_path=str(mesh.GetPath()), cooking_src_simplification_enabled=False,
        set_visibility_with_guide_purpose=True)
    root = body.GetPrim()
    root.ApplyAPI('PhysxSurfaceDeformableBodyAPI')
    root.GetAttribute('physxDeformableBody:selfCollision').Set(True)
    root.GetAttribute('physxDeformableBody:solverPositionIterationCount').Set(16)
    UsdPhysics.MassAPI.Apply(root).CreateMassAttr(float(flex.attrib['mass']))
    contact = flex.find('contact'); elastic = flex.find('elasticity')
    material = native_path + 'Material'
    friction = float(contact.attrib['friction'].split()[0])
    ok = deformableUtils.add_surface_deformable_material(stage, material,
        static_friction=friction, dynamic_friction=friction,
        youngs_modulus=float(elastic.attrib['young']), poissons_ratio=float(elastic.attrib['poisson']),
        surface_thickness=float(elastic.attrib['thickness']))
    if not ok:
        raise RuntimeError('isaac_native_coat_material_creation_failed')
    physicsUtils.add_physics_material_to_prim(stage, root, material)
    material_prim = stage.GetPrimAtPath(material)
    material_prim.ApplyAPI('PhysxSurfaceDeformableMaterialAPI')
    material_prim.GetAttribute('physxDeformableMaterial:elasticityDamping').Set(float(elastic.attrib['damping']))
    sim = stage.GetPrimAtPath(path + '/simMesh')
    collision = PhysxSchema.PhysxCollisionAPI.Apply(sim)
    collision.CreateRestOffsetAttr(float(flex.attrib['radius']))
    collision.CreateContactOffsetAttr(2 * float(flex.attrib['radius']))
    return dict(schema='airport_isaac_native_coat_conversion/1', path=path,
        vertices=len(points), triangles=len(triangles), mass_kg=float(flex.attrib['mass']),
        young_pa=float(elastic.attrib['young']), poisson=float(elastic.attrib['poisson']),
        elastic_thickness_m=float(elastic.attrib['thickness']), friction=friction,
        disabled_imported_node_bodies=disabled, source_engine='mujoco',
        target_engine='isaacsim', target_physics='physx_surface_deformable',
        material_equivalence_verified=False, task_success=None)
