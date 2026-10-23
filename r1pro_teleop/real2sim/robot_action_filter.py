"""Mandatory mobile19 command bounds for website simulation, independent of model.

Raw predictions remain evidence. This is not a collision, effort or hardware
safety certification; it constrains position targets and their commanded rate.
"""
import hashlib
import json
from pathlib import Path

import numpy as np

FILTER_VERSION = 'mandatory_robot_filter/2'
ARMS = np.r_[0:7, 8:15]
GRIPPERS = np.array([7, 15])


def validate_limits(limits):
    try:
        if limits['schema'] != 'robot_action_limits/1':
            raise ValueError()
        for key in ('max_step_rad', 'max_velocity_rad_s',
                    'max_tracking_error_rad', 'max_observation_age_seconds'):
            value = limits[key]
            if isinstance(value, bool) or not np.isfinite(value) or value <= 0:
                raise ValueError()
        ranges = [limits['gripper_range_m']]
        ranges += [limits['mechanical']['ranges'][f'{side}_arm_joint{j}']
                   for side in ('left', 'right') for j in range(1, 8)]
        for bounds in ranges:
            values = np.asarray(bounds, dtype=float)
            if values.shape != (2,) or not np.isfinite(values).all() or values[0] >= values[1]:
                raise ValueError()
        if limits['gripper_range_m'][0] < 0:
            raise ValueError()
    except (KeyError, TypeError, ValueError):
        raise ValueError('robot_filter_invalid_limits') from None
    return limits


def load_limits(code_root=None):
    root = Path(code_root) if code_root else Path(__file__).resolve().parents[2]
    paths = [root/'gpu/robot_action_limits.json', root/'apps/scene-agent/gpu/robot_action_limits.json']
    path = next((p for p in paths if p.is_file()), None)
    if path is None:
        raise ValueError('robot_filter_limits_missing')
    return validate_limits(json.loads(path.read_text(encoding='utf8')))


