"""Isaac-native corpus gate. Legacy MuJoCo media cannot be relabeled as native.

The native task observer must close qualification before this module accepts
an episode. This gate verifies that receipt and media/time alignment; it is
not a replacement for native physical task evaluation.
"""
import hashlib
import json
from pathlib import Path
import subprocess
import re
import time
import numpy as np

PROMPTS = ('Pick up the tray', 'Place the tray', 'Flush tray to the left')
ACTION_DIRS = ('pick_up_the_tray', 'place_the_tray', 'flush_tray_to_the_left')
CAMERAS = {'head_left': (1920, 1536), 'head_right': (1920, 1536),
           'left_wrist': (1280, 720), 'right_wrist': (1280, 720)}
THREE_TRAY_PROFILE = 'isaac_three_tray_loaded_action3_v1'
THREE_TRAY_RULE = '20261015_three_tray_loaded_handover_left_motion3cm_v1'


def validate_three_tray_cycles(manifest, qualification, spans):
    """Validate repeated three-label cycles; never translate old push semantics."""
    if manifest.get('task_rule_revision') != THREE_TRAY_RULE or not spans or len(spans) % 3:
        raise ValueError('isaac_three_tray_loaded_rule_and_cycles_required')
    if (qualification.get('profile') != THREE_TRAY_PROFILE or
            set(qualification.get('qualified_tray_ids', [])) != {'tray_0', 'tray_1', 'tray_2'}):
        raise ValueError('isaac_all_three_trays_need_native_qualification')
    loads = manifest.get('payload_load_events', [])
    cycles = qualification.get('cycles', [])
    if len(loads) != len(spans) // 3 or len(cycles) != len(loads):
        raise ValueError('isaac_each_three_tray_cycle_needs_actual_load_and_qualification')
    for i, (load, physical) in enumerate(zip(loads, cycles)):
        pick, place, flush = spans[i * 3:i * 3 + 3]
        tray = pick.get('tray_id')
        if (tray not in ('tray_0', 'tray_1', 'tray_2') or
                tuple(s.get('prompt') for s in (pick, place, flush)) != PROMPTS or
                any(s.get('tray_id') != tray or s.get('cycle_id') != i for s in (pick, place, flush))):
            raise ValueError('isaac_three_tray_cycle_identity_or_prompt_changed')
        frame = load.get('frame')
        if (type(frame) is not int or not place['end'] <= frame < flush['start'] or
                load.get('tray_id') != tray or load.get('cycle_id') != i or
                load.get('robot_and_all_trays_unchanged') is not True):
            raise ValueError('isaac_three_tray_environment_loading_invalid')
        if physical.get('tray_id') != tray or physical.get('cycle_id') != i:
            raise ValueError('isaac_three_tray_physical_cycle_identity_changed')
        displacement = physical.get('actual_tray_left_displacement_m')
        if (isinstance(displacement, bool) or not isinstance(displacement, (float, int)) or
                not np.isfinite(displacement) or displacement < .03):
            raise ValueError('isaac_three_tray_requires_real_tray_left_motion_3cm')
        for key in ('opposed_long_edges_pick_place', 'empty_pick_place', 'front_region_manipulation',
                    'long_axis_parallel_robot_forward', 'right_actual_push', 'left_stable_grasp',
                    'right_release_after_left_grasp', 'left_motion_after_right_release',
                    'final_release', 'stable_table_support', 'all_three_payloads_on_tray'):
            if physical.get(key) is not True:
                raise ValueError('isaac_three_tray_missing_native_physical_evidence:' + key)


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(8 * 1024**2), b''):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_inside(root, relative):
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError('isaac_artifact_missing_or_outside_episode')
    return path


def video_probe(path):
    result = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0',
        '-count_frames', '-show_entries', 'stream=width,height,avg_frame_rate,nb_read_frames',
        '-of', 'json', str(path)], capture_output=True, text=True, check=True)
    stream, = json.loads(result.stdout)['streams']
    numerator, denominator = map(int, stream['avg_frame_rate'].split('/'))
    return dict(width=int(stream['width']), height=int(stream['height']),
                frames=int(stream['nb_read_frames']), fps=numerator / denominator)


