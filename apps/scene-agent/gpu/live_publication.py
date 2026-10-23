"""Bounded live telemetry and per-run media publication, independent of GPU control."""
import hashlib
import json
from pathlib import Path
import subprocess
import threading
import time
import urllib.request
from studio_backend import ROOT,JOBS,read,write,alive

def live_gpu_busy():
    # Dedicated GPU0; do not block on unrelated GPU1 or stop its processes.
    # The common gpu_job.lock is still acquired by the runner.
    try:
        p=subprocess.run(['nvidia-smi','--id=0','--query-gpu=memory.free','--format=csv,noheader,nounits'],capture_output=True,text=True,timeout=8)
        if p.returncode or float(p.stdout.strip())<24000:return 'GPU0 needs 24 GB free for model loading and Isaac; waiting without stopping services'
    except Exception:return 'GPU0 availability could not be verified'
    return None

def candidates():
    return [p.parent for p in sorted(JOBS.glob('*/request.json'),key=lambda p:p.stat().st_mtime,reverse=True) if read(p).get('kind')=='evaluation.live'][:20]

def snapshot(run):
    req=read(run/'request.json')['payload'];state=read(run/'status.json');progress=read(run/'progress.json')
    live=read(run/'native/live.json');inference=read(run/'inference_status.json')
    effective=read(run/'execution_contract.json')
    if effective.get('actionFilterContract'):req={**req,**effective}
    from job_diagnostics import diagnostics
    return dict(diagnostics=diagnostics(run),engine=read(run/'native/physics_runtime_settings.json'),jobId=run.name,simulationOnly=True,sampledAt=time.time(),checkpointId=req['checkpointIds'][0],roomId=req['roomIds'][0],
        configuration=req,status=state.get('status'),stage=state.get('status') if state.get('status') in ('failed','completed','cancelled','waiting_gpu') else progress.get('stage',state.get('status')),
        message=state.get('message'),report=read(run/'report.json'),progress=progress,inference=inference,**live)

def publish(config,run):
    data=snapshot(run);pubpath=run/('live_publication_local.json' if config.get('offline') else 'live_publication_cloud.json');pub=read(pubpath,{'files':{},'failures':{}})
    terminal=data.get('status') in ('completed','failed','cancelled')
    if terminal:
        import zipfile
        from job_diagnostics import redact
        archive=run/'diagnostics.zip'
        if not archive.exists():
            import os
            temporary=run/f'diagnostics.{os.getpid()}.tmp'
            with zipfile.ZipFile(temporary,'w',zipfile.ZIP_DEFLATED) as z:
                for path in list(run.glob('*.log'))+list(run.glob('*failure*.json'))+list((run/'native').glob('*failure*.json'))+list((run/'native/rooms').glob('*/failure.json'))+list((run/'policy').glob('*.error.json')):
                    z.writestr(str(path.relative_to(run)),redact(path.read_text(errors='replace')))
            temporary.replace(archive)
        files=[('diagnostics.zip',archive),('overview_simulation_time.mp4',run/'native/global_overview.mp4'),('run_report.json',run/'report.json')]
        files += [(f'{name}.mp4',run/'native/rooms/room_000'/f'{name}.mp4') for name in ('head_left','left_wrist','right_wrist')]
        from mse_artifacts import upload
        media=run/'web_media';media.mkdir(exist_ok=True)
        for name,source in files:
            if name in pub['files'] or pub['failures'].get(name,0)>=3 or not source.exists() or source.stat().st_size==0:continue
            if source.suffix=='.mp4':
                if not data.get('frame',0):continue
                probe=subprocess.run(['ffprobe','-v','error','-show_entries','format=duration','-of','json',str(source)],capture_output=True,text=True,timeout=10)
                if probe.returncode:continue
            content=source.read_bytes()
            if len(content)>32*1024*1024:
                pub['failures'][name]=3;pub['error']=name+' exceeds 32 MB site upload limit; original retained on workstation';continue
            digest=hashlib.sha256(content).hexdigest();target=media/name
            if not target.exists():target.write_bytes(content)
            try:
                url=upload(config,run.name,media,dict(name=name,sha256=digest))
                pub['files'][name]=dict(name=name,url=url,sha256=digest,bytes=len(content),timeline='20 Hz simulation time' if name.endswith('.mp4') else 'Measured run report')
            except Exception as exc:pub['failures'][name]=pub['failures'].get(name,0)+1;pub['error']=str(exc)
            write(pubpath,pub)
            break
    data['downloads']=[f for f in pub['files'].values() if not f['name'].endswith('.mp4') or data.get('frame',0)>0];data['mediaError']=pub.get('error')
    request=urllib.request.Request(config['siteUrl'].rstrip('/')+'/api/live',data=json.dumps(data).encode(),method='PUT',headers={'Content-Type':'application/json','X-Worker-Token':config['workerToken'],'OAI-Sites-Authorization':'Bearer '+config['siteToken']})
    with urllib.request.urlopen(request,timeout=8) as r:
        if r.status!=200:raise RuntimeError('Live snapshot upload failed')

def start_publisher(config,controller):
    stop=threading.Event()
    def loop():
        last_done={}
        while not stop.is_set():
            for run in candidates():
                if stop.is_set():break
                terminal=read(run/'status.json').get('status') in ('completed','failed','cancelled')
                if terminal and time.time()-last_done.get(run.name,0)<30:continue
                try:publish(config,run)
                except Exception as exc:write(controller/'live_publication_error.json',dict(error=str(exc),jobId=run.name,time=time.time()))
                if terminal:last_done[run.name]=time.time()
            stop.wait(.1 if config.get('offline') else .5)
    threading.Thread(target=loop,daemon=True,name='live-publication').start()
    return stop
