"""Explicit prepared-pose initialization for diagnostics, never an online teacher.

Sources must be registered in a frozen training manifest and retain their hashes.
Velocities are reset to zero; this is a pose-matched diagnostic, not exact replay.
"""
import hashlib
import json
from pathlib import Path

import numpy as np

from .robot_action_filter import bounds, representable_clip


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def prepared_pick_start(manifest_path, source_room, case, limits):
    manifest_path, source_room = Path(manifest_path), Path(source_room)
    manifest = json.loads(manifest_path.read_text())
    if manifest.get('schema') != 'parallel_pickplace_frozen_training/1' or manifest.get('ready') is not True:
        raise ValueError('diagnostic_start_requires_frozen_manifest')
    rows = [s for p in manifest['pairs'] for s in p['segments']
            if Path(s['source_room']) == source_room and s['prompt'] == 'Pick up the tray']
    if len(rows) != 1:
        raise ValueError('diagnostic_start_source_not_unique')
    row = rows[0]
    trace, result_path = source_room/'native_trace.npz', source_room/'result.json'
    if sha(trace) != row['source_trace_sha256'] or sha(result_path) != row['source_result_sha256']:
        raise ValueError('diagnostic_start_source_hash_changed')
    result = json.loads(result_path.read_text())
    receipt = json.loads(Path(row['actual_engine_exit_receipt']).read_text())
    if receipt.get('actual_child_wait') is not True or receipt.get('returncode') != 0 or not result.get('passed'):
        raise ValueError('diagnostic_start_source_not_successfully_closed')
    for key in ('seed', 'parent_scene_id', 'parent_split', 'initial_base_world', 'tray_pose'):
        if result['case'][key] != case[key]:
            raise ValueError('diagnostic_start_case_mismatch:'+key)
    frame = row['source_frame_interval'][0]
    if type(frame) is not int or frame < 1 or row['frames'] != 60 or row['source_frame_interval'][1]-frame!=60:
        raise ValueError('diagnostic_start_invalid_pick_span')
    with np.load(trace, allow_pickle=False) as z:
        if row['source_frame_interval'][1]>=len(z['state']):
            raise ValueError('diagnostic_start_invalid_pick_span')
        state = np.asarray(z['state'][frame], float)
        initial_base = np.asarray(z['state'][0, 16:19], float)
        tray = np.asarray(z['tray_pose'][frame, 0], float)
    station_path = source_room/'initial_base_station.json'
    origin = np.asarray(json.loads(station_path.read_text())['original_drive_origin'], float)
    if state.shape != (19,) or tray.shape != (7,) or origin.shape != (3,) or initial_base.shape != (3,) or not np.isfinite(np.r_[state, tray, origin, initial_base]).all():
        raise ValueError('diagnostic_start_nonfinite_or_invalid_state')
    low, high = bounds(limits)
    bounded = representable_clip(state[:16], low, high)
    base = origin + state[16:]
    base[2] = np.arctan2(np.sin(base[2]), np.cos(base[2]))
    # Match the existing cache's float32 subtraction from FULL-EPISODE first
    # feedback, not a new origin at the prepared Pick frame.
    policy_base = state[16:].astype(np.float32)-initial_base.astype(np.float32)
    return dict(schema='prepared_pick_pose_diagnostic/2', scope='prepared_pose_policy_diagnostic',
                source_room=str(source_room), source_frame=frame, manifest_sha256=sha(manifest_path),
                trace_sha256=row['source_trace_sha256'], result_sha256=row['source_result_sha256'],
                station_sha256=sha(station_path), original_state=state.tolist(),
                source_initial_base_state=initial_base.tolist(),
                policy_initial_base_state=policy_base.tolist(),
                state16=bounded.tolist(), tray_pose=tray.tolist(), base_world=base.tolist(),
                initialization_bound_delta=(bounded-state[:16]).tolist(),
                velocity_initialization='zero_not_recorded_source_velocity',
                gripper_finger_initialization='symmetric_half_of_measured_total_opening',
                initialization_only=True, online_teacher=False, full_task_success_eligible=False,
                training_eligible=False)


def validate_prepared_start(start, limits):
    if (start.get('schema') != 'prepared_pick_pose_diagnostic/2' or start.get('initialization_only') is not True
            or start.get('online_teacher') is not False or start.get('full_task_success_eligible') is not False
            or start.get('training_eligible') is not False):
        raise ValueError('invalid_prepared_pose_diagnostic_contract')
    state = np.asarray(start['state16'], float)
    tray = np.asarray(start['tray_pose'], float)
    base = np.asarray(start['base_world'], float)
    original = np.asarray(start['original_state'], float)
    initial_base = np.asarray(start['source_initial_base_state'], float)
    policy_base = np.asarray(start['policy_initial_base_state'], float)
    if state.shape != (16,) or tray.shape != (7,) or base.shape != (3,) or not np.isfinite(np.r_[state, tray, base]).all():
        raise ValueError('diagnostic_start_nonfinite_or_invalid_state')
    low, high = bounds(limits)
    if np.any(state < low) or np.any(state > high) or not np.isclose(np.linalg.norm(tray[3:]), 1, atol=1e-5):
        raise ValueError('diagnostic_start_outside_registered_bounds')
    if (original.shape!=(19,) or initial_base.shape!=(3,) or policy_base.shape!=(3,)
            or not np.isfinite(np.r_[original,initial_base,policy_base]).all()
            or not np.array_equal(policy_base,original[16:].astype(np.float32)-initial_base.astype(np.float32))):
        raise ValueError('diagnostic_start_base_reference_mismatch')
    return state, tray, base


def policy_base_reference(measured_state, start, limits):
    """Preserve the cached initial base observation while measuring later drift."""
    measured=np.asarray(measured_state,dtype=float)
    if measured.shape!=(19,) or not np.isfinite(measured).all():
        raise ValueError('diagnostic_start_nonfinite_or_invalid_state')
    if start is None:return measured[16:].copy()
    validate_prepared_start(start,limits)
    return measured[16:]-np.asarray(start['policy_initial_base_state'],float)


def initial_commands(states, prepared_rooms=()):
    """Normal starts open grippers; prepared starts hold their measured opening."""
    commands=np.asarray(states,dtype=float).copy()
    if commands.ndim!=2 or commands.shape[1]!=19 or not np.isfinite(commands).all():
        raise ValueError('invalid_initial_room_states')
    prepared=set(prepared_rooms)
    if any(type(i) is not int or not 0<=i<len(commands) for i in prepared):
        raise ValueError('invalid_prepared_room_index')
    for i in range(len(commands)):
        if i not in prepared:commands[i,[7,15]]=.08
    return commands