def validate_episode(root, registry, *, probe=video_probe):
    root = Path(root).resolve()
    manifest = json.loads((root / 'episode.json').read_text())
    if (manifest.get('schema') != 'airport_isaac_episode/1' or
        manifest.get('engine') != 'isaacsim' or manifest.get('physics_backend') != 'physx' or
        manifest.get('source') != 'simulation/program_generated' or
        manifest.get('execution_mode') != 'expert_collection' or
        manifest.get('free_run_diagnostic') is not False):
        raise ValueError('isaac_native_collection_provenance_required')
    parent = manifest['parent_scene_id']
    for value in (parent, manifest.get('episode_id')):
        if not isinstance(value, str) or re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,191}', value) is None:
            raise ValueError('isaac_safe_scene_and_episode_identifiers_required')
    if manifest.get('split') not in ('train', 'val', 'test') or registry.get(parent) != manifest['split']:
        raise ValueError('isaac_parent_split_leakage')
    receipt = json.loads(resolve_inside(root, manifest['exit_receipt']).read_text())
    if receipt.get('returncode') != 0 or receipt.get('actual_child_wait') is not True:
        raise ValueError('isaac_actual_successful_process_exit_required')
    trace = resolve_inside(root, manifest['trace'])
    profile = manifest.get('profile', 'isaac_single_tray_action3_v1')
    if profile not in ('isaac_single_tray_action3_v1', THREE_TRAY_PROFILE):
        raise ValueError('isaac_unknown_task_profile')
    multi = profile == THREE_TRAY_PROFILE
    qualification_path = resolve_inside(root, manifest['qualification'])
    qualification = json.loads(qualification_path.read_text())
    if (qualification.get('schema') != 'airport_isaac_task_qualification/1' or
        qualification.get('engine') != 'isaacsim' or
        qualification.get('physics_backend') != 'physx' or
        qualification.get('complete_task_success') is not True or
        qualification.get('trace_sha256') != sha(trace) or
        qualification.get('episode_id') != manifest.get('episode_id') or
        qualification.get('task_rule_revision') != manifest.get('task_rule_revision')):
        raise ValueError('isaac_whole_native_task_qualification_required')
    if manifest.get('fps') != 20 or manifest.get('physics_dt') != .002 or manifest.get('substeps_per_frame') != 25:
        raise ValueError('isaac_control_record_timebase_required')
    front_evidence=None
    with np.load(trace, allow_pickle=False) as arrays:
        t = arrays['time']; n = len(t) - 1
        if n < 1 or not np.isfinite(t).all() or not np.allclose(np.diff(t), .05, atol=1e-4, rtol=0):
            raise ValueError('isaac_nonmonotonic_or_unaligned_control_time')
        for key, shape in [('state', (n + 1, 19)), ('raw_action', (n, 19)), ('action', (n, 19)),
                           ('submitted_control', (n, 25, 21)), ('tray_pose', (n + 1, 3, 7) if multi else (n + 1, 7))]:
            if arrays[key].shape != shape or not np.isfinite(arrays[key]).all():
                raise ValueError('isaac_invalid_trace_array:' + key)
        if 'front_manipulating' in arrays:
            from r1pro_teleop.single_tray_3table.observer import table_front_region_violation
            mapping=json.loads((root/'native_mapping.json').read_text())
            if mapping.get('front_drift_limit_m')!=.05:raise ValueError('isaac_authorized_front_drift_contract_required')
            base=next(i for i,p in enumerate(mapping['sensor_paths']) if Path(p).name=='base_link')
            mask=arrays['front_manipulating'];refs=arrays['front_reference_xy'];positions=arrays['rigid_pose'][:,base,:2]
            if mask.shape!=(n+1,) or refs.shape!=(n+1,2) or not np.isfinite(refs).all():raise ValueError('isaac_front_drift_trace_shape')
            drift=np.linalg.norm(positions-refs,axis=1)
            for frame in np.flatnonzero(mask):
                ti=int(arrays['front_reference_table_index'][frame])
                if ti<0 or ti>=len(mapping['task_tables']):raise ValueError('isaac_front_table_identity')
                if (table_front_region_violation(mapping['task_tables'][ti],refs[frame]) or drift[frame]>.05+1e-9 or
                        abs(drift[frame]-arrays['front_drift_m'][frame])>1e-6 or not arrays['front_region_ok'][frame]):
                    raise ValueError('isaac_front_reference_or_drift_not_closed')
            front_evidence=dict(strict_reference_verified=True,authorized_limit_m=.05,
                actual_max_drift_m=round(float(drift[mask].max()),9) if mask.any() else 0.,
                allowance_frames=int(np.asarray(arrays['front_allowance_used'])[mask].sum()))
    spans = manifest['actions']
    if not multi and (len(spans) != 3 or tuple(row.get('prompt') for row in spans) != PROMPTS):
        raise ValueError('isaac_exact_three_prompts_required')
    previous = 0
    for span in spans:
        start, end = span['start'], span['end']
        if type(start) is not int or type(end) is not int or not previous <= start < end <= n:
            raise ValueError('isaac_action_spans_invalid_or_overlapping')
        previous = end
    if multi:
        validate_three_tray_cycles(manifest, qualification, spans)
    else:
        load = manifest['payload_load_frame']
        if type(load) is not int or not spans[1]['end'] <= load < spans[2]['start']:
            raise ValueError('isaac_payload_loading_must_be_outside_training_spans')
    media = manifest['videos']
    if set(media) != set(CAMERAS):
        raise ValueError('isaac_four_native_cameras_required')
    videos = {}
    for name, dimensions in CAMERAS.items():
        row = media[name]; path = resolve_inside(root, row['path'])
        if sha(path) != row['sha256']:
            raise ValueError('isaac_native_video_hash_changed')
        info = probe(path)
        if (info['width'], info['height']) != dimensions or info['frames'] != n or abs(info['fps'] - 20) > 1e-6:
            raise ValueError('isaac_native_camera_time_alignment_failed')
        videos[name] = dict(path=str(path), **info, sha256=row['sha256'])
    result=dict(episode_id=manifest['episode_id'], parent_scene_id=parent,
        episode_directory=str(root),
        split=manifest['split'], frames=n, actions=spans, videos=videos, profile=profile,
        engine='isaacsim', physics_backend='physx', trace=str(trace),
        trace_sha256=sha(trace), manifest_sha256=sha(root / 'episode.json'),
        qualification_sha256=sha(qualification_path), source='simulation/program_generated')
    if front_evidence is not None:result['front_drift_evidence']=front_evidence
    return result


