"""Registered, immutable job queue and telemetry for the Scene Studio bridge.

No caller-supplied filesystem paths, shell commands or model identifiers reach a
subprocess. GPU work is serialized and waits for the existing training process.
"""
from pathlib import Path
import hashlib
import json
import math
import os
import re
import statistics
import subprocess
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

ROOT = Path(os.environ.get('AIRPORT_PROJECT', '/home/michelle/haoze/r1pro-airport-sim'))
CURRENT = ROOT/'runs/real_isaac300_timeweighted_pi05_20261017_v1'
JOBS = ROOT/'runs/web_studio_jobs_20261017_v1'
REGISTRY = Path(__file__).with_name('dataset_registry.json')
EXECUTION_POLICY = Path(__file__).with_name('maintenance_policy.json')


def read(path, default=None):
    try:return json.loads(Path(path).read_text(encoding='utf8'))
    except (OSError, ValueError):return {} if default is None else default


def write(path, data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(data,ensure_ascii=False,allow_nan=False),encoding='utf8');tmp.replace(path)


def training_block_reason():
    """Server-owned repair gate; missing/malformed policy cannot enable training."""
    policy=read(EXECUTION_POLICY)
    if (not isinstance(policy,dict) or policy.get('schema')!='studio_maintenance_policy/1'
            or policy.get('trainingAllowed') is not True):
        return 'training_disabled_during_repair: use existing checkpoints for diagnostics'
    return None


def assert_training_allowed(kind):
    if kind=='training.create':
        reason=training_block_reason()
        if reason:raise ValueError(reason)


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(8*1024*1024),b''):h.update(block)
    return h.hexdigest()


def identity(pid):
    try:
        proc=Path('/proc')/str(int(pid));stat=(proc/'stat').read_text().rsplit(')',1)[1].split()
        return dict(pid=int(pid),start_ticks=stat[19],state=stat[0],command=(proc/'cmdline').read_bytes().replace(b'\0',b' ').decode(),cwd=str((proc/'cwd').resolve()))
    except (OSError,ValueError,TypeError):return None


def alive(record):
    current=identity(record.get('pid')) if record else None
    return bool(current and current['state']!='Z' and current['start_ticks']==record.get('start_ticks') and current['command']==record.get('command'))


def checkpoints():
    rows=[]
    runs=[(CURRENT,'新 300 对 + 真机 50/50')]
    if JOBS.exists():runs += [(p.parent/'training','自选配比 '+p.parent.name[:8]) for p in JOBS.glob('*/request.json') if read(p).get('kind')=='training.create']
    for root,label in runs:
        for receipt in sorted(root.glob('checkpoint_*.json')):
            d=read(receipt);cp=Path(d.get('checkpoint','/nonexistent'));updates=d.get('checkpoint_updates')
            if not d.get('checkpoint_saved') or not isinstance(updates,int) or not d.get('spec'):continue
            expected=Path(d['spec']['run_dir'])/'checkpoints'/d['spec']['name']/'training'/str(updates-1)
            if cp.resolve()!=expected.resolve() or not cp.is_relative_to(root) or not (cp/'_CHECKPOINT_METADATA').exists() or not (cp/'params/manifest.ocdbt').exists():continue
            rows.append(dict(id='cp_'+hashlib.sha256(str(cp).encode()).hexdigest()[:24],label=f'{label} · {updates} 步',updates=updates,closed=True,
                source=d.get('source',d.get('engine','real_world_plus_isaac')),checkpoint=str(cp),receipt=str(receipt),receiptSha256=sha(receipt),spec=d['spec'],run=str(root)))
    for name,label in [('real_only_pi05_20261012_v1','真机 100%'),('real_sim_pickplace_20261009_v3','真机 90% / 仿真 10%')]:
        root=ROOT/'runs'/name;receipt=root/'pi05/training_status.json';d=read(receipt);cp=Path(d.get('checkpoint','/nonexistent'))
        if d.get('stage')!='trained' or not d.get('spec') or not d.get('updates'):continue
        spec=d['spec'];expected=Path(spec['run_dir'])/'checkpoints'/spec['name']/'training'/str(d['updates']-1)
        if cp.resolve()!=expected.resolve() or not (cp/'params/manifest.ocdbt').exists() or not (cp/'_CHECKPOINT_METADATA').exists():continue
        rows.append(dict(id='cp_'+hashlib.sha256(str(cp).encode()).hexdigest()[:24],label=f'{label} · {d["updates"]} 步',updates=d['updates'],closed=True,
            source=d.get('source','unknown'),checkpoint=str(cp),receipt=str(receipt),receiptSha256=sha(receipt),spec=spec,run=str(root)))
    from model_registry import entries
    return rows[-80:]+entries()


