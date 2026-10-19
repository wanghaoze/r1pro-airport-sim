"""Bounded, resumable generation -> native export -> report, using frozen code.

Run from the release directory used to preflight the collection. This never
changes scenes or success criteria, and exports only clean physics successes.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys


def batches(rows, size):
    if size < 1:
        raise ValueError('batch size must be positive')
    ids = [row['scene_id'] for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError('duplicate scene_id in registry')
    return [ids[i:i+size] for i in range(0, len(ids), size)]


def only_quarantined_exports(root):
    """A missing dependency/disk/encoder error must never be silently skipped."""
    summary = root/'quality/export_summary.json'
    if not summary.is_file():
        return False
    errors = json.loads(summary.read_text()).get('export_failures_this_run', [])
    if not errors:
        return False
    for error in errors:
        quality = root/'attempts'/error['scene_id']/error['attempt']/'export_quality.json'
        if not quality.is_file() or json.loads(quality.read_text()).get('status') != 'rejected':
            return False
    return True


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', type=Path, required=True)
    p.add_argument('--workers', type=int, default=8)
    p.add_argument('--batch-size', type=int, default=8)
    p.add_argument('--limit', type=int, help='Optional smoke subset; omitted processes every registered scene')
    p.add_argument('--gpu', type=int, default=0, help='Physical nvidia-smi GPU index; resolved by PCI/UUID')
    a = p.parse_args(argv)
    if a.workers < 1 or a.batch_size < 1 or (a.limit is not None and a.limit < 1):
        p.error('workers, batch-size and limit must be positive')
    root = a.root.resolve()
    rows = json.loads((root/'scenes/index.json').read_text())
    if a.limit is not None:
        rows = rows[:a.limit]
    groups = batches(rows, a.batch_size)
    max_passes = json.loads((root/'collection.json').read_text())['config']['max_attempts_per_scene']
    import fcntl  # Linux server only; released automatically on process exit.
    lock = open(root/'.batch_pipeline.lock', 'a+')
    try:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit('Another batch pipeline is already running for this root')
    run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    logs = root/'logs'/('pipeline_'+run_id)
    logs.mkdir(parents=True, exist_ok=False)
    from select_r1pro_gpu import select
    gpu = select(a.gpu)
    env = dict(os.environ, MUJOCO_GL='egl', MUJOCO_EGL_DEVICE_ID=str(gpu['egl_index']),
               CUDA_VISIBLE_DEVICES=gpu['uuid'], CUDA_DEVICE_ORDER='PCI_BUS_ID',
               PYOPENGL_PLATFORM='egl', PYTHONUNBUFFERED='1',
               OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1')
    (logs/'gpu_mapping.json').write_text(json.dumps(gpu, indent=2))
    prefix = [sys.executable, '-m', 'r1pro_teleop.airport_fsm']
    with (logs/'events.jsonl').open('a', buffering=1) as events:
        for index, ids in enumerate(groups):
            commands = [
                ['generate', '--root', str(root), '--workers', str(a.workers), '--scene-ids', *ids],
                ['export', '--root', str(root), '--shard-size', '1', '--action-layout', 'mobile19'],
                ['report', '--root', str(root)],
            ]
            for pass_index in range(max_passes):
                retry_quality = False
                for command in commands:
                    log = logs/f'{index:03d}_p{pass_index:02d}_{command[0]}.log'
                    record = {'batch': index, 'batches': len(groups), 'scene_ids': ids,
                              'pass': pass_index, 'command': command[0], 'log': str(log)}
                    print(json.dumps({**record, 'status': 'started'}), flush=True)
                    with log.open('x') as stream:
                        code = subprocess.call(prefix+command, stdout=stream, stderr=subprocess.STDOUT, env=env)
                    events.write(json.dumps({**record, 'exit_code': code})+'\n')
                    if code == 2 and command[0] == 'export' and only_quarantined_exports(root):
                        retry_quality = True
                        print(json.dumps({**record, 'status': 'quality_rejected_attempts_quarantined'}), flush=True)
                    elif code:
                        # Infrastructure errors stop; bounded physical failures
                        # are retained by generate and do not abort other scenes.
                        print(json.dumps({**record, 'status': 'stopped', 'exit_code': code}), flush=True)
                        return code
                if not retry_quality:
                    break
            print(json.dumps({'batch': index, 'status': 'accounted_and_export_checked'}), flush=True)
    print(json.dumps({'status': 'all_selected_scenes_processed', 'selected': len(rows),
                      'all_successful': 'consult quality report; processing is not success', 'logs': str(logs)}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
