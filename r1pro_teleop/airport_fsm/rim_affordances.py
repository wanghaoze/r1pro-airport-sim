"""Offline grasp geometry candidates; not enabled by the controller.

Both edge pairs use their own physical span. Feasibility still requires complete
IK, collision, camera, closure, and live force qualification.
"""
from dataclasses import dataclass
import numpy as np
from scipy.spatial.transform import Rotation


class RimCandidate(tuple):
    """Three-value legacy candidate with explicit grasp geometry metadata."""
    def __new__(cls, base, face, rim, rim_pair):
        instance = super().__new__(cls, (base, face, rim))
        instance.rim_pair = rim_pair
        return instance


@dataclass(frozen=True)
class RimPair:
    axis: str
    face: float
    half_span: float
    edge_half_length: float

    def __post_init__(self):
        if (self.axis not in ('width', 'length') or
                not np.isfinite([self.face, self.half_span, self.edge_half_length]).all() or
                self.half_span <= 0 or self.edge_half_length <= 0):
            raise ValueError('Rim pair requires a valid axis, finite face and positive dimensions')

    def goals(self, center, *, x_offset=0., sides=('left', 'right'), pitch_deg=-30., roll_deg=10.):
        center = np.asarray(center, float)
        if center.shape != (3,) or not np.isfinite(center).all():
            raise ValueError('Finite XYZ center required')
        if not np.isfinite([x_offset, pitch_deg, roll_deg]).all() or abs(x_offset) > self.edge_half_length:
            raise ValueError('Rim offset exceeds the selected physical edge')
        if any(side not in ('left', 'right') for side in sides):
            raise ValueError('Unknown gripper side')
        rotation = Rotation.from_euler('z', self.face).as_matrix()
        return {side: (center + rotation @ np.array([x_offset, sign*self.half_span, 0.]),
                       rotation @ (Rotation.from_euler('y', pitch_deg, degrees=True)*
                                   Rotation.from_euler('x', -roll_deg*sign, degrees=True)).as_matrix())
                for side, sign in (('left', 1), ('right', -1)) if side in sides}


def rim_pairs(size, tray_yaw, aisle_normal, *, inset):
    """Return width and length edge pairs, each facing the nearest aisle side."""
    size = np.asarray(size, float)
    if size.shape not in ((2,), (3,)) or not np.isfinite(size).all() or np.any(size <= 0):
        raise ValueError('Positive tray dimensions required')
    if not np.isfinite([tray_yaw, aisle_normal, inset]).all() or not 0 <= inset < min(size[:2])/2:
        raise ValueError('Invalid yaw, normal, or inset')
    result = []
    for axis, angle, span, edge in (('width', tray_yaw, size[1], size[0]),
                                    ('length', tray_yaw+np.pi/2, size[0], size[1])):
        candidates = [angle, angle+np.pi]
        face = min(candidates, key=lambda x: abs(np.arctan2(np.sin(x-aisle_normal), np.cos(x-aisle_normal))))
        face = float(np.arctan2(np.sin(face), np.cos(face)))
        result.append(RimPair(axis, face, float(span/2-inset), float(edge/2-inset)))
    return tuple(result)