def telemetry(run, history):
    run=Path(run);pipe=read(run/'pipeline_status.json');t=read(run/'training_status.json');now=time.time()
    step=max(int(t.get('actual_completed_updates',0)),int(pipe.get('actual_completed_updates',0)))
    target=int(t.get('target_updates',read(run/'inputs.json').get('training_steps',10000)))
    pid=identity(t.get('pid'));live=bool(pid and pid['state']!='Z' and str(run) in pid['command'] and now-t.get('heartbeat_unix',0)<120)
    samples=read(history,[])
    loss=t.get('metrics',{}).get('loss')
    if live and t.get('stage')=='training' and math.isfinite(loss or 0) and (not samples or samples[-1]['step']!=step):
        samples.append(dict(step=step,loss=loss,unix=t.get('heartbeat_unix',now),pid=pid['pid']))
        samples=samples[-160:];write(history,samples)
    speeds=[(b['unix']-a['unix'])/(b['step']-a['step']) for a,b in zip(samples,samples[1:]) if b['pid']==a['pid'] and b['step']>a['step'] and 0<b['unix']-a['unix']<120]
    milestone=t.get('milestone_updates')
    if not milestone:
        match=re.fullmatch(r'train_(\d+)',pipe.get('stage',''));milestone=int(match[1]) if match else None
    rate=t.get('seconds_per_step')
    if not rate and milestone and milestone>step and t.get('eta_seconds'):rate=t['eta_seconds']/(milestone-step)
    if len(speeds)>=3:rate=statistics.median(speeds[-30:])
    eta=None
    if live and t.get('stage')=='training' and rate and rate>0:
        ordered=sorted(speeds[-30:]);lo=ordered[len(ordered)//5] if len(ordered)>=5 else rate*.8;hi=ordered[min(len(ordered)-1,len(ordered)*4//5)] if len(ordered)>=5 else rate*1.25
        eta=dict(lowSeconds=max(0,target-step)*lo,highSeconds=max(0,target-step)*hi,sampledAt=t.get('heartbeat_unix'),scope='remaining_gradient_updates_only',excludes=['initialization','checkpoint_save','MSE','VLA'])
    saved=[read(p).get('checkpoint_updates') for p in sorted(run.glob('checkpoint_*.json')) if read(p).get('checkpoint_saved')]
    return dict(stage=t.get('stage',pipe.get('stage','unknown')),pipelineStage=pipe.get('stage'),actual_completed_updates=step,target_updates=target,
        training_started=bool(step),live=live,sampledAt=t.get('heartbeat_unix',pipe.get('heartbeat_unix')),eta=eta,secondsPerStep=rate,
        milestone=milestone,milestoneEtaSeconds=max(0,milestone-step)*rate if rate and milestone else None,
        metrics=t.get('metrics',{}),samples=samples,checkpointUpdates=saved,devices=t.get('actual_devices',[]),runDirectory=str(run),process=pid)


def validate_request(job):
    if not re.fullmatch(r'[A-Za-z0-9_-]{8,80}',job.get('id','')):raise ValueError('invalid_job_id')
    p=job['payload'];kind=job['kind']
    if kind in ('evaluation.vla','evaluation.live'):
        from r1pro_teleop.real2sim.robot_action_filter import configured_limits
        configured_limits(p.get('filterSettings'))
    if kind=='evaluation.auto':
        from auto_evaluation import payload,training_root
        if p!=payload(p.get('trainingRun')):raise ValueError('invalid_automatic_evaluation_contract')
        source=p['trainingRun']
        if source!='current' and (not isinstance(source,str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,80}',source)):raise ValueError('invalid_automatic_training_id')
        training_root(sys.modules[__name__],job)
    elif kind=='training.create':
        if 'autoEvaluate' in p and type(p['autoEvaluate']) is not bool:raise ValueError('invalid_automatic_evaluation_option')
        ids=p.get('datasets',[]);registry=read(REGISTRY)
        if not ids or len(ids)!=len(set(ids)) or any(i not in registry for i in ids):raise ValueError('unregistered_dataset')
        ratio=p.get('realPercent');steps=p.get('steps')
        if type(ratio)!=int or not 0<=ratio<=100 or type(steps)!=int or not 1<=steps<=100000:raise ValueError('invalid_training_config')
        if ratio>0 and 'real_pickplace_v2' not in ids:raise ValueError('real_data_required')
        if ratio<100 and not any(i!='real_pickplace_v2' for i in ids):raise ValueError('simulation_data_required')
        if p.get('rewardEnabled') is not False:raise ValueError('only_BC_authorized')
    elif kind in ('evaluation.mse','evaluation.vla','evaluation.live'):
        ids=p.get('checkpointIds',[]);registered={c['id']:c for c in checkpoints()}
        if not 1<=len(ids)<=(4 if kind.endswith('mse') else 1) or len(ids)!=len(set(ids)) or any(i not in registered for i in ids):raise ValueError('checkpoint_not_closed_or_registered')
        if kind.endswith('mse') and any(registered[i].get('family') for i in ids):raise ValueError('External adapters require a separate MSE protocol')
        if kind.endswith('mse') and (p.get('split') not in ('val','test') or p.get('protocol')!='real_all_frames_h20_noise42000_v1'):raise ValueError('invalid_MSE_protocol')
        if kind in ('evaluation.vla','evaluation.live'):
            if p.get('transport','file') not in ('file','ros2'):raise ValueError('invalid_policy_transport')
            if any(registered[i].get('family') for i in ids) and p.get('transport')!='ros2':raise ValueError('External models require ROS2 transport')
            rooms=p.get('roomIds',[]);budget=p.get('framesPerAction')
            if p.get('sceneSetId')!='isaac32_20261017' or not rooms or len(rooms)!=len(set(rooms)) or any(type(n)!=int or not 0<=n<32 for n in rooms):raise ValueError('invalid_registered_scene_selection')
            if type(budget)!=int or not 20<=budget<=(200000 if kind=='evaluation.live' else 1200) or p.get('teacherFallback') is not False or p.get('baseActuatorMask')!='fixed_episode_base':raise ValueError('invalid_native_policy_contract')
        if kind=='evaluation.live':
            if p.get('runtimeProfile','baseline') not in ('baseline','realtime'):raise ValueError('invalid_runtime_profile')
            if p.get('actionSafetyMode','strict') not in ('strict','clip_diagnostic','robot_limits'):raise ValueError('invalid_action_safety_mode')
            if len(p['roomIds'])!=1 or p.get('transport')!='ros2':raise ValueError('live_single_room_ros2_required')
            for key,low,high in [('maxSimulationSeconds',1,10000),('maxWallSeconds',0,604800),('inferenceTimeoutSeconds',1,300)]:
                if type(p.get(key))!=int or not low<=p[key]<=high:raise ValueError('invalid_live_time_budget:'+key)
            if p['framesPerAction']!=p['maxSimulationSeconds']*20:raise ValueError('inconsistent_live_frame_budget')
        from execution_settings import selection
        selection(p,kind)
        return [registered[i] for i in ids]
    else:raise ValueError('unsupported_job_kind')
    if kind=='training.create':
        from execution_settings import selection
        selection(p,kind)
    return []


def enqueue(job):
    assert_training_allowed(job.get('kind'))
    selected=validate_request(job);run=JOBS/job['id']
    for entry in selected:
        if entry.get('family'):continue
        cp=Path(entry['checkpoint']);norm=cp/'assets'/entry['spec']['dataset_repo_id']/'norm_stats.json'
        if not norm.exists() or not (cp/'train_state').is_dir():raise ValueError('checkpoint_assets_or_optimizer_not_closed')
        bound=[cp/'_CHECKPOINT_METADATA',cp/'params/manifest.ocdbt',norm]
        entry['contentBindings']={str(p):sha(p) for p in bound}
    if run.exists():
        if read(run/'request.json')!=job:raise ValueError('job_request_conflict')
    else:
        run.mkdir(parents=True);write(run/'request.json',job);write(run/'checkpoints.json',selected)
        registry=read(REGISTRY)
        write(run/'dataset_selection.json',{i:registry[i] for i in job['payload'].get('datasets',[])})
        write(run/'status.json',dict(status='waiting_training' if job['kind']=='evaluation.auto' else 'waiting_gpu',message='Configuration frozen. Waiting for training completion.' if job['kind']=='evaluation.auto' else 'Configuration frozen. Waiting for GPU resources.',artifactDirectory=str(run),createdAt=time.time(),heartbeat_unix=time.time()))
    if (JOBS/'.cancellations'/job['id']).exists():
        cancel(job['id'])
        return dict(status='cancelled',message='Stopped by user before execution',artifactDirectory=str(run))
    if job['kind']=='evaluation.auto':return dict(status='waiting_training',message='Automatic evaluation enabled for the latest final checkpoint.',artifactDirectory=str(run))
    return dict(status='waiting_gpu',message='独立任务已登记，等待 GPU；现有训练继续。',artifactDirectory=str(run))


def cancel(job_id):
    if not isinstance(job_id,str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,80}',job_id):raise ValueError('invalid_cancel_job_id')
    run=JOBS/job_id
    if (run/'request.json').exists() and read(run/'request.json').get('kind') not in ('evaluation.live','evaluation.vla'):raise ValueError('only_policy_jobs_can_be_stopped')
    state=read(run/'status.json')
    if state.get('status') in ('completed','failed','cancelled'):return
    markers=JOBS/'.cancellations';markers.mkdir(parents=True,exist_ok=True)
    (markers/job_id).touch(exist_ok=True)
    if not (run/'request.json').exists():return
    (run/'stop_requested').touch(exist_ok=True)
    if not alive(read(run/'runner_identity.json')):
        write(run/'status.json',dict(state,status='cancelled',message='Stopped by user before execution',heartbeat_unix=time.time()))


def gpu_busy():
    pipe=read(CURRENT/'pipeline_status.json');pid=identity(pipe.get('pid'))
    if pid and pid['state']!='Z' and str(CURRENT) in pid['command']:return '既有训练监督器仍在运行'
    result=subprocess.run(['nvidia-smi','--query-compute-apps=used_gpu_memory','--format=csv,noheader,nounits'],capture_output=True,text=True,timeout=8)
    if result.returncode:return 'GPU 资源状态暂不可核验'
    for line in result.stdout.splitlines():
        try:
            if float(line.strip())>4096:return 'GPU 上仍有模型或仿真进程'
        except ValueError:return 'GPU 显存状态暂不可核验'
    return None


def queue_tick():
    JOBS.mkdir(parents=True,exist_ok=True)
    import fcntl
    with (JOBS/'scheduler.lock').open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return
        from auto_evaluation import reconcile
        reconcile(sys.modules[__name__])
        queued=[];active=False
        for request in sorted(JOBS.glob('*/request.json'),key=lambda p:p.stat().st_mtime):
            if read(request).get('kind')=='evaluation.auto':continue
            run=request.parent;state=read(run/'status.json');proc=read(run/'runner_identity.json')
            if state.get('status') in ('preparing','running'):
                if alive(proc):active=True
                elif time.time()-state.get('heartbeat_unix',0)>120:
                    write(run/'status.json',dict(state,status='failed',message='作业进程身份消失且未记录正常退出；保留失败现场。',heartbeat_unix=time.time()))
            elif state.get('status')=='waiting_gpu':queued.append(run)
        if active or not queued:return
        from execution_settings import availability
        eligible=[]
        for candidate in queued:
            job=read(candidate/'request.json')
            if job.get('kind')=='training.create' and (reason:=training_block_reason()):
                write(candidate/'status.json',dict(read(candidate/'status.json'),status='blocked',message=reason,heartbeat_unix=time.time()))
                continue
            if (JOBS/'.cancellations'/candidate.name).exists():cancel(candidate.name);continue
            reason=availability(job['payload'],job['kind'])
            if reason:write(candidate/'status.json',dict(read(candidate/'status.json'),message=reason,heartbeat_unix=time.time()))
            else:eligible.append(candidate)
        if not eligible:return
        queued=eligible
        run=queued[0];write(run/'status.json',dict(read(run/'status.json'),status='preparing',message='GPU 已释放，启动独立作业。',heartbeat_unix=time.time()))
        with (run/'runner.log').open('ab') as log:
            process=subprocess.Popen([sys.executable,str(Path(__file__).with_name('studio_job_runner.py')),'--run',str(run)],cwd=ROOT,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        write(run/'runner_identity.json',identity(process.pid) or dict(pid=process.pid))


def updates():
    from job_diagnostics import failure_details
    return [dict(id=p.parent.name,status=read(p).get('status','failed'),result=dict(read(p),diagnostics=failure_details(p.parent))) for p in sorted(JOBS.glob('*/status.json'),key=lambda p:p.stat().st_mtime)[-50:]]
