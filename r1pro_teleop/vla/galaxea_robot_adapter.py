"""Protocol/unit adapter only; robot scheduler retains command filtering."""
import numpy as np

PROMPTS = ('Pick up the tray', 'Place the tray')
CAMERAS = {'head_left': 'head_rgb', 'left_wrist': 'left_wrist_rgb', 'right_wrist': 'right_wrist_rgb'}


def vector(value, count, name):
    a = np.asarray(value, dtype=np.float32).reshape(-1)
    if a.shape != (count,) or not np.isfinite(a).all():
        raise ValueError(f'{name}: expected {count} finite values')
    return a


def observation(obs, resize):
    task = obs['task']
    if task not in PROMPTS:
        raise ValueError('Only exact trained Pick/Place texts are supported')
    state = obs['state']
    x = np.r_[vector(state['left_arm'], 7, 'left_arm'),
              vector(state['left_gripper'], 1, 'left_gripper') * .001,
              vector(state['right_arm'], 7, 'right_arm'),
              vector(state['right_gripper'], 1, 'right_gripper') * .001,
              np.zeros(3, dtype=np.float32)].astype(np.float32)
    result = dict(state=x, prompt=task)
    for target, source in CAMERAS.items():
        a = np.asarray(obs['images'][source])
        if a.dtype != np.uint8 or a.ndim != 3 or a.shape[0] != 3:
            raise ValueError(f'{source}: expected RGB uint8 CHW')
        result['image/' + target] = resize(a.transpose(1, 2, 0), 224, 224)
    return result


def command(row, gripper_range_mm=None):
    a = vector(row, 19, 'model_action')
    # Do not clip or binarize. The existing robot filter decides admissibility.
    result = dict(left_arm=a[:7], left_gripper=a[7:8] * 1000,
                  right_arm=a[8:15], right_gripper=a[15:16] * 1000)
    if gripper_range_mm is not None:
        bounds=vector(gripper_range_mm,2,'gripper_range_mm')
        if bounds[0]>=bounds[1]:raise ValueError('Invalid gripper bounds')
        for name in ['left_gripper','right_gripper']:
            result[name]=np.clip(result[name],bounds[0],bounds[1])
    return result
