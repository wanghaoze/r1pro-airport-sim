"""Independent, bounded source expansion; no training or task-rule changes."""
import argparse
import hashlib
import html
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from r1pro_teleop.single_tray_3table.campaign import atomic_json, verified_case
from r1pro_teleop.single_tray_3table.owned_command import command_state
from r1pro_teleop.single_tray_3table.workflow import process_identity, checked_process
from r1pro_teleop.vla.three_table_single_tray_pipeline import campaign_gate

PROMPTS = ('Pick up the tray', 'Place the tray', 'Flush tray to the left')
FOLDERS = ('pick_up_the_tray', 'place_the_tray', 'flush_tray_to_the_left')
TERMINAL = ('complete', 'blocked_target_not_met', 'blocked_demo_failed',
            'blocked_child_contract', 'blocked_integrity', 'blocked_recovery_limit')


def read(path):
    return json.loads(Path(path).read_text())


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        while chunk := f.read(8 * 1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def lock(path):
    import fcntl
    f = Path(path).open('a+')
    fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    return f


def validate_options(o):
    if o.get('schema') != 'airport_three_action_expansion_options/1':
        raise ValueError('explicit_expansion_options_required')
    for key in ('run_dir', 'release', 'campaign_dir', 'data_run_dir', 'sim_python', 'vla_python'):
        if not isinstance(o.get(key), str) or not o[key]:
            raise ValueError('explicit_path_required:' + key)
    root = Path(o['run_dir']).resolve()
    for key in ('campaign_dir', 'data_run_dir'):
        if not Path(o[key]).resolve().is_relative_to(root):
            raise ValueError('fresh_run_child_required:' + key)
    if type(o.get('target_train_sources')) is not int or o['target_train_sources'] < 67:
        raise ValueError('at_least_67_complete_train_sources_required')
    for key in ('campaign_command', 'data_command'):
        if not isinstance(o.get(key), list) or not o[key] or any(not isinstance(x, str) for x in o[key]):
            raise ValueError('explicit_argv_required:' + key)
    if '--execute' not in o['campaign_command'] or '--data-only' not in o['data_command']:
        raise ValueError('actual_source_execution_and_data_only_required')
    if Path(o['campaign_command'][1]).resolve().parent.parent != Path(o['release']).resolve():
        raise ValueError('campaign_release_binding_required')
    if Path(o['data_command'][1]).resolve().parent.parent != Path(o['release']).resolve():
        raise ValueError('data_release_binding_required')
    if 'preflight_command' in o:
        command = o['preflight_command']
        if (not isinstance(command, list) or len(command) < 2 or
                any(not isinstance(x, str) for x in command) or
                Path(command[1]).resolve().parent.parent != Path(o['release']).resolve()):
            raise ValueError('explicit_preflight_release_binding_required')
        if not Path(o.get('preflight_report', '')).resolve().is_relative_to(root):
            raise ValueError('fresh_preflight_report_required')
    return root


def owned_stage(o, state, stage, argv, pulse):
    """Adopt actual durable receipts; ordinary missing exits request outer recovery."""
    root = Path(o['run_dir']) / 'owned' / stage
    root.mkdir(parents=True, exist_ok=True)
    journal = root / 'stage.json'
    saved = read(journal) if journal.exists() else dict(attempt=0)
    attempt = saved['attempt']
    while True:
        directory = root / f'attempt_{attempt:02d}'
        directory.mkdir(exist_ok=True)
        options = directory / 'command.json'
        output = directory / 'process'
        command = list(argv)
        if attempt or (stage == 'campaign' and (Path(o['campaign_dir']) / 'status.json').exists()) or (stage == 'data' and (Path(o['data_run_dir']) / 'pipeline_status.json').exists()):
            if stage in ('campaign', 'data') and '--recover' not in command:
                command.append('--recover')
        if options.exists():
            command = read(options)['argv']
        else:
            atomic_json(options, dict(schema='airport_three_table_owned_command/1', argv=command,
                                      cwd=o['release'], output=str(output), environment=o.get('environment', {})))
        launch = directory / 'wrapper.json'
        current = command_state(output, options)
        if current['stage'] == 'unstarted_or_startup_gap' and not launch.exists():
            wrapper = [command[0], str(Path(o['release']) / 'scripts/run_three_table_owned_command.py'), '--options', str(options)]
            with (directory / 'wrapper.log').open('xb') as f:
                child = subprocess.Popen(wrapper, cwd=o['release'], stdin=subprocess.DEVNULL,
                                         stdout=f, stderr=subprocess.STDOUT, start_new_session=True,
                                         env=dict(os.environ, OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1'))
            identity = process_identity(child.pid)
            if not identity:
                child.wait()
                raise RuntimeError('wrapper_exited_before_registration')
            # Startup may not have execed yet; retain expected argv separately.
            atomic_json(launch, dict(pid=child.pid, start_ticks=identity['start_ticks'], argv=wrapper, cwd=o['release']))
        atomic_json(journal, dict(attempt=attempt, options=str(options), output=str(output)))
        while True:
            current = command_state(output, options)
            pulse(stage, actual_child_state=current, active_stage_output=str(output))
            if current['stage'] == 'closed':
                if current['returncode'] != 0:
                    raise ValueError('actual_owned_child_nonzero:' + stage + ':' + str(current['returncode']))
                state[stage + '_exit'] = current
                pulse(stage + '_exit_zero', **{stage + '_exit': current})
                return
            if current['stage'] == 'incomplete_exit_not_observed' or (current['stage'] == 'unstarted_or_startup_gap' and launch.exists() and not checked_process(read(launch))):
                attempt += 1
                atomic_json(journal, dict(attempt=attempt, previous_incomplete_output=str(output)))
                raise RuntimeError('ordinary_owned_process_missing_exit:' + stage)
            time.sleep(o.get('poll_seconds', 10))


def demo_gate(o, pulse):
    gate = o.get('demo_gate')
    if not gate:
        return
    while True:
        current = command_state(gate['owned_output'], gate['owned_options'])
        pulse('waiting_for_existing_demo', demo_child_state=current, demo_case=gate['case'])
        if current['stage'] == 'closed':
            case = Path(gate['case'])
            if current['returncode'] != 0:
                raise ValueError('demo_actual_nonzero_exit')
            result = read(case / 'result.json')
            if not verified_case(case / 'result.json', gate['expected_variant']):
                raise ValueError('demo_actual_physical_or_source_failure')
            pulse('demo_verified_complete', demo_result=str(case / 'result.json'), demo_result_sha256=sha(case / 'result.json'), demo_exit=current,
                  demo_frames=result['frames'], training_started=False)
            return
        if current['stage'] == 'incomplete_exit_not_observed':
            raise ValueError('existing_demo_missing_exit_no_automatic_restart')
        time.sleep(o.get('poll_seconds', 10))


def verified_source_gate(o):
    campaign = read(Path(o['campaign_dir']) / 'status.json')
    if campaign.get('stage') != 'physical_candidates_complete' or campaign.get('completed') != campaign.get('selected'):
        raise ValueError('all_registered_physical_candidates_must_close')
    plan = read(Path(o['campaign_dir']) / 'plan.json')
    preflight_rows = {}
    if o.get('preflight_command'):
        preflight_proof(o)
        index = read(Path(o['preflight_report']).parent / 'qualified_initial_pose_index.json')
        preflight_rows = {(r['parent_scene_id'], r['variant_seed']):r for r in index['records']}
    for row in campaign['results']:
        if row.get('task_completed') and not verified_case(row['result'], plan['variants'][row['index']]):
            raise ValueError('actual_closed_source_not_qualified')
        if row.get('task_completed') and preflight_rows:
            variant = plan['variants'][row['index']]
            expected = preflight_rows[(variant['parent_scene_id'], variant['variant_seed'])]
            actual_scene = read(Path(row['result']).parent / 'scene/scene.json')
            if actual_scene.get('initial_tray_pose') != expected['initial_pose']:
                raise ValueError('collected_initial_pose_differs_from_private_preflight')
    proof = campaign_gate(o['campaign_dir'], o.get('certified_source_catalog'))
    counts = {s: len(proof['successful_splits'][s]) for s in ('train', 'val', 'test')}
    return proof, counts


def preflight_proof(o):
    """Private qualification is a proposal gate, never complete-task evidence."""
    if 'preflight_command' not in o:
        return None
    report_path = Path(o['preflight_report'])
    report = read(report_path)
    if (report.get('schema') != 'airport_three_table_preflight_plan_status/1' or
            report.get('stage') != 'preflight_candidates_ready' or
            report.get('task_success_not_certified') is not True):
        raise ValueError('actual_long_rim_preflight_not_closed')
    command = o['campaign_command']
    selection = Path(command[command.index('--selection') + 1]).resolve()
    if selection != Path(report['selection']).resolve() or sha(selection) != report['selection_sha256']:
        raise ValueError('preflight_selection_binding_changed')
    index = read(report_path.parent / 'qualified_initial_pose_index.json')
    if (index.get('fixed_angle_filter_used') is not False or
            index.get('proposal_yaw_changed') is not False):
        raise ValueError('random_initial_pose_proposal_changed')
    config = command[command.index('--config') + 1]
    rows = {(r['parent_scene_id'], r['variant_seed']): r for r in index['records']}
    counts = dict(train=0, val=0, test=0)
    seen = set(); parents = {}
    for variant in read(selection)['variants']:
        key = (variant['parent_scene_id'], variant['variant_seed'])
        if key in seen or key not in rows:
            raise ValueError('unique_actual_preflight_receipt_required')
        seen.add(key); row = rows[key]; receipt = read(row['preflight'])
        if (receipt.get('accepted') is not True or receipt.get('live_state_unchanged') is not True or
                receipt.get('physical_ticks') != 0 or receipt.get('proposal_yaw_changed') is not False or
                receipt.get('config_sha256') != sha(config) or receipt.get('initial_pose') != row['initial_pose'] or
                receipt.get('parent_scene_id') != key[0] or receipt.get('seed') != key[1] or
                receipt.get('split') != row['split']):
            raise ValueError('actual_private_preflight_identity_changed')
        if sha(receipt['scene']) != receipt['scene_sha256'] or sha(receipt['scene_xml']) != receipt['scene_xml_sha256']:
            raise ValueError('preflight_scene_bytes_changed')
        if not receipt.get('accepted_candidates'):
            raise ValueError('actual_private_grasp_candidate_required')
        # The task tray's long local axis is X; opposed long rims use width.
        if any(c['rim_geometry']['axis'] != 'width' for c in receipt['accepted_candidates']):
            raise ValueError('private_short_rim_cannot_qualify_source')
        split = row['split']
        if split not in counts or parents.setdefault(key[0], split) != split:
            raise ValueError('preflight_parent_split_leakage')
        counts[split] += 1
    if counts != report['qualified_candidate_counts'] or counts['train'] < o['target_train_sources'] or not counts['val'] or not counts['test']:
        raise ValueError('actual_preflight_split_target_not_met')
    return dict(verified=True, selection_sha256=sha(selection), report_sha256=sha(report_path),
                qualified_candidate_counts=counts, task_success_not_certified=True)


def archive_actions(data_root, output, target, pulse):
    """Copy byte-identical official media; original episode ids are preserved."""
    import pyarrow.parquet as pq
    output = Path(output); output.mkdir(parents=True, exist_ok=True)
    rows = []; parents = {}; counts = {}; paths = []
    for split in ('train', 'val', 'test'):
        dataset = Path(data_root) / 'datasets' / split
        manifest = read(dataset / 'airport_training_manifest.json')
        if manifest.get('dataset_ready') is not True or manifest.get('split') != split:
            raise ValueError('official_export_not_ready:' + split)
        info = read(dataset / 'meta/info.json')
        episodes = manifest['episodes']; seen = set(); scene_actions = {}
        for episode in episodes:
            i = episode['episode_index']; task = episode['task_index']; prompt = episode['language_prompt']
            if task not in range(3) or prompt != PROMPTS[task] or i in seen:
                raise ValueError('exact_unique_three_prompts_required')
            seen.add(i)
            parent = episode['parent_scene_id']
            if parents.setdefault(parent, split) != split:
                raise ValueError('parent_split_leakage')
            actions = scene_actions.setdefault(episode['scene_id'], set())
            if task in actions:
                raise ValueError('duplicate_scene_action')
            actions.add(task)
            chunk = i // info.get('chunks_size', 1000)
            parquet = dataset / info['data_path'].format(episode_chunk=chunk, episode_index=i)
            table = pq.read_table(parquet)
            if len(table) != episode['frames'] or set(table['task_index'].to_pylist()) != {task} or set(table['episode_index'].to_pylist()) != {i}:
                raise ValueError('original_episode_rows_changed')
            if any(len(row) != 19 or not all(math.isfinite(v) for v in row) for name in ('observation.state', 'action') for row in table[name].to_pylist()):
                raise ValueError('complete_finite_mobile19_required')
            folder = output / FOLDERS[task] / split / f'episode_{i:06d}'
            folder.mkdir(parents=True, exist_ok=True)
            originals = {'trajectory.parquet': parquet}
            for camera in ('head_left', 'left_wrist', 'right_wrist'):
                originals[camera + '.mp4'] = dataset / info['video_path'].format(episode_chunk=chunk, episode_index=i, video_key='observation.images.' + camera)
            files = []
            for name, origin in originals.items():
                destination = folder / name; digest = sha(origin)
                if destination.exists():
                    if sha(destination) != digest:
                        raise ValueError('partial_archive_file_changed:' + str(destination))
                else:
                    temp = destination.with_suffix(destination.suffix + '.copying')
                    shutil.copy2(origin, temp)
                    if sha(temp) != digest:
                        raise ValueError('archive_copy_not_identical')
                    temp.replace(destination)
                files.append(dict(path=str(destination), source=str(origin), sha256=digest))
                if name.endswith('.mp4'): paths.append(str(destination))
            text = folder / 'prompt.txt'
            if text.exists() and text.read_text() != prompt + '\n':
                raise ValueError('archive_prompt_changed')
            text.write_text(prompt + '\n')
            row = dict(episode, split=split, directory=str(folder), files=files, source_dataset=str(dataset),
                       source_manifest_sha256=sha(dataset / 'airport_training_manifest.json'),
                       original_episode_and_task_indices_preserved=True, standalone_lerobot_dataset=False)
            atomic_json(folder / 'metadata.json', row); atomic_json(folder / 'FILES_SHA256.json', files)
            rows.append(row); pulse('archiving_three_action_directories', archived_segments=len(rows))
        if any(actions != {0, 1, 2} for actions in scene_actions.values()):
            raise ValueError('every_source_requires_all_three_whole_actions')
        counts[split] = dict(complete_sources=len(scene_actions), action_segments=len(episodes))
    if counts['train']['complete_sources'] < target:
        raise ValueError('exported_train_source_target_not_met')
    result = dict(schema='airport_three_action_expansion_archive/1', dataset_ready=True, counts=counts,
                  rows=rows, training_started=False, standalone_lerobot_dataset=False, source_datasets_modified=False)
    atomic_json(output / 'manifest.json', result)
    (output / 'VIDEO_PATHS.txt').write_text('\n'.join(paths) + '\n')
    (output / 'DATA_LOCATION.txt').write_text(str(output) + '\n' + '\n'.join(str(output / f) for f in FOLDERS) + '\n')
    links = []
    for task, name in enumerate(FOLDERS):
        subset = [r for r in rows if r['task_index'] == task]
        cards = []
        for row in subset:
            relative = Path(row['directory']).relative_to(output / name).as_posix()
            cards.append('<section><h3>' + html.escape(row['split'] + ' / ' + row['scene_id']) + '</h3>' + ''.join(f'<video controls preload="none" width="240" src="{relative}/{c}.mp4"></video>' for c in ('head_left', 'left_wrist', 'right_wrist')) + '</section>')
        (output / name / 'index.html').write_text('<!doctype html><meta charset="utf-8"><h1>' + PROMPTS[task] + '</h1>' + ''.join(cards))
        links.append(f'<li><a href="{name}/">{PROMPTS[task]}</a></li>')
    (output / 'index.html').write_text('<!doctype html><meta charset="utf-8"><h1>Three action dataset</h1><p>' + html.escape(json.dumps(counts)) + '</p><ul>' + ''.join(links) + '</ul>')
    return result


def supervise(path):
    o = read(path); root = validate_options(o); root.mkdir(parents=True, exist_ok=True)
    handle = lock(root / 'expansion.lock')
    status = root / 'expansion_status.json'; state = read(status) if status.exists() else {}
    digest = sha(path)
    if state.get('options_sha256', digest) != digest:
        raise ValueError('frozen_expansion_options_changed')
    if state.get('stage') in TERMINAL:
        return 0 if state['stage'] == 'complete' else 2
    state.update(schema='airport_three_action_expansion_status/1', options_sha256=digest, identity=process_identity(os.getpid()), training_started=False, dataset_ready=False)
    def pulse(stage, **fields):
        state.update(stage=stage, heartbeat_unix=time.time(), **fields)
        preflight = Path(o['preflight_report']) if o.get('preflight_report') else None
        if preflight is not None and preflight.exists():
            p = read(preflight)
            state['preflight_progress'] = {k:p.get(k) for k in ('stage', 'heartbeat_unix', 'qualified_candidate_counts', 'targets', 'statistics', 'last_error')}
        campaign = Path(o['campaign_dir']) / 'status.json'
        if campaign.exists():
            c = read(campaign)
            state['physical_progress'] = {k:c.get(k) for k in ('stage', 'selected', 'completed', 'successful', 'workers')}
        pipeline = Path(o['data_run_dir']) / 'pipeline_status.json'
        if pipeline.exists():
            p = read(pipeline)
            state['data_progress'] = {k:p.get(k) for k in ('stage', 'heartbeat_unix', 'error', 'case_errors', 'dataset_ready')}
        atomic_json(status, state)
    try:
        pulse('starting_or_recovering')
        demo_gate(o, pulse)
        if o.get('preflight_command'):
            owned_stage(o, state, 'preflight', o['preflight_command'], pulse)
            pulse('actual_initial_poses_qualified', preflight_verification=preflight_proof(o))
        owned_stage(o, state, 'campaign', o['campaign_command'], pulse)
        if o.get('qualification_command'):
            owned_stage(o, state, 'qualification', o['qualification_command'], pulse)
        proof, counts = verified_source_gate(o)
        pulse('qualified_sources_closed', qualified_source_counts=counts)
        if counts['train'] < o['target_train_sources'] or not counts['val'] or not counts['test']:
            pulse('blocked_target_not_met', last_error='complete_qualified_source_target_not_met', target_train_sources=o['target_train_sources'])
            return 2
        owned_stage(o, state, 'data', o['data_command'], pulse)
        pipeline = read(Path(o['data_run_dir']) / 'pipeline_status.json')
        if pipeline.get('stage') != 'data_only_exports_verified_no_training' or pipeline.get('dataset_ready') is not True:
            raise ValueError('actual_data_only_pipeline_not_closed')
        from r1pro_teleop.vla.three_table_recovery import dataset_proof
        records = [json.loads(line) for line in (Path(o['data_run_dir']) / 'source_records.jsonl').read_text().splitlines() if line.strip()]
        for split in ('train', 'val', 'test'):
            folder = Path(o['data_run_dir']) / 'datasets' / split
            dataset_proof(folder, split, records, repo_id=read(folder / 'airport_training_manifest.json')['repo_id'])
        result = archive_actions(o['data_run_dir'], root / 'by_action', o['target_train_sources'], pulse)
        pulse('complete', dataset_ready=True, counts=result['counts'], archive=str(root / 'by_action'), data_pipeline_status_sha256=sha(Path(o['data_run_dir']) / 'pipeline_status.json'))
        return 0
    except ValueError as error:
        name = 'blocked_demo_failed' if state.get('stage', '').startswith('waiting_for_existing_demo') else 'blocked_child_contract'
        pulse(name, last_error=repr(error)); return 2
    except Exception as error:
        pulse('ordinary_process_fault_pending_recovery', last_error=repr(error)); return 3


def guardian(path):
    o = read(path); root = validate_options(o); root.mkdir(parents=True, exist_ok=True)
    handle = lock(root / 'expansion_guardian.lock')
    status = root / 'expansion_guardian_status.json'
    state = read(status) if status.exists() else dict(recoveries=0)
    if state.get('options_sha256', sha(path)) != sha(path):
        raise ValueError('frozen_guardian_options_changed')
    state.update(identity=process_identity(os.getpid()), options_sha256=sha(path))
    argv = [o['vla_python'], str(Path(o['release']) / 'scripts/supervise_three_action_expansion.py'), '--options', str(Path(path).resolve())]
    while True:
        pipeline = read(root / 'expansion_status.json') if (root / 'expansion_status.json').exists() else {}
        if pipeline.get('stage') in TERMINAL:
            state.update(stage='guardian_terminal', pipeline_stage=pipeline['stage'], heartbeat_unix=time.time()); atomic_json(status, state); return
        old = state.get('supervisor_identity')
        if old and checked_process(old):
            state.update(stage='adopting_healthy_supervisor', heartbeat_unix=time.time()); atomic_json(status, state)
            time.sleep(o.get('poll_seconds', 10)); continue
        if state['recoveries'] > 3:
            state.update(stage='blocked_recovery_limit', heartbeat_unix=time.time()); atomic_json(status, state); return
        number = state['recoveries']
        if number:
            delay = (10, 30, 90)[number - 1]
            state.update(stage='recovery_backoff', backoff_seconds=delay, heartbeat_unix=time.time()); atomic_json(status, state)
            time.sleep(delay)
        with (root / f'expansion_supervisor_{number:02d}.log').open('ab') as f:
            child = subprocess.Popen(argv, cwd=o['release'], stdin=subprocess.DEVNULL, stdout=f, stderr=subprocess.STDOUT, start_new_session=True)
        identity = process_identity(child.pid)
        state.update(stage='supervising', supervisor_identity=dict(pid=child.pid, argv=argv, cwd=o['release'], start_ticks=(identity or {}).get('start_ticks')), heartbeat_unix=time.time())
        atomic_json(status, state)
        while child.poll() is None:
            state.update(heartbeat_unix=time.time()); atomic_json(status, state); time.sleep(o.get('poll_seconds', 10))
        state.update(last_actual_supervisor_exit=child.wait(), recoveries=number + 1, heartbeat_unix=time.time()); atomic_json(status, state)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--options', required=True); p.add_argument('--guardian', action='store_true')
    a = p.parse_args()
    return guardian(a.options) if a.guardian else supervise(a.options)


if __name__ == '__main__':
    raise SystemExit(main())
