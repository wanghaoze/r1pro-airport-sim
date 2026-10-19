"""Restore nominal source sliding friction in a NEW PhysX USD layer.

MuJoCo uses one sliding coefficient and equal-priority max combination.
The importer authored dynamic friction but left static friction at zero.
This translation does not identify real hardware material parameters.
"""
import argparse
import hashlib
import json
from pathlib import Path


def source_friction_plan(model):
    rows = {}
    if model.npair:
        raise ValueError('isaac_explicit_contact_pairs_require_separate_translation')
    for index in range(model.ngeom):
        if not (model.geom_contype[index] or model.geom_conaffinity[index]):
            continue
        if model.geom_priority[index] != 0:
            raise ValueError('isaac_nondefault_friction_priority_requires_separate_translation')
        name = model.geom(index).name
        if not name:
            raise ValueError('isaac_named_contact_geometries_required')
        rows[name] = float(model.geom_friction[index, 0])
    return rows


def convert(source_usd, source_xml, output):
    from pxr import Usd, UsdPhysics, UsdShade, Sdf
    import mujoco
    model = mujoco.MjModel.from_xml_path(str(source_xml))
    friction = source_friction_plan(model)
    stage = Usd.Stage.Open(str(source_usd)); stage.SetEditTarget(stage.GetSessionLayer())
    materials, missing = {}, []
    for prim in Usd.PrimRange.Stage(stage, Usd.TraverseInstanceProxies()):
        if not prim.HasAPI(UsdPhysics.CollisionAPI) or not UsdPhysics.CollisionAPI(prim).GetCollisionEnabledAttr().Get():
            continue
        ancestor, geom = prim, None
        # Prototype child names can belong to a different source geometry.
        # Resolve the writable source instance, rather than its proxy child.
        while ancestor:
            if ancestor.GetName() in friction and not ancestor.IsInstanceProxy():
                geom = ancestor
            ancestor = ancestor.GetParent()
        if not geom:
            missing.append(str(prim.GetPath())); continue
        name = geom.GetName(); coefficient = friction[name]
        # A physics material may be absent on imported instanced primitives.
        # Author a per-source-geom material at its writable instance root.
        path = '/NativePhysicsMaterials/' + name
        if path in materials:
            continue
        material, _ = UsdShade.MaterialBindingAPI(prim).ComputeBoundMaterial(materialPurpose='physics')
        original = material
        material = UsdShade.Material.Define(stage, path)
        if original:
            for schema in original.GetPrim().GetAppliedSchemas():
                material.GetPrim().AddAppliedSchema(schema)
            for attr in original.GetPrim().GetAttributes():
                if attr.HasAuthoredValueOpinion():
                    material.GetPrim().CreateAttribute(attr.GetName(), attr.GetTypeName(),
                        custom=attr.IsCustom()).Set(attr.Get())
        UsdPhysics.MaterialAPI.Apply(material.GetPrim())
        UsdShade.MaterialBindingAPI.Apply(geom).Bind(material,
            bindingStrength=UsdShade.Tokens.strongerThanDescendants, materialPurpose='physics')
        api = UsdPhysics.MaterialAPI(material.GetPrim())
        materials[path] = dict(coefficient=coefficient,
            before_static=api.GetStaticFrictionAttr().Get(), before_dynamic=api.GetDynamicFrictionAttr().Get())
    if missing:
        raise ValueError('isaac_unmapped_active_collision_geometries:' + str(missing[:3]))
    for path, row in materials.items():
        prim = stage.GetPrimAtPath(path)
        api = UsdPhysics.MaterialAPI(prim)
        api.CreateStaticFrictionAttr(row['coefficient'])
        api.CreateDynamicFrictionAttr(row['coefficient'])
        prim.AddAppliedSchema('PhysxMaterialAPI')
        prim.CreateAttribute('physxMaterial:frictionCombineMode', Sdf.ValueTypeNames.Token).Set('max')
    stage.Export(str(output))
    report = dict(schema='airport_isaac_nominal_friction_translation/1',
        source_xml=str(source_xml), source_usd=str(source_usd), output_usd=str(output),
        materials=materials, combine_mode='max', static_and_dynamic='source_single_sliding_coefficient',
        real_hardware_calibration=False, contact_dynamics_equivalence_claimed=False,
        output_sha256=hashlib.sha256(Path(output).read_bytes()).hexdigest())
    Path(output).with_suffix('.materials.json').write_text(json.dumps(report, indent=2))
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--usd', type=Path, required=True)
    parser.add_argument('--xml', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    report = convert(args.usd, args.xml, args.output)
    print(json.dumps(dict(materials=len(report['materials']), output=str(args.output))))
