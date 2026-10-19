"""Detached native task -> immutable action3 corpus -> BC supervisor.

Full native success and real child exit are both mandatory. Failed physical
cases are evidence, never retried indefinitely or relabelled into training.
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

CODE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(CODE))
from r1pro_teleop.vla.real_sim_data import write


def main():
    p=argparse.ArgumentParser();p.add_argument('--config',type=Path,required=True);a=p.parse_args()
    cfg=json.loads(a.config.read_text());run=Path(cfg['run']);run.mkdir(parents=True,exist_ok=True)
    lock=(run/'task_pipeline.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    project=Path(cfg['project']);logs=run/'logs';logs.mkdir(exist_ok=True)
    state=dict(stage='demo',training_status='waiting_for_data',training_started=False,qualified_sources=0)
    def identity(pid,argv):
        return dict(pid=pid,start_ticks=Path(f'/proc/{pid}/stat').read_text().rsplit(')',1)[1].split()[19],argv=argv,cwd=str(project))
    write(run/'supervisor_identity.json',identity(os.getpid(),sys.argv))
    def status(**data):
        state.update(data,heartbeat_unix=time.time());write(run/'pipeline_status.json',state)
    def freeze_write(path,value):
        path=Path(path)
        if path.exists():
            if json.loads(path.read_text())!=value:raise RuntimeError('immutable_receipt_or_inputs_changed:'+str(path))
        else:write(path,value)
    def stage(name,argv,required):
        receipt=logs/(name+'.exit.json')
        if receipt.exists():
            old=json.loads(receipt.read_text())
            if old['returncode']==0 and all(Path(f).exists() for f in required):return
            raise RuntimeError('failed_stage_preserved_requires_new_attempt:'+name)
        status(stage=name,command=argv)
        from isaacsim_stage_runner import checked
        launch=logs/(name+'.launch.json');jobfile=logs/(name+'.job.json')
        runner_identity=logs/(name+'.job.runner.json')
        if not launch.exists() and not jobfile.exists():
            write(jobfile,dict(argv=argv,cwd=str(project),log=str(logs/(name+'.log')),
                launch=str(launch),receipt=str(receipt),environment={'OMNI_KIT_ACCEPT_EULA':'YES','AIRPORT_PROJECT':str(project)}))
            subprocess.Popen([sys.executable,str(CODE/'scripts/isaacsim_stage_runner.py'),'--job',str(jobfile)],
                cwd=project,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
        while not receipt.exists():
            if launch.exists():
                job=json.loads(launch.read_text())
                if job['argv']!=argv or job['cwd']!=str(project):raise RuntimeError('stage_command_changed_no_duplicate')
                if not checked(job):
                    if runner_identity.exists() and checked(json.loads(runner_identity.read_text())):
                        time.sleep(1);continue
                    raise RuntimeError('child_died_without_actual_wait_receipt')
            elif runner_identity.exists() and not checked(json.loads(runner_identity.read_text())):
                raise RuntimeError('stage_runner_died_before_child_launch')
            else:job={}
            if not launch.exists() and not runner_identity.exists() and time.time()-jobfile.stat().st_mtime>60:
                raise RuntimeError('stage_runner_not_started_no_physics_timeout_applied')
            if launch.exists():
                training=run/'training/training_status.json'
                t=json.loads(training.read_text()) if training.exists() else {}
                status(child_pid=job['pid'],training_started=t.get('training_started',False),
                    training_status=t.get('stage','waiting_for_data'),actual_updates=t.get('actual_completed_updates',0))
            else:status(child_pid=None,substage='starting_independent_stage_runner')
            time.sleep(5)
        rc=json.loads(receipt.read_text())['returncode']
        if rc or not all(Path(f).exists() for f in required):raise RuntimeError('actual_stage_failure:'+name)
    try:
        demo=Path(cfg['demo']);receipt=Path(cfg['demo_exit']);ident=json.loads(Path(cfg['demo_identity']).read_text())
        from isaacsim_stage_runner import checked
        ident['argv']=ident.get('argv',ident.get('command'))
        while not receipt.exists():
            if not checked(ident):
                raise RuntimeError('external_demo_exited_without_actual_wait_receipt')
            status(stage='demo',child_pid=ident['pid'],actual_progress=json.loads((demo/'progress.json').read_text()) if (demo/'progress.json').exists() else {})
            time.sleep(5)
        if json.loads(receipt.read_text())['returncode']!=0:raise RuntimeError('native_full_demo_failed_no_collection_or_training')
        # The independent parent owns this actual wait receipt; the native
        # child cannot truthfully write its own exit status before exiting.
        freeze_write(demo/'process_exit.json',json.loads(receipt.read_text()))
        from r1pro_teleop.vla.isaac_dataset import validate_episode
        registry=json.loads(Path(cfg['registry']).read_text());validated=validate_episode(demo,registry)
        freeze_write(demo/'native_data_validation.json',validated)
        status(stage='demo_passed',qualified_sources=1,demo=str(demo))
        # Each case has its own predeclared scene identity and immutable directory.
        # Source assets are distinct per parent split; never reuse train poses as test.
        sources=[str(demo)]
        for source in cfg.get('reuse_validated_episodes',[]):
            if str(source) in sources:continue
            validated=validate_episode(Path(source),registry)
            freeze_write(Path(source)/'native_data_validation.json',validated)
            sources.append(str(source))
        status(qualified_sources=len(sources))
        for index,case in enumerate(cfg['cases']):
            root=Path(case['scene_root']);out=run/'episodes'/f'case_{index:04d}'
            if case.get('asset_stages'):
                for i,item in enumerate(case['asset_stages']):
                    stage(f'asset_{index:04d}_{i}',item['argv'],item['required'])
                    if item.get('exit_receipt'):
                        freeze_write(Path(item['exit_receipt']),json.loads((logs/f'asset_{index:04d}_{i}.exit.json').read_text()))
            stage(f'episode_{index:04d}',[cfg['isaac_python'],str(CODE/'scripts/run_isaacsim_three_tray_task.py'),
                '--scene-root',str(root),'--output',str(out),'--seed',str(case['seed']),'--episode-id',case.get('episode_id',f'isaac_three_tray_{index:04d}')],[str(out/'episode.json')])
            exit_data=json.loads((logs/f'episode_{index:04d}.exit.json').read_text());freeze_write(out/'process_exit.json',exit_data)
            validated=validate_episode(out,registry);freeze_write(out/'native_data_validation.json',validated)
            sources.append(str(out));status(qualified_sources=len(sources))
            # First full train/val/test batch, rather than waiting for all cases.
            splits={json.loads((Path(s)/'episode.json').read_text())['split'] for s in sources}
            if splits=={'train','val','test'}:break
        if {json.loads((Path(s)/'episode.json').read_text())['split'] for s in sources}!={'train','val','test'}:
            raise RuntimeError('first_batch_missing_legal_parent_split')
        freeze_write(run/'first_batch_sources.json',sources)
        data=run/'dataset_v1';cache=run/'cache_v1';clips=run/'three_actions_v1'
        common=[cfg['source_python'],str(CODE/'scripts/prepare_isaacsim_dataset.py'),'--registry',cfg['registry']]
        stage('freeze',common+['--mode','freeze','--episodes',str(run/'first_batch_sources.json'),'--output',str(data)],[str(data/'manifest.json')])
        stage('clips',common+['--mode','clips','--manifest',str(data/'manifest.json'),'--output',str(clips)],[str(clips/'manifest.json')])
        stage('cache',common+['--mode','cache','--manifest',str(data/'manifest.json'),'--output',str(cache)],[str(cache/'integrity.json')])
        train=run/'training';freeze_write(train/'inputs.json',dict(cache=str(cache),manifest=str(data/'manifest.json'),registry=cfg['registry'],parent_checkpoint=cfg['parent_checkpoint'],parent_status=cfg['parent_status']))
        command=[cfg['vla_python'],str(CODE/'scripts/train_pi05_isaac_three_tray.py'),'--run',str(train)]
        stage('train_prepare',command+['--mode','prepare'],[str(train/'preparation_status.json')])
        for milestone in (10,100,1000,10000,100000):
            stage(f'train_{milestone}',command+['--mode','train','--stop',str(milestone)],[str(train/f'checkpoint_{milestone:06d}.json')])
            # Evaluation is a separately configured pure policy entry point.
            eval_command=cfg.get('evaluation_command')
            if eval_command:
                stage(f'evaluate_{milestone}',[x.replace('{training}',str(train)).replace('{step}',str(milestone)) for x in eval_command],
                    [str(run/f'evaluations/step_{milestone}/summary.json')])
            else:status(model_evaluation_status='not_started_no_qualified_native_policy_entry',model_test_passed=False)
        status(stage='training_complete_model_evaluation_pending' if not cfg.get('evaluation_command') else 'complete')
    except BaseException as exc:
        status(stage='failed',last_error=repr(exc));(run/'supervisor_exception.txt').write_text(traceback.format_exc());raise


if __name__=='__main__':main()
