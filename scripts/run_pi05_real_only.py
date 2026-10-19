"""Real-only BC and offline held-out action evaluation; never controls a robot."""
import argparse
import dataclasses
import functools
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback

import numpy as np

CODE = Path(__file__).resolve().parents[1]
ROOT = Path(os.environ.get('AIRPORT_PROJECT', '/home/michelle/haoze/r1pro-airport-sim'))
sys.path[:0] = [str(CODE), str(ROOT/'third_party/openpi/src'), str(ROOT/'third_party/openpi/packages/openpi-client/src')]
from r1pro_teleop.vla.real_sim_data import Cache, CAMERAS, ARMS, GRIPPERS, write, sha

SOURCE = ROOT/'runs/real_sim_pickplace_20261009_v3'
BASE = ROOT/'resources/models/pi05_base'
STEPS = 10000
BATCH = 8


def validate_real_splits(manifests):
    groups = {}
    content = {}
    for split, manifest in manifests.items():
        if manifest.get('ready') is not True or manifest.get('source_domains') != ['real']:
            raise ValueError('only_closed_real_data_allowed')
        rows = manifest['episodes']
        if not rows or {e['task_index'] for e in rows} != {0, 1}:
            raise ValueError('both_real_tasks_required_in_each_split')
        if any(e['domain'] != 'real' or e['split'] != split for e in rows):
            raise ValueError('source_domain_or_split_mismatch')
        groups[split] = {e['raw_file_name'] for e in rows}
        content[split] = {e['parquet_sha256'] for e in rows}
    for a, b in [('train', 'val'), ('train', 'test'), ('val', 'test')]:
        if groups[a] & groups[b] or content[a] & content[b]:
            raise ValueError('recording_or_content_split_leak')


def real_schedule(tasks, steps=STEPS, batch=BATCH):
    rng = np.random.default_rng(42)
    pools = {t: np.flatnonzero(tasks == t) for t in (0, 1)}
    if any(not len(v) for v in pools.values()):
        raise ValueError('missing_real_task')
    return np.asarray([rng.choice(pools[int(rng.integers(2))]) for _ in range(steps*batch)], dtype=np.int64).reshape(steps, batch)


def brightness(images):
    # Exclude only the all-frame constant black letterbox, not dark scene pixels.
    valid = np.any(images > 0, axis=(0, 3))
    gray = images.astype(np.float32) @ np.array([.2126, .7152, .0722], np.float32)
    pixels = gray[:, valid]
    return dict(frames=len(images), sampled_content_pixels=int(pixels.size), mean=float(pixels.mean()),
                std=float(pixels.std()), p05=float(np.quantile(pixels, .05)), p95=float(np.quantile(pixels, .95)),
                dark_fraction=float((pixels < 16).mean()), bright_fraction=float((pixels > 239).mean()),
                black_padding_mask='pixels_black_in_all_sampled_frames_excluded')


