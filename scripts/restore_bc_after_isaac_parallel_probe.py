"""Restore the unchanged original BC between exclusive probe and collection.

Only restores the exact deferred coordinator after its own native probes have
closed. It never starts training on the unqualified probe/new pose candidates.
"""
import argparse
import fcntl
import json
from pathlib import Path
import subprocess
import time
from isaacsim_stage_runner import atomic, identity, checked


def main():
    p=argparse.ArgumentParser();p.add_argument('--config',type=Path,required=True);a=p.parse_args()
    cfg=json.loads(a.config.read_text());run=Path(cfg['run']);run.mkdir(exist_ok=True)
    lock=(run/'bc_restore.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    probe=Path(cfg['probe_run']);diverse=Path(cfg['diverse_run']);resume=Path(cfg['resume_config'])
    deferred=json.loads((probe/'BC_resource_deferral.json').read_text())
    if deferred['resume_config']!=str(resume) or deferred['training_status']['actual_completed_updates']!=0:
        raise RuntimeError('restore_requires_exact_verified_zero_update_deferral')
    original=json.loads(resume.read_text());target=original['training']
    def status(stage,**kw):atomic(run/'pipeline_status.json',dict(stage=stage,heartbeat_unix=time.time(),training_started=False,**kw))
    try:
        while True:
            state=json.loads((probe/'pipeline_status.json').read_text())
            running=[]
            for root in (probe,diverse,*map(Path,cfg.get('additional_native_roots',[]))):
                for launch in root.glob('*.launch.json'):
                    j=json.loads(launch.read_text())
                    # Only native simulation children; never touch another job.
                    if j and any(x.endswith(('/probe_isaac_parallel_collection.py','/run_isaacsim_fast_pickplace.py')) for x in j['argv']) and checked(j):
                        running.append(j)
            pending=[p for p in cfg.get('additional_pending_receipts',[]) if not Path(p).exists()]
            failed_additional=[]
            for p in cfg.get('additional_terminal_failure_statuses',[]):
                path=Path(p)
                if path.exists() and json.loads(path.read_text()).get('stage')=='failed':failed_additional.append(p)
            if failed_additional:pending=[]  # Resource release after failure is NOT a success receipt.
            if state['stage'] in ('failed','integration_complete_adaptive_collection_pending') and not running and not pending:
                break
            status('waiting_for_exclusive_native_probes_to_close',active_native_children=running,
                   integration_stage=state['stage'],pending_actual_exit_receipts=pending);time.sleep(5)
        for path in Path('/proc').iterdir():
            if not path.name.isdigit():continue
            try:
                argv=(path/'cmdline').read_text().split('\0')[:-1]
                if not argv or (target not in argv and str(resume) not in argv):continue
                j=identity(int(path.name))
            except PermissionError:continue  # Unrelated users' /proc entries.
            except FileNotFoundError:continue
            if not j:continue
            argv=j['argv']
            if (target in argv and any(x.endswith('/train_pi05_isaac_three_tray.py') for x in argv)) or (str(resume) in argv and any(x.endswith('/guard_isaacsim_expansion.py') for x in argv)):
                status('restored_original_coordinator',adopted_existing=j,original_config=str(resume));return
        stream=(run/'original_BC_guardian.log').open('x')
        child=subprocess.Popen([cfg['control_python'],cfg['original_guard'],'--config',str(resume)],
            cwd=cfg['project'],stdin=subprocess.DEVNULL,stdout=stream,stderr=subprocess.STDOUT,start_new_session=True)
        j=identity(child.pid);atomic(run/'original_BC_guardian.launch.json',j)
        if not checked(j):raise RuntimeError('original_BC_guardian_not_alive_after_launch')
        status('restored_original_coordinator',original_guardian=j,original_config=str(resume),
               new_pose_dataset_used=False,actual_gradient_updates_must_be_read_from_original_training_status=True)
    except BaseException as exc:
        status('failed',error=repr(exc));raise


if __name__=='__main__':main()