def freeze_corpus(episodes, registry, output, *, probe=video_probe):
    """Freeze indices only after all three splits and complete sources close."""
    rows = [validate_episode(p, registry, probe=probe) for p in episodes]
    if {row['split'] for row in rows} != {'train', 'val', 'test'}:
        raise ValueError('isaac_first_batch_requires_train_val_test')
    if len({row['episode_id'] for row in rows}) != len(rows) or len({row['trace_sha256'] for row in rows}) != len(rows):
        raise ValueError('isaac_duplicate_episode_or_trace')
    if len({row['profile'] for row in rows}) != 1:
        raise ValueError('isaac_single_and_three_tray_scopes_cannot_share_corpus')
    output = Path(output)
    if output.exists():
        raise FileExistsError('isaac_frozen_corpus_already_exists')
    output.mkdir(parents=True)
    for index, directory in enumerate(ACTION_DIRS):
        target = output / 'by_action' / directory
        target.mkdir(parents=True)
        with (target / 'segments.jsonl').open('w') as stream:
            for row in rows:
                for span in row['actions']:
                    if span['prompt'] == PROMPTS[index]:
                        stream.write(json.dumps(dict(episode_id=row['episode_id'], split=row['split'],
                            trace=row['trace'], videos=row['videos'], **span)) + '\n')
    manifest = dict(schema='airport_isaac_frozen_corpus/1', engine='isaacsim', physics_backend='physx',
        profile=rows[0]['profile'], full_sources=len(rows), action_segments=sum(len(r['actions']) for r in rows), native_camera_files=4 * len(rows),
        counts={split: dict(full_sources=sum(r['split'] == split for r in rows),
                           action_segments=sum(len(r['actions']) for r in rows if r['split'] == split)) for split in ('train', 'val', 'test')},
        episodes=rows, data_index_ready=True, training_cache_ready=False,
        note='Indices reference validated full videos; action video clips and model cache must close separately.')
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2))
    return manifest