def prepare(run):
    if (run/'preparation_status.json').exists():
        if json.loads((run/'preparation_status.json').read_text()).get('stage') == 'ready':
            verify(run)
            return
    caches = {s: Cache(SOURCE/'cache'/s) for s in ('train', 'val', 'test')}
    validate_real_splits({s: c.manifest for s, c in caches.items()})
    selection = dict(source='real_world/user_provided', simulation_frames=0,
                     split_policy='preserved_raw_recording_hash42_80_10_10_no_repartition',
                     real_counts={s: len(c.manifest['episodes']) for s, c in caches.items()},
                     real={s: c.manifest['episodes'] for s, c in caches.items()},
                     base_checkpoint=str(BASE), base_is_project_sim_finetune=False)
    write(run/'frozen_data_selection.json', selection)
    bindings = {}
    audit = {}
    for split, cache in caches.items():
        dest = run/'cache'/split
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not dest.exists(): dest.symlink_to(cache.path.resolve(), target_is_directory=True)
        offset = 0
        for episode in cache.manifest['episodes']:
            n = episode['frames']
            if episode['offset'] != offset or np.any(cache.ends[offset:offset+n] != offset+n):
                raise ValueError('episode_boundary_mismatch')
            if sha(episode['parquet']) != episode['parquet_sha256']:
                raise ValueError('original_numeric_source_changed')
            for video in episode['verified_videos'].values():
                if sha(video['path']) != video['sha256']: raise ValueError('original_video_changed')
            offset += n
        if offset != len(cache.state) or not np.isfinite(cache.state).all() or not np.isfinite(cache.action).all():
            raise ValueError('invalid_real_cache')
        if np.any(cache.action[:,16:] != 0): raise ValueError('moving_base_not_supported')
        for path in sorted(cache.path.glob('*')):
            if path.is_file(): bindings[str(path.resolve())] = sha(path)
        ids = np.linspace(0, len(cache.state)-1, min(128, len(cache.state)), dtype=int)
        audit[split] = dict(frames=len(cache.state), episodes=len(cache.manifest['episodes']),
                           task_counts={str(t): int(sum(e['task_index']==t for e in cache.manifest['episodes'])) for t in (0,1)},
                           brightness={c: brightness(np.asarray(cache.images[c][ids])) for c in CAMERAS},
                           action_min=cache.action.min(0).tolist(), action_max=cache.action.max(0).tolist(),
                           state_min=cache.state.min(0).tolist(), state_max=cache.state.max(0).tolist())
        write(run/'preparation_status.json', dict(stage='validating_real_sources', split=split, training_started=False))
    indices = real_schedule(caches['train'].task)
    np.save(run/'cache/sample_indices.npy', indices)
    stats = {}
    for key in ('state', 'action'):
        a = getattr(caches['train'], key)[indices.reshape(-1)]
        stats['actions' if key == 'action' else key] = dict(mean=a.mean(0).tolist(), std=a.std(0).tolist(),
            q01=np.quantile(a,.01,axis=0).tolist(), q99=np.quantile(a,.99,axis=0).tolist())
    write(run/'cache/norm.json', stats)
    for split, cache in caches.items():
        audit[split]['quantile_outside_fraction'] = {}
        for key, statkey in [('state','state'),('action','actions')]:
            a = getattr(cache,key); lo=np.array(stats[statkey]['q01']); hi=np.array(stats[statkey]['q99'])
            audit[split]['quantile_outside_fraction'][key] = ((a<lo)|(a>hi)).mean(0).tolist()
    # Historical sim data is inspected ONLY for domain-shift diagnosis, never training or norm.
    historical = Cache(SOURCE/'cache/simulation')
    ids=np.linspace(0,len(historical.state)-1,128,dtype=int)
    audit['historical_sim_diagnostic_only'] = dict(used_in_training=False,
        brightness={c:brightness(np.asarray(historical.images[c][ids])) for c in CAMERAS},
        action_min=historical.action.min(0).tolist(),action_max=historical.action.max(0).tolist())
    write(run/'data_audit.json', dict(scope='offline_data_audit_not_causal_proof', splits=audit,
        units=dict(arms='rad',grippers='m_from_user_confirmed_mm',base='static_hold_not_evaluated'),
        fps=20,original_fps=30,action_horizon=20,tail_padding='repeat_final_training_target; excluded_from_eval',
        alignment='same_nearest_timestamp_index_RGB_state_action; sensor_latency_not_established'))
    for path in [run/'frozen_data_selection.json',run/'cache/norm.json',run/'cache/sample_indices.npy']:
        bindings[str(path)] = sha(path)
    base_files={str(p):sha(p) for p in BASE.glob('params/*') if p.is_file()}
    if not base_files or not (BASE/'params/manifest.ocdbt').exists(): raise ValueError('official_base_missing')
    write(run/'integrity.json', dict(files=bindings, base_metadata=base_files,
        train_only_norm=True,simulation_training_samples=0,validation_or_test_in_norm=False))
    root=run/'training_input';real=caches['train']
    features={k:dict(shape=[19],dtype='float32') for k in ['observation.state','action']}
    features.update({'observation.images.'+c:dict(shape=[224,224,3],dtype='uint8') for c in CAMERAS})
    write(root/'meta/info.json',dict(format='project_verified_numpy_cache/1',fps=20,total_frames=len(real.state),features=features,official_lerobot_export=False))
    write(root/'airport_training_manifest.json',dict(split='train',episodes=real.manifest['episodes'],action_semantics='absolute_mobile19',state_semantics='measured_joint16_plus_base_origin_offset3',source='real_world/user_provided',fps=20))
    write(run/'preparation_status.json',dict(stage='ready',training_started=False,real_counts=selection['real_counts'],simulation_frames=0,train_frames=len(real.state)))


