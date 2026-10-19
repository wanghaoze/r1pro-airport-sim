"""Independent, single-instance conditional BC startup after 300 frozen pairs."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from isaacsim_stage_runner import atomic,checked
from r1pro_teleop.vla.parallel_pickplace_training import freeze_pairs,materialize_parallel_cache,verify_frozen


def prepare_data(cfg):
    run=Path(cfg['run']);source=Path(cfg['production_manifest'])
    production=json.loads(source.read_text());minimum=cfg.get('minimum_sources',300)
    if production.get('schema')!='parallel_pickplace_production/1' or not production.get('ready') or production['source_pairs']<minimum:
        raise ValueError('production_300_pairs_not_ready')
    frozen=run/'frozen_simulation.json';parents=json.loads(Path(cfg['parent_split_registry']).read_text())
    freeze_pairs([r['manifest'] for r in production['pairs']],frozen,parents,minimum_sources=minimum)
    sim=run/'simulation_cache'
    if not (sim/'manifest.json').exists():materialize_parallel_cache(frozen,sim)
    else:
        verify_frozen(frozen)
        from r1pro_teleop.vla.real_sim_data import sha
        for name,h in json.loads((sim/'integrity.json').read_text()).items():
            if sha(sim/name)!=h:raise ValueError('existing_cache_changed')
    inputs=dict(real_cache_root=cfg['real_cache_root'],sim_cache=str(sim),frozen_manifest=str(frozen),
        parent_checkpoint=cfg['parent_checkpoint'],parent_status=cfg['parent_status'],
        training_steps=cfg.get('training_steps',10000),minimum_sources=minimum,reward_enabled=False,
        method='duration_weighted_sampling_BC',base_observation='relative_to_episode_initial_feedback',
        base_action='static_zero_hold',arm_units='rad',gripper_units='m',fps=20)
    if (run/'inputs.json').exists() and json.loads((run/'inputs.json').read_text())!=inputs:
        raise ValueError('frozen_training_inputs_changed')
    atomic(run/'inputs.json',inputs)


def supervise(cfg_path):
    import fcntl
    cfg=json.loads(cfg_path.read_text());run=Path(cfg['run']);run.mkdir(parents=True,exist_ok=True)
    lock=(run/'supervisor.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    code=Path(cfg['code']);python=cfg['python'];state=dict(pid=os.getpid(),training_started=False)
    def status(**kw):state.update(kw,heartbeat_unix=time.time());atomic(run/'pipeline_status.json',state)
    source=Path(cfg['production_manifest'])
    while True:
        p=json.loads(source.read_text()) if source.exists() else {}
        if p.get('ready') and p.get('source_pairs',0)>=cfg.get('minimum_sources',300):break
        progress=Path(cfg.get('production_status',str(source.parent.parent/'production_status.json')))
        production=json.loads(progress.read_text()) if progress.exists() else {}
        blocked=str(production.get('stage','')).startswith(('blocked','failed'))
        status(stage='blocked_by_data_generation' if blocked else 'waiting_for_data',
               complete_source_pairs=production.get('qualified_pairs',p.get('source_pairs',0)),
               last_error=production.get('last_error') if blocked else None,
               production_status=production);time.sleep(10)
    stages=[('prepare_data',[python,str(code/'scripts/supervise_parallel_real_mix.py'),'--config',str(cfg_path),'--mode','prepare-data']),
            ('prepare_training',[python,str(code/'scripts/train_pi05_parallel_real_mix.py'),'--run',str(run),'--mode','prepare']),
            ('cpu_transform_check',[python,str(code/'scripts/check_parallel_mix_cpu.py'),'--run',str(run)])]
    for step in sorted(set([10,100,1000,10000,cfg.get('training_steps',10000)])):
        if step<=cfg.get('training_steps',10000):
            stages.append((f'train_{step}',[python,str(code/'scripts/train_pi05_parallel_real_mix.py'),'--run',str(run),'--mode','train','--stop',str(step)]))
    stages.append(('real_test_mse',[python,str(code/'scripts/train_pi05_parallel_real_mix.py'),'--run',str(run),'--mode','evaluate']))
    try:
        for stage,argv in stages:
            status(stage=stage)
            for attempt in range(3):
                stem=run/f'{stage}_attempt_{attempt}';job=stem.with_suffix('.job.json');exit_path=stem.with_suffix('.exit.json');launch=stem.with_suffix('.launch.json')
                if not job.exists():
                    atomic(job,dict(argv=argv,cwd=cfg['project'],log=str(stem.with_suffix('.log')),launch=str(launch),receipt=str(exit_path),environment=cfg.get('environment',{})))
                    subprocess.Popen([python,str(code/'scripts/isaacsim_stage_runner.py'),'--job',str(job)],cwd=cfg['project'],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
                while not exit_path.exists():
                    training=run/'training_status.json';t=json.loads(training.read_text()) if training.exists() else {}
                    child=json.loads(launch.read_text()) if launch.exists() else None
                    runner=job.with_suffix('.runner.json')
                    if child and not checked(child) and not (runner.exists() and checked(json.loads(runner.read_text()))):
                        raise RuntimeError('stage_disappeared_without_actual_wait')
                    status(stage=stage,attempt=attempt,child=child,training_started=t.get('training_started',False),actual_completed_updates=t.get('actual_completed_updates',0));time.sleep(5)
                receipt=json.loads(exit_path.read_text())
                if receipt.get('actual_child_wait') is True and receipt['returncode']==0:break
                if not stage.startswith('train_') or attempt==2:raise RuntimeError('stage_failed:'+stage)
                time.sleep(5*(attempt+1))
            if stage.startswith('train_'):
                step=int(stage.split('_')[1]);checkpoint=json.loads((run/f'checkpoint_{step:06d}.json').read_text())
                if not checkpoint.get('checkpoint_saved') or checkpoint.get('checkpoint_updates')!=step:
                    raise ValueError('milestone_checkpoint_not_closed')
                if not (Path(checkpoint['checkpoint'])/'params').exists():raise ValueError('checkpoint_params_missing')
        report=json.loads((run/'mse_parallel_real50_duration_bc.json').read_text())
        if not report.get('real_test_episode_holdout') or not report.get('base_channels_excluded'):
            raise ValueError('real_test_mse_report_not_closed')
        status(stage='training_and_real_test_mse_complete_native_model_rollout_pending',child=None,
               mse_report=str(run/'mse_parallel_real50_duration_bc.json'))
    except Exception as exc:
        status(stage='failed',last_error=repr(exc));raise


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--config',type=Path,required=True);p.add_argument('--mode',choices=['supervise','prepare-data'],default='supervise');a=p.parse_args()
    if a.mode=='prepare-data':prepare_data(json.loads(a.config.read_text()))
    else:supervise(a.config.resolve())
