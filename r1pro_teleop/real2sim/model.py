"""Build a separate full-joint MuJoCo model from a source URDF and scene.

Preserves visual/collision/inertia/camera assets. URDF defines joint transforms,
axes, position/effort limits. New torso PD parameters are explicit, uncalibrated.
No fitted limits, qpos teleport during dynamics, or task acceptance changes.
"""
from pathlib import Path
import xml.etree.ElementTree as ET
import numpy as np
from scipy.spatial.transform import Rotation
from .trajectory import CHANNELS, sha256, write_json


def fmt(values):
    return " ".join(format(float(x), ".15g") for x in values)


def align_gripper_joints(root, robot):
    """Use URDF geometry/limits with positive outward coordinates for both fingers.

    URDF finger 2 has negative travel along +Y; our logical mapping uses
    positive half-opening, so negate its axis and limits together.
    """
    changes = []
    for side in ('left', 'right'):
        efforts = []
        for i in (1, 2):
            name = f'{side}_gripper_finger_joint{i}'
            spec = robot.find(f"./joint[@name='{name}']")
            if spec is None or spec.get('type') != 'prismatic':
                raise ValueError('real2sim_source_finger_missing')
            body = root.find(f".//body[@name='{spec.find('child').get('link')}']")
            joint = body.find(f"joint[@name='{name}']")
            limit = spec.find('limit'); sign = 1. if i == 1 else -1.
            bounds = sorted(sign * float(limit.get(k)) for k in ('lower', 'upper'))
            if not np.allclose(bounds, [0., .05]):
                raise ValueError('real2sim_source_finger_opening_contract_changed')
            before = dict(joint.attrib)
            origin = spec.find('origin')
            for key in ('quat', 'euler', 'axisangle', 'xyaxes', 'zaxis'):
                body.attrib.pop(key, None)
            body.set('pos', origin.get('xyz', '0 0 0'))
            quat = Rotation.from_euler('xyz', np.fromstring(origin.get('rpy', '0 0 0'), sep=' ')).as_quat()
            body.set('quat', fmt(quat[[3, 0, 1, 2]]))
            effort = float(limit.get('effort')); efforts.append(effort)
            joint.attrib.update(type='slide', axis=fmt(sign * np.fromstring(spec.find('axis').get('xyz'), sep=' ')),
                                range=fmt(bounds), limited='true', actuatorfrcrange=fmt([-effort, effort]))
            changes.append(dict(joint=name, before=before, after=dict(joint.attrib),
                                urdf_to_positive_opening_sign=sign))
        actuator = root.find(f"./actuator/position[@name='{side}_gripper_target']")
        actuator.attrib.update(ctrlrange='0 0.05', ctrllimited='true',
                              forcerange=fmt([-min(efforts), min(efforts)]), forcelimited='true')
        equality = root.find(f"./equality/joint[@joint1='{side}_gripper_finger_joint1']")
        if equality is None or equality.get('joint2') != f'{side}_gripper_finger_joint2':
            raise ValueError('real2sim_finger_coupling_missing')
        equality.set('polycoef', '0 1 0 0 0')
    return changes


