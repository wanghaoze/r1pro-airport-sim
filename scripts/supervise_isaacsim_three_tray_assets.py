"""Detached, single-instance asset migration stages; not a task/train supervisor.

The explicit terminal state is waiting for a native task controller/qualified
data. This tool cannot claim that a healthy asset probe trained a model.
"""
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
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run',type=Path,required=True)
    p.add_argument('--project',type=Path,required=True)
    p.add_argument('--legacy-root',type=Path,required=True)
    p.add_argument('--payload-template',type=Path,required=True)
    p.add_argument('--isaac-python',type=Path,required=True)
    p.add_argument('--source-python',type=Path,required=True)
    args=p.parse_args();run=args.run.resolve();run.mkdir(parents=True,exist_ok=True)
    lock=(run/'assets.lock').open('a+');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    code=Path(__file__).resolve().parents[1]
    def write(path,value):
        path=run/path;tmp=path.with_suffix(path.suffix+'.tmp')
        tmp.write_text(json.dumps(value,indent=2));tmp.replace(path)
    def identity(pid,command):
        return dict(pid=pid,start_ticks=Path(f'/proc/{pid}/stat').read_text().split()[21],
            command=list(map(str,command)),cwd=str(args.project))
    write(Path('supervisor_identity.json'),identity(os.getpid(),sys.argv))
    state=dict(schema='airport_three_tray_isaac_asset_supervisor/1',training_status='waiting_for_data',
        training_started=False,qualified_new_native_sources=0,task_controller_ported=False,
        assets_only=True,stage=None)
    def stage(name,command,progress=None):
        receipt=run/(name+'_exit.json')
        if receipt.exists():
            raise ValueError('fresh_run_required_no_unverified_stage_reuse:'+name)
        state.update(stage=name,status='running',heartbeat_unix=time.time())
        write(Path('pipeline_status.json'),state)
        with (run/(name+'.log')).open('x') as log:
            child=subprocess.Popen(list(map(str,command)),cwd=args.project,stdout=log,
                stderr=subprocess.STDOUT,env={**os.environ,'OMNI_KIT_ACCEPT_EULA':'YES'})
            write(Path(name+'_child.json'),identity(child.pid,command))
            while child.poll() is None:
                state.update(heartbeat_unix=time.time(),child_pid=child.pid,
                    progress_file=str(progress) if progress else None)
                write(Path('pipeline_status.json'),state)
                time.sleep(5)  # no stage/physics timeout; never substitutes old action budgets
            rc=child.wait()
        write(Path(name+'_exit.json'),dict(returncode=rc,actual_child_wait=True,unix=time.time()))
        if rc:raise RuntimeError(f'{name}: actual child exit {rc}; see {name}.log')
    try:
        stage('prepare',[args.source_python,code/'scripts/prepare_isaacsim_three_tray.py',
            '--legacy-root',args.legacy_root,'--payload-template',args.payload_template,
            '--output',run/'preparation'])
        scenes=sorted((run/'preparation/scenes/train').glob('*/scene.json'))
        if len(scenes)!=1:raise ValueError('one_registered_train_asset_candidate_required')
        scene=json.loads(scenes[0].read_text());xml=Path(scene['xml'])
        stage('import',[args.isaac_python,code/'scripts/isaacsim_scene_smoke.py','--xml',xml,
            '--output',run/'asset','--steps','100'],run/'asset/status.json')
        stage('materials',[args.isaac_python,code/'scripts/isaacsim_materials.py','--usd',
            run/'asset/airport_scene.usda','--xml',run/'asset/import_only.xml',
            '--output',run/'material_scene.usda'])
        command=[args.isaac_python,code/'scripts/isaacsim_control_preflight.py','--usd',
            run/'material_scene.usda','--xml',run/'asset/import_only.xml','--output',run/'control',
            '--native-coat','--restore-source-base-drives']
        for i in range(3):command.extend(['--coat-name',f'tray_{i}_passenger_coat'])
        stage('control',command,run/'control/status.json')
        result=json.loads((run/'control/validation.json').read_text())
        if not result.get('passed'):raise RuntimeError('native_control_probe_rejected')
        state.update(status='assets_preflight_complete',stage='waiting_native_task_controller',
            blocked_reason='native_three_tray_loaded_handover_controller_and_whole_task_observer_not_ported',
            heartbeat_unix=time.time(),migration_complete=False)
        write(Path('pipeline_status.json'),state)
        write(Path('assets_supervisor_exit.json'),dict(returncode=0,assets_preflight_passed=True,
            task_success=None,training_started=False,full_pipeline_complete=False,unix=time.time()))
    except Exception as e:
        state.update(status='failed',last_error=repr(e),heartbeat_unix=time.time())
        write(Path('pipeline_status.json'),state)
        (run/'supervisor_exception.txt').write_text(traceback.format_exc())
        write(Path('assets_supervisor_exit.json'),dict(returncode=1,error=repr(e),unix=time.time()))
        raise


if __name__=='__main__':main()