def verify(run):
    receipt=json.loads((run/'integrity.json').read_text())
    for p,h in {**receipt['files'],**receipt['base_metadata']}.items():
        if sha(p)!=h: raise ValueError('frozen_real_input_changed:'+p)


def config_for(run):
    from r1pro_teleop.vla.training import TrainingSpec, build_openpi_config
    from r1pro_teleop.vla.training_accelerated import vision_parameter_filter
    from flax import nnx
    spec=TrainingSpec(dataset_root=str(run/'training_input'),dataset_repo_id='airport/real_only_pickplace_20261012',
        openpi_root=str(ROOT/'third_party/openpi'),base_params=str(BASE/'params'),run_dir=str(run/'pi05'),
        name='pi05_real_only_pickplace',num_train_steps=STEPS,batch_size=BATCH,save_interval=1000,
        action_horizon=20,num_workers=0,seed=42,lr_warmup_steps=500,prompt_mode='legacy')
    cfg=build_openpi_config(spec)
    return dataclasses.replace(cfg,freeze_filter=nnx.Any(cfg.freeze_filter,vision_parameter_filter),
        policy_metadata=dict(robot='r1pro',source='real_world/user_provided',method='BC_LoRA',fps=20,
        action_semantics='absolute_mobile19',prompt_mode='legacy',simulation_training_fraction=0)),spec


def train(run):
    import jax
    from r1pro_teleop.vla.training import AirportInputs, _load_script
    from openpi import transforms
    from openpi.shared import normalize
    from openpi.training import checkpoints, sharding
    from openpi.models import model
    verify(run)
    config,spec=config_for(run);real=Cache(run/'cache/train');indices=np.load(run/'cache/sample_indices.npy')
    stats=json.loads((run/'cache/norm.json').read_text())
    norm={k:normalize.NormStats(**{f:np.asarray(v) for f,v in row.items()}) for k,row in stats.items()}
    normalize.save(config.assets_dirs/spec.dataset_repo_id,norm)
    data=config.data.create(config.assets_dirs,config.model)
    transform=transforms.compose([AirportInputs('legacy'),transforms.Normalize(norm,use_quantiles=True),*data.model_transforms.inputs])
    if jax.device_count()!=1: raise ValueError('one_reserved_gpu_required')
    mesh=sharding.make_mesh(1);rep=jax.sharding.NamedSharding(mesh,jax.sharding.PartitionSpec());ds=jax.sharding.NamedSharding(mesh,jax.sharding.PartitionSpec(sharding.DATA_AXIS))
    official=_load_script(ROOT/'third_party/openpi','train.py');rng,init=jax.random.split(jax.random.key(42))
    class Loader:
        def data_config(self):return data
    resume=config.checkpoint_dir.exists()
    manager,resuming=checkpoints.initialize_checkpoint_dir(config.checkpoint_dir,keep_period=1000,overwrite=False,resume=resume)
    status=dict(stage='initializing',training_started=False,updates=0,target_updates=STEPS,pid=os.getpid(),
        source='real_world/user_provided',method='BC_LoRA',spec=dataclasses.asdict(spec),simulation_training_fraction=0,
        initialization='official_pi05_base_not_project_sim_checkpoint',resuming=resuming)
    write(run/'pi05/training_status.json',status)
    state,state_sharding=official.init_train_state(config,init,mesh,resume=resuming)
    if resuming: state=checkpoints.restore_state(manager,state,Loader())
    update=jax.jit(functools.partial(official.train_step,config),in_shardings=(rep,state_sharding,ds),out_shardings=(state_sharding,rep),donate_argnums=(1,))
    started=time.monotonic();ema=None
    for step in range(int(state.step),STEPS):
        tick=time.monotonic();samples=[real.get(int(i)) for i in indices[step]]
        host=jax.tree.map(lambda *a:np.stack(a),*[transform(s) for s in samples])
        batch=jax.device_put((model.Observation.from_dict(host),host['actions']),ds)
        with sharding.set_mesh(mesh):state,info=update(rng,state,batch)
        metrics={k:float(v) for k,v in jax.device_get(info).items()}
        if not all(np.isfinite(v) for v in metrics.values()):raise ValueError('nonfinite_real_update')
        duration=time.monotonic()-tick;ema=duration if ema is None else .1*duration+.9*ema
        status.update(stage='training',training_started=True,updates=step+1,metrics=metrics,elapsed_seconds=time.monotonic()-started,
            seconds_per_update_ema=ema,eta_seconds=(STEPS-step-1)*ema,eta_scope='remaining_training_only',heartbeat_unix=time.time())
        write(run/'pi05/training_status.json',status)
        if (step+1)%1000==0:
            checkpoints.save_state(manager,state,Loader(),step);manager.wait_until_finished()
            write(run/'pi05'/f'checkpoint_{step+1:06d}.json',dict(status,checkpoint=str(config.checkpoint_dir/str(step))))
    manager.close()
    write(run/'pi05/training_status.json',dict(status,stage='trained',updates=STEPS,checkpoint=str(config.checkpoint_dir/str(STEPS-1))))


