"""BC on frozen, qualified native three-tray sources; no policy execution here."""
import argparse
import dataclasses
import functools
import json
import os
from pathlib import Path
import sys
import time
os.environ['XLA_PYTHON_CLIENT_PREALLOCATE']='false'
os.environ.setdefault('OMP_NUM_THREADS','2')
os.environ.setdefault('OPENBLAS_NUM_THREADS','2')
os.environ.setdefault('WANDB_MODE','disabled')
import numpy as np

CODE=Path(__file__).resolve().parents[1]
ROOT=Path(os.environ.get('AIRPORT_PROJECT','/home/michelle/haoze/r1pro-airport-sim'))
sys.path[:0]=[str(CODE),str(ROOT/'third_party/openpi/src'),str(ROOT/'third_party/openpi/packages/openpi-client/src')]
from r1pro_teleop.vla.real_sim_data import Cache,CAMERAS,write,sha


def config_for(run):
    from r1pro_teleop.vla.training import TrainingSpec,build_openpi_config
    from r1pro_teleop.vla.training_accelerated import vision_parameter_filter
    from flax import nnx
    inputs=json.loads((run/'inputs.json').read_text())
    spec=TrainingSpec(dataset_root=str(run/'training_input'),dataset_repo_id='airport/isaac_three_tray_action3',
        openpi_root=str(ROOT/'third_party/openpi'),base_params=str(Path(inputs['parent_checkpoint'])/'params'),
        run_dir=str(run/'pi05'),name='pi05_isaac_three_tray',num_train_steps=100000,batch_size=8,
        save_interval=1000,action_horizon=20,num_workers=0,seed=42,lr_warmup_steps=500,prompt_mode='legacy')
    cfg=build_openpi_config(spec)
    return dataclasses.replace(cfg,freeze_filter=nnx.Any(cfg.freeze_filter,vision_parameter_filter),
        policy_metadata=dict(engine='isaacsim',source='simulation/program_generated',method='BC_LoRA',
        fps=20,action_semantics='absolute_mobile19',teacher_fallback=False)),spec


def prepare(run):
    from r1pro_teleop.vla.isaac_dataset import load_frozen
    inputs=json.loads((run/'inputs.json').read_text());registry=json.loads(Path(inputs['registry']).read_text())
    corpus=load_frozen(inputs['manifest'],registry)
    caches={s:Cache(Path(inputs['cache'])/s) for s in ('train','val','test')}
    for s,c in caches.items():
        if c.manifest.get('source_manifest_sha256')!=sha(inputs['manifest']) or set(map(int,c.task))!={0,1,2}:
            raise ValueError('native_cache_identity_or_three_actions_missing:'+s)
        if not np.isfinite(c.state).all() or not np.isfinite(c.action).all():raise ValueError('nonfinite_native_cache')
    if not (Path(inputs['parent_checkpoint'])/'params/manifest.ocdbt').exists():raise ValueError('parent_weights_missing')
    import importlib.util
    module_spec=importlib.util.spec_from_file_location('verify_native_parent',CODE/'scripts/serve_pi05_airport.py')
    verifier=importlib.util.module_from_spec(module_spec);module_spec.loader.exec_module(verifier)
    verifier.verify_training_checkpoint(inputs['parent_status'])
    parent=json.loads(Path(inputs['parent_status']).read_text())
    if Path(parent['checkpoint']).resolve()!=Path(inputs['parent_checkpoint']).resolve():raise ValueError('verified_parent_identity_mismatch')
    cache=caches['train'];rng=np.random.default_rng(42);pools=[np.flatnonzero(cache.task==i) for i in range(3)]
    schedule=np.asarray([rng.choice(pools[int(rng.integers(3))]) for _ in range(100000*8)],np.int64).reshape(100000,8)
    np.save(run/'sample_indices.npy',schedule)
    norm={}
    for key in ('state','action'):
        # Only training frames contribute normalization, never val/test.
        a=getattr(cache,key)
        norm['actions' if key=='action' else key]=dict(mean=a.mean(0).tolist(),std=a.std(0).tolist(),
            q01=np.quantile(a,.01,axis=0).tolist(),q99=np.quantile(a,.99,axis=0).tolist())
    write(run/'norm.json',norm)
    features={k:dict(shape=[19],dtype='float32') for k in ['observation.state','action']}
    features.update({'observation.images.'+c:dict(shape=[224,224,3],dtype='uint8') for c in CAMERAS})
    write(run/'training_input/meta/info.json',dict(format='project_verified_numpy_cache/1',fps=20,total_frames=len(cache.state),features=features))
    write(run/'training_input/airport_training_manifest.json',dict(split='train',episodes=cache.manifest['episodes'],
        action_semantics='absolute_mobile19',state_semantics='measured_joint16_plus_base_origin_offset3',fps=20))
    files=[run/'inputs.json',Path(inputs['manifest']),Path(inputs['parent_status']),run/'norm.json',run/'sample_indices.npy']
    files += list((run/'training_input').rglob('*.json'))
    for c in caches.values():files+=list(c.path.glob('*.npy'))+[c.path/'manifest.json']
    write(run/'integrity.json',dict(files={str(p):sha(p) for p in files}))
    write(run/'preparation_status.json',dict(stage='ready',training_started=False,
        full_sources=corpus['full_sources'],action_segments=corpus['action_segments'],counts=corpus['counts']))


