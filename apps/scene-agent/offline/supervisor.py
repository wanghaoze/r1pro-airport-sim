"""Owned foreground supervisor. Lock, heartbeat, PID identity and actual child exits."""
import fcntl
import json
import os
from pathlib import Path
import secrets
import signal
import subprocess
import sys
import time
import urllib.request

APP=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(APP/'gpu'))
from studio_backend import identity,write

def main():
    root=Path(os.environ['AIRPORT_PROJECT']);run=root/'runs/scene_studio_offline_20261019_v1'
    run.mkdir(parents=True,exist_ok=True);lock=(run/'service.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    host=os.environ.get('STUDIO_HOST','127.0.0.1');port=os.environ.get('STUDIO_PORT','9080');url=f'http://{host if host!="0.0.0.0" else "127.0.0.1"}:{port}'
    token=secrets.token_urlsafe(32)
    # No visitor login. This token is only the local worker-to-service channel.
    cfg=run/'worker.json';write(cfg,dict(siteUrl=url,siteToken='',workerToken=token,runDirectory=str(run/'bridge'),offline=True));cfg.chmod(0o600)
    env={**os.environ,'STUDIO_OFFLINE':'1','STUDIO_DATA':str(run/'data'),'GPU_WORKER_TOKEN':token,'STUDIO_HOST':host,'STUDIO_PORT':port}
    write(run/'supervisor.identity.json',identity(os.getpid()));children=[];logs=[];stopping=False;rc=0
    def stop(*args):
        nonlocal stopping
        stopping=True
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    def start(name,argv):
        log=(run/(name+'.log')).open('ab');logs.append(log)
        p=subprocess.Popen(argv,cwd=APP,env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT)
        children.append((name,p));write(run/(name+'.identity.json'),identity(p.pid));return p
    try:
        server=start('web',['node',str(APP/'offline-dist/server.mjs')])
        for _ in range(100):
            if server.poll() is not None:raise RuntimeError('web_service_failed')
            try:
                with urllib.request.urlopen(url+'/api/health',timeout=2) as r:
                    if json.load(r).get('ok'):break
            except OSError:time.sleep(.2)
        else:raise TimeoutError('web_start_timeout')
        start('bridge',[sys.executable,str(APP/'gpu/worker.py'),'--config',str(cfg)])
        print(url,flush=True)
        while not stopping:
            failed=[name for name,p in children if p.poll() is not None]
            if 'web' in failed:raise RuntimeError('child_exited:web')
            # Preserve the UI and its stale-state evidence after bounded bridge retries.
            if 'bridge' in failed:
                for name,p in children:
                    if name=='bridge':write(run/'bridge.exit.json',dict(returncode=p.wait(),actual_child_wait=True,pid=p.pid,endedAt=time.time()))
            write(run/'heartbeat.json',dict(stage='degraded_bridge' if 'bridge' in failed else 'serving',heartbeat_unix=time.time(),url=url,pid=os.getpid(),authentication='disabled'))
            time.sleep(2)
    except Exception as exc:
        rc=1;write(run/'failure.json',dict(error=repr(exc),time=time.time()))
    finally:
        for name,p in reversed(children):
            if p.poll() is None:p.terminate()
            try:code=p.wait(timeout=20)
            except subprocess.TimeoutExpired:p.kill();code=p.wait()
            write(run/(name+'.exit.json'),dict(returncode=code,actual_child_wait=True,pid=p.pid,endedAt=time.time()))
        for log in logs:log.close()
        write(run/'exit.json',dict(returncode=rc,endedAt=time.time()))
    return rc

if __name__=='__main__':sys.exit(main())
