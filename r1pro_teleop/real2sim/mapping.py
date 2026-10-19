"""Explicit affine channel-to-joint bindings; no engine joint-order assumptions."""
from dataclasses import dataclass
import numpy as np
from .trajectory import CHANNELS


@dataclass(frozen=True)
class Binding:
    joint: str
    channel: str
    scale: float = 1.
    offset: float = 0.
    actuator: str | None = None


class JointMap:
    def __init__(self, channels, bindings):
        self.channels = tuple(channels)
        self.bindings = tuple(bindings)
        self.joints = tuple(b.joint for b in bindings)
        if len(set(self.joints)) != len(self.joints) or set(b.channel for b in bindings) != set(channels):
            raise ValueError("real2sim_mapping_coverage_or_duplicate_joint")
        self.indices = np.array([self.channels.index(b.channel) for b in bindings])
        self.scale = np.array([b.scale for b in bindings])
        self.offset = np.array([b.offset for b in bindings])
        if not np.isfinite(np.r_[self.scale, self.offset]).all() or np.any(self.scale == 0):
            raise ValueError("real2sim_invalid_affine_mapping")

    def encode(self, values):
        values = np.asarray(values, dtype=float)
        if values.shape != (len(self.channels),) or not np.isfinite(values).all():
            raise ValueError("real2sim_invalid_logical_target")
        return values[self.indices] * self.scale + self.offset

    def decode(self, positions):
        positions = np.asarray(positions, dtype=float)
        if positions.shape != self.scale.shape or not np.isfinite(positions).all():
            raise ValueError("real2sim_invalid_backend_observation")
        logical = (positions - self.offset) / self.scale
        return np.array([logical[self.indices == i].mean() for i in range(len(self.channels))])


def r1pro_map():
    bindings = []
    for name in CHANNELS:
        if "opening" in name:
            side = name.split("_")[0]
            bindings.extend(Binding(f"{side}_gripper_finger_joint{i}", name, .5,
                                    actuator=f"{side}_gripper_target" if i == 1 else None) for i in (1, 2))
        else:
            bindings.append(Binding(name, name, actuator=name + "_target"))
    return JointMap(CHANNELS, bindings)