def train(run,stop):
    import faulthandler
    diagnostic=(run/'initialization_stacks.log').open('a')
    faulthandler.enable(file=diagnostic)
    faulthandler.dump_traceback_later(60,repeat=True,file=diagnostic)
    import jax
    from r1pro_teleop.vla.training import AirportInputs,_load_script
    from r1pro_teleop.vla.training_accelerated import project_checkpoint_manager
    from openpi import transforms
    from openpi.shared import normalize
    from openpi.training import checkpoints,sharding
    from openpi.models import model
    for p,h in json.loads((run/'integrity.json').read_text())['files'].items():
        if sha(p)!=h:raise ValueError('frozen_native_data_changed:'+p)
    cfg,spec=config_for(run);inputs=json.loads((run/'inputs.json').read_text());cache=Cache(Path(inputs['cache'])/'train')
    if jax.device_count()!=2:raise ValueError('two_visible_training_devices_required')
    norm={k:normalize.NormStats(**{f:np.asarray(v) for f,v in row.items()}) for k,row in json.loads((run/'norm.json').read_text()).items()}
    normalize.save(cfg.assets_dirs/spec.dataset_repo_id,norm);data=cfg.data.create(cfg.assets_dirs,cfg.model)
    transform=transforms.compose([AirportInputs('legacy'),transforms.Normalize(norm,use_quantiles=True),*data.model_transforms.inputs])
    mesh=sharding.make_mesh(1);rep=jax.sharding.NamedSharding(mesh,jax.sharding.PartitionSpec());ds=jax.sharding.NamedSharding(mesh,jax.sharding.PartitionSpec(sharding.DATA_AXIS))
    official=_load_script(ROOT/'third_party/openpi','train.py');rng,init=jax.random.split(jax.random.key(42))
    class Loader:
        def data_config(self):return data
    resume=any(cfg.checkpoint_dir.rglob('train_state')) if cfg.checkpoint_dir.exists() else False
    manager,resuming=project_checkpoint_manager(cfg,checkpoints,resume=resume)
    status=dict(stage='initializing',training_started=False,actual_completed_updates=0,target_updates=100000,
        pid=os.getpid(),spec=dataclasses.asdict(spec),method='BC_LoRA',engine='isaacsim',
        initialization='own_optimizer_resume' if resume else 'verified_parent_weights_new_optimizer',
        precision=dict(compute='bfloat16',trainable_optimizer='float32',rgb='uint8',numeric='float32'),
        actual_devices=list(map(str,jax.devices())),freeze_visual_encoder=True,
        communication_transport={k:os.environ.get(k) for k in ('NCCL_P2P_DISABLE','NCCL_SHM_DISABLE','NCCL_NET','NCCL_CUMEM_HOST_ENABLE','XLA_FLAGS')})
    write(run/'training_status.json',status)
    from r1pro_teleop.vla.training_preview import host_replicated_key
    status['rng_verification_receipts']=[]
    persist=lambda:write(run/'training_status.json',status)
    def phase(name):
        status.update(initialization_phase=name,heartbeat_unix=time.time())
        persist()
        print('TRAIN_PHASE',name,flush=True)
    rng=host_replicated_key(jax,rng,rep,status['rng_verification_receipts'],persist)
    init=host_replicated_key(jax,init,rep,status['rng_verification_receipts'],persist)
    phase('init_train_state')
    original_load=official._load_weights_and_validate
    def observed_load(*args,**kwargs):
        phase('load_and_validate_parent_weights')
        result=original_load(*args,**kwargs)
        phase('parent_loaded_initialization_jit')
        return result
    official._load_weights_and_validate=observed_load
    try:state,state_sharding=official.init_train_state(cfg,init,mesh,resume=resuming)
    finally:official._load_weights_and_validate=original_load
    phase('block_until_initialized_state_ready')
    jax.block_until_ready(state)
    phase('initialized_state_ready')
    if resuming:state=checkpoints.restore_state(manager,state,Loader())
    update=jax.jit(functools.partial(official.train_step,cfg),in_shardings=(rep,state_sharding,ds),out_shardings=(state_sharding,rep),donate_argnums=(1,))
    schedule=np.load(run/'sample_indices.npy',mmap_mode='r');ema=None
    for step in range(int(state.step),stop):
        phase('prepare_batch_'+str(step))
        tick=time.monotonic();samples=[transform(cache.get(int(i))) for i in schedule[step]]
        host=jax.tree.map(lambda *a:np.stack(a),*samples);batch=jax.device_put((model.Observation.from_dict(host),host['actions']),ds)
        phase('gradient_dispatch_'+str(step))
        with sharding.set_mesh(mesh):state,info=update(rng,state,batch)
        jax.block_until_ready((state,info))
        phase('gradient_metrics_wait_'+str(step))
        metrics={k:float(v) for k,v in jax.device_get(info).items()}
        if not all(np.isfinite(v) for v in metrics.values()):raise ValueError('nonfinite_gradient_update')
        if metrics.get('param_norm',0.)<=0:raise ValueError('invalid_zero_model_parameter_norm_no_verified_update')
        seconds=time.monotonic()-tick;ema=seconds if ema is None else .1*seconds+.9*ema
        status.update(stage='training',training_started=True,actual_completed_updates=step+1,metrics=metrics,
            heartbeat_unix=time.time(),eta_seconds=(stop-step-1)*ema,eta_scope='active_training_to_milestone_only')
        write(run/'training_status.json',status)
        if step==0:faulthandler.cancel_dump_traceback_later()
        if (step+1)%1000==0 or step+1==stop:
            checkpoints.save_state(manager,state,Loader(),step);manager.wait_until_finished()
            status.update(checkpoint=str(cfg.checkpoint_dir/str(step)),checkpoint_updates=step+1,checkpoint_saved=True)
            write(run/f'checkpoint_{step+1:06d}.json',status)
    manager.close();write(run/'training_status.json',dict(status,stage='milestone_checkpoint'))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);p.add_argument('--mode',choices=['prepare','train'],required=True)
    p.add_argument('--stop',type=int,choices=[10,100,1000,10000,100000],default=10);a=p.parse_args()
    prepare(a.run) if a.mode=='prepare' else train(a.run,a.stop)