def evaluate(run):
    from openpi.policies import policy_config
    verify(run)
    cfg,_=config_for(run);status=json.loads((run/'pi05/training_status.json').read_text())
    if status['stage']!='trained':raise ValueError('saved_trained_checkpoint_required')
    policy=policy_config.create_trained_policy(cfg,status['checkpoint'])
    out=run/'evaluation';out.mkdir(exist_ok=True)
    for split in ('val','test'):
        cache=Cache(run/'cache'/split);rows=[];summaries={}
        for n,e in enumerate(cache.manifest['episodes']):
            case=out/split/f'episode_{n:03d}';case.mkdir(parents=True,exist_ok=True)
            sums=np.zeros(19);first=np.zeros(19);hold=np.zeros(19);count=0;calls=0;preds=[];targets=[];valids=[];ids=[]
            for i in range(e['offset'],e['offset']+e['frames'],5):
                sample=cache.get(i);noise=np.random.default_rng(42000+i).standard_normal((20,32)).astype(np.float32)
                pred=np.asarray(policy.infer({k:v for k,v in sample.items() if k!='actions'},noise=noise)['actions'])[:,:19]
                if pred.shape!=(20,19) or not np.isfinite(pred).all(): raise ValueError('invalid_model_prediction')
                valid=min(20,int(cache.ends[i]-i));error=pred[:valid]-sample['actions'][:valid]
                sums+=(error**2).sum(0);first+=(error[0]**2);hold+=((sample['state']-sample['actions'][:valid])**2).sum(0)
                count+=valid;calls+=1;preds.append(pred);targets.append(sample['actions']);valids.append(valid);ids.append(i)
            np.savez_compressed(case/'predictions.npz',prediction=preds,target=targets,valid_lengths=valids,cache_indices=ids)
            m=sums/count
            row=dict(prompt=e['prompt'],raw_file_name=e['raw_file_name'],model_calls=calls,valid_targets=count,
                arm_mse_rad2=float(m[ARMS].mean()),gripper_mse_mm2=float(m[GRIPPERS].mean()*1e6),
                first_action_arm_mse_rad2=float((first/calls)[ARMS].mean()),per_channel_mse=m[:16].tolist(),
                hold_state_baseline_arm_mse_rad2=float((hold/count)[ARMS].mean()),videos=e['videos'],predictions=str(case/'predictions.npz'))
            write(case/'result.json',row);rows.append(row)
            g=summaries.setdefault(e['prompt'],dict(sums=np.zeros(19),hold=np.zeros(19),count=0,calls=0,episodes=0))
            g['sums']+=sums;g['hold']+=hold;g['count']+=count;g['calls']+=calls;g['episodes']+=1
            write(run/'evaluation_status.json',dict(stage='offline_evaluating',split=split,completed=n+1,total=len(cache.manifest['episodes']),heartbeat_unix=time.time()))
        groups={p:dict(episodes=g['episodes'],model_calls=g['calls'],arm_mse_rad2=float((g['sums']/g['count'])[ARMS].mean()),
            gripper_mse_mm2=float((g['sums']/g['count'])[GRIPPERS].mean()*1e6),hold_state_baseline_arm_mse_rad2=float((g['hold']/g['count'])[ARMS].mean())) for p,g in summaries.items()}
        write(out/f'{split}_summary.json',dict(scope='offline_real_action_prediction_not_robot_success',checkpoint=status['checkpoint'],
            groups=groups,episodes=rows,base_excluded=True,padded_tail_excluded=True,overlapping_H20_targets=True,
            noise='fixed_per_frame_seed_42000_plus_index',data_selection_sha256=sha(run/'frozen_data_selection.json')))
    # Brightness sensitivity uses validation only and identical flow noise across paired images.
    cache=Cache(run/'cache/val');pairs=[]
    for e in cache.manifest['episodes']:
        for i in np.linspace(e['offset'],e['offset']+e['frames']-1,4,dtype=int):
            sample=cache.get(int(i));noise=np.random.default_rng(42000+int(i)).standard_normal((20,32)).astype(np.float32)
            item=dict(index=int(i),prompt=e['prompt'],factors={})
            for factor in (.7,1.,1.3):
                obs={k:v for k,v in sample.items() if k!='actions'}
                for c in CAMERAS:obs['image/'+c]=np.clip(obs['image/'+c].astype(np.float32)*factor,0,255).astype(np.uint8)
                pred=np.asarray(policy.infer(obs,noise=noise)['actions'])[:,:19];valid=min(20,int(cache.ends[i]-i))
                if not np.isfinite(pred).all():raise ValueError('invalid_brightness_prediction')
                item['factors'][str(factor)]=dict(arm_mse_rad2=float(((pred[:valid,ARMS]-sample['actions'][:valid,ARMS])**2).mean()),gripper_mse_mm2=float(((pred[:valid,GRIPPERS]-sample['actions'][:valid,GRIPPERS])**2).mean()*1e6))
            pairs.append(item)
    write(out/'brightness_sensitivity.json',dict(scope='paired_validation_sensitivity_not_causal_proof',same_noise=True,rows=pairs))
    write(run/'evaluation_status.json',dict(stage='complete',real_robot_commands=0,task_success_rate=None,report=str(out/'test_summary.json')))


