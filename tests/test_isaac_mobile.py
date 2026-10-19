import math
import numpy as np
import pytest
from r1pro_teleop.real2sim.isaac_mobile import d6_targets, mobile_targets, IsaacMobile19Backend


def test_d6_world_axes_and_degree_conversion():
    np.testing.assert_allclose(d6_targets([.1, .2, math.pi / 2], np.eye(3)), [.1, .2, 90])
    # Actual imported joint frame may reverse world Y and world Z.
    np.testing.assert_allclose(d6_targets([.1, .2, math.pi / 2], np.diag([1, -1, -1])), [.1, -.2, -90])
    with pytest.raises(ValueError, match='planar_axes'):
        d6_targets([0, 0, 0], np.array([[0, 0, 1], [0, 1, 0], [-1, 0, 0]]))


def test_mobile_arm_order_and_aperture_are_not_mm():
    action = np.arange(19, dtype=float) / 100
    targets = mobile_targets(action)
    assert len(targets) == 18
    assert targets['left_arm_joint7'] == .06
    assert targets['right_arm_joint1'] == .08
    assert targets['left_gripper_finger_joint1'] == .035
    assert targets['right_gripper_finger_joint2'] == .075
    with pytest.raises(ValueError, match='mobile19'):
        mobile_targets(np.full(19, np.nan))


def test_unvalidated_native_scene_cannot_be_used_by_model():
    with pytest.raises(ValueError, match='native_drive_validation_required'):
        IsaacMobile19Backend(None, None, np.eye(3), [0, 0, 0], {})
