"""Restore compiled source mass/COM/principal inertia on a NEW native asset.

The importer can otherwise infer tens of kilograms from overlapping visual
volumes. This is a source-parameter translation, never an arbitrary mass tweak.
"""
import argparse
import hashlib
import json
from pathlib import Path


def convert(source_usd,source_xml,output):
    from pxr import Usd,UsdPhysics,Gf,Sdf
    import mujoco
    model=mujoco.MjModel.from_xml_path(str(source_xml))
    stage=Usd.Stage.Open(str(source_usd));stage.SetEditTarget(stage.GetSessionLayer());rows=[]
    names={model.body(i).name:i for i in range(1,model.nbody)}
    for prim in stage.Traverse():
        if not prim.HasAPI(UsdPhysics.RigidBodyAPI):continue
        name=prim.GetName()
        if name not in names:continue
        i=names[name];mass=float(model.body_mass[i])
        if mass<=0:continue
        api=UsdPhysics.MassAPI.Apply(prim)
        before=dict(mass=api.GetMassAttr().Get(),diagonal_inertia=str(api.GetDiagonalInertiaAttr().Get()))
        api.CreateMassAttr(mass);api.CreateCenterOfMassAttr(Gf.Vec3f(*map(float,model.body_ipos[i])))
        api.CreateDiagonalInertiaAttr(Gf.Vec3f(*map(float,model.body_inertia[i])))
        q=list(map(float,model.body_iquat[i]));api.CreatePrincipalAxesAttr(Gf.Quatf(q[0],Gf.Vec3f(*q[1:])))
        rows.append(dict(name=name,path=str(prim.GetPath()),before=before,source_mass_kg=mass,
            source_center_of_mass_m=model.body_ipos[i].tolist(),source_principal_inertia_kg_m2=model.body_inertia[i].tolist(),
            source_inertial_quaternion_wxyz=q))
    if not rows:raise ValueError('no_source_rigid_mass_properties_translated')
    # Preserve the source equality on the passive finger, rather than adding a
    # second actuator (which would double the available gripping effort).
    joints={p.GetName():p for p in stage.Traverse() if p.IsA(UsdPhysics.Joint)}
    couplings=[]
    for arm in ('left','right'):
        active=joints[f'{arm}_gripper_finger_joint1'];passive=joints[f'{arm}_gripper_finger_joint2']
        source_pair=[model.joint(active.GetName()).id,model.joint(passive.GetName()).id]
        matches=[i for i in range(model.neq) if int(model.eq_type[i])==int(mujoco.mjtEq.mjEQ_JOINT)
                 and {int(model.eq_obj1id[i]),int(model.eq_obj2id[i])}==set(source_pair)]
        if len(matches)!=1 or list(model.eq_data[matches[0]][:5])!=[0.,1.,0.,0.,0.]:
            raise ValueError('source_finger_equality_not_identity')
        passive.AddAppliedSchema('NewtonMimicAPI')
        passive.CreateAttribute('newton:mimicCoef0',Sdf.ValueTypeNames.Double).Set(0.)
        passive.CreateAttribute('newton:mimicCoef1',Sdf.ValueTypeNames.Double).Set(1.)
        passive.CreateRelationship('newton:mimicJoint').SetTargets([active.GetPath()])
        couplings.append(dict(passive=str(passive.GetPath()),reference=str(active.GetPath()),coefficient=1.))
    stage.Export(str(output))
    result=dict(schema='airport_isaac_source_mass_properties/1',source_usd=str(source_usd),source_xml=str(source_xml),
        output_usd=str(output),source_xml_sha256=hashlib.sha256(Path(source_xml).read_bytes()).hexdigest(),
        output_sha256=hashlib.sha256(Path(output).read_bytes()).hexdigest(),bodies=rows,
        arbitrary_mass_tuning=False,native_measured_mass_validation_required=True,finger_couplings=couplings)
    Path(output).with_suffix('.mass.json').write_text(json.dumps(result,indent=2));return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--usd',type=Path,required=True);parser.add_argument('--xml',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    if args.output.exists():raise FileExistsError(args.output)
    print(json.dumps(dict(bodies=len(convert(args.usd,args.xml,args.output)['bodies']),output=str(args.output))))
