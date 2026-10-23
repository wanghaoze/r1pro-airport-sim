"""Outbound bridge for Scene Studio with registered, serialized GPU jobs.

Runtime credentials live only in the server's mode-0600 secret configuration.
Each operation has an immutable receipt. Existing runs are observed, never edited.
"""
from pathlib import Path
import argparse
import copy
import datetime
import hashlib
import json
import math
import os
import re
import signal
import sys
import time
import urllib.request

WORKER_ID = 'xinmatrix-scene-agent-v1'
ROOT = Path(os.environ.get('AIRPORT_PROJECT','/home/michelle/haoze/r1pro-airport-sim'))
PRODUCTION = ROOT / 'runs/isaacsim_parallel_pickplace300_20261017_v1'
TRAINING = ROOT / 'runs/real_isaac300_timeweighted_pi05_20261017_v1'
BASE_CONFIG = PRODUCTION / 'batch_001/config.json'
ALLOWED_DATASETS = {'isaac300_20261017', 'real_pickplace_v2'}


def read(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {} if default is None else default


def write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf8")
    temporary.replace(path)


def digest(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


def identity(pid):
    """Capture PID reuse-resistant identity; no environment/credentials are read."""
    try:
        proc = Path('/proc') / str(int(pid))
        stat = (proc / 'stat').read_text().rsplit(')', 1)[1].split()
        return {'pid': int(pid), 'start_ticks': stat[19],
                'command': (proc / 'cmdline').read_bytes().replace(b'\0', b' ').decode(),
                'cwd': str((proc / 'cwd').resolve()), 'process_state': stat[0]}
    except (OSError, ValueError, TypeError):
        return None


def snapshot(seed):
    from studio_backend import telemetry, checkpoints, JOBS
    import studio_backend
    from auto_evaluation import summaries
    data = copy.deepcopy(seed)
    p = read(PRODUCTION / 'production_status.json') or read(PRODUCTION / 'pipeline_status.json')
    t = read(TRAINING / 'pipeline_status.json')
    data.update(capturedAt=int(time.time()*1000), workerId=WORKER_ID)
    data['production'] = {k: p.get(k) for k in ('stage', 'qualified_pairs', 'target_source_pairs', 'heartbeat_unix', 'pid')}
    data['training'] = {k: t.get(k) for k in ('stage', 'training_started', 'heartbeat_unix', 'pid', 'last_error')}
    data['training']['actual_completed_updates'] = t.get('actual_completed_updates', 0)
    data['production']['process'] = identity(p.get('pid'))
    data['training']['process'] = identity(t.get('pid'))
    active = [p.parent/'training' for p in JOBS.glob('*/status.json') if read(p).get('status')=='running' and (p.parent/'training/training_status.json').exists()]
    observed = active[0] if active else TRAINING
    data['training'] = telemetry(observed, JOBS/('telemetry_'+hashlib.sha256(str(observed).encode()).hexdigest()[:12]+'.json'))
    data['checkpoints'] = [{**{k:c[k] for k in ('id','label','updates','source','closed')},'family':c.get('family','pi05'),'policyHorizon':c.get('modelConfig',{}).get('horizon',20)} for c in checkpoints()]
    data['automaticEvaluations'] = summaries(studio_backend)
    from mse_artifacts import summaries as figure_summaries
    data['mseFigures'] = figure_summaries(local=os.environ.get('STUDIO_OFFLINE')=='1')
    from batch_catalog import catalog
    data['batchCatalog'] = catalog(ROOT)
    from model_registry import summary
    data['modelAdapters'] = summary()
    from execution_settings import gpu_inventory
    data['gpuInventory']=gpu_inventory()
    from r1pro_teleop.real2sim.robot_action_filter import load_limits
    limits=load_limits()
    data['filterLimits']={k:limits[v] for k,v in {'maxStepRad':'max_step_rad','maxVelocityRadS':'max_velocity_rad_s','maxTrackingErrorRad':'max_tracking_error_rad','maxObservationAgeSeconds':'max_observation_age_seconds'}.items()}
    data['simulationEngine']={'name':'NVIDIA Isaac Sim','physics':'PhysX','preview':'Three.js','physicsProfile':'realtime: CPU PhysX; baseline: GPU PhysX','substeps':25,'physicsDt':.002}
    if os.environ.get('STUDIO_OFFLINE')=='1':
        def compact(v):
            if isinstance(v,dict):return {k:compact(x) for k,x in v.items() if k not in ('byEpisode','contentBindings')}
            if isinstance(v,list):return [compact(x) for x in v]
            return v
        data['recentJobs']=[dict(id=p.parent.name,kind=read(p).get('kind'),payload=read(p).get('payload',{}),status=read(p.parent/'status.json').get('status'),result=compact(read(p.parent/'status.json')),created_at=int(p.stat().st_mtime*1000)) for p in sorted(JOBS.glob('*/request.json'),key=lambda p:p.stat().st_mtime)[-20:]]
    for dataset in data.get('datasets', []):
        if dataset['id'] == 'isaac300_20261017':
            frozen=read(TRAINING/'frozen_simulation.json')
            n = int(frozen.get('complete_source_pairs',0)) if frozen else min(300,int(p.get('qualified_pairs',0)))
            dataset.update(pairs=n, segments=n*2, split={'train': n, 'val': 0, 'test': 0}, status=p.get('stage', 'unknown'))
    # The frozen seed is a source reference, not a current physical robot pose.
    return data


def validate_rooms(rooms):
    if not isinstance(rooms, list) or len(rooms) != 32 or {r.get('id') for r in rooms} != set(range(32)):
        raise ValueError('invalid_room_selection')
    for room in rooms:
        for name, size in [('robot_base_pose', 3), ('tray_pose', 4)]:
            value = room.get(name)
            if not isinstance(value, list) or len(value) != size or not all(type(v) in (int, float) and math.isfinite(v) for v in value):
                raise ValueError('invalid_finite_vector')
        for name in ('robot_color', 'tray_color'):
            if not isinstance(room.get(name), str) or not re.fullmatch(r'#[0-9A-Fa-f]{6}', room[name]):
                raise ValueError('invalid_color')


def scene_sync(payload, directory):
    rooms = payload.get('rooms')
    validate_rooms(rooms)
    if payload.get('profile') != 'isaac32_fixed_base_pickplace':
        raise ValueError('invalid_scene_profile')
    baseline = read(BASE_CONFIG)
    if len(baseline.get('cases', [])) != 32:
        raise ValueError('baseline_config_missing')
    result = copy.deepcopy(baseline)
    for room in rooms:
        case = result['cases'][room['id']]
        # Inherit parent split/seed/task gates exclusively from the registered source.
        case['initial_base_world'] = list(room['robot_base_pose'])
        case['fixed_base_world'] = list(room['robot_base_pose'])
        x, y, z, yaw = room['tray_pose']
        case['tray_pose'] = [x, y, z, math.cos(yaw/2), 0, 0, math.sin(yaw/2)]
        for key in list(case):
            if 'preflight' in key or 'precheck' in key or 'qualified' in key:
                del case[key]
    result['output'] = str(directory / 'native')
    result['web_scene_draft'] = {'revision': payload['revision'], 'requires_native_preflight': True,
                                 'physical_execution_authorized_by_this_job': False}
    write(directory / 'native_config.draft.json', result)
    write(directory / 'visual_patch.json', {'scope': 'pure_visual_mesh_whitelist_only', 'native_adapter_verified': False,
          'rooms': [{'id': r['id'], 'robot_color': r['robot_color'], 'tray_color': r['tray_color']} for r in rooms]})
    write(directory / 'scene.json', payload)
    return {'status': 'draft_synced', 'message': '32房间草稿已同步。原生颜色适配与物理预检待验证；没有改变当前仿真或训练输入。',
            'artifactDirectory': str(directory), 'configSha256': digest(result),
            'physicsValidated': False, 'simulationStarted': False, 'trainingStarted': False}


def training_attach(payload, directory):
    if set(payload.get('datasets', [])) != ALLOWED_DATASETS or payload.get('recipe') != 'real50_isaac300_duration_bc':
        raise ValueError('unapproved_training_recipe')
    status = read(TRAINING / 'pipeline_status.json')
    config = read(TRAINING / 'config.json')
    proc = identity(status.get('pid'))
    heartbeat = float(status.get('heartbeat_unix', 0))
    healthy = bool(proc and proc['process_state'] != 'Z' and str(TRAINING) in proc['command'] and time.time()-heartbeat < 120)
    evidence = {'observedAt': time.time(), 'pipelineStatus': status, 'process': proc, 'configSha256': digest(config),
                'statusFile': str(TRAINING / 'pipeline_status.json'), 'runDirectory': str(TRAINING),
                'newProcessStarted': False, 'inputDatasetModified': False}
    write(directory / 'training_observation.json', evidence)
    if not healthy:
        return {'status': 'blocked', 'message': '现有训练监督器身份或心跳未通过核验。未重复启动任务；请检查服务器运行证据。',
                'artifactDirectory': str(directory), **evidence}
    return {'status': 'attached_existing', 'message': f"已关联现有监督器，当前阶段 {status.get('stage')}。数据资格满足后由既有流程执行训练。",
            'artifactDirectory': str(directory), **evidence}


def execute_job(job, run):
    identifier = job.get('id', '')
    if not re.fullmatch(r'[A-Za-z0-9_-]{8,80}', identifier):
        raise ValueError('invalid_request_id')
    directory = Path(run) / 'jobs' / identifier
    receipt_path = directory / 'receipt.json'
    prior = read(receipt_path)
    fingerprint = digest(job)
    if prior:
        if prior.get('requestSha256') != fingerprint:
            raise ValueError('request_id_conflict')
        return prior['ack']
    directory.mkdir(parents=True, exist_ok=True)
    write(directory / 'request.json', job)
    try:
        if job['kind'] == 'scene.sync':
            result = scene_sync(job['payload'], directory)
        elif job['kind'] == 'training.attach':
            result = training_attach(job['payload'], directory)
        elif job['kind'] in ('training.create','evaluation.mse','evaluation.vla','evaluation.live','evaluation.auto'):
            from studio_backend import enqueue
            result = enqueue(job)
        else:
            raise ValueError('unsupported_operation')
        status = result.pop('status')
    except Exception as error:
        status = 'failed'
        result = {'message': str(error), 'artifactDirectory': str(directory), 'trainingStarted': False}
    ack = {'id': identifier, 'status': status, 'result': result}
    write(receipt_path, {'requestSha256': fingerprint, 'ack': ack, 'finishedAt': time.time()})
    return ack


def exchange(config, payload):
    request = urllib.request.Request(config['siteUrl'].rstrip('/')+'/api/worker',
        data=json.dumps({'workerId': WORKER_ID, **payload}).encode(),
        headers={'Content-Type': 'application/json', 'OAI-Sites-Authorization': 'Bearer '+config['siteToken'],
                 'X-Worker-Token': config['workerToken']}, method='POST')
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def main():
    import fcntl  # Linux process lock; command validation tests also run on Windows.
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True)
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args()
    config = read(args.config)
    if (Path(args.config).stat().st_mode & 0o077) != 0:
        raise ValueError('worker_config_permissions')
    run = Path(config['runDirectory'])
    run.mkdir(parents=True, exist_ok=True)
    lock = (run / 'worker.lock').open('a+')
    fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    seed = read(Path(__file__).with_name('initial-snapshot.json'))
    started = time.time()
    write(run / 'identity.json', {**identity(os.getpid()), 'startedAt': started, 'workerId': WORKER_ID})
    stopping = False
    def stop(*_):
        nonlocal stopping
        stopping = True
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    failures, exit_code, last_error = 0, 0, None
    pending_ack = None
    from live_publication import start_publisher
    publisher_stop=start_publisher(config,run)
    try:
        while not stopping:
            try:
                from studio_backend import queue_tick, updates
                # Process authenticated stop requests before scheduling new work.
                from mse_artifacts import tick as figure_tick
                try:
                    figure_tick(config)
                except Exception as exc:
                    write(run/'figure_error.json', {'error': repr(exc), 'observedAt': time.time()})
                response = exchange(config, {'snapshot': snapshot(seed), 'updates':updates(), 'claim': True, **({'ack': pending_ack} if pending_ack else {})})
                pending_ack = None
                from studio_backend import cancel
                for target in response.get('cancellations',[]):cancel(target)
                queue_tick()
                job = response.get('job')
                if job:
                    pending_ack = execute_job(job, run)
                failures = 0
                write(run / 'heartbeat.json', {'pid': os.getpid(), 'startedAt': started, 'heartbeat_unix': time.time(),
                     'stage': 'job_receipt_pending' if pending_ack else 'polling', 'lastJobId': job['id'] if job else None,
                     'last_error': None, 'artifactDirectory': str(run)})
                if args.once:
                    if pending_ack:
                        exchange(config, {'ack': pending_ack})
                    break
                time.sleep(1 if pending_ack else 2)
            except Exception as error:
                failures += 1
                last_error = type(error).__name__ + ': ' + str(error)
                write(run / 'heartbeat.json', {'pid': os.getpid(), 'startedAt': started, 'heartbeat_unix': time.time(),
                     'stage': 'retry_backoff', 'attempt': failures, 'last_error': last_error})
                print(json.dumps({'time': time.time(), 'error': last_error, 'attempt': failures}), flush=True)
                if failures >= 3:
                    exit_code = 1
                    break
                time.sleep(10 * 2**(failures-1))
    finally:
        publisher_stop.set()
        write(run / 'exit.json', {'pid': os.getpid(), 'startedAt': started, 'endedAt': time.time(),
              'actual_exit_code': exit_code, 'last_error': last_error, 'stage': 'stopped' if exit_code == 0 else 'failed'})
    return exit_code


if __name__ == '__main__':
    sys.exit(main())