def contract_id(limits):
    validate_limits(limits)
    return FILTER_VERSION + ':' + hashlib.sha256(
        json.dumps(limits, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def configured_limits(options=None, code_root=None):
    """Per-run limits may tighten, never exceed the registered robot envelope."""
    limits = load_limits(code_root)
    options = {} if options is None else options
    fields = {'maxStepRad': 'max_step_rad', 'maxVelocityRadS': 'max_velocity_rad_s',
              'maxTrackingErrorRad': 'max_tracking_error_rad',
              'maxObservationAgeSeconds': 'max_observation_age_seconds'}
    if not isinstance(options, dict) or set(options)-set(fields):
        raise ValueError('robot_filter_unknown_setting')
    for key, value in options.items():
        field = fields[key]
        if type(value) not in (int, float) or not np.isfinite(value) or not 0 < value <= limits[field]:
            raise ValueError('robot_filter_setting_exceeds_robot_envelope:'+key)
        limits[field] = value
    return validate_limits(limits)


def interpolate_commands(previous, target, substep, substeps=25):
    """Convex interpolation of already filtered endpoints at 500 Hz."""
    if type(substep) is not int or not 1 <= substep <= substeps:
        raise ValueError('robot_filter_invalid_substep')
    previous, target = np.asarray(previous, dtype=float), np.asarray(target, dtype=float)
    if previous.shape != target.shape or not np.isfinite([previous, target]).all():
        raise ValueError('robot_filter_invalid_interpolation')
    return previous + (target-previous)*(substep/substeps)


def bounds(limits, model=None):
    validate_limits(limits)
    low = np.zeros(16); high = np.zeros(16)
    for side, start in (('left', 0), ('right', 8)):
        for j in range(8):
            names = [f'{side}_arm_joint{j+1}'] if j < 7 else [f'{side}_gripper_finger_joint{k}' for k in (1, 2)]
            lo, hi = limits['mechanical']['ranges'][names[0]] if j < 7 else limits['gripper_range_m']
            if model is not None:
                for name in names:
                    idx = model.joint(name).id
                    r = np.asarray(model.jnt_range[idx], dtype=float) * (1 if j < 7 else 2)
                    if not model.jnt_limited[idx] or not np.isfinite(r).all():
                        raise ValueError('robot_filter_invalid_mechanical_limits')
                    lo, hi = max(lo, r[0]), min(hi, r[1])
            if lo >= hi:
                raise ValueError('robot_filter_empty_limit_intersection')
            low[start+j], high[start+j] = lo, hi
    return low, high


def vector(value):
    result = np.asarray(value, dtype=float)
    if result.shape != (19,) or not np.isfinite(result).all():
        raise ValueError('robot_filter_invalid_vector')
    return result


def representable_clip(values, low, high):
    """Use inward-rounded float32 endpoints, as consumed by PhysX/ROS.

    Ordinary casting can turn an exact upper/lower bound into an out-of-range
    target. This changes no physical tolerance and also preserves rate bounds.
    """
    lo = np.asarray(low, dtype=np.float32)
    hi = np.asarray(high, dtype=np.float32)
    lo = np.where(lo.astype(float) < low, np.nextafter(lo, np.float32(np.inf)), lo)
    hi = np.where(hi.astype(float) > high, np.nextafter(hi, np.float32(-np.inf)), hi)
    if np.any(lo > hi):
        raise ValueError('robot_filter_no_valid_command')
    return np.clip(np.clip(values, low, high).astype(np.float32), lo, hi).astype(float)


def bound_actions(actions, limits, horizon):
    """Validate before clipping: Inf must never turn into an accepted endpoint."""
    raw = np.asarray(actions, dtype=float)
    if raw.shape != (horizon, 19) or not np.isfinite(raw).all():
        raise ValueError('robot_filter_invalid_action_chunk')
    low, high = bounds(limits)
    applied = raw.copy()
    applied[:, :16] = representable_clip(raw[:, :16], low, high)
    applied[:, 16:] = 0.  # Fixed-base policy channels; runtime owns the actual hold.
    return applied


def filter_command(command, previous, measured, model, limits, observation_age, dt=.05):
    """Intersect mechanical and per-frame rate bounds, failing closed on feedback."""
    target, previous, measured = map(vector, (command, previous, measured))
    low, high = bounds(limits, model)
    if (not np.isfinite(observation_age) or observation_age < 0
            or observation_age > limits['max_observation_age_seconds']):
        raise ValueError('robot_filter_stale_feedback')
    if not np.isfinite(dt) or dt <= 0 or dt > .05:
        raise ValueError('robot_filter_invalid_control_period')
    if np.max(np.abs(measured[ARMS]-previous[ARMS])) > limits['max_tracking_error_rad']:
        raise ValueError('robot_filter_tracking_error')
    if np.any(previous[:16] < low) or np.any(previous[:16] > high):
        raise ValueError('robot_filter_previous_outside_limits')
    # PhysX consumes float32 targets at 25 substeps. Two rounded adjacent
    # interpolants can differ by one ULP more than the ideal increment. Reserve
    # two ULPs per substep (also covering float64 interpolation arithmetic).
    # This tightens the command numerically; it is not a physical tolerance.
    requested_step = min(limits['max_step_rad'], limits['max_velocity_rad_s'] * dt)
    magnitude = np.maximum(np.abs(previous[ARMS]-requested_step),np.abs(previous[ARMS]+requested_step))
    quantum = np.spacing(magnitude.astype(np.float32)).astype(float)
    step = np.minimum(limits['max_step_rad'],np.maximum(0.,limits['max_velocity_rad_s']*dt-2*25*quantum))
    low[ARMS] = np.maximum(low[ARMS], previous[ARMS]-step)
    high[ARMS] = np.minimum(high[ARMS], previous[ARMS]+step)
    applied = target.copy()
    applied[:16] = representable_clip(target[:16], low, high)
    applied[16:] = previous[16:]  # Never accept policy-driven base movement.
    if not np.isfinite(applied).all() or np.any(low > high):
        raise ValueError('robot_filter_no_valid_command')
    return applied
