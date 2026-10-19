"""Run a checkpoint server and camera-driven Isaac diagnostic; simulation only."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

CODE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(CODE/'gpu'))
from studio_backend import checkpoints,identity,write,sha,ROOT,JOBS

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--run',type=Path,required=True)
    p.add_argument('--checkpoint-id',required=True)
    p.add_argument('--room',type=int,default=0)
    p.add_argument('--frames',type=int,default=200)
    p.add_argument('--gpu',default='0')
    p.add_argument('--keep-server',action='store_true')
    p.add_argument('--serve-only',action='store_true',help='Load the checkpoint and keep its ROS2/model endpoint running')
    a=p.parse_args()
    if not 0<=a.room<32 or not 1<=a.frames<=2000:raise ValueError('invalid diagnostic budget')
    run=a.run.resolve();run.mkdir(parents=True,exist_ok=False)
    entries=[c for c in checkpoints() if c['id']==a.checkpoint_id]
    if len(entries)!=1:raise ValueError('unknown checkpoint')
    if not entries[0].get('family'):
        entry=entries[0];cp=Path(entry['checkpoint'])
        norm=cp/'assets'/entry['spec']['dataset_repo_id']/'norm_stats.json'
        if not norm.exists() or not (cp/'train_state').is_dir():raise ValueError('checkpoint not closed')
        entry['contentBindings']={str(f):sha(f) for f in [cp/'_CHECKPOINT_METADATA',cp/'params/manifest.ocdbt',norm]}
    write(run/'checkpoints.json',entries)
    write(run/'request.json',{'kind':'evaluation.vla','payload':{'checkpointIds':[a.checkpoint_id],'roomIds':[a.room],'framesPerAction':a.frames,'transport':'ros2','externalService':True,'realtimePacing':True}})
    (run/'policy').mkdir()
    write(run/'controller.identity.json',identity(os.getpid()))
    stop=False
    def interrupt(*_):
        nonlocal stop
        stop=True
    signal.signal(signal.SIGTERM,interrupt);signal.signal(signal.SIGINT,interrupt)
    env={**os.environ,'AIRPORT_PROJECT':str(ROOT),'CUDA_VISIBLE_DEVICES':a.gpu,'STUDIO_SIM_GPU':a.gpu,'PYTHONUNBUFFERED':'1'}
    children=[];logs=[];rc=0
    def launch(name,args):
        log=(run/(name+'.log')).open('ab');logs.append(log)
        child=subprocess.Popen(args,cwd=ROOT,env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT)
        children.append((name,child));write(run/(name+'.identity.json'),identity(child.pid));return child
    def heartbeat(stage,**extra):write(run/'live_status.json',dict(stage=stage,heartbeat_unix=time.time(),pid=os.getpid(),checkpointId=a.checkpoint_id,gpu=a.gpu,simulationOnly=True,**extra))
    try:
        with (JOBS/'gpu_job.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            service=launch('checkpoint_service',[sys.executable,str(CODE/'scripts/studio_vla_evaluate.py'),'--run',str(run),'--serve'])
            deadline=time.monotonic()+1200
            while not (run/'policy/ready.json').exists():
                heartbeat('loading_checkpoint')
                if stop:raise InterruptedError('stopped')
                if service.poll() is not None:raise RuntimeError('checkpoint_service_failed')
                if time.monotonic()>deadline:raise TimeoutError('checkpoint startup')
                time.sleep(2)
            if not a.serve_only:
                evaluation=launch('evaluation',[sys.executable,str(CODE/'scripts/studio_vla_evaluate.py'),'--run',str(run),'--native-python','/home/michelle/miniconda3/envs/env_isaaclab6/bin/python'])
                while evaluation.poll() is None:
                    heartbeat('simulator_running')
                    if stop:raise InterruptedError('stopped')
                    if service.poll() is not None:raise RuntimeError('checkpoint_service_exited')
                    time.sleep(2)
                code=evaluation.wait();write(run/'evaluation.exit.json',dict(returncode=code,actual_child_wait=True))
                if code:raise RuntimeError('simulation_process_failed')
        ready_stage='server_ready' if a.serve_only else 'rollout_finished_server_ready'
        heartbeat(ready_stage,taskReport=None if a.serve_only else str(run/'report.json'))
        while (a.keep_server or a.serve_only) and not stop:
            if service.poll() is not None:raise RuntimeError('checkpoint_service_exited')
            heartbeat(ready_stage,taskReport=None if a.serve_only else str(run/'report.json'));time.sleep(2)
    except Exception as exc:
        rc=1;write(run/'controller.failure.json',dict(error=repr(exc),unix=time.time()))
    finally:
        (run/'policy/stop').touch()
        for name,child in reversed(children):
            if child.poll() is None:child.terminate()
            try:exitcode=child.wait(timeout=25)
            except subprocess.TimeoutExpired:child.kill();exitcode=child.wait()
            write(run/(name+'.exit.json'),dict(returncode=exitcode,actual_child_wait=True,pid=child.pid))
        for log in logs:log.close()
        heartbeat('stopped',returncode=rc)
        write(run/'controller.exit.json',dict(returncode=rc,actual_child_wait=True,unix=time.time()))
    return rc

if __name__=='__main__':sys.exit(main())
