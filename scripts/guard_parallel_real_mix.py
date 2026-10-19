"""Bounded supervisor recovery with independent actual wait and single instance."""
import argparse,fcntl,json,os,subprocess,time
from pathlib import Path
from isaacsim_stage_runner import atomic,identity,checked

def main():
    p=argparse.ArgumentParser();p.add_argument('--config',type=Path,required=True);a=p.parse_args()
    cfg=json.loads(a.config.read_text());run=Path(cfg['run']);run.mkdir(parents=True,exist_ok=True)
    lock=(run/'guard.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    atomic(run/'guard_identity.json',identity(os.getpid()))
    for attempt in range(3):
        stem=run/f'supervisor_attempt_{attempt}';receipt=stem.with_suffix('.exit.json');launch=stem.with_suffix('.launch.json')
        if receipt.exists():
            if json.loads(receipt.read_text())['returncode']==0:return
            continue
        if launch.exists():
            old=json.loads(launch.read_text())
            while checked(old) and not receipt.exists():time.sleep(5)
            if receipt.exists() and json.loads(receipt.read_text())['returncode']==0:return
            if receipt.exists():continue
        with stem.with_suffix('.log').open('a') as log:
            child=subprocess.Popen([cfg['python'],str(Path(cfg['code'])/'scripts/supervise_parallel_real_mix.py'),'--config',str(a.config)],cwd=cfg['project'],stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            atomic(launch,identity(child.pid));atomic(run/'guard_status.json',dict(stage='supervising',attempt=attempt,supervisor=identity(child.pid),heartbeat_unix=time.time()))
            rc=child.wait()
        atomic(receipt,dict(returncode=rc,actual_child_wait=True,unix=time.time()))
        if rc==0:return
        time.sleep(5*(attempt+1))
    atomic(run/'guard_status.json',dict(stage='blocked',last_error='supervisor_failed_after_three_attempts',heartbeat_unix=time.time()))

if __name__=='__main__':main()
