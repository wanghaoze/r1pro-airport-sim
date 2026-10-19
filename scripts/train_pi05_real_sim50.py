"""Independent 50/50 BC release; reuses immutable validated real/sim caches."""
import argparse,dataclasses,functools,importlib.util,json,os,subprocess,sys,time,traceback
from pathlib import Path
import numpy as np

CODE=Path(__file__).resolve().parents[1]
ROOT=Path('/home/michelle/haoze/r1pro-airport-sim')
sys.path[:0]=[str(CODE),str(ROOT/'third_party/openpi/src'),str(ROOT/'third_party/openpi/packages/openpi-client/src')]
from r1pro_teleop.vla.real_sim_data import Cache,write,sha,CAMERAS
SOURCE=ROOT/'runs/real_sim_pickplace_20261009_v3'


def schedule(real_tasks,sim_tasks,steps=10000,batch=8,seed=42):
    if batch%2:raise ValueError('Even batch required for exact per-batch 50/50')
    rng=np.random.default_rng(seed)
    domains=np.tile([0]*(batch//2)+[1]*(batch//2),(steps,1)).astype(np.int8)
    for row in domains:rng.shuffle(row)
    flat=domains.ravel();indices=np.empty(flat.size,np.int64)
    for domain,tasks in [(0,real_tasks),(1,sim_tasks)]:
        positions=np.flatnonzero(flat==domain);classes=np.array(sorted(set(map(int,tasks))))
        labels=np.resize(classes,len(positions));rng.shuffle(labels)
        for task in classes:
            selected=positions[labels==task];indices[selected]=rng.choice(np.flatnonzero(tasks==task),len(selected))
    return domains,indices.reshape(steps,batch)


def bridge():
    spec=importlib.util.spec_from_file_location('mix_base',CODE/'scripts/run_real_sim_pickplace.py')
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


def prepare(run):
    if (run/'preparation_status.json').exists():verify(run);return
    native_path=run/'isaac_inputs.json'
    native=json.loads(native_path.read_text()) if native_path.exists() else None
    native_counts=None
    if native is not None:
        if native.get('engine')!='isaacsim' or native.get('physics_backend')!='physx':
            raise ValueError('Native Isaac cache binding required')
        native_root=Path(native['cache_root']).resolve()
        integrity=json.loads((native_root/'integrity.json').read_text())
        for split in ['train','val','test']:
            manifest_path=native_root/split/'manifest.json'
            meta=json.loads(manifest_path.read_text())
            if (meta.get('schema')!='airport_isaac_training_cache/1' or meta.get('engine')!='isaacsim'
                or meta.get('physics_backend')!='physx' or meta.get('split')!=split or meta.get('ready') is not True):
                raise ValueError('All native cache splits must close before mixed training')
            if sha(Path(meta['source_manifest']))!=meta['source_manifest_sha256']:
                raise ValueError('Frozen native source manifest changed')
            for file,h in integrity[split].items():
                if sha(native_root/split/file)!=h:raise ValueError('Frozen native cache changed')
        native_counts=json.loads((native_root/'train/manifest.json').read_text())
        clips_path=Path(native['action_clips_manifest']).resolve()
        clips=json.loads(clips_path.read_text())
        if (clips.get('schema')!='airport_isaac_action_clips/1' or clips.get('ready') is not True
            or clips.get('source_manifest_sha256')!=native_counts['source_manifest_sha256']):
            raise ValueError('Native three-action video clips must close before training')
        clip_inputs={str(clips_path):sha(clips_path)}
        for row in clips['segments']:
            for key in ['trajectory','instruction']:
                file=Path(row['trajectory'] if key=='trajectory' else row['instruction_path'])
                expected=row[key+'_sha256']
                if sha(file)!=expected:raise ValueError('Native action clip artifact changed')
                clip_inputs[str(file.resolve())]=expected
            for video in row['videos'].values():
                file=Path(video['path'])
                if sha(file)!=video['sha256']:raise ValueError('Native action clip video changed')
                clip_inputs[str(file.resolve())]=video['sha256']
    (run/'cache').mkdir(exist_ok=True);inputs={};counts={}
    for split in ['train','val','test','simulation']:
        source=(native_root/'train') if native is not None and split=='simulation' else SOURCE/'cache'/split
        if not (run/'cache'/split).exists():(run/'cache'/split).symlink_to(source.resolve(),target_is_directory=True)
        cache=Cache(source);assert cache.manifest['ready'] and len(cache.state)==cache.manifest['frames']
        expected='train' if split=='simulation' else split
        assert all(e['split']==expected for e in cache.manifest['episodes'])
        assert cache.action.shape==cache.state.shape==(len(cache.task),19)
        assert np.isfinite(cache.state).all() and np.isfinite(cache.action).all()
        for key in ['manifest.json','state.npy','action.npy','task.npy','end.npy']:
            p=source/key;inputs[str(p.resolve())]=sha(p)
        counts[split]=dict(episodes=len(cache.manifest['episodes']),frames=len(cache.state))
    if native is None:
        (run/'frozen_data_selection.json').write_bytes((SOURCE/'frozen_data_selection.json').read_bytes())
    else:
        real_selection=json.loads((SOURCE/'frozen_data_selection.json').read_text())
        # Keep historical real selection as provenance, not as a second simulator source.
        write(run/'frozen_data_selection.json',dict(real_source_selection=real_selection,
            simulation_engine='isaacsim',simulation_cache=str(native_root/'train'),
            native_frozen_manifest=native_counts['source_manifest'],
            native_frozen_manifest_sha256=native_counts['source_manifest_sha256'],
            legacy_simulation_cache_not_used=True))
        inputs[str(native_path.resolve())]=sha(native_path)
        inputs.update(clip_inputs)
        for split in ['train','val','test']:
            for file,h in integrity[split].items():inputs[str(native_root/split/file)]=h
    real=Cache(run/'cache/train');sim=Cache(run/'cache/simulation')
    domains,indices=schedule(real.task,sim.task)
    np.save(run/'cache/sample_domains.npy',domains);np.save(run/'cache/sample_indices.npy',indices)
    stats={}
    for key,out in [('state','state'),('action','actions')]:
        values=np.empty((domains.size,19),np.float32)
        for domain,cache in [(0,real),(1,sim)]:
            mask=domains.ravel()==domain;values[mask]=getattr(cache,key)[indices.ravel()[mask]]
        stats[out]=dict(mean=values.mean(axis=0).tolist(),std=values.std(axis=0).tolist(),q01=np.quantile(values,.01,axis=0).tolist(),q99=np.quantile(values,.99,axis=0).tolist())
    write(run/'cache/norm.json',stats)
    for p in [run/'frozen_data_selection.json',run/'cache/sample_domains.npy',run/'cache/sample_indices.npy',run/'cache/norm.json']:inputs[str(p)]=sha(p)
    write(run/'integrity.json',dict(files=inputs))
    write(run/'normalization_provenance.json',dict(train_only=True,real_fraction=.5,sim_fraction=.5,real_draws=int((domains==0).sum()),sim_draws=int((domains==1).sum()),every_batch_real4_sim4=True,validation_or_test_used=False,selection_sha256=sha(run/'frozen_data_selection.json')))
    write(run/'preparation_status.json',dict(stage='ready',counts=counts,training_started=False,
        simulation_engine='isaacsim' if native else 'mujoco',
        sim_complete_sources=native_counts['full_source_count'] if native else 10,
        sim_action_clips=native_counts['action_segment_count'] if native else 30,
        real_training_episodes=counts['train']['episodes']))


def verify(run):
    for p,h in json.loads((run/'integrity.json').read_text())['files'].items():
        if sha(p)!=h:raise ValueError('Frozen input changed: '+p)


def config_for(run):
    from flax import nnx
    from r1pro_teleop.vla.training import build_openpi_config
    from r1pro_teleop.vla.training_accelerated import vision_parameter_filter
    # Same weights-only parent as historical 90/10 experiment, new optimizer.
    base=bridge();_,spec=base.mixed_config(run)
    manifest=run/'training_input/airport_training_manifest.json';d=json.loads(manifest.read_text());d.update(real_fraction=.5,simulation_fraction=.5);write(manifest,d)
    native=(run/'isaac_inputs.json').exists()
    spec=dataclasses.replace(spec,name='pi05_real_isaac50' if native else 'pi05_real_sim50',
        dataset_repo_id='airport/real_isaac50_20261015' if native else 'airport/real_sim50_20261015')
    if native:
        d.update(simulation_engine='isaacsim',physics_backend='physx');write(manifest,d)
    cfg=build_openpi_config(spec)
    return dataclasses.replace(cfg,freeze_filter=nnx.Any(cfg.freeze_filter,vision_parameter_filter),policy_metadata=dict(robot='r1pro',source='real_world_plus_simulation',method='BC_LoRA',fps=20,real_fraction=.5,sim_fraction=.5,prompt_mode='legacy',action_semantics='absolute_mobile19')),spec


def train(run):
    import jax
    from openpi import transforms
    from openpi.shared import normalize
    from openpi.training import checkpoints,sharding
    from openpi.models import model
    from r1pro_teleop.vla.training import AirportInputs,_load_script
    verify(run);cfg,spec=config_for(run)
    real=Cache(run/'cache/train');sim=Cache(run/'cache/simulation');domains=np.load(run/'cache/sample_domains.npy');indices=np.load(run/'cache/sample_indices.npy')
    stats=json.loads((run/'cache/norm.json').read_text());norm={k:normalize.NormStats(**{f:np.asarray(v) for f,v in row.items()}) for k,row in stats.items()};normalize.save(cfg.assets_dirs/spec.dataset_repo_id,norm)
    data=cfg.data.create(cfg.assets_dirs,cfg.model);transform=transforms.compose([AirportInputs('legacy'),transforms.Normalize(norm,use_quantiles=True),*data.model_transforms.inputs])
    if jax.device_count()!=1:raise ValueError('One reserved GPU required')
    mesh=sharding.make_mesh(1);rep=jax.sharding.NamedSharding(mesh,jax.sharding.PartitionSpec());ds=jax.sharding.NamedSharding(mesh,jax.sharding.PartitionSpec(sharding.DATA_AXIS));official=_load_script(ROOT/'third_party/openpi','train.py');rng,init=jax.random.split(jax.random.key(42))
    class Loader:
        def data_config(self):return data
    manager,resuming=checkpoints.initialize_checkpoint_dir(cfg.checkpoint_dir,keep_period=1000,overwrite=False,resume=cfg.checkpoint_dir.exists())
    status=dict(stage='initializing',training_started=False,updates=0,target_updates=10000,pid=os.getpid(),method='BC_LoRA',source='real_world_plus_simulation',real_sampling_fraction=.5,sim_sampling_fraction=.5,spec=dataclasses.asdict(spec),parent_weights_only_new_optimizer=not resuming,resuming=resuming)
    write(run/'pi05/training_status.json',status);state,shards=official.init_train_state(cfg,init,mesh,resume=resuming)
    if resuming:state=checkpoints.restore_state(manager,state,Loader())
    update=jax.jit(functools.partial(official.train_step,cfg),in_shardings=(rep,shards,ds),out_shardings=(shards,rep),donate_argnums=(1,));started=time.monotonic();ema=None
    for step in range(int(state.step),10000):
        tick=time.monotonic();samples=[(real if d==0 else sim).get(int(i)) for d,i in zip(domains[step],indices[step])];host=jax.tree.map(lambda *a:np.stack(a),*[transform(s) for s in samples]);batch=jax.device_put((model.Observation.from_dict(host),host['actions']),ds)
        with sharding.set_mesh(mesh):state,info=update(rng,state,batch)
        metrics={k:float(v) for k,v in jax.device_get(info).items()}
        if not all(np.isfinite(v) for v in metrics.values()):raise ValueError('Nonfinite training metrics')
        elapsed=time.monotonic()-tick;ema=elapsed if ema is None else .1*elapsed+.9*ema
        status.update(stage='training',training_started=True,updates=step+1,metrics=metrics,heartbeat_unix=time.time(),elapsed_seconds=time.monotonic()-started,seconds_per_update_ema=ema,eta_seconds=(9999-step)*ema,eta_scope='remaining_training_only')
        write(run/'pi05/training_status.json',status)
        if (step+1)%1000==0:
            checkpoints.save_state(manager,state,Loader(),step);manager.wait_until_finished();write(run/'pi05'/f'checkpoint_{step+1:06d}.json',dict(status,checkpoint=str(cfg.checkpoint_dir/str(step))))
    manager.close();write(run/'pi05/training_status.json',dict(status,stage='trained',checkpoint=str(cfg.checkpoint_dir/'9999')))


def supervise(run):
    import fcntl
    lock=(run/'pipeline.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    env=dict(os.environ,CUDA_VISIBLE_DEVICES='0',XLA_PYTHON_CLIENT_MEM_FRACTION='.85',OMP_NUM_THREADS='2',OPENBLAS_NUM_THREADS='2',MKL_NUM_THREADS='2',WANDB_MODE='disabled',TOKENIZERS_PARALLELISM='false',PYTHONUNBUFFERED='1')
    status=dict(stage='starting',pid=os.getpid(),training_started=False)
    try:
        for mode in ['prepare','train','evaluate']:
            status.update(stage=mode)
            for attempt in range(3):
                log=run/'logs'/f'{mode}_{attempt:02d}.log';log.parent.mkdir(exist_ok=True)
                with log.open('x') as f:child=subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'--run',str(run),'--mode',mode],cwd=CODE,env=env,stdin=subprocess.DEVNULL,stdout=f,stderr=f,start_new_session=True)
                write(log.with_suffix('.launch.json'),dict(pid=child.pid,start_ticks=Path(f'/proc/{child.pid}/stat').read_text().rsplit(')',1)[1].split()[19],argv=[sys.executable,str(Path(__file__).resolve()),'--run',str(run),'--mode',mode],cwd=str(CODE)))
                while child.poll() is None:
                    p=run/'pi05/training_status.json';t=json.loads(p.read_text()) if p.exists() else {};status.update(active_pid=child.pid,attempt=attempt,heartbeat_unix=time.time(),training_started=t.get('training_started',False),updates=t.get('updates',0));write(run/'pipeline_status.json',status);time.sleep(5)
                code=child.wait();write(log.with_suffix('.exit.json'),dict(returncode=code,actual_child_wait=True))
                if code==0:break
                if mode!='train' or attempt==2:raise RuntimeError(f'{mode} failed, exit {code}; see {log}')
                time.sleep(5*(attempt+1))
        write(run/'pipeline_status.json',dict(status,stage='complete',active_pid=None))
    except BaseException as e:write(run/'pipeline_status.json',dict(status,stage='failed',error=repr(e),heartbeat_unix=time.time()));raise


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);p.add_argument('--mode',choices=['prepare','train','evaluate','supervise'],required=True);a=p.parse_args()
    if a.mode=='evaluate':
        verify(a.run);base=bridge();base.mixed_config=config_for;base.mse(a.run,'mixed_pi05')
    else:globals()[a.mode](a.run)
