"""Candidate physics-rate sampling and exact applied-control evidence.

This module does not change Runtime, recording or export defaults. It samples
the already selected C2 curve itself (never a new per-frame fit). A 20 Hz label
is an interval-end reference; exact replay requires the float64 actuator rows.
"""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np


@dataclass(frozen=True)
class PhysicsClock:
    timestep: float
    fps: int = 20

    def __post_init__(self):
        if not np.isfinite(self.timestep) or self.timestep <= 0 or self.fps <= 0:
            raise ValueError('finite positive clock required')
        if not np.isclose(round(1/(self.fps*self.timestep))*self.timestep,
                          1/self.fps, atol=1e-12, rtol=0):
            raise ValueError('video frame must contain an integer number of physics steps')

    @property
    def nstep(self):
        return round(1/(self.fps*self.timestep))


@dataclass(frozen=True)
class ReferenceFrame:
    position: np.ndarray
    velocity: np.ndarray
    acceleration: np.ndarray
    jerk: np.ndarray
    start: tuple
    end: tuple


def _readonly(value):
    value = np.array(value, dtype=np.float64, copy=True)
    if not np.isfinite(value).all():
        raise ValueError('nonfinite control reference')
    value.flags.writeable = False
    return value


def sample_path_frame(path, frame_index, total_frames, clock):
    """Sample at right endpoints of each 2 ms integration interval.

    The frame duration and rounded whole-path duration are unchanged. At the
    last substep the command equals the existing 20 Hz interval-end action.
    Polynomial knots inside a frame are handled by path.evaluate itself.
    """
    if (not isinstance(frame_index, int) or not isinstance(total_frames, int) or
            total_frames < 1 or not 0 <= frame_index < total_frames):
        raise ValueError('invalid frame index or duration')
    indices = frame_index*clock.nstep + np.arange(1, clock.nstep+1)
    progress = indices/(total_frames*clock.nstep)
    duration = total_frames/clock.fps
    values = tuple(_readonly(x) for x in path.evaluate(progress, duration))
    if len(values) != 4 or any(x.ndim != 2 or x.shape[0] != clock.nstep for x in values):
        raise ValueError('path must return position/velocity/acceleration/jerk matrices')
    if any(x.shape != values[0].shape for x in values):
        raise ValueError('inconsistent reference shapes')
    start = tuple(_readonly(x) for x in path.evaluate(frame_index/total_frames, duration))
    end = tuple(_readonly(x) for x in path.evaluate((frame_index+1)/total_frames, duration))
    return ReferenceFrame(*values, start, end)


def sample_path_targets(path, frame_index, frame_count, substeps, fps=20):
    """Integration adapter preserving Simulation's float32 target convention.

    Runtime must also verify model.opt.timestep*substeps == 1/fps. Replay uses
    actual recorded float64 ctrl rows, not these quantized high-level labels.
    """
    if not isinstance(substeps, int) or substeps < 1:
        raise ValueError('positive integer substep count required')
    reference = sample_path_frame(path, frame_index, frame_count,
                                  PhysicsClock(1/(substeps*fps), fps))
    return reference.position.astype(np.float32)


def require_c2_join(previous, following, *, position_atol=1e-10,
                    velocity_atol=1e-10, acceleration_atol=1e-10):
    """Never silently bridge independently planned, discontinuous references.

    Callers must explicitly plan a checked bridge or choose a compatible path
    start if a new path differs from the prior command/derivatives. Tracking
    error is not permission to reset a command to measured qpos.
    """
    for order, tol in enumerate((position_atol, velocity_atol, acceleration_atol)):
        a, b = np.asarray(previous[order]), np.asarray(following[order])
        if a.shape != b.shape or not np.isfinite(a).all() or not np.isfinite(b).all():
            raise ValueError('invalid C2 boundary state')
        if not np.allclose(a, b, atol=tol, rtol=0):
            raise ValueError(f'discontinuous reference derivative order {order}')


def mapped_controls(position, baseline_ctrl, actuator_ids, reference_columns, gains=None):
    """Map sampled references into actual actuator controls, retaining other channels.

    R1 gripper position actuators need gain=0.5; arm and base joint targets use
    gain=1. Base yaw must already be unwrapped by the existing route planner.
    World-base coordinates must be converted to joint targets BEFORE this map.
    """
    position = np.asarray(position, float); baseline = np.asarray(baseline_ctrl, float)
    ids = np.asarray(actuator_ids, int); columns = np.asarray(reference_columns, int)
    if (position.ndim != 2 or baseline.ndim != 1 or ids.ndim != 1 or
            columns.shape != ids.shape or len(set(ids.tolist())) != len(ids)):
        raise ValueError('invalid or overlapping actuator mapping')
    if (np.any(ids < 0) or np.any(ids >= len(baseline)) or np.any(columns < 0) or
            np.any(columns >= position.shape[1])):
        raise ValueError('mapping index out of range')
    gain = np.ones(len(ids)) if gains is None else np.asarray(gains, float)
    if gain.shape != ids.shape:
        raise ValueError('gain shape mismatch')
    controls = np.broadcast_to(baseline, (len(position), len(baseline))).copy()
    controls[:, ids] = position[:, columns]*gain
    return _readonly(controls)


class AppliedControlJournal:
    """Fixed-shape trace payload, including the executed prefix of a failed frame."""
    def __init__(self, nstep, nu):
        if nstep < 1 or nu < 1:
            raise ValueError('positive control dimensions required')
        self.ctrl = np.zeros((nstep, nu), dtype=np.float64)
        self.executed = 0

    def fields(self):
        return {'ctrl_substeps': self.ctrl.copy(),
                'executed_substeps': np.int32(self.executed)}


def execute_control_frame(mj, model, data, controls, journal, *, guard, before_step=None):
    """Write/step/forward/guard each row; preserve guard failures and prefix evidence.

    Runtime owns the 20 Hz deadline, initial observation, trace append and phase
    checks. before_step can expose this substep's high-level target to guard
    logic. It must not advance physics or change unrelated model parameters.
    A supplied journal survives exceptions and is appended by Runtime.finally.
    """
    controls = np.asarray(controls, dtype=np.float64)
    if controls.shape != journal.ctrl.shape or controls.shape[1] != model.nu:
        raise ValueError('substep control dimensions mismatch')
    if journal.executed or not np.isfinite(controls).all():
        raise ValueError('fresh journal and finite controls required')
    for index, command in enumerate(controls):
        if before_step is not None:
            before_step(index)
        data.ctrl[:] = command
        journal.ctrl[index] = data.ctrl
        mj.mj_step(model, data)
        journal.executed = index+1
        mj.mj_forward(model, data)
        guard()


def replay_control_frame(mj, model, data, recorded_ctrl, executed_substeps, *,
                         expected_nstep, transition_completed):
    """Strict replay of a recorded control prefix; never synthesize missing rows.

    Successful dataset export must require transition_completed. Diagnostic
    replay may explicitly apply the executed prefix of the terminal failed
    frame; it then stops, preserving the original partial-frame timestamp.
    """
    controls = np.asarray(recorded_ctrl)
    if (controls.dtype != np.float64 or controls.shape != (expected_nstep, model.nu) or
            not np.isfinite(controls).all() or not isinstance(executed_substeps, (int, np.integer)) or
            not 0 <= executed_substeps <= expected_nstep):
        raise ValueError('invalid recorded substep controls')
    if transition_completed and executed_substeps != expected_nstep:
        raise ValueError('completed interval is missing physical controls')
    for command in controls[:executed_substeps]:
        data.ctrl[:] = command
        mj.mj_step(model, data)
        mj.mj_forward(model, data)
