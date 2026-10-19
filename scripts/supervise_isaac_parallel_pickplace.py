"""Single-instance detached feedback collection and qualified export pipeline."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from isaacsim_stage_runner import atomic, checked, identity


def main():
    p=argparse.ArgumentParser();p.add_argument('--config',type=Path,required=True);a=p.parse_args()
    cfg=json.loads(a.config.read_text());run=Path(cfg['run']);run.mkdir(exist_ok=True)
    lock=(run/'pipeline.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    state=dict(pid=os.getpid(),scope='parallel_fixed_base_pickplace',training_started=False)
    def report(stage,**extra):
        state.update(stage=stage,heartbeat_unix=time.time(),**extra);atomic(run/'pipeline_status.json',state)
    try:
        for item in cfg['stages']:
            root=Path(item['run']);root.mkdir(exist_ok=True)
            native=root/'native';receipt=root/'native.exit.json';job=root/'native.job.json'
            if not job.exists():
                atomic(root/'config.json',dict(item['native_config'],output=str(native)))
                atomic(root/'parent_splits.json',item['parent_splits'])
                atomic(job,dict(argv=[cfg['native_python'],str(Path(cfg['code'])/'scripts/run_isaac_parallel_pickplace.py'),'--config',str(root/'config.json')],cwd=cfg['project'],log=str(root/'native.log'),launch=str(root/'native.launch.json'),receipt=str(receipt),environment=dict(OMNI_KIT_ACCEPT_EULA='YES',PYTHONUNBUFFERED='1')))
            runner_path=root/'native.job.runner.json'
            # Stage runner naming is job.with_suffix('.runner.json').
            runner_path=job.with_suffix('.runner.json')
            if not receipt.exists():
                if runner_path.exists():
                    if not checked(json.loads(runner_path.read_text())):raise RuntimeError('native_waiter_missing_no_duplicate_launch')
                elif (root/'native.launch.json').exists():
                    launch=json.loads((root/'native.launch.json').read_text())
                    if not checked(launch):raise RuntimeError('native_identity_lost_without_exit')
                else:
                    proc=subprocess.Popen([cfg['control_python'],str(Path(cfg['code'])/'scripts/isaacsim_stage_runner.py'),'--job',str(job)],cwd=cfg['project'],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
                    atomic(root/'supervisor_spawn.json',dict(runner=identity(proc.pid)))
            while not receipt.exists():
                progress=native/'status.json'
                report('native_collection',rooms=item['rooms'],active_run=str(root),native=json.loads(progress.read_text()) if progress.exists() else None)
                if runner_path.exists() and not checked(json.loads(runner_path.read_text())) and not receipt.exists():raise RuntimeError('native_waiter_lost_without_exit')
                time.sleep(5)
            actual=json.loads(receipt.read_text())
            if actual.get('actual_child_wait') is not True or actual.get('returncode')!=0:raise RuntimeError('native_process_failed:'+str(receipt))
            progress=json.loads((native/'status.json').read_text())
            if progress['stage']!='parallel_batch_closed':raise RuntimeError('native_artifacts_not_closed')
            benchmark=dict(rooms=item['rooms'],native_status=progress,actual_exit=actual,
                simulation_and_record_wall_seconds=progress.get('elapsed_seconds'),phase_wall_seconds=progress.get('timings'),
                global_frames=progress['frames'],global_real_substeps=progress.get('global_real_substeps'),
                scope='shared_engine_expert_not_model_test')
            atomic(native/'benchmark_summary.json',benchmark)
            export_receipt=root/'export.exit.json'
            if not export_receipt.exists():
                ejob=root/'export.job.json'
                atomic(ejob,dict(argv=[cfg['control_python'],str(Path(cfg['code'])/'scripts/export_isaac_parallel_pickplace.py'),'--run',str(native),'--receipt',str(receipt),'--parent-splits',str(root/'parent_splits.json')],cwd=cfg['project'],log=str(root/'export.log'),launch=str(root/'export.launch.json'),receipt=str(export_receipt)))
                waiter=subprocess.Popen([cfg['control_python'],str(Path(cfg['code'])/'scripts/isaacsim_stage_runner.py'),'--job',str(ejob)],cwd=cfg['project'],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
                while not export_receipt.exists():
                    report('exporting',rooms=item['rooms'],active_run=str(root),export_runner=identity(waiter.pid))
                    if waiter.poll() is not None and not export_receipt.exists():raise RuntimeError('export_waiter_lost')
                    time.sleep(3)
            if json.loads(export_receipt.read_text()).get('returncode')!=0:raise RuntimeError('export_process_failed')
            catalog=json.loads((native/'dataset_catalog.json').read_text())
            report('stage_closed',rooms=item['rooms'],active_run=str(root),qualified_pairs=catalog['complete_source_pairs'],action_segments=catalog['action_segments'])
            if catalog['complete_source_pairs']<1 or catalog.get('overview_error'):raise RuntimeError('no_qualified_pair_or_overview_no_scaleup')
        report('complete')
    except BaseException as exc:
        report('blocked',error=repr(exc));atomic(run/'failure.json',dict(error=repr(exc),traceback=traceback.format_exc()))
        raise


if __name__=='__main__':main()