def build_model(scene_xml, urdf, destination, *, torso_kp=250., torso_kv=25., finger_collision_bundle=None,
                tray_width_scale=1.):
    import mujoco
    source, urdf, destination = map(lambda p: Path(p).resolve(), (scene_xml, urdf, destination))
    if destination.exists():
        raise FileExistsError(destination)
    if torso_kp <= 0 or torso_kv < 0 or not np.isfinite([torso_kp, torso_kv]).all():
        raise ValueError("real2sim_invalid_torso_servo")
    old = mujoco.MjModel.from_xml_path(str(source)); old_data = mujoco.MjData(old)
    home = mujoco.mj_name2id(old, mujoco.mjtObj.mjOBJ_KEY, "teleop_home")
    if home >= 0:
        mujoco.mj_resetDataKeyframe(old, old_data, home)
    root = ET.parse(source).getroot(); robot = ET.parse(urdf).getroot()
    if not np.isfinite(tray_width_scale) or tray_width_scale <= 0:
        raise ValueError('real2sim_invalid_estimated_tray_width_scale')
    tray_report = None
    if tray_width_scale != 1.:
        tray = root.find(".//body[@name='tray']")
        meshes = {g.get('mesh') for g in tray.findall('geom')}
        if None in meshes:
            raise ValueError('real2sim_tray_scaling_requires_mesh_geoms')
        for name in meshes:
            mesh = root.find(f"./asset/mesh[@name='{name}']")
            scale = np.fromstring(mesh.get('scale','1 1 1'),sep=' ')
            scale[1] *= tray_width_scale; mesh.set('scale',fmt(scale))
        # The source XML uses link-local mesh vertices and identity geom transforms.
        for geom in tray.findall('geom'):
            if not np.allclose(np.fromstring(geom.get('pos','0 0 0'),sep=' '),0) or any(k in geom.attrib for k in ('quat','euler','axisangle')):
                raise ValueError('real2sim_tray_scaling_requires_local_mesh_frame')
        bid = old.body('tray').id
        rotation = Rotation.from_quat(old.body_iquat[bid][[1,2,3,0]]).as_matrix()
        inertia = rotation @ np.diag(old.body_inertia[bid]) @ rotation.T
        second = np.eye(3)*np.trace(inertia)/2-inertia
        transform = np.diag([1.,tray_width_scale,1.])
        second = transform @ second @ transform.T
        scaled_inertia = np.eye(3)*np.trace(second)-second
        inertial=tray.find('inertial')
        if inertial is None:
            inertial=ET.SubElement(tray,'inertial',mass=str(old.body_mass[bid]))
        for key in ('diaginertia','quat','euler','axisangle'):inertial.attrib.pop(key,None)
        inertial.set('fullinertia',fmt([*np.diag(scaled_inertia),scaled_inertia[0,1],scaled_inertia[0,2],scaled_inertia[1,2]]))
        inertial.set('pos',fmt(old.body_ipos[bid]*np.array([1.,tray_width_scale,1.])))
        tray_report=dict(width_scale=float(tray_width_scale),estimated_not_measured=True,
                         mass_kg=float(old.body_mass[bid]),mass_policy='fixed_source_mass_affine_inertia_transform',
                         visual_and_collision_scaled_together=True)
    if root.findall("include"):
        raise ValueError("real2sim_flat_scene_xml_required")
    changes = []
    for name in CHANNELS:
        if "opening" in name:
            continue
        spec = robot.find(f"./joint[@name='{name}']")
        if spec is None or spec.get("type") != "revolute":
            raise ValueError("real2sim_source_revolute_joint_missing")
        body = root.find(f".//body[@name='{spec.find('child').get('link')}']")
        if body is None:
            raise ValueError("real2sim_source_child_body_missing")
        origin, limit = spec.find("origin"), spec.find("limit")
        before = dict(body.attrib)
        for key in ("quat", "euler", "axisangle", "xyaxes", "zaxis"):
            body.attrib.pop(key, None)
        body.set("pos", origin.get("xyz", "0 0 0"))
        quat = Rotation.from_euler("xyz", np.fromstring(origin.get("rpy", "0 0 0"), sep=" ")).as_quat()
        body.set("quat", fmt(quat[[3, 0, 1, 2]]))
        joint = body.find(f"joint[@name='{name}']")
        new = joint is None
        if new:
            if not name.startswith("torso_"):
                raise ValueError("real2sim_unexpected_missing_arm_joint")
            joint = ET.SubElement(body, "joint", name=name, damping="2", armature="0.02")
            body.set("gravcomp", "1")
        previous_range = joint.get("range")
        joint.attrib.update(type="hinge", axis=spec.find("axis").get("xyz"),
                            range=limit.get("lower") + " " + limit.get("upper"), limited="true",
                            actuatorfrcrange=f"-{limit.get('effort')} {limit.get('effort')}")
        actuator = root.find(f"./actuator/position[@name='{name}_target']")
        if new:
            actuator = ET.SubElement(root.find("actuator"), "position", name=name + "_target",
                                     joint=name, kp=str(torso_kp), kv=str(torso_kv))
        if actuator is None:
            raise ValueError("real2sim_position_actuator_missing")
        actuator.set("ctrlrange", joint.get("range"))
        actuator.set("forcerange", f"-{limit.get('effort')} {limit.get('effort')}")
        changes.append(dict(joint=name, added=new, prior_body=before, prior_range=previous_range,
                            new_range=joint.get("range"), new_body=dict(body.attrib)))
    gripper_changes = align_gripper_joints(root, robot)
    # Paths stay in the project on this host; a package export must copy its assets.
    compiler = root.find("compiler")
    meshdir = compiler.get("meshdir", "") if compiler is not None else ""
    texturedir = compiler.get("texturedir", "") if compiler is not None else ""
    for node in root.iter():
        if node.get("file"):
            prefix = meshdir if node.tag == "mesh" else texturedir if node.tag == "texture" else ""
            node.set("file", str((source.parent / prefix / node.get("file")).resolve()))
    if compiler is not None:
        compiler.attrib.pop("meshdir", None); compiler.attrib.pop("texturedir", None)
    for keyframe in root.findall("keyframe"):
        root.remove(keyframe)
    collision_report = None
    if finger_collision_bundle:
        from .collision import apply_finger_collision_bundle
        collision_report = apply_finger_collision_bundle(root, finger_collision_bundle, sha256(urdf))
    destination.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(root).write(destination, encoding="unicode")
    model = mujoco.MjModel.from_xml_path(str(destination)); q = model.qpos0.copy()
    for jid in range(old.njnt):
        name = old.joint(jid).name
        target = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, name) if name else -1
        if not name:
            # Flex-generated slide joints have no names. Their owning body and
            # ordinal are stable even when four torso DOFs shift global indices.
            bid = int(old.jnt_bodyid[jid]); body_name = old.body(bid).name
            new_bid = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, body_name)
            ordinal = jid - int(old.body_jntadr[bid])
            if new_bid >= 0 and old.body_jntnum[bid] == model.body_jntnum[new_bid]:
                target = int(model.body_jntadr[new_bid]) + ordinal
        if target < 0:
            raise ValueError("real2sim_existing_joint_lost")
        if model.jnt_type[target] != old.jnt_type[jid]:
            raise ValueError("real2sim_existing_joint_type_changed")
        size = 7 if old.jnt_type[jid] == mujoco.mjtJoint.mjJNT_FREE else 4 if old.jnt_type[jid] == mujoco.mjtJoint.mjJNT_BALL else 1
        a, b = int(old.jnt_qposadr[jid]), int(model.jnt_qposadr[target])
        q[b:b + size] = old_data.qpos[a:a + size]
    ET.SubElement(ET.SubElement(root, "keyframe"), "key", name="real2sim_home", qpos=fmt(q))
    ET.ElementTree(root).write(destination, encoding="unicode")
    report = dict(schema="real2sim_model/1", source_scene=str(source), source_scene_sha256=sha256(source),
                  source_urdf=str(urdf), source_urdf_sha256=sha256(urdf), output_sha256=sha256(destination),
                  changes=changes, geometry_inertia_cameras=("preserved_except_explicit_recorded_geometry_overrides"
                      if collision_report or tray_report else "preserved_from_scene"),
                  torso_servo=dict(kp=torso_kp, kv=torso_kv, gravcomp=1, calibrated=False),
                  hardware_identity_verified=False, scene_registration_verified=False,
                  finger_collision_override=collision_report)
    report['estimated_tray_geometry'] = tray_report
    report['gripper_joint_alignment'] = gripper_changes
    write_json(destination.with_suffix(".manifest.json"), report)
    return report
