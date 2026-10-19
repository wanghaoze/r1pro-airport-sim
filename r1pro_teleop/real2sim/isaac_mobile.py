"""Native mobile19 / PhysX articulation + world D6 drive routing.

No physics stepping, IK, trajectory correction or live pose reset occurs here.
Production use requires a native drive-validation receipt for the scene.
"""
import math
import numpy as np


def _numpy(value):
    return value.detach().cpu().numpy() if hasattr(value, 'detach') else np.asarray(value)


def d6_targets(offset, joint_rotation):
    """World XY / world yaw offsets -> USD joint-frame metres / degrees."""
    offset = np.asarray(offset, dtype=float)
    rotation = np.asarray(joint_rotation, dtype=float)
    if offset.shape != (3,) or rotation.shape != (3, 3) or not np.isfinite(offset).all() or not np.isfinite(rotation).all():
        raise ValueError('isaac_invalid_planar_base_mapping')
    if not np.allclose(rotation.T @ rotation, np.eye(3), atol=1e-6) or not np.isclose(np.linalg.det(rotation), 1., atol=1e-6):
        raise ValueError('isaac_base_frame_not_rotation')
    yaw_axis = rotation.T @ [0., 0., 1.]
    if not np.allclose(yaw_axis[:2], 0., atol=1e-6):
        raise ValueError('isaac_d6_planar_axes_require_native_reconstruction')
    translation = rotation.T @ [offset[0], offset[1], 0.]
    return np.array([translation[0], translation[1],
                     math.degrees(offset[2]) * yaw_axis[2]])


def mobile_targets(action):
    action = np.asarray(action, dtype=float)
    if action.shape != (19,) or not np.isfinite(action).all():
        raise ValueError('isaac_invalid_mobile19_action')
    result = {}
    for side, start in [('left', 0), ('right', 8)]:
        for index in range(7):
            result[f'{side}_arm_joint{index + 1}'] = float(action[start + index])
        for index in (1, 2):
            result[f'{side}_gripper_finger_joint{index}'] = float(action[start + 7] / 2)
    return result


class IsaacMobile19Backend:
    """Uses imported scalar arm/finger joints and the independently driven D6.

    The validation receipt is produced by a native physics preflight, never by
    this adapter. Initial poses belong to the scene initializer, not command().
    """
    def __init__(self, robot, base_joint_prim, joint_world_rotation, base_origin,
                 validation_receipt, *, scene_sha256=None, action_factory=None):
        if (validation_receipt.get('schema') != 'airport_isaac_native_drive_validation/1' or
            validation_receipt.get('passed') is not True or
            validation_receipt.get('engine') != 'isaacsim' or
            validation_receipt.get('physics_backend') != 'physx' or
            not scene_sha256 or validation_receipt.get('scene_sha256') != scene_sha256 or
            any(validation_receipt.get(key) is not True for key in
                ('base_control_verified', 'arm_control_verified', 'gripper_control_verified'))):
            raise ValueError('isaac_native_drive_validation_required')
        self.robot = robot
        self.rotation = np.asarray(joint_world_rotation, dtype=float)
        self.origin = np.asarray(base_origin, dtype=float)
        d6_targets(np.zeros(3), self.rotation)
        if self.origin.shape != (3,) or not np.isfinite(self.origin).all():
            raise ValueError('isaac_invalid_base_origin')
        if action_factory is None:
            from isaacsim.core.utils.types import ArticulationAction
            action_factory = ArticulationAction
        from pxr import UsdPhysics
        self.action_factory = action_factory
        self.tensor_backend = validation_receipt.get('tensor_backend', 'numpy')
        self.device = validation_receipt.get('device', 'cpu')
        self.names = tuple(mobile_targets(np.zeros(19)))
        self.indices = np.array([robot.get_dof_index(name) for name in self.names], dtype=int)
        if np.any(self.indices < 0) or len(set(self.indices.tolist())) != 18:
            raise ValueError('isaac_arm_finger_mapping_missing_or_duplicate')
        self.drives = [UsdPhysics.DriveAPI.Get(base_joint_prim, axis)
                       for axis in ('transX', 'transY', 'rotZ')]
        if any(not drive for drive in self.drives):
            raise ValueError('isaac_world_d6_position_drives_missing')

    def command(self, action):
        targets = mobile_targets(action)
        positions = np.array([targets[name] for name in self.names])
        base = d6_targets(np.asarray(action)[16:], self.rotation)
        submitted, indices = positions, self.indices
        if self.tensor_backend == 'torch':
            import torch
            submitted = torch.as_tensor(positions, dtype=torch.float32, device=self.device)
            indices = torch.as_tensor(self.indices, dtype=torch.int64, device=self.device)
        self.robot.apply_action(self.action_factory(joint_positions=submitted, joint_indices=indices))
        for drive, target in zip(self.drives, base):
            drive.GetTargetPositionAttr().Set(float(target))
        return dict(values=np.r_[positions, base], names=[*self.names, 'base_transX', 'base_transY', 'base_rotZ'],
                    units=['rad'] * 7 + ['m'] * 2 + ['rad'] * 7 + ['m'] * 2 + ['m', 'm', 'degree'])

    def observe(self):
        indices = self.indices
        if self.tensor_backend == 'torch':
            import torch
            indices = torch.as_tensor(indices, dtype=torch.int64, device=self.device)
        q = dict(zip(self.names, _numpy(self.robot.get_joint_positions(joint_indices=indices))))
        values = []
        for side in ('left', 'right'):
            values.extend(q[f'{side}_arm_joint{index}'] for index in range(1, 8))
            values.append(q[f'{side}_gripper_finger_joint1'] + q[f'{side}_gripper_finger_joint2'])
        xyz, quat = [_numpy(value) for value in self.robot.get_world_pose()]
        w, x, y, z = quat
        yaw = math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z))
        delta = yaw - self.origin[2]
        values.extend([xyz[0] - self.origin[0], xyz[1] - self.origin[1], math.atan2(math.sin(delta), math.cos(delta))])
        result = np.asarray(values, dtype=float)
        if result.shape != (19,) or not np.isfinite(result).all():
            raise RuntimeError('isaac_nonfinite_native_state')
        return result
