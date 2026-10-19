"""Qualified native variants -> version-2 action3 data -> queued independent BC.

Never mutates the first batch or the trainer currently reading it. Each failed
source is retained; three consecutive physical failures stop this producer.
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
    p=argparse.ArgumentParser();p.add_argument('--config',type=Path,required=True);a=p.parse_args()
    cfg=json.loads(a.config.read_text());run=Path(cfg['run']);run.mkdir(parents=True,exist_ok=True)
    lock=(run/'producer.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    code=Path(cfg['code']);sys.path[:0]=[str(code),str(code/'scripts')]
    from isaacsim_stage_runner import atomic,identity,checked
    from r1pro_teleop.vla.isaac_dataset import validate_episode,freeze_corpus,load_frozen
    registry=json.loads(Path(cfg['registry']).read_text());primary=Path(cfg['primary'])
    logs=run/'logs';logs.mkdir(exist_ok=True)
    atomic(run/'identity.json',identity(os.getpid()))
    state=dict(stage='waiting_first_qualified_batch',training_started=False,complete_sources=0,train_action_segments=0)
    def status(**kw):state.update(kw,heartbeat_unix=time.time());atomic(run/'pipeline_status.json',state)
    def command(name,argv):
        receipt=logs/(name+'.exit.json');job=logs/(name+'.job.json');launch=logs/(name+'.launch.json')
        if not receipt.exists() and not job.exists():
            atomic(job,dict(argv=argv,cwd=cfg['project'],log=str(logs/(name+'.log')),launch=str(launch),receipt=str(receipt),
                environment={'OMNI_KIT_ACCEPT_EULA':'YES','AIRPORT_PROJECT':cfg['project']}))
            subprocess.Popen([sys.executable,str(code/'scripts/isaacsim_stage_runner.py'),'--job',str(job)],
                cwd=cfg['project'],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
        while not receipt.exists():
            if launch.exists():
                child=json.loads(launch.read_text())
                if child and child['argv']!=argv:raise RuntimeError('producer_stage_command_changed')
                if child and not checked(child):
                    runner=logs/(name+'.job.runner.json')
                    if not runner.exists() or not checked(json.loads(runner.read_text())):raise RuntimeError('producer_child_missing_wait_receipt')
            tp=run/'training_v2/training_status.json';training=json.loads(tp.read_text()) if tp.exists() else {}
            status(active_stage=name,training_started=training.get('training_started',False),
                actual_updates=training.get('actual_completed_updates',0));time.sleep(5)
        return json.loads(receipt.read_text())
    try:
        while not (primary/'cache_v1/integrity.json').exists():
            s=primary/'pipeline_status.json';s=json.loads(s.read_text()) if s.exists() else {}
            if s.get('stage')=='failed':raise RuntimeError('primary_native_pipeline_failed_before_first_batch')
            status(primary_stage=s.get('stage'));time.sleep(10)
        corpus=load_frozen(primary/'dataset_v1/manifest.json',registry)
        sources=[r['episode_directory'] for r in corpus['episodes']]
        train_segments=sum(len(r['actions']) for r in corpus['episodes'] if r['split']=='train')
        consecutive=0
        for seed in cfg['seeds']:
            if train_segments>=cfg['target_train_segments']:break
            out=run/'episodes'/f'seed_{seed}';name=f'case_{seed}'
            status(stage='native_generation',complete_sources=len(sources),train_action_segments=train_segments,seed=seed,
                randomization_scope='same_registered_train_parent_small_xy_yaw_variants_not_independent_scenes')
            receipt=command(name,[cfg['isaac_python'],str(code/'scripts/run_isaacsim_three_tray_task.py'),
                '--scene-root',cfg['train_scene_root'],'--output',str(out),'--seed',str(seed),'--episode-id',f'isaac_three_tray_variant_{seed}'])
            target=out/'process_exit.json'
            if not target.exists():atomic(target,receipt)
            try:
                if receipt['returncode']:raise RuntimeError('actual_native_child_failure')
                row=validate_episode(out,registry)
                if row['split']!='train':raise RuntimeError('variant_parent_not_train')
            except Exception as exc:
                consecutive+=1;status(last_failed_case=str(out),last_error=repr(exc),consecutive_physical_failures=consecutive)
                if consecutive>=3:raise RuntimeError('three_consecutive_physical_failures_need_control_diagnosis') from exc
                continue
            consecutive=0
            if str(out) not in sources:sources.append(str(out));train_segments+=len(row['actions'])
            atomic(run/'qualified_sources.json',sources)
            paths=[]
            for source in sources:
                e=json.loads((Path(source)/'episode.json').read_text())
                paths.extend(str(Path(source)/v['path']) for v in e['videos'].values())
            (run/'VIDEO_PATHS.txt').write_text('\n'.join(paths)+'\n')
        if train_segments<cfg['target_train_segments']:raise RuntimeError('registered_variant_seed_budget_exhausted')
        data=run/'dataset_v2'
        if not (data/'manifest.json').exists():freeze_corpus(sources,registry,data)
        elif {r['episode_directory'] for r in load_frozen(data/'manifest.json',registry)['episodes']}!=set(sources):
            raise RuntimeError('existing_frozen_variant_source_set_changed')
        common=[cfg['source_python'],str(code/'scripts/prepare_isaacsim_dataset.py'),'--registry',cfg['registry'],'--manifest',str(data/'manifest.json')]
        for mode,folder,receipt_file in [('clips','three_actions_v2','manifest.json'),('cache','cache_v2','integrity.json')]:
            result=command(mode,common+['--mode',mode,'--output',str(run/folder)])
            if result['returncode'] or not (run/folder/receipt_file).exists():raise RuntimeError('variant_data_export_failed:'+mode)
        status(stage='dataset_v2_ready_waiting_primary_training',complete_sources=len(sources),train_action_segments=train_segments)
        # Queue another immutable training version; never compete with the first trainer.
        while True:
            s=json.loads((primary/'pipeline_status.json').read_text())
            if s['stage']=='failed':raise RuntimeError('primary_training_failed_new_training_not_started')
            if s['stage'] in ('complete','training_complete_model_evaluation_pending'):break
            status(stage='dataset_v2_ready_waiting_primary_training');time.sleep(15)
        train=run/'training_v2';inputs=dict(cache=str(run/'cache_v2'),manifest=str(data/'manifest.json'),registry=cfg['registry'],
            parent_checkpoint=cfg['parent_checkpoint'],parent_status=cfg['parent_status'])
        if not (train/'inputs.json').exists():train.mkdir(parents=True,exist_ok=True);atomic(train/'inputs.json',inputs)
        base=[cfg['vla_python'],str(code/'scripts/train_pi05_isaac_three_tray.py'),'--run',str(train)]
        if command('train_prepare',base+['--mode','prepare'])['returncode']:raise RuntimeError('v2_training_preparation_failed')
        for step in (10,100,1000,10000,100000):
            status(stage='training_v2_initializing_or_updating',current_milestone=step)
            if command(f'train_{step}',base+['--mode','train','--stop',str(step)])['returncode']:raise RuntimeError('v2_training_stage_failed')
        status(stage='training_v2_complete_model_evaluation_pending')
    except BaseException as exc:
        status(stage='failed',last_error=repr(exc));(run/'exception.txt').write_text(traceback.format_exc());raise


if __name__=='__main__':main()
