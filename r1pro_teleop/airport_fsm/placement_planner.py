"""Pure placement proposals; physical contact and path validation stay authoritative.

No helper updates simulator state, authorizes a release, or changes a limit.
Opening goals must only execute after measured table support.  Small release
goals are intentional: full opening belongs to the later free-hand retreat.
"""
from __future__ import annotations

import numpy as np


def align_carried_lateral_offset(base_goal, measured_base, payload_position):
    """Center the measured payload laterally while retaining chassis standoff.

    Rigid carrying is used only to propose a destination, never to attach or
    move the object. Navigation must still validate the entire route against
    real carried geometry and execute it through physical control.
    """
    goal=np.asarray(base_goal,float)
    current=np.asarray(measured_base,float)
    payload=np.asarray(payload_position,float)
    if (goal.shape!=(3,) or current.shape!=(3,) or payload.shape!=(3,)
            or not all(np.isfinite(x).all() for x in (goal,current,payload))):
        raise ValueError('Finite base XY/yaw and payload XYZ required')
    current_lateral=np.array([-np.sin(current[2]),np.cos(current[2])])
    offset=float(np.dot(payload[:2]-current[:2],current_lateral))
    goal_lateral=np.array([-np.sin(goal[2]),np.cos(goal[2])])
    corrected=goal.copy()
    corrected[:2]-=offset*goal_lateral
    return corrected,offset


def touchdown_position(position, vertices, rotation, *, table_height, preload):
    """Use the *commanded* orientation's collision-vertex bottom, not arrival tilt.

    ``preload`` is a command offset, not permitted physical penetration. Callers
    still enforce the existing penetration and support-contact guards.
    """
    position = np.asarray(position, dtype=float)
    vertices = np.asarray(vertices, dtype=float)
    rotation = np.asarray(rotation, dtype=float)
    if (position.shape != (3,) or vertices.ndim != 2 or vertices.shape[1] != 3
            or not len(vertices) or rotation.shape != (3, 3)
            or not all(np.isfinite(x).all() for x in (position, vertices, rotation))
            or not np.isfinite([table_height, preload]).all() or preload < 0):
        raise ValueError('Finite position, collision vertices, rotation and nonnegative preload required')
    if not np.allclose(rotation.T @ rotation, np.eye(3), atol=1e-7) or not np.isclose(np.linalg.det(rotation), 1):
        raise ValueError('A proper rotation is required')
    target = position.copy()
    target[2] = float(table_height) - float((vertices @ rotation.T)[:, 2].min()) - float(preload)
    return target


def release_endpoint(reference, measured, release_sides, *, open_limit, clearance):
    """Propose just enough finger separation from the measured rim contact.

    Changing a lift/placement branch must not silently request a full 10 cm
    opening. Both arms and retained gripper remain exactly at their references.
    The force-based release acceptance remains mandatory, including when the
    proposed aperture saturates at the existing open limit.
    """
    reference = np.asarray(reference, dtype=float)
    measured = np.asarray(measured, dtype=float)
    if (reference.shape != (16,) or measured.shape != (16,)
            or not np.isfinite(reference).all() or not np.isfinite(measured).all()
            or not np.isfinite([open_limit, clearance]).all()
            or open_limit <= 0 or clearance <= 0):
        raise ValueError('Finite 16-column states and positive opening parameters required')
    sides = tuple(release_sides)
    if not sides or len(set(sides)) != len(sides) or any(s not in ('left', 'right') for s in sides):
        raise ValueError('One or two distinct release sides required')
    target = reference.copy()
    for side in sides:
        col = 7 if side == 'left' else 15
        if not -1e-6 <= measured[col] <= open_limit+1e-6 or not -1e-6 <= reference[col] <= open_limit+1e-6:
            raise ValueError('Gripper opening outside configured range')
        target[col] = min(open_limit, max(reference[col], measured[col] + clearance))
    return target


def descent_budget_frames(*, remaining_frames, release_frames, support_frames=2):
    """Allocate a single primitive budget on the recorder's integer clock.

    The returned budget excludes release and measured support verification.
    It never creates additional time or permits a zero-frame descent.
    """
    values = (remaining_frames, release_frames, support_frames)
    if any(isinstance(x, bool) or not isinstance(x, (int, np.integer)) or x < 0 for x in values):
        raise ValueError('Nonnegative integer frame counts required')
    if release_frames < 1 or support_frames < 1:
        raise ValueError('Release and support verification need at least one frame')
    frames = remaining_frames - release_frames - support_frames
    if frames < 1:
        raise ValueError('No time remains for descent')
    return frames
