"""Two-action configurable real/Isaac BC; no time reward or RL is enabled."""
import argparse,dataclasses,functools,importlib.util,json,os,sys,time
from pathlib import Path
import numpy as np
CODE=Path(__file__).resolve().parents[1]
ROOT=Path(os.environ.get('AIRPORT_PROJECT','/home/michelle/haoze/r1pro-airport-sim'))
sys.path[:0]=[str(CODE),str(ROOT/'third_party/openpi/src'),str(ROOT/'third_party/openpi/packages/openpi-client/src')]
from resume_isaacsim_bc_after_video import verified_legacy_gpu_runtime
os.environ.update(verified_legacy_gpu_runtime())
os.environ.setdefault('CUDA_VISIBLE_DEVICES','0,1')
os.environ['XLA_PYTHON_CLIENT_PREALLOCATE']='false'
os.environ.setdefault('OMP_NUM_THREADS','2')
os.environ.setdefault('OPENBLAS_NUM_THREADS','2')
os.environ.setdefault('WANDB_MODE','disabled')
from r1pro_teleop.vla.real_sim_data import Cache,CAMERAS,write,sha
from r1pro_teleop.vla.parallel_pickplace_training import verify_frozen,balanced_mixed_schedule,duration_sampling_weights


class EmptySimulation:
    state=np.empty((0,19),np.float32);action=state;task=np.empty(0,np.int64)
    manifest=dict(episodes=[],complete_source_pairs=0,action_segments=0)


class MixedCache:
    def __init__(self,run):
        inputs=json.loads((run/'inputs.json').read_text())
        self.real=Cache(Path(inputs['real_cache_root'])/'train');self.sim=Cache(inputs['sim_cache']) if inputs.get('sim_cache') else EmptySimulation()
    def get(self,index):
        return self.real.get(index) if index<len(self.real.state) else self.sim.get(index-len(self.real.state))


def verify(run):
    for file,h in json.loads((run/'integrity.json').read_text())['files'].items():
        if sha(file)!=h:raise ValueError('frozen_mixed_input_changed:'+file)


