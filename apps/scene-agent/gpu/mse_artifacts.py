"""Publish derived figures separately from immutable evaluation reports and arrays."""
import hashlib
from pathlib import Path
import subprocess
import sys
import time
import urllib.request
from studio_backend import ROOT, JOBS, read, write, identity, alive

FIGURES = ROOT/'runs/web_mse_figures_20261019_v1'


def candidates():
    return [p.parent for p in sorted(JOBS.glob('*/request.json'),key=lambda p:p.stat().st_mtime,reverse=True)
            if read(p).get('kind')=='evaluation.mse' and read(p.parent/'status.json').get('status')=='completed'][:10]


def upload(config, job_id, directory, item):
    path=(directory/item['name']).resolve()
    if path.parent!=directory.resolve(): raise ValueError('invalid_plot_artifact_path')
    data=path.read_bytes()
    if hashlib.sha256(data).hexdigest()!=item['sha256']: raise ValueError('plot_artifact_changed')
    key=f"{job_id}/{item['sha256'][:16]}/{item['name']}"
    req=urllib.request.Request(config['siteUrl'].rstrip('/')+'/api/artifacts?key='+key,data=data,method='PUT',
        headers={'Content-Type':'application/octet-stream','X-Artifact-Sha256':item['sha256'],
                 'OAI-Sites-Authorization':'Bearer '+config['siteToken'],'X-Worker-Token':config['workerToken']})
    with urllib.request.urlopen(req,timeout=15) as response:
        if response.status!=200: raise ValueError('plot_upload_not_confirmed')
    return '/api/artifacts?key='+key


def _tick(config):
    FIGURES.mkdir(parents=True,exist_ok=True)
    runs=candidates(); active=any(alive(read(p/'identity.json')) or alive(read(p/'child_identity.json')) for p in FIGURES.iterdir() if p.is_dir())
    for run in runs:
        out=FIGURES/run.name
        if not out.exists() and not active:
            out.mkdir()
            with (out/'controller.log').open('ab') as log:
                p=subprocess.Popen([sys.executable,str(Path(__file__).with_name('plot_runner.py')),'--job-id',run.name],cwd=ROOT,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            write(out/'identity.json',identity(p.pid) or {'pid':p.pid}); active=True
        if not out.exists(): continue
        manifest=read(out/'manifest.json'); receipt=read(out/'exit.json'); state=read(out/'publication.json',{'uploaded':{},'attempts':{}})
        if not manifest or receipt.get('returncode')!=0 or not receipt.get('actual_child_wait'): continue
        if config.get('offline'):continue
        pending=[f for f in manifest['files'] if f['name'] not in state['uploaded'] and state['attempts'].get(f['name'],0)<3]
        # Keep telemetry fresh; retries are bounded and publication cannot fail the GPU bridge.
        for item in pending[:2]:
            if time.time()<state.get('retryAfter',0): break
            try:
                state['uploaded'][item['name']]=upload(config,run.name,out,item); state.pop('error',None)
            except Exception as exc:
                count=state['attempts'].get(item['name'],0)+1; state['attempts'][item['name']]=count
                state.update(error=type(exc).__name__+': '+str(exc),retryAfter=time.time()+10*2**(count-1))
            write(out/'publication.json',state)
        # A single bundle per tick prevents multiple completed jobs delaying heartbeats.
        if pending: break


def tick(config):
    import fcntl
    FIGURES.mkdir(parents=True,exist_ok=True)
    with (FIGURES/'controller.lock').open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return
        _tick(config)


def summaries(local=False):
    result={}
    for run in candidates():
        out=FIGURES/run.name; manifest=read(out/'manifest.json'); receipt=read(out/'exit.json'); pub=read(out/'publication.json'); uploaded=pub.get('uploaded',{})
        if local and manifest and receipt.get('returncode')==0 and receipt.get('actual_child_wait'):
            uploaded={f['name']:f"/api/artifacts?key={run.name}/{f['sha256'][:16]}/{f['name']}" for f in manifest['files']}
        status='completed' if manifest and len(uploaded)==len(manifest['files']) else 'uploading' if manifest else 'rendering' if alive(read(out/'identity.json')) or alive(read(out/'child_identity.json')) else 'pending'
        if (receipt and receipt.get('returncode')!=0) or any(v>=3 for v in pub.get('attempts',{}).values()): status='failed'
        result[run.name]=dict(status=status,uploaded=len(uploaded),total=len(manifest.get('files',[])),progress=read(out/'progress.json'),
            message=pub.get('error') if status=='failed' else None,
            images=[dict(i,url=uploaded[i['name']]) for i in manifest.get('images',[]) if i['name'] in uploaded],
            downloads=[dict(name=n,url=url) for n,url in uploaded.items() if n.endswith(('.zip','.csv','.json'))])
    return result
