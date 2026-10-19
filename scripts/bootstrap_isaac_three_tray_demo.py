"""Resume a real controller regression into recorded demo and existing pipeline."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from isaacsim_stage_runner import atomic, identity, checked


def main():
    p=argparse.ArgumentParser();p.add_argument('--config',type=Path,required=True);a=p.parse_args()
    cfg=json.loads(a.config.read_text());run=Path(cfg['run']);run.mkdir(exist_ok=True)
    lock=(run/'bootstrap.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    def state(stage,**kw):atomic(run/'status.json',dict(stage=stage,training_started=False,heartbeat_unix=time.time(),**kw))
    def launch(argv,stem):
        path=run/(stem+'.launch.json')
        if path.exists():
            j=json.loads(path.read_text())
            if checked(j):return j
            raise RuntimeError('closed_bootstrap_child_requires_explicit_new_attempt:'+stem)
        stream=(run/(stem+'.log')).open('x')
        proc=subprocess.Popen(argv,cwd=cfg['project'],stdin=subprocess.DEVNULL,stdout=stream,stderr=subprocess.STDOUT,start_new_session=True)
        j=identity(proc.pid);atomic(path,j);return j
    try:
        receipt=Path(cfg['regression_exit'])
        while not receipt.exists():
            j=json.loads(Path(cfg['regression_identity']).read_text())
            runner=json.loads(Path(cfg['regression_runner']).read_text())
            if not checked(j) and not checked(runner):raise RuntimeError('regression_missing_real_wait_receipt')
            progress=Path(cfg['regression_case'])/'progress.json'
            state('real_physx_controller_regression_not_training',child=j,progress=json.loads(progress.read_text()) if progress.exists() else {})
            time.sleep(5)
        r=json.loads(receipt.read_text());q=json.loads((Path(cfg['regression_case'])/'qualification.json').read_text())
        if r['returncode']!=0 or not r.get('actual_child_wait') or not q['complete_task_success']:
            raise RuntimeError('controller_regression_failed_no_recorded_demo_or_training')
        state('controller_regression_passed_without_media_not_dataset',regression_exit=r)
        code=Path(cfg['code']);py=cfg['source_python']
        demo_job=Path(cfg['demo_job']);job=json.loads(demo_job.read_text())
        launch([py,str(code/'scripts/isaacsim_stage_runner.py'),'--job',str(demo_job)],'demo_runner')
        while not Path(job['launch']).exists():time.sleep(.1)
        demo=json.loads(Path(job['launch']).read_text())
        primary=launch([py,str(code/'scripts/supervise_isaacsim_three_tray_task.py'),'--config',cfg['pipeline_config']],'supervisor')
        guard=launch([py,str(code/'scripts/guard_isaacsim_three_tray_task.py'),'--config',cfg['pipeline_config'],'--adopt',str(run/'supervisor.launch.json')],'guardian')
        expansion=launch([py,str(Path(cfg['project'])/'scripts/guard_isaacsim_expansion.py'),'--config',cfg['expansion_config']],'expansion_guardian')
        atomic(Path(cfg['pointer_path']),cfg['pointer'])
        state('recorded_demo_and_background_pipeline_started',demo=demo,supervisor=primary,guardian=guard,expansion=expansion,
            complete_demo_verified=False,data_ready=False)
    except BaseException as exc:
        state('failed',last_error=repr(exc));raise


if __name__=='__main__':main()
