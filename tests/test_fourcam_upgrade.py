import json
from pathlib import Path
import xml.etree.ElementTree as ET

import mujoco
import numpy as np
import pytest

from scripts.upgrade_airport_fourcam import camera_profile, patch_xml
from r1pro_teleop.airport_fsm.contracts import camera_shapes, FOUR_CAMERA_SHAPES, NATIVE_CAMERA_SHAPES


def profile():
    path = Path(__file__).resolve().parents[1] / 'resources/calibration/camera_audit.json'
    return camera_profile(json.loads(path.read_text()))


def test_legacy_and_fourcam_contract():
    assert camera_shapes({'camera': profile()}) == FOUR_CAMERA_SHAPES
    assert camera_shapes({'camera': {'streams': {k: dict(height=v[0], width=v[1]) for k,v in NATIVE_CAMERA_SHAPES.items()}}}) == NATIVE_CAMERA_SHAPES
    p = profile(); del p['streams']['head_right']
    with pytest.raises(ValueError): camera_shapes({'camera': p})


def test_measured_tf_and_intrinsics_preserve_physics(tmp_path):
    source = tmp_path / 'old.xml'; target = tmp_path / 'new.xml'
    source.write_text('<mujoco><worldbody><body name="torso_link4"><geom size=".1"/></body><body name="left_gripper_link" pos="1 0 0"><geom size=".1"/></body><body name="right_gripper_link" pos="-1 0 0"><geom size=".1"/></body></worldbody></mujoco>')
    p = profile(); patch_xml(source, target, p)
    old = mujoco.MjModel.from_xml_path(str(source)); new = mujoco.MjModel.from_xml_path(str(target))
    np.testing.assert_array_equal(old.body_mass, new.body_mass)
    np.testing.assert_array_equal(old.geom_pos, new.geom_pos)
    assert new.ncam == 4
    d = mujoco.MjData(new); mujoco.mj_forward(new, d)
    assert np.linalg.norm(d.cam_xpos[new.camera('head_left').id]-d.cam_xpos[new.camera('head_right').id]) == pytest.approx(.12)
    for name, c in p['streams'].items():
        cam = new.camera(name)
        np.testing.assert_allclose(new.cam_intrinsic[cam.id][:2], [c['K'][0],c['K'][4]], rtol=1e-6)
        assert not c['distortion_applied']
    assert not p['deployment_calibration_validated']


def test_principal_point_render_sign():
    # Asymmetric target detects both sign errors; pixel centers are index+0.5.
    m = mujoco.MjModel.from_xml_string('<mujoco><visual><headlight ambient="1 1 1" diffuse="0 0 0"/></visual><worldbody><camera name="c" resolution="320 240" sensorsize="320 240" focalpixel="200 200" principalpixel="-20 15"/><geom type="sphere" size=".03" pos="0 0 -2" rgba="1 0 0 1"/></worldbody></mujoco>')
    d = mujoco.MjData(m); mujoco.mj_forward(m,d)
    with mujoco.Renderer(m,240,320) as renderer:
        renderer.update_scene(d,camera='c'); im=renderer.render()
    y,x=np.where(im[:,:,0]>100)
    assert x.mean()+.5 == pytest.approx(180,abs=.6)
    assert y.mean()+.5 == pytest.approx(105,abs=.6)