def prepare(run):
    if (run/'preparation_status.json').exists():verify(run);return
    inputs=json.loads((run/'inputs.json').read_text())
    if inputs.get('reward_enabled',False):raise ValueError('reward_method_not_implemented_or_approved')
    fraction=float(inputs.get('real_fraction',.5))
    if not np.isfinite(fraction) or not 0<=fraction<=1:raise ValueError('invalid_real_fraction')
    frozen=verify_frozen(inputs['frozen_manifest']) if fraction<1 else None
    if frozen and frozen['complete_source_pairs']<inputs.get('minimum_sources',1):raise ValueError('insufficient_complete_sources')
    real={s:Cache(Path(inputs['real_cache_root'])/s) for s in ('train','val','test')};sim=Cache(inputs['sim_cache']) if fraction<1 else EmptySimulation()
    if fraction<1 and (sim.manifest.get('schema')!='parallel_pickplace_bc_cache/1' or sim.manifest.get('source_manifest_sha256')!=sha(inputs['frozen_manifest'])):raise ValueError('parallel_cache_binding_invalid')
    seen=set();files=[run/'inputs.json',Path(inputs['parent_status'])]+([Path(inputs['frozen_manifest'])] if fraction<1 else [])
    for split,cache in real.items():
        if cache.manifest.get('source_domains')!=['real'] or not cache.manifest.get('ready'):raise ValueError('original_real_cache_required')
        if any(e['split']!=split for e in cache.manifest['episodes']):raise ValueError('real_split_changed')
        keys={(e['dataset'],e['raw_file_name']) for e in cache.manifest['episodes']}
        if keys:
            if seen.intersection(keys):raise ValueError('real_episode_split_leak')
            seen.update(keys)
    if fraction<1 and (sim.manifest['split']!='train' or any(e['split']!='train' for e in sim.manifest['episodes'])):raise ValueError('simulation_holdout_leak')
    for cache in [*real.values()]+([sim] if fraction<1 else []):
        if cache.state.shape!=cache.action.shape or cache.state.shape[1]!=19:raise ValueError('mobile19_cache_required')
        if not np.isfinite(cache.state).all() or not np.isfinite(cache.action).all():raise ValueError('nonfinite_cache')
        files+=list(cache.path.glob('*.npy'))+[cache.path/'manifest.json']
    parent=json.loads(Path(inputs['parent_status']).read_text())
    if Path(parent['checkpoint']).resolve()!=Path(inputs['parent_checkpoint']).resolve():raise ValueError('parent_checkpoint_identity_mismatch')
    p=Path(inputs['parent_checkpoint'])/'params'
    if not (p/'manifest.ocdbt').exists():raise ValueError('parent_weights_not_saved')
    # Comparison trainer has its own recorded status schema, not airport serve's.
    parent_spec=parent.get('spec',{})
    expected=Path(parent_spec['run_dir'])/'checkpoints'/parent_spec['name']/'training'/str(parent['updates']-1)
    if (parent.get('stage')!='trained' or parent.get('model')!='pi05' or parent.get('updates')!=10000
            or parent.get('source')!='simulation/program_generated' or expected.resolve()!=p.parent.resolve()
            or not np.isfinite(parent.get('metrics',{}).get('param_norm',np.nan))):
        raise ValueError('comparison_parent_training_evidence_invalid')
    files+=list(q for q in p.rglob('*') if q.is_file())
    steps=inputs.get('training_steps',10000)
    rw,rreport=duration_sampling_weights(real['train'].task,real['train'].manifest['episodes']) if fraction>0 else (None,dict(unused=True))
    sw,sreport=duration_sampling_weights(sim.task,sim.manifest['episodes']) if fraction<1 else (None,dict(unused=True))
    domains,indices=balanced_mixed_schedule(real['train'].task,sim.task,steps=steps,real_weights=rw,sim_weights=sw,real_fraction=fraction)
    write(run/'duration_weighting.json',dict(method='duration_weighted_sampling_BC',not_RL=True,real=rreport,simulation=sreport,requested_real_fraction=fraction,actual_real_fraction=float(np.mean(domains==0)),draw_counts=dict(real=int(np.sum(domains==0)),simulation=int(np.sum(domains==1))),action_balance='cumulative_within_domain',batch_size=8,loss='unchanged_mean_flow_matching_loss_under_weighted_training_sampler'))
    combined=indices+np.where(domains==1,len(real['train'].state),0)
    np.save(run/'sample_domains.npy',domains);np.save(run/'sample_indices.npy',combined)
    norm={}
    for key in ('state','action'):
        values=np.empty((domains.size,19),np.float32)
        for d,cache in ((0,real['train']),(1,sim)):
            selected=domains.ravel()==d;values[selected]=getattr(cache,key)[indices.ravel()[selected]]
        norm['actions' if key=='action' else key]=dict(mean=values.mean(0).tolist(),std=values.std(0).tolist(),q01=np.quantile(values,.01,axis=0).tolist(),q99=np.quantile(values,.99,axis=0).tolist())
    write(run/'norm.json',norm)
    features={k:dict(shape=[19],dtype='float32') for k in ('observation.state','action')}
    features.update({'observation.images.'+c:dict(shape=[224,224,3],dtype='uint8') for c in CAMERAS})
    write(run/'training_input/meta/info.json',dict(format='project_verified_numpy_cache/1',fps=20,total_frames=len(real['train'].state)+len(sim.state),features=features))
    write(run/'training_input/airport_training_manifest.json',dict(split='train',episodes=(real['train'].manifest['episodes'] if fraction>0 else [])+sim.manifest['episodes'],action_semantics='absolute_mobile19',state_semantics='measured_joint16_plus_base_origin_offset3',base_reference='episode_initial_measured_feedback',base_action='static_zero_hold',fps=20,real_fraction=fraction,simulation_fraction=1-fraction,method='duration_weighted_sampling_BC',reward_enabled=False))
    files+=[run/'norm.json',run/'sample_domains.npy',run/'sample_indices.npy',run/'duration_weighting.json']+list((run/'training_input').rglob('*.json'))
    (run/'cache').mkdir(exist_ok=True)
    for split in ('train','val','test'):
        link=run/'cache'/split
        if not link.exists():link.symlink_to(real[split].path.resolve(),target_is_directory=True)
    write(run/'frozen_data_selection.json',dict(simulation_manifest=str(Path(inputs['frozen_manifest']).resolve()) if fraction<1 else None,
        simulation_manifest_sha256=sha(inputs['frozen_manifest']) if fraction<1 else None,real_cache_manifests={s:sha(c.path/'manifest.json') for s,c in real.items()}))
    files.append(run/'frozen_data_selection.json')
    write(run/'integrity.json',dict(files={str(p.resolve()):sha(p) for p in files}))
    write(run/'preparation_status.json',dict(stage='ready',training_started=False,method='duration_weighted_sampling_BC',reward_enabled=False,simulation_complete_pairs=sim.manifest['complete_source_pairs'],simulation_action_segments=sim.manifest['action_segments'],real_episodes={s:len(c.manifest['episodes']) for s,c in real.items()},real_fraction=fraction,simulation_fraction=1-fraction,sim_holdout_created=False,parent_weights_only_new_optimizer=True))


