"""Detached bounded recovery for the native variant producer, not physics retries."""
import argparse
import fcntl
import json
from pathlib import Path
import subprocess
import sys
import time
from isaacsim_stage_runner import atomic, identity, checked


def main():
    p=argparse.ArgumentParser();p.add_argument('--config',type=Path,required=True);a=p.parse_args()
    cfg=json.loads(a.config.read_text());run=Path(cfg['run']);run.mkdir(parents=True,exist_ok=True)
    lock=(run/'guardian.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    status=run/'guardian_status.json';previous=json.loads(status.read_text()) if status.exists() else {}
    attempt=int(previous.get('attempt',0))
    terminals=tuple(cfg.get('producer_terminal_stages',('failed','training_v2_complete_model_evaluation_pending')))
    while True:
        out=run/cfg.get('producer_status_name','pipeline_status.json');state=json.loads(out.read_text()) if out.exists() else {}
        if state.get('stage') in terminals:
            atomic(status,dict(stage='terminal_producer_status',attempt=attempt,producer_status=state,unix=time.time()));return
        launch=run/f'producer_attempt_{attempt}.launch.json'
        child=json.loads(launch.read_text()) if launch.exists() else None
        if not child:
            stream=(run/f'producer_attempt_{attempt}.log').open('x')
            proc=subprocess.Popen([sys.executable,cfg.get('producer_entry',str(Path(cfg['code'])/'scripts/expand_isaacsim_three_tray.py')),'--config',str(a.config)],
                cwd=cfg['project'],stdin=subprocess.DEVNULL,stdout=stream,stderr=subprocess.STDOUT,start_new_session=True)
            child=identity(proc.pid);atomic(launch,child)
        if not checked(child):
            # Give the producer's terminal state precedence over process recovery.
            state=json.loads(out.read_text()) if out.exists() else {}
            if state.get('stage') in terminals:continue
            if attempt>=3:atomic(status,dict(stage='recovery_exhausted',attempt=attempt,unix=time.time()));return
            delay=(10,30,90)[attempt];atomic(status,dict(stage='process_backoff',attempt=attempt,delay=delay,unix=time.time()))
            time.sleep(delay);attempt+=1;continue
        atomic(status,dict(stage='watching_verified_producer',attempt=attempt,producer=child,heartbeat_unix=time.time()))
        time.sleep(5)


if __name__=='__main__':main()