def load_frozen(path, registry, *, probe=video_probe):
    path = Path(path)
    manifest = json.loads(path.read_text())
    if manifest.get('schema') != 'airport_isaac_frozen_corpus/1' or not manifest.get('data_index_ready'):
        raise ValueError('isaac_frozen_native_index_required')
    for old in manifest['episodes']:
        fresh = validate_episode(old['episode_directory'], registry, probe=probe)
        if fresh != old:
            raise ValueError('isaac_frozen_source_changed')
    return manifest


def export_action_clips(manifest_path, registry, output):
    """Re-encode exact frame ranges; four native views remain on the server."""
    manifest = load_frozen(manifest_path, registry)
    return _export_action_rows(manifest,manifest_path,output)


def export_episode_preview(episode,registry,output):
    """One qualified source may be inspected before all training splits exist."""
    row=validate_episode(episode,registry)
    manifest=dict(episodes=[row],full_sources=1)
    return _export_action_rows(manifest,Path(episode)/'episode.json',output,preview=True)


def _export_action_rows(manifest,manifest_path,output,*,preview=False):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    completed = []
    try:
        for source in manifest['episodes']:
            with np.load(source['trace'], allow_pickle=False) as arrays:
                for index, span in enumerate(source['actions']):
                    task_index = PROMPTS.index(span['prompt'])
                    target = output / 'by_action' / ACTION_DIRS[task_index] / source['split'] / source['episode_id']
                    if source['profile'] == THREE_TRAY_PROFILE:
                        target = target / f"cycle_{span['cycle_id']:04d}_{span['tray_id']}"
                    target.mkdir(parents=True, exist_ok=False)
                    start, end = span['start'], span['end']; frames = end - start
                    videos = {}
                    for camera, video in source['videos'].items():
                        path = target / (camera + '.mp4')
                        subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-n',
                            '-ss',f'{start/20:.6f}','-i', video['path'],
                            '-vf', 'setpts=PTS-STARTPTS','-frames:v',str(frames),
                            '-an', '-c:v', 'libx264', '-preset', 'fast', '-crf', '18',
                            '-threads','2','-fps_mode', 'passthrough', str(path)], check=True)
                        info = video_probe(path)
                        if info['frames'] != frames or info['fps'] != 20 or (info['width'], info['height']) != CAMERAS[camera]:
                            raise ValueError('isaac_action_clip_failed_frame_closure')
                        videos[camera] = dict(path=str(path), sha256=sha(path), **info)
                    np.savez_compressed(target / 'trajectory.npz',
                        time=arrays['time'][start:end + 1], state=arrays['state'][start:end + 1],
                        raw_action=arrays['raw_action'][start:end],
                        action=arrays['action'][start:end],
                        submitted_control=arrays['submitted_control'][start:end],
                        tray_pose=arrays['tray_pose'][start:end + 1],
                        source_frame=np.arange(start, end))
                    (target / 'instruction.txt').write_text(span['prompt'] + '\n')
                    row = dict(episode_id=source['episode_id'], parent_scene_id=source['parent_scene_id'],
                        split=source['split'], engine='isaacsim', physics_backend='physx',
                        prompt=span['prompt'], start=start, end=end, frames=frames, videos=videos,
                        profile=source['profile'], cycle_id=span.get('cycle_id'), tray_id=span.get('tray_id'),
                        trajectory=str(target / 'trajectory.npz'),
                        trajectory_sha256=sha(target / 'trajectory.npz'),
                        instruction_path=str(target / 'instruction.txt'), instruction_sha256=sha(target / 'instruction.txt'),
                        source_trace_sha256=source['trace_sha256'])
                    (target / 'segment.json').write_text(json.dumps(row, indent=2))
                    completed.append(row)
                    progress=output/'export_progress.json';temporary=progress.with_suffix('.tmp')
                    temporary.write_text(json.dumps(dict(stage='exporting_action_clips',completed_segments=len(completed),
                        total_segments=sum(len(s['actions']) for s in manifest['episodes']),closed_camera_files=4*len(completed),
                        heartbeat_unix=time.time(),training_cache_ready=False),indent=2));temporary.replace(progress)
        result = dict(schema='airport_isaac_episode_action_preview/1' if preview else 'airport_isaac_action_clips/1', ready=True,
            full_sources=manifest['full_sources'], action_segments=len(completed),
            native_camera_files=4 * len(completed), source_manifest_sha256=sha(manifest_path),
            segments=completed)
        if preview:result.update(training_cache_ready=False,scope='qualified_complete_source_preview_not_three_split_training_batch')
        (output / 'manifest.json').write_text(json.dumps(result, indent=2))
        (output / 'VIDEO_PATHS.txt').write_text('\n'.join(
            video['path'] for row in completed for video in row['videos'].values()) + '\n')
        return result
    except Exception as error:
        (output / 'export_failure.json').write_text(json.dumps(dict(
            ready=False, error=repr(error), completed_segments=len(completed)), indent=2))
        raise


