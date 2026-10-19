"""Read-only metadata snapshot; never starts training or downloads video."""
from pathlib import Path
from datetime import datetime, timezone, timedelta
import argparse
import json
import os
import subprocess


def read_status(path):
    try:
        body = json.loads(path.read_text(encoding='utf8'))
        return dict(path=str(path), exists=True, data=body)
    except FileNotFoundError:
        return dict(path=str(path), exists=False)
    except (ValueError, OSError) as error:
        return dict(path=str(path), exists=True, read_error=str(error))


def snapshot(data_root, training_root):
    data_root = Path(data_root).resolve()
    training_root = Path(training_root).resolve()
    now = datetime.now(timezone.utc)
    training = read_status(training_root / 'training_status.json')
    native = read_status(data_root/'native_full_v1/status.json')
    forwarded = native.get('data', {}).get('forwarded_to')
    if isinstance(forwarded, str):
        path = Path(forwarded).resolve()
        if path.is_relative_to(data_root):
            previous = native['path']
            native = read_status(path)
            native['forwarded_from'] = previous
        else:
            native['read_error'] = 'Native producer forwarding path is outside the data root'
    pid = training.get('data', {}).get('pid')
    # A last-written status is not evidence that the trainer is still alive.
    active = None
    if os.name == 'posix' and type(pid) is int:
        try:
            command = Path(f'/proc/{pid}/cmdline').read_bytes().replace(b'\0', b' ')
            active = str(training_root).encode() in command
        except OSError:
            active = False
    training['matching_trainer_process_alive'] = active
    summaries = []
    for path in sorted((training_root / 'evaluations').glob('step_*/*summary*.json')):
        summaries.append(read_status(path))
    try:
        gpu = subprocess.check_output([
            'nvidia-smi', '--query-gpu=index,uuid,memory.used,utilization.gpu',
            '--format=csv,noheader'], text=True, timeout=10).strip().splitlines()
    except (OSError, subprocess.SubprocessError):
        gpu = None
    return dict(schema='airport_vla_pipeline_snapshot/1',
        checked_utc=now.isoformat(),
        checked_singapore=now.astimezone(timezone(timedelta(hours=8))).isoformat(),
        data_root=str(data_root), training_root=str(training_root),
        native=native,
        exports=[read_status(path) for path in sorted(data_root.glob('action8_export_*/status.json'))],
        training=training,
        supervisor=[read_status(training_root/name) for name in (
            'supervisor_status.json', 'pipeline_status.json', 'orchestration_status.json')],
        cache=read_status(training_root/'data_cache/status.json'),
        evaluations=summaries, gpu_csv=gpu,
        evaluation_states=[read_status(path) for path in sorted(
            (training_root/'evaluations').glob('step_*/evaluation_status.json'))],
        evaluation_index=read_status(training_root/'evaluations/evaluation_index.json'),
        media_downloaded=False)


def text_report(record):
    native = record['native'].get('data', {})
    lines = ['VLA training / evaluation metadata snapshot',
             'Verified at (Asia/Singapore): '+record['checked_singapore'],
             'Data root: '+record['data_root'],
             'Training and model-test artifact root: '+record['training_root'],
             'Source: simulation/program_generated',
             'Native full tasks: {}/{}; producer_state={} (native media alone is not a ready training dataset)'.format(
                 native.get('completed_scene_count', 'unknown'), native.get('selected', 193),
                 native.get('status', native.get('stage', 'unknown')))]
    for export in record['exports']:
        body = export.get('data', {})
        scope = ('current parallel v2' if 'parallel_v2' in export['path']
                 else 'historical snapshot; serial v1 superseded')
        lines.append('Export {} [{}]: {}/{}; stage={}; dataset_ready={}; status={}'.format(
            body.get('split', 'unknown'), scope, body.get('completed_scenes', 'unknown'),
            body.get('expected_scenes', 'unknown'), body.get('stage', 'unknown'),
            body.get('dataset_ready', False), export['path']))
    training = record['training'].get('data', {})
    lines.extend([
        'Training state: '+str(training.get('status', 'not_started')),
        'Actual completed updates in NEW run: '+str(training.get('actual_completed_updates', 0)),
        'Matching live trainer process: '+str(record['training']['matching_trainer_process_alive']),
        'Checkpoint status: '+record['training']['path'],
        'Milestone evaluation artifacts: '+record['training_root']+'/evaluations',
    ])
    for supervisor in record['supervisor']:
        if supervisor.get('exists'):
            body = supervisor.get('data', {})
            lines.append('Supervisor state: {}; pid={}; evaluation_mode={}; status={}'.format(
                body.get('stage', body.get('status', 'unknown')), body.get('pid', 'unknown'),
                body.get('evaluation_mode', 'unknown'), supervisor['path']))
    cache = record['cache'].get('data', {})
    if record['cache'].get('exists'):
        lines.append('Training cache: {}; written_frames={}/{}; model_training_started={}; status={}'.format(
            cache.get('status', 'unknown'), cache.get('written_frames', 'unknown'),
            cache.get('frames', 'unknown'), cache.get('training_started', False), record['cache']['path']))
    for evaluation in record['evaluation_states']:
        body = evaluation.get('data', {})
        lines.append('Evaluation progress: {}; completed_updates={}; status={}'.format(
            body.get('stage', 'unknown'), body.get('actual_completed_updates', 'unknown'),
            evaluation['path']))
    if not record['evaluations']:
        lines.append('No new-model success rate is available: no actual milestone summary exists yet.')
    for evaluation in record['evaluations']:
        summary = evaluation.get('data', {})
        main = summary.get('main_test', {})
        lines.append('Evaluation {}: completed={}/{}; approximate_rate={}; strict_rate={}; status={}'.format(
            evaluation['path'], main.get('approximate_completed', 'unknown'),
            main.get('denominator', 'unknown'), main.get('approximate_success_rate', 'unknown'),
            main.get('strict_success_rate', 'unknown'), summary.get('status', 'unknown')))
        subset = summary.get('teacher_success_subset', {})
        lines.append('Teacher-success subset: completed={}/{}; approximate_rate={}; main_attempted={}; main_not_run={}'.format(
            subset.get('approximate_completed', 'unknown'), subset.get('denominator', 'unknown'),
            subset.get('approximate_success_rate', 'unknown'), main.get('attempted', 'unknown'),
            main.get('not_run', 'unknown')))
    lines.append('Video and trajectory files stay on the server; this snapshot contains metadata only.')
    return '\n'.join(lines)+'\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-root', required=True)
    parser.add_argument('--training-root', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--text-output', required=True)
    args = parser.parse_args()
    record = snapshot(args.data_root, args.training_root)
    for path, content in ((Path(args.output), json.dumps(record, indent=2)),
                          (Path(args.text_output), text_report(record))):
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name+'.tmp')
        temporary.write_text(content, encoding='utf8')
        temporary.replace(path)
    print(text_report(record), end='')


if __name__ == '__main__':
    main()
