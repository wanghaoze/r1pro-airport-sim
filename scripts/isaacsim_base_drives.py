"""Restore missing D6 drive instances from named source position actuators."""
import numpy as np


def source_base_servo(model, joint_name):
    jid = model.joint(joint_name).id
    ids = [i for i in range(model.nu) if int(model.actuator_trnid[i, 0]) == jid]
    if len(ids) != 1:
        raise ValueError('isaac_named_base_position_actuator_required')
    i, = ids
    gain = float(model.actuator_gainprm[i, 0]); bias = model.actuator_biasprm[i]
    if (model.actuator_dyntype[i] != 0 or model.actuator_gaintype[i] != 0 or
            model.actuator_biastype[i] != 1 or not np.allclose(model.actuator_gear[i], [1,0,0,0,0,0]) or
            not np.isclose(bias[0], 0) or not np.isclose(bias[1], -gain) or gain <= 0 or bias[2] > 0):
        raise ValueError('isaac_unsupported_base_actuator_translation')
    force = model.actuator_forcerange[i]
    if not model.actuator_forcelimited[i] or not np.isclose(force[0], -force[1]) or force[1] <= 0:
        raise ValueError('isaac_symmetric_source_force_limit_required')
    return dict(stiffness=gain, damping=float(-bias[2]), max_force=float(force[1]))


def restore_missing(stage, joint, model):
    from pxr import UsdPhysics
    if joint.GetTypeName() != 'PhysicsJoint':
        raise ValueError('isaac_generic_world_d6_required')
    rows = []
    for axis, source in [('transX','agent_base_x'),('transY','agent_base_y'),('rotZ','agent_base_yaw')]:
        if UsdPhysics.DriveAPI.Get(joint, axis):
            continue
        values = source_base_servo(model, source)
        api = UsdPhysics.DriveAPI.Apply(joint, axis)
        api.CreateTypeAttr('force');api.CreateStiffnessAttr(values['stiffness'])
        api.CreateDampingAttr(values['damping']);api.CreateMaxForceAttr(values['max_force'])
        api.CreateTargetPositionAttr(0.);api.CreateTargetVelocityAttr(0.)
        limit=UsdPhysics.LimitAPI.Apply(joint,axis)
        limit.CreateLowAttr(float('-inf'));limit.CreateHighAttr(float('inf'))
        rows.append(dict(axis=axis,source_joint=source,**values))
    return dict(schema='airport_isaac_missing_base_drive_translation/1', restored=rows,
        existing_drives_unchanged=True,contact_dynamics_equivalence_claimed=False)
