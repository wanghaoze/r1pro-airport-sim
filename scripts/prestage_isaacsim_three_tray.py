"""Prepare registered held-out assets while a native demo runs independently."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback


def main():
    p=argparse.ArgumentParser();p.add_argument('--config',type=Path,required=True)
    p.add_argument('--code-dir',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    a.output.mkdir(parents=True,exist_ok=True);lock=(a.output/'lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    sys.path.insert(0,str(a.code_dir/'scripts'));from isaacsim_stage_runner import atomic,identity,checked
    cfg=json.loads(a.config.read_text());project=Path(cfg['project']);logs=Path(cfg['run'])/'logs';logs.mkdir(parents=True,exist_ok=True)
    atomic(a.output/'identity.json',identity(os.getpid()))
    try:
        for i,case in enumerate(cfg['cases']):
            for j,item in enumerate(case.get('asset_stages',[])):
                name=f'asset_{i:04d}_{j}';receipt=logs/(name+'.exit.json');launch=logs/(name+'.launch.json');job=logs/(name+'.job.json')
                runner=None
                if not receipt.exists() and not job.exists():
                    descriptor=dict(argv=item['argv'],cwd=str(project),log=str(logs/(name+'.log')),
                        launch=str(launch),receipt=str(receipt),environment={'OMNI_KIT_ACCEPT_EULA':'YES','AIRPORT_PROJECT':str(project)})
                    with job.open('x') as stream:json.dump(descriptor,stream)
                    runner=subprocess.Popen([sys.executable,str(a.code_dir/'scripts/isaacsim_stage_runner.py'),'--job',str(job)],
                        cwd=project,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
                while not receipt.exists():
                    if launch.exists():
                        child=json.loads(launch.read_text())
                        if child['argv']!=item['argv']:raise RuntimeError('registered_asset_command_changed')
                        if not checked(child):
                            rid=logs/(name+'.job.runner.json')
                            if not rid.exists() or not checked(json.loads(rid.read_text())):raise RuntimeError('asset_child_missing_actual_wait_receipt')
                    elif runner is not None and runner.poll() is not None:raise RuntimeError('asset_runner_failed_before_launch')
                    atomic(a.output/'status.json',dict(stage=name,split=case['split'],heartbeat_unix=time.time(),
                        qualification=False,training_started=False))
                    time.sleep(5)
                result=json.loads(receipt.read_text())
                if result['returncode'] or not all(Path(f).exists() for f in item['required']):raise RuntimeError('actual_asset_stage_failed:'+name)
                if item.get('exit_receipt'):
                    target=Path(item['exit_receipt'])
                    if target.exists():
                        if json.loads(target.read_text())!=result:raise RuntimeError('immutable_control_receipt_changed')
                    else:atomic(target,result)
        atomic(a.output/'status.json',dict(stage='val_test_assets_ready_not_dataset',qualification=False,training_started=False,heartbeat_unix=time.time()))
    except BaseException as exc:
        atomic(a.output/'status.json',dict(stage='failed',error=repr(exc),qualification=False,heartbeat_unix=time.time()))
        (a.output/'exception.txt').write_text(traceback.format_exc());raise


if __name__=='__main__':main()
