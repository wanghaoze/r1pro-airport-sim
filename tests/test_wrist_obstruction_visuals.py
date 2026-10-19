from copy import deepcopy
import xml.etree.ElementTree as ET
import numpy as np
import pytest
from r1pro_teleop.single_tray_lab.camera_visuals import remove_wrist_camera_housing_visuals
from r1pro_teleop.single_tray_lab.scene import TEMPLATE


def original():
    return ET.parse(TEMPLATE).getroot()


def test_remove_only_camera_visuals_preserves_gripper_shells_and_every_other_element():
    before=original();after=deepcopy(before)
    report=remove_wrist_camera_housing_visuals(after)
    assert report['profile']=='wrist_camera_housing_removed_gripper_shell_preserved_v3'
    assert report['gripper_shell_visuals_preserved'] and not report['gripper_shell_visuals_removed']
    assert report['finger_visuals_preserved'] and report['physical_grippers_preserved']
    assert not report['collision_geometry_removed'] and not report['camera_pose_changed']
    assert {r['mesh'] for r in report['removed_visuals']}=={
        s+'_realsense_link' for s in ('left','right')}
    for side in ('left','right'):
        body=after.find(f".//body[@name='{side}_gripper_link']")
        assert any(g.get('mesh')==side+'_gripper_link' and g.get('group')=='1' for g in body.findall('geom'))
    for r in report['removed_visuals']:
        body=before.find(f".//body[@name='{r['body']}']")
        geom=next(g for g in body.findall('geom') if g.get('mesh')==r['mesh'] and g.get('group')=='1')
        body.remove(geom)
    assert ET.tostring(after)==ET.tostring(before)


@pytest.mark.parametrize('change',[{'contype':'1'},{'conaffinity':'1'},
    {'mass':'.01'},{'density':'.01'},{'mass':'0','density':'.01'},
    {'mass':'nan'},{'mass':'inf'}])
def test_any_physical_weight_or_contact_field_refuses_atomic_removal(change):
    root=original();body=root.find(".//body[@name='right_realsense_link']")
    geom=next(g for g in body.findall('geom') if g.get('mesh')=='right_realsense_link' and g.get('group')=='1')
    geom.attrib.update(change);before=ET.tostring(root)
    with pytest.raises(ValueError,match='visual_is_physical'):
        remove_wrist_camera_housing_visuals(root)
    assert ET.tostring(root)==before


def test_missing_declared_zero_weight_refuses_removal():
    root=original();body=root.find(".//body[@name='left_realsense_link']")
    geom=next(g for g in body.findall('geom') if g.get('mesh')=='left_realsense_link' and g.get('group')=='1')
    geom.attrib.pop('mass',None);geom.attrib.pop('density',None)
    with pytest.raises(ValueError,match='visual_is_physical'):
        remove_wrist_camera_housing_visuals(root)


def test_missing_original_housing_keeps_existing_rejection_code():
    root=original();body=root.find(".//body[@name='left_realsense_link']")
    parent=next(p for p in root.iter() if body in list(p))
    parent.remove(body);before=ET.tostring(root)
    with pytest.raises(ValueError,match='missing_wrist_camera_housing_body:left_realsense_link'):
        remove_wrist_camera_housing_visuals(root)
    assert ET.tostring(root)==before


def test_compiled_physics_camera_and_100_real_substeps_are_identical(tmp_path):
    import mujoco
    # Put files beside copied resources so the original model's relative mesh
    # references resolve, without editing the original template.
    from pathlib import Path
    import shutil
    folder=tmp_path/'model';shutil.copytree(Path(TEMPLATE).parent,folder)
    path=folder/Path(TEMPLATE).name
    old=mujoco.MjModel.from_xml_path(str(path));root=ET.parse(path).getroot()
    remove_wrist_camera_housing_visuals(root);ET.ElementTree(root).write(path)
    new=mujoco.MjModel.from_xml_path(str(path))
    for key in ('body_mass','body_inertia','body_ipos','body_iquat','jnt_type',
        'jnt_axis','jnt_range','dof_damping','dof_frictionloss','actuator_gainprm',
        'actuator_biasprm','actuator_gear','actuator_ctrlrange','actuator_forcerange',
        'cam_pos','cam_quat','cam_fovy','cam_intrinsic'):
        np.testing.assert_array_equal(getattr(old,key),getattr(new,key),err_msg=key)
    def contacts(m):
        return {m.geom(i).name:tuple(getattr(m,k)[i].tobytes() for k in
            ('geom_contype','geom_conaffinity','geom_size','geom_pos','geom_quat',
             'geom_friction','geom_solref','geom_solimp','geom_condim'))
            for i in range(m.ngeom) if m.geom_contype[i] or m.geom_conaffinity[i]}
    assert contacts(old)==contacts(new)
    a=mujoco.MjData(old);b=mujoco.MjData(new)
    if old.nkey:mujoco.mj_resetDataKeyframe(old,a,0);mujoco.mj_resetDataKeyframe(new,b,0)
    for _ in range(100):
        mujoco.mj_step(old,a);mujoco.mj_step(new,b)
        np.testing.assert_array_equal(a.qpos,b.qpos)
        np.testing.assert_array_equal(a.qvel,b.qvel)
        assert a.time==b.time