def materialize_cache(manifest_path, registry, output, *, decode=None):
    """FP32 numeric / uint8 RGB caches compatible with the established BC loader.

    H20 chunks are clipped to each action end, never across loading or prompts.
    """
    if decode is None:
        from .real_sim_data import decode_selected
        decode = decode_selected
    manifest = load_frozen(manifest_path, registry)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    cache_files = {}
    for split in ('train', 'val', 'test'):
        sources = [row for row in manifest['episodes'] if row['split'] == split]
        total = sum(span['end'] - span['start'] for row in sources for span in row['actions'])
        if total < 1:
            raise ValueError('isaac_empty_split_cache')
        target = output / split; target.mkdir()
        data = {key: np.lib.format.open_memmap(target / (key + '.npy'), mode='w+',
            dtype=np.float32, shape=(total, 19)) for key in ('state', 'action')}
        images = {camera: np.lib.format.open_memmap(target / (camera + '.npy'), mode='w+',
            dtype=np.uint8, shape=(total, 224, 224, 3)) for camera in ('head_left', 'left_wrist', 'right_wrist')}
        ends = np.empty(total, np.int64); task = np.empty(total, np.int32)
        episodes = []; offset = 0
        for source in sources:
            with np.load(source['trace'], allow_pickle=False) as arrays:
                selected_indices = np.concatenate([
                    np.arange(span['start'], span['end']) for span in source['actions']])
                selected_count = len(selected_indices)
                for camera in images:
                    frames = decode(source['videos'][camera]['path'], selected_indices,
                        images[camera][offset:offset + selected_count])
                    if frames != source['frames']:
                        raise ValueError('isaac_cache_source_video_frame_count_changed')
                for span in source['actions']:
                    task_index = PROMPTS.index(span['prompt'])
                    start, end = span['start'], span['end']; count = end - start
                    data['state'][offset:offset + count] = arrays['state'][start:end]
                    data['action'][offset:offset + count] = arrays['action'][start:end]
                    ends[offset:offset + count] = offset + count
                    task[offset:offset + count] = task_index
                    episodes.append(dict(episode_id=source['episode_id'], parent_scene_id=source['parent_scene_id'],
                        split=split, engine='isaacsim', domain='simulation', task_index=task_index,
                        profile=source['profile'], cycle_id=span.get('cycle_id'), tray_id=span.get('tray_id'),
                        offset=offset, frames=count, start=start, end=end, trace_sha256=source['trace_sha256']))
                    offset += count
        for array in [*data.values(), *images.values()]:
            array.flush()
        np.save(target / 'end.npy', ends); np.save(target / 'task.npy', task)
        metadata = dict(schema='airport_isaac_training_cache/1', ready=True, engine='isaacsim',
            physics_backend='physx', split=split, frames=total, episodes=episodes,
            profile=manifest['profile'],
            full_source_count=len(sources), action_segment_count=len(episodes), fps=20,
            source_manifest=str(Path(manifest_path).resolve()), source_manifest_sha256=sha(manifest_path),
            numeric_dtype='float32', rgb_dtype='uint8', action_width=19,
            arm_units='rad', gripper_units='m', source_domains=['simulation'],
            base_target='planar_position_offset_from_initial_origin',
            sample_alignment='native_frame_index_shared_by_state_action_video',
            chunk_boundary='each_action_end_excludes_environment_loading')
        (target / 'manifest.json').write_text(json.dumps(metadata, indent=2))
        cache_files[split] = {p.name: sha(p) for p in target.glob('*.npy')}
        cache_files[split]['manifest.json'] = sha(target / 'manifest.json')
    (output / 'integrity.json').write_text(json.dumps(cache_files, indent=2))
    return cache_files
