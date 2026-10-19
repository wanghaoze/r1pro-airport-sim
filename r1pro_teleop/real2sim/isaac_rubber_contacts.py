"""Nominal soft-finger torsional contact translation; not hardware calibration."""
import numpy as np


def nominal_patch_radius(sliding, torsional):
    if not np.isfinite([sliding,torsional]).all() or sliding<=0 or torsional<0:
        raise ValueError('invalid_source_soft_finger_friction')
    return float(torsional/sliding)


def restore_soft_finger_contacts(stage, model):
    from pxr import PhysxSchema, UsdPhysics
    fingers={f'{side}_gripper_finger_link{k}' for side in ('left','right') for k in (1,2)}
    source={model.geom(i).name:i for i in range(model.ngeom)
            if model.body(model.geom_bodyid[i]).name in fingers and
            (model.geom_contype[i] or model.geom_conaffinity[i])}
    rows=[]
    for prim in stage.Traverse():
        if prim.GetName() not in source or not prim.HasAPI(UsdPhysics.CollisionAPI):continue
        gid=source[prim.GetName()];sliding,torsional=model.geom_friction[gid,:2]
        if model.geom_condim[gid]<4:continue
        radius=nominal_patch_radius(sliding,torsional)
        api=PhysxSchema.PhysxCollisionAPI.Apply(prim)
        before=dict(radius=api.GetTorsionalPatchRadiusAttr().Get(),minimum=api.GetMinTorsionalPatchRadiusAttr().Get())
        api.CreateTorsionalPatchRadiusAttr(radius);api.CreateMinTorsionalPatchRadiusAttr(radius)
        rows.append(dict(path=str(prim.GetPath()),source_sliding=float(sliding),source_torsional_m=float(torsional),
                         source_condim=int(model.geom_condim[gid]),effective_radius_m=radius,before=before))
    if len(rows)!=4:raise ValueError('four_native_soft_finger_collisions_required')
    return dict(schema='native_nominal_soft_finger_contact_translation/1',rows=rows,
                method='nominal_torque_bound_mu_times_radius_matches_source_torsional_coefficient',
                hardware_calibrated=False,exact_contact_dynamics_equivalence=False,
                no_geometry_mass_or_sliding_friction_change=True,no_external_force_or_attachment=True)
