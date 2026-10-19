"""MuJoCo FK and initialization adapter for portable scene registration."""
import numpy as np
from .registration import validate_registration


def recorded_pad_centres(model, trajectory, mapping):
    import mujoco
    data = mujoco.MjData(model)
    mujoco.mj_resetDataKeyframe(model, data, model.key('real2sim_home').id)
    qids = [model.jnt_qposadr[model.joint(n).id] for n in mapping.joints]
    ids = []
    for side in ('left', 'right'):
        geoms = [i for i in range(model.ngeom) if model.body(model.geom_bodyid[i]).name in
                 (side+'_gripper_finger_link1', side+'_gripper_finger_link2')
                 and model.geom_type[i] == mujoco.mjtGeom.mjGEOM_BOX]
        if len(geoms) != 2:
            raise ValueError('real2sim_two_finger_pad_geoms_required')
        ids.append(geoms)
    pads = []
    for feedback in trajectory.feedback:
        data.qpos[qids] = mapping.encode(feedback)
        mujoco.mj_forward(model, data)
        base = data.body('base_link')
        rotation = base.xmat.reshape(3,3)
        pads.append([rotation.T @ (data.geom_xpos[g].mean(0) - base.xpos) for g in ids])
    return np.asarray(pads)


def apply_initial_registration(model, registration):
    """Edit the new model's home key ONLY, before backend initialization."""
    import mujoco
    r = validate_registration(registration)
    home = model.key('real2sim_home').id
    base = r['base_pose']; q = base['quaternion_wxyz']
    yaw = 2*np.arctan2(q[3], q[0])
    # Mobile scenes store a spawn transform in body pos/quat. Slide/yaw qpos
    # are offsets from that transform, not world coordinates.
    ids = [model.jnt_qposadr[model.joint(n).id] for n in ('agent_base_x','agent_base_y','agent_base_yaw')]
    scratch = mujoco.MjData(model)
    mujoco.mj_resetDataKeyframe(model, scratch, home)
    scratch.qpos[ids] = 0.
    mujoco.mj_forward(model, scratch)
    rotation = scratch.body('base_link').xmat.reshape(3,3)
    offset_yaw = np.arctan2(rotation[1,0],rotation[0,0])
    scratch.qpos[ids[2]] = (yaw-offset_yaw+np.pi) % (2*np.pi) - np.pi
    mujoco.mj_forward(model, scratch)
    origin = scratch.body('base_link').xpos[:2].copy()
    basis = []
    for address in ids[:2]:
        scratch.qpos[address] = 1.
        mujoco.mj_forward(model, scratch)
        basis.append(scratch.body('base_link').xpos[:2].copy()-origin)
        scratch.qpos[address] = 0.
    scratch.qpos[ids[:2]] = np.linalg.solve(np.array(basis).T, np.asarray(base['xyz'][:2])-origin)
    mujoco.mj_forward(model, scratch)
    if not np.allclose(scratch.body('base_link').xpos, base['xyz'], atol=1e-8):
        raise ValueError('real2sim_base_registration_transform_mismatch')
    model.key_qpos[home, ids] = scratch.qpos[ids]
    address = model.jnt_qposadr[model.joint('tray_free').id]
    model.key_qpos[home, address:address+7] = r['tray_pose']['xyz'] + r['tray_pose']['quaternion_wxyz']


def contact_diagnostics(backend):
    """Raw contact evidence; no new task-success tolerance or gate."""
    model, data = backend.model, backend.data
    totals = dict(left_tray_n=0., right_tray_n=0., table_tray_n=0.)
    for c in backend.contacts():
        if c['geom1'] < 0 or c['geom2'] < 0:
            # Flex contacts use -1, never index the last rigid geom by accident.
            continue
        names = [model.body(model.geom_bodyid[c[g]]).name for g in ('geom1','geom2')]
        if 'tray' not in names:
            continue
        other = names[1] if names[0] == 'tray' else names[0]
        for side in ('left', 'right'):
            if other in (side+'_gripper_finger_link1', side+'_gripper_finger_link2'):
                totals[side+'_tray_n'] += c['normal_force_n']
        if other in ('front_left','front_right','rear'):
            totals['table_tray_n'] += c['normal_force_n']
    return dict(**totals, tray_xyz=data.body('tray').xpos.tolist(),
                tray_quaternion_wxyz=data.body('tray').xquat.tolist(),
                max_penetration_m=max([0.] + [-c.dist for c in data.contact]))