def supervise(run):
    import fcntl
    run.mkdir(parents=True,exist_ok=True);(run/'logs').mkdir(exist_ok=True)
    lock=(run/'pipeline.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    status=dict(stage='starting',pid=os.getpid(),training_started=False,simulation_training_fraction=0)
    try:
        for stage,artifact in [('prepare','preparation_status.json'),('train','pi05/training_status.json'),('evaluate','evaluation_status.json')]:
            closed=list((run/'logs').glob(stage+'_*.exit.json'))
            expected={'prepare':'ready','train':'trained','evaluate':'complete'}[stage]
            if (run/artifact).exists() and json.loads((run/artifact).read_text()).get('stage')==expected and any(json.loads(p.read_text()).get('returncode')==0 for p in closed):
                verify(run)
                continue
            for attempt in range(3):
                argv=[sys.executable,str(Path(__file__).resolve()),'--run',str(run),'--mode',stage]
                log=run/'logs'/f'{stage}_{attempt}_{int(time.time())}.log'
                with log.open('x') as f:child=subprocess.Popen(argv,cwd=ROOT,stdin=subprocess.DEVNULL,stdout=f,stderr=subprocess.STDOUT,start_new_session=True)
                birth=Path(f'/proc/{child.pid}/stat').read_text().rsplit(')',1)[1].split()[19]
                write(log.with_suffix('.launch.json'),dict(pid=child.pid,start_ticks=birth,argv=argv,cwd=str(ROOT)))
                status.update(stage=stage,active_pid=child.pid,start_ticks=birth,log=str(log),attempt=attempt)
                while child.poll() is None:
                    p=run/'pi05/training_status.json';t=json.loads(p.read_text()) if p.exists() else {}
                    status.update(heartbeat_unix=time.time(),training_started=t.get('training_started',False),actual_updates=t.get('updates',0))
                    write(run/'pipeline_status.json',status);time.sleep(5)
                code=child.wait();write(log.with_suffix('.exit.json'),dict(pid=child.pid,start_ticks=birth,returncode=code,actual_child_wait=True))
                if code==0:
                    receipt=json.loads((run/artifact).read_text())
                    if receipt['stage'] not in ('ready','trained','complete'):raise ValueError('stage_output_not_closed')
                    break
                if attempt==2:raise RuntimeError(f'{stage} failed after 3 attempts; see {log}')
                status.update(stage='retry_backoff',last_exit=code);write(run/'pipeline_status.json',status);time.sleep(15*(attempt+1))
        write(run/'pipeline_status.json',dict(status,stage='complete',active_pid=None,heartbeat_unix=time.time()))
    except BaseException as error:
        write(run/'pipeline_status.json',dict(status,stage='failed',active_pid=None,error=repr(error),heartbeat_unix=time.time()));raise


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--run',type=Path,required=True);parser.add_argument('--mode',choices=['prepare','train','evaluate','supervise'],required=True)
    args=parser.parse_args()
    globals()[args.mode](args.run)