def config_for(run):
    from r1pro_teleop.vla.training import TrainingSpec,build_openpi_config
    from r1pro_teleop.vla.training_accelerated import vision_parameter_filter
    from flax import nnx
    inputs=json.loads((run/'inputs.json').read_text())
    fraction=float(inputs.get('real_fraction',.5))
    target=inputs.get('training_steps',10000)
    spec=TrainingSpec(dataset_root=str(run/'training_input'),dataset_repo_id='airport/parallel_pickplace_real50',openpi_root=str(ROOT/'third_party/openpi'),base_params=str(Path(inputs['parent_checkpoint'])/'params'),run_dir=str(run/'pi05'),name='pi05_parallel_pickplace_real50',num_train_steps=target,batch_size=8,save_interval=1000,action_horizon=20,num_workers=0,seed=42,lr_warmup_steps=min(500,max(0,target//20)),prompt_mode='legacy')
    cfg=build_openpi_config(spec)
    return dataclasses.replace(cfg,freeze_filter=nnx.Any(cfg.freeze_filter,vision_parameter_filter),policy_metadata=dict(source='real_world' if fraction==1 else 'simulation/program_generated' if fraction==0 else 'real_world_plus_isaac',method='duration_weighted_sampling_BC_LoRA',fps=20,real_fraction=fraction,simulation_fraction=1-fraction,action_semantics='absolute_mobile19',base_reference='episode_initial_measured_feedback',base_action='static_zero_hold',reward_enabled=False)),spec


def train(run,stop):
    import fcntl
    lock=(run/'training.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
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
    cfg,spec=config_for(run);inputs=json.loads((run/'inputs.json').read_text());cache=MixedCache(run);fraction=float(inputs.get('real_fraction',.5))
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
    status=dict(stage='initializing',training_started=False,actual_completed_updates=0,target_updates=spec.num_train_steps,
        pid=os.getpid(),spec=dataclasses.asdict(spec),method='duration_weighted_sampling_BC_LoRA',engine='jax_two_gpu',source='real_world/user_provided' if fraction==1 else 'simulation/program_generated' if fraction==0 else 'real_world_plus_isaac',real_fraction=fraction,sim_fraction=1-fraction,reward_enabled=False,
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
            heartbeat_unix=time.time(),eta_seconds=(stop-step-1)*ema,eta_scope='active_training_to_milestone_only',milestone_updates=stop,seconds_per_step=ema,total_gradient_eta_seconds=(spec.num_train_steps-step-1)*ema)
        write(run/'training_status.json',status)
        if step==0:faulthandler.cancel_dump_traceback_later()
        if (step+1)%1000==0 or step+1==stop:
            status.update(stage='saving_checkpoint',heartbeat_unix=time.time());write(run/'training_status.json',status)
            checkpoints.save_state(manager,state,Loader(),step);manager.wait_until_finished()
            status.update(checkpoint=str(cfg.checkpoint_dir/str(step)),checkpoint_updates=step+1,checkpoint_saved=True)
            write(run/f'checkpoint_{step+1:06d}.json',status)
    manager.close();write(run/'training_status.json',dict(status,stage='milestone_checkpoint'))


def evaluate(run):
    verify(run)
    from openpi.policies import policy_config
    cfg,_=config_for(run);status=json.loads((run/'training_status.json').read_text());checkpoint=status['checkpoint']
    model=policy_config.create_trained_policy(cfg,checkpoint)
    spec=importlib.util.spec_from_file_location('offline_mix_mse',CODE/'scripts/run_real_sim_pickplace.py')
    evaluator=importlib.util.module_from_spec(spec);spec.loader.exec_module(evaluator)
    def policy(_run,_name):
        def infer(sample):return np.asarray(model.infer({k:v for k,v in sample.items() if k!='actions'})['actions'])[:,:19]
        return infer,checkpoint
    evaluator.policy=policy
    evaluator.mse(run,'parallel_real50_duration_bc')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);p.add_argument('--mode',choices=['prepare','train','evaluate'],required=True);p.add_argument('--stop',type=int,default=10000);a=p.parse_args()
    if a.mode=='prepare':prepare(a.run)
    elif a.mode=='evaluate':evaluate(a.run)
    else:
        inputs=json.loads((a.run/'inputs.json').read_text())
        if not 1<=a.stop<=inputs.get('training_steps',10000):raise ValueError('invalid_stop')
        train(a.run,a.stop)
