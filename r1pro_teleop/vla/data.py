"""Immutable frame-aligned VLA supervision inventory; no simulator or trainer imports.

Video references describe original media ranges, never newly cut/retimed clips.
Metadata alone cannot establish video quality or turn failed rollouts into experts.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import subprocess

import h5py
import numpy as np

from r1pro_teleop.airport_fsm.contracts import NAMES, BASE_NAMES, camera_shapes

SCHEMA = 'airport_vla_segments/1'
ACTION_SEMANTICS = ('absolute joint references (rad), physical gripper opening (m), '
                    'then planar position-servo targets: world dx/dy from initial origin (m), '
                    'yaw offset from initial heading (rad); not torque or chassis cmd_vel')
TAKEOFF_CONTACT_HEIGHT_TOLERANCE_M = .02


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def probe_video(path):
    """Count decoded frames rather than trusting container frame-count tags."""
    command = ['ffprobe', '-v', 'error', '-count_frames', '-select_streams', 'v:0',
               '-show_entries', 'stream=width,height,avg_frame_rate,nb_read_frames',
               '-of', 'json', str(path)]
    data = json.loads(subprocess.check_output(command, text=True))['streams'][0]
    numerator, denominator = data['avg_frame_rate'].split('/')
    return {'width': int(data['width']), 'height': int(data['height']),
            'fps': float(numerator) / float(denominator),
            'frames': int(data['nb_read_frames'])}


def validate_trace(path, scene_id, split):
    with h5py.File(path, 'r') as f:
        if f.attrs.get('schema') not in ('airport_fsm_raw/1', 'airport_fsm_raw/2'):
            raise ValueError('unsupported_trace_schema')
        metadata = json.loads(f.attrs['metadata_json'])
        metadata['observation_semantics'] = str(f.attrs.get('observation_semantics',
            'state/images before action interval; action[t] applied after observation[t]'))
        if metadata['scene_id'] != scene_id or metadata['split'] != split:
            raise ValueError('trace_scene_split_mismatch')
        n = int(f.attrs['num_frames'])
        if n < 2 or any(len(ds) != n for ds in f.values()):
            raise ValueError('trace_frame_count_mismatch')
        # All numeric evidence is checked, including physics journals and guards.
        for name, ds in f.items():
            if np.issubdtype(ds.dtype, np.number) and not np.isfinite(ds[:]).all():
                raise ValueError('nonfinite_trace:' + name)
        if f['state'].shape != (n, 16) or f['action'].shape != (n, 16) or f['base_action'].shape != (n, 3):
            raise ValueError('mobile19_shape_mismatch')
        fps = float(metadata['fps'])
        if not math.isfinite(fps) or fps <= 0 or not np.allclose(f['timestamp'][:], np.arange(n) / fps, atol=1e-8):
            raise ValueError('trace_timestamp_grid_mismatch')
        return metadata, n, fps, f['transition_completed'][:].astype(bool)


def _events(path, n):
    rows = []
    if Path(path).exists():
        for line in Path(path).read_text(encoding='utf-8').splitlines():
            event = json.loads(line)
            frame = event.get('frame')
            if not isinstance(frame, int) or not 0 <= frame <= n:
                raise ValueError('invalid_event_frame')
            if event['event'] in ('operation_selected', 'state_transition'):
                rows.append(event)
    return sorted(rows, key=lambda item: item['frame'])


def language_prompt(segment, operation=None, *, include_phase=False, prompt_mode="legacy"):
    from .prompts import validate_prompt_mode, skill_prompt
    validate_prompt_mode(prompt_mode)
    if prompt_mode == "skill_only_v1":
        return skill_prompt(segment["skill"])
    if prompt_mode == "task_complete_action8_v1":
        from .data_task_labels import label_complete_action
        row, excluded = label_complete_action({**segment, 'operation': operation or {}})
        if row is None:
            raise ValueError(excluded['exclusion_reason'])
        return row['language_prompt']
    if segment['skill'] == 'initialize_posture':
        return 'Move both arms to the initial tucked posture.'
    tray, slot = segment.get('target_tray_id'), segment.get('target_slot_id')
    target = f'tray {tray}' if tray is not None else 'the selected tray'
    verbs = {'navigate_to_tray': 'Move the base toward', 'push_adjust_tray': 'Push and align',
             'grasp_lift_tray': 'Grasp and lift', 'carry_tray': 'Carry',
             'place_release_tray': 'Place and release', 'verify_or_recover': 'Verify'}
    text = f"{verbs.get(segment['skill'], segment['skill'])} {target}"
    if slot is not None:
        text += f' for slot {slot}'
    if operation and operation.get('temporary'):
        text += ' at the temporary supported buffer'
    return text + (f". Current phase: {segment['phase']}." if include_phase else '.')


_language = language_prompt


def _video_ranges(references, start, end, fps, shapes, probe, cache):
    output, missing = {}, []
    for camera, shape in shapes.items():
        candidates = [r for r in references if r['camera'] == camera and
                      int(r.get('source_start_frame', 0)) <= start and
                      int(r.get('source_start_frame', 0)) + int(r['frames']) >= end]
        if not candidates:
            missing.append(camera)
            continue
        if len(candidates) != 1:
            raise ValueError('ambiguous_video_reference:' + camera)
        ref = candidates[0]
        path = Path(ref['path']).resolve()
        entry = {'path': str(path), 'exists': path.is_file(), 'verified': False}
        video_start = int(ref.get('video_start_frame', 0)) + start - int(ref.get('source_start_frame', 0))
        if video_start < 0:
            raise ValueError('negative_video_offset')
        entry.update(start_frame=video_start, end_frame=video_start + end - start,
                     start_time_s=video_start / fps, end_time_s=(video_start + end - start) / fps,
                     interval='half-open', source_start_frame=start, source_end_frame=end)
        if entry['exists'] and probe is not None:
            if str(path) not in cache:
                cache[str(path)] = (probe(path), digest(path))
            measured, sha = cache[str(path)]
            if ref.get('sha256') and ref['sha256'] != sha:
                raise ValueError('video_hash_mismatch')
            if measured['width'] != shape[1] or measured['height'] != shape[0] or abs(measured['fps'] - fps) > 1e-6:
                raise ValueError('video_native_contract_mismatch')
            if measured['frames'] < entry['end_frame']:
                raise ValueError('video_frame_count_mismatch')
            entry.update(verified=True, sha256=sha, measured=measured)
        if not entry['verified']:
            missing.append(camera)
        output[camera] = entry
    return output, missing


def prepare_manifest(collections, output, *, video_references=(), local_qualifications=(),
                     video_probe=None):
    """Inventory all spans; only verified, selected spans have training_ready=true.

    Qualification records require segment_id, trace_sha256, locally_verified=true,
    reviewer, reason. They form a separate failed-prefix data class.
    """
    output = Path(output).resolve()
    roots = [Path(root).resolve() for root in collections]
    if output.exists():
        raise ValueError('refuse_existing_output')
    if any(output.is_relative_to(root) for root in roots):
        raise ValueError('output_must_not_mutate_collection')
    scene_splits, scene_hashes, records, cache = {}, {}, [], {}
    selected_successes = {}
    references = list(video_references)
    qualifications = {q['segment_id']: q for q in local_qualifications}
    if len(qualifications) != len(local_qualifications):
        raise ValueError('duplicate_qualification')
    for root in roots:
        collection = read_json(root / 'collection.json')
        for scene in read_json(root / 'scenes/index.json'):
            sid, split = scene['scene_id'], scene['split']
            if split not in ('train', 'val', 'test'):
                raise ValueError('invalid_scene_split')
            source_hash = scene.get('source_json_sha256')
            if not source_hash:
                raise ValueError('missing_scene_source_hash')
            if sid in scene_splits and scene_splits[sid] != split:
                raise ValueError('scene_split_leakage:' + sid)
            if sid in scene_hashes and scene_hashes[sid] != source_hash:
                raise ValueError('scene_version_mismatch:' + sid)
            scene_splits[sid], scene_hashes[sid] = split, source_hash
            for result_path in sorted((root / 'attempts' / sid).glob('a*/result.json')):
                attempt = result_path.parent
                trace = attempt / 'trace.h5'
                segments_path = attempt / 'segments.json'
                if not trace.is_file() or not segments_path.is_file():
                    continue
                result = read_json(result_path)
                if result.get('scene_id', sid) != sid or result.get('split', split) != split:
                    raise ValueError('result_scene_split_mismatch')
                if (result.get('task_completed', result.get('physics_success', False)) and
                        not result.get('diagnostic_only', False) and sid not in selected_successes):
                    selected_successes[sid] = str(attempt)
                selected_success = selected_successes.get(sid)
                metadata, n, fps, complete = validate_trace(trace, sid, split)
                if metadata.get('environment_source', 'simulation') != 'simulation':
                    raise ValueError('unsupported_environment_source')
                controller_source = metadata.get('controller_source', 'program_generated')
                trace_hash = digest(trace)
                shapes = camera_shapes(metadata['scene'])
                events = _events(attempt / 'events.jsonl', n)
                first_operation = next((e['frame'] for e in events if e['event'] == 'operation_selected'), None)
                settle_frame = round(2 * fps)
                matched_refs = [r for r in references if str(Path(r['trace']).resolve()) == str(trace.resolve())]
                spans = read_json(segments_path)
                previous = 0
                for segment in spans:
                    start, end = segment['start_frame'], segment['end_frame']
                    if (not isinstance(start, int) or not isinstance(end, int) or
                            start != previous or not start < end <= n or
                            segment['scene_id'] != sid or segment['split'] != split):
                        raise ValueError('invalid_segment_partition')
                    previous = end
                    lift_qualification = _verified_lift_takeoff(trace, segment, result, metadata)
                    boundaries = [start] + sorted({e['frame'] for e in events if start < e['frame'] < end}) + [end]
                    if (segment['skill'] == 'verify_or_recover' and segment['phase'] == 'unknown'
                            and start < settle_frame < end and first_operation is not None):
                        boundaries = sorted(set(boundaries + [settle_frame]))
                    for a, b in zip(boundaries[:-1], boundaries[1:]):
                        active = [e for e in events if e['frame'] <= a]
                        operations = [e for e in active if e['event'] == 'operation_selected']
                        transitions = [e for e in active if e['event'] == 'state_transition']
                        op = operations[-1] if operations else {}
                        transition = transitions[-1] if transitions else {}
                        success = bool(result.get('task_completed', result.get('physics_success', False)))
                        eligible = (success and str(attempt) == selected_success and not result.get('diagnostic_only', False) and
                                    not segment.get('recovery', False) and
                                    (not segment.get('needs_review', True) or lift_qualification is not None) and
                                    bool(complete[a:b].all()))
                        initialize = (segment['skill'] == 'verify_or_recover' and segment['phase'] == 'unknown'
                                      and segment['state'] == 'SEARCH_TARGET' and first_operation is not None
                                      and a >= settle_frame and b <= first_operation
                                      and not segment.get('recovery', False) and not result.get('recovery_used', False))
                        skill = 'initialize_posture' if initialize else segment['skill']
                        phase = 'initial_tuck' if initialize else segment['phase']
                        if skill == 'verify_or_recover':
                            eligible = False  # waits/verification remain inventory, not ambiguous BC motions.
                        quality_class = 'complete_task' if success else 'failed_diagnostic'
                        qualification = qualifications.get(segment['segment_id'])
                        if qualification is not None:
                            if (qualification.get('trace_sha256') != trace_hash or
                                    qualification.get('locally_verified') is not True or
                                    not qualification.get('reviewer') or not qualification.get('reason')):
                                raise ValueError('invalid_local_qualification')
                            if not success:
                                quality_class = 'reviewed_local_prefix'
                                eligible = (not segment.get('recovery', False) and
                                            not segment.get('needs_review', True) and bool(complete[a:b].all()))
                        if skill == 'verify_or_recover':
                            eligible = False
                        videos, missing = _video_ranges(matched_refs, a, b, fps, shapes, video_probe, cache)
                        # A learner rollout is not automatically an expert action label.
                        eligible = eligible and controller_source == 'program_generated'
                        records.append({'schema': SCHEMA, 'segment_id': segment['segment_id'] + f'__{a:06d}_{b:06d}',
                            'source_segment_id': segment['segment_id'], 'scene_id': sid, 'split': split,
                            'scene_source_sha256': source_hash, 'collection': str(root),
                            'collection_fingerprint': collection['fingerprint'], 'attempt': attempt.name,
                            'trace': str(trace.resolve()), 'trace_sha256': trace_hash,
                            'result_sha256': digest(result_path), 'start_frame': a, 'end_frame': b,
                            'frames': b-a, 'fps': fps, 'start_time_s': a/fps, 'end_time_s': b/fps,
                            'interval': 'half-open', 'skill': skill, 'phase': phase,
                            'source_skill': segment['skill'], 'source_phase': segment['phase'],
                            'state': segment['state'], 'operation_index': op.get('operation_index'),
                            'operation': op.get('operation'), 'dag_node_id': transition.get('dag_node_id'),
                            'target_tray_id': segment.get('target_tray_id'), 'target_slot_id': segment.get('target_slot_id'),
                            'language_prompt': _language({**segment, 'skill': skill, 'phase': phase}, op.get('operation')),
                            'action_layout': 'mobile19', 'action_names': NAMES + BASE_NAMES,
                            'action_semantics': ACTION_SEMANTICS,
                            'observation_semantics': str(metadata.get('observation_semantics', 'state/images before action interval')),
                            'quality_class': quality_class, 'episode_task_completed': success,
                            'selected_success_attempt': selected_success,
                            'episode_strict_success': bool(result.get('strict_success', result.get('physics_success', False))),
                            'acceptance_profile': result.get('effective_acceptance_profile', result.get('acceptance_profile', 'strict')),
                            'failure_reason': result.get('failure_code'), 'local_qualification': qualification,
                            'source_needs_review': bool(segment.get('needs_review', True)),
                            'verified_lift_takeoff': lift_qualification,
                            'strict_deviations': result.get('strict_deviations', result.get('acceptance_deviations', {})),
                            'approximate_deviation_counts': result.get('approximate_deviation_counts', {}),
                            'initial_posture_qualification': ({'qualification': 'initial_tuck_after_physical_settle',
                                'settle_end_frame': settle_frame, 'first_operation_frame': first_operation}
                                if initialize else None),
                            'supervision_eligible': eligible, 'training_ready': eligible and not missing,
                            'missing_or_unverified_cameras': missing, 'videos': videos,
                            'environment_source': 'simulation', 'controller_source': controller_source,
                            'supervision_action_source': ('recorded_program_generated_controller'
                                if controller_source == 'program_generated' else 'learner_unqualified'),
                            'human_demonstration': False, 'privileged_state_as_observation': False})
                if previous != n:
                    raise ValueError('incomplete_segment_partition')
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('x', encoding='utf-8') as stream:
        for record in records:
            stream.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + '\n')
    return {'path': str(output), 'sha256': digest(output), 'segments': len(records),
            'training_ready': sum(r['training_ready'] for r in records),
            'scenes': len(scene_splits), 'normalization_split': 'train_only'}


def _verified_lift_takeoff(trace, segment, result, metadata):
    """Review the physical takeoff interval, whose initial table contact is legal.

    This only overrides the old whole-interval support==0 annotation. It neither
    changes source labels nor approves failed/recovered/learner trajectories.
    The endpoint is observation[b], after the accepted action[b-1] interval.
    """
    config = metadata.get('config', {})
    if (not result.get('task_completed', result.get('physics_success', False))
            or result.get('diagnostic_only', False) or result.get('recovery_used', False)
            or metadata.get('controller_source', 'program_generated') != 'program_generated'
            or config.get('approximate_completion_enabled') is not True
            or config.get('acceptance_profile') != 'completion_first'
            or segment.get('phase') != 'lift' or segment.get('state') != 'GRASP_TRAY'
            or segment.get('skill') != 'grasp_lift_tray' or segment.get('recovery', False)
            or segment.get('needs_review') is not True):
        return None
    start, end = segment['start_frame'], segment['end_frame']
    minimum = config.get('completion_lift_min_m')
    if (isinstance(minimum, bool) or not isinstance(minimum, (float, int))
            or not math.isfinite(minimum) or minimum <= 0):
        return None
    with h5py.File(trace, 'r') as f:
        required = ('target_tray', 'min_z', 'gripper_contact_force', 'support_contact', 'transition_completed')
        if any(key not in f for key in required) or end >= len(f['transition_completed']):
            return None
        tray = int(f['target_tray'][start])
        if tray < 0 or not np.all(f['target_tray'][start:end] == tray):
            return None
        forces = f['gripper_contact_force'][start:end, tray]
        support = f['support_contact'][start:end, tray]
        if (not f['transition_completed'][start:end].all() or not np.isfinite(forces).all()
                or not (forces > .5).all() or not np.any(support != 0)):
            return None
        if 'recovery' in f and f['recovery'][start:end].any():
            return None
        # Contact may chatter 0 -> supported -> 0 while lift starts at the
        # table. Require a sustained airborne suffix after the LAST contact,
        # and prove the entire preceding takeoff stays near initial height.
        # A descent/recontact after a real lift is not this annotation error.
        supported = np.flatnonzero(support != 0)
        airborne_start = int(supported[-1]) + 1
        baseline = float(f['min_z'][0, tray])
        takeoff_heights = f['min_z'][start:start + airborne_start, tray] - baseline
        if (airborne_start >= len(support) or not np.all(support[airborne_start:] == 0)
                or not np.isfinite(takeoff_heights).all()
                or np.max(np.abs(takeoff_heights)) > TAKEOFF_CONTACT_HEIGHT_TOLERANCE_M):
            return None
        endpoint_force = f['gripper_contact_force'][end, tray]
        clearance = float(f['min_z'][end, tray] - f['min_z'][0, tray])
        if (not np.isfinite(endpoint_force).all() or not (endpoint_force > .5).all()
                or f['support_contact'][end, tray] != 0 or not math.isfinite(clearance)
                or clearance < minimum):
            return None
        return {'qualification': 'verified_lift_takeoff', 'rule_version': 2,
                'original_review_reason': 'support_nonzero_during_legal_initial_takeoff',
                'source_interval': [start, end], 'endpoint_observation_frame': end,
                'initial_supported_frames': int(len(supported)),
                'support_observation_frames': (supported + start).tolist(),
                'last_supported_observation_frame': int(start + supported[-1]),
                'airborne_tail_start_frame': int(start + airborne_start),
                'airborne_tail_interval_frames': int(end - start - airborne_start),
                'early_support_nonmonotonic': bool(np.any(np.diff((support != 0).astype(int)) > 0)),
                'takeoff_near_initial_height_tolerance_m': TAKEOFF_CONTACT_HEIGHT_TOLERANCE_M,
                'takeoff_max_abs_initial_height_delta_m': float(np.max(np.abs(takeoff_heights))),
                'bilateral_min_force_n': float(np.min(forces)),
                'endpoint_force_n': endpoint_force.tolist(), 'endpoint_support_contact': 0,
                'endpoint_clearance_m': clearance, 'declared_lift_min_m': float(minimum),
                'clearance_reference': 'source_trace_frame0_min_z',
                'source_needs_review_preserved': True,
                'source': 'simulation/program_generated'}


def base_qpos_projection(record, *, cache=None):
    """Find actual planar joint columns from the hash-matched scene model.

    Raw base_state is WORLD pose, so it is never an initial-origin observation.
    Do not guess qpos column ordering from a particular MuJoCo model version.
    """
    import mujoco
    xml = Path(record['collection']) / 'scenes' / record['scene_id'] / 'mobile.xml'
    key = str(xml.resolve())
    if cache is not None and key in cache:
        return cache[key]
    with h5py.File(record['trace'], 'r') as f:
        metadata = json.loads(f.attrs['metadata_json'])
    if not metadata.get('scene_xml_sha256') or digest(xml) != metadata['scene_xml_sha256']:
        raise ValueError('state_projection_scene_xml_hash_mismatch')
    model = mujoco.MjModel.from_xml_path(str(xml))
    columns = []
    for name in ('agent_base_x', 'agent_base_y', 'agent_base_yaw'):
        joint = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, name)
        if joint < 0:
            raise ValueError('measured_base_joint_missing:' + name)
        columns.append(int(model.jnt_qposadr[joint]))
    if cache is not None:
        cache[key] = columns
    return columns


def read_mobile19_segment(record, *, state_layout='joint16'):
    """Load only public 16d joint state and 19d action, never tray truth/qpos."""
    trace = record['trace']
    if digest(trace) != record['trace_sha256']:
        raise ValueError('trace_hash_changed')
    a, b = record['start_frame'], record['end_frame']
    columns = base_qpos_projection(record) if state_layout == 'mobile19' else None
    with h5py.File(trace, 'r') as f:
        state = f['state'][a:b].astype(np.float32)
        if state_layout == 'mobile19':
            if 'qpos' not in f or max(columns) >= f['qpos'].shape[1]:
                raise ValueError('measured_base_qpos_required')
            state = np.concatenate((state, f['qpos'][a:b][:, columns]), axis=-1).astype(np.float32)
        elif state_layout != 'joint16':
            raise ValueError('unsupported_state_layout')
        action = np.concatenate((f['action'][a:b], f['base_action'][a:b]), axis=-1).astype(np.float32)
    return {'observation.state': state, 'action': action,
            'task': record['language_prompt']}


def iter_training_records(path, *, split='train', include_reviewed_local=False):
    """Explicit split gate: held-out scenes never enter training/normalization."""
    if split not in ('train', 'val', 'test'):
        raise ValueError('invalid_scene_split')
    with Path(path).open(encoding='utf-8') as stream:
        for line in stream:
            row = json.loads(line)
            if row['schema'] != SCHEMA:
                raise ValueError('unsupported_manifest_schema')
            if row['split'] != split or not row['training_ready']:
                continue
            if row['quality_class'] == 'complete_task' or (
                    include_reviewed_local and row['quality_class'] == 'reviewed_local_prefix'):
                yield row
