"""Outer guard: bounded coordinator recovery, never retries physical failures."""
import argparse
import fcntl
import json
from pathlib import Path
import subprocess
import sys
import time
from isaacsim_stage_runner import atomic,identity,checked


def main():
    p=argparse.ArgumentParser();p.add_argument('--config',type=Path,required=True);p.add_argument('--adopt',type=Path,required=True);a=p.parse_args()
    cfg=json.loads(a.config.read_text());run=Path(cfg['run']);run.mkdir(parents=True,exist_ok=True)
    lock=(run/'guardian.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    out=run/'guardian_status.json';old=json.loads(out.read_text()) if out.exists() else {}
    job=old.get('supervisor')
    if job is None or not checked(job):job=json.loads(a.adopt.read_text())
    if not checked(job):raise RuntimeError('adopted_coordinator_already_dead')
    recoveries=int(old.get('recoveries',0))
    while True:
        state=dict(guardian=identity(__import__('os').getpid()),supervisor=job,recoveries=recoveries,heartbeat_unix=time.time())
        if checked(job):atomic(out,dict(state,stage='watching_verified_supervisor'))
        else:
            pipeline=run/'pipeline_status.json';s=json.loads(pipeline.read_text()) if pipeline.exists() else {}
            if s.get('stage') in ('failed','complete','training_complete_model_evaluation_pending'):
                atomic(out,dict(state,stage='terminal_coordinator_status',pipeline=s));return
            if recoveries>=3:atomic(out,dict(state,stage='process_recovery_limit_exhausted'));return
            delay=(10,30,90)[recoveries];atomic(out,dict(state,stage='coordinator_process_backoff',backoff_seconds=delay))
            # The worker's actual wait receipts survive coordinator crashes.
            time.sleep(delay);recoveries+=1
            argv=[sys.executable,str(Path(__file__).with_name('supervise_isaacsim_three_tray_task.py')),'--config',str(a.config)]
            stream=(run/f'coordinator_recovery_{recoveries}.log').open('x')
            child=subprocess.Popen(argv,cwd=cfg['project'],stdin=subprocess.DEVNULL,stdout=stream,stderr=subprocess.STDOUT,start_new_session=True)
            job=identity(child.pid);atomic(run/f'coordinator_recovery_{recoveries}.json',job)
        time.sleep(5)


if __name__=='__main__':main()
