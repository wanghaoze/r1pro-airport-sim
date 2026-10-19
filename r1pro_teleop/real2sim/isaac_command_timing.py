"""Causal upsampling of recorded 20Hz commands for native 500Hz drives."""
import numpy as np


def substep_commands(previous, target, count=25):
    previous = np.asarray(previous, dtype=float)
    target = np.asarray(target, dtype=float)
    if previous.shape != (19,) or target.shape != (19,) or count < 1:
        raise ValueError('invalid_native_command_interpolation_shape')
    if not np.isfinite(previous).all() or not np.isfinite(target).all():
        raise ValueError('nonfinite_native_command_interpolation')
    alpha = np.arange(1, count + 1, dtype=float)[:, None] / count
    return previous + alpha * (target - previous)
