"""Offline real/sim transfer experiment; no real robot command interface."""
import argparse,dataclasses,importlib.util,json,os,subprocess,sys,time,traceback
from pathlib import Path
import numpy as np

CODE=Path(__file__).resolve().parents[1]
ROOT=Path(os.environ.get('AIRPORT_PROJECT','/home/michelle/haoze/r1pro-airport-sim'))
sys.path.insert(0,str(CODE));sys.path.insert(0,str(ROOT/'third_party/openpi/src'));sys.path.insert(0,str(ROOT/'third_party/openpi/packages/openpi-client/src'))
from r1pro_teleop.vla.real_sim_data import (Cache,CAMERAS,REAL_CAMERAS,PROMPTS,ARMS,GRIPPERS,write,sha,split_for,resample_indices,make_cache,mixed_schedule,mse_groups)
OLD=ROOT/'runs/afford_pi05_pickup120_20261008_v2'
SIM=ROOT/'runs/three_actions_gripper_preserved_20261007_v4/data_batch_v1'


def bridge():
    p=ROOT/'releases/afford_pi05_pickup120_20261008_v2/scripts/compare_pickup120.py'
    s=importlib.util.spec_from_file_location('real_mix_old_comparison',p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);m.RUN=OLD;return m


def prepare(run):
    import pyarrow.parquet as pq
    gate=json.loads((run/'conversion_contract.json').read_text())
    if gate.get('gripper_unit')!='mm' or gate.get('unit_confirmed_by_user') is not True:raise ValueError('real_gripper_unit_not_confirmed')
    source=json.loads((run/'source_status_attempt01.json').read_text())
    if source['stage']!='sources_extracted':raise ValueError('real_sources_not_closed')
    records={s:[] for s in ['train','val','test']};seen={};archive_hashes=[]
    for entry in source['datasets']:
        root=Path(entry['root']);info=json.loads((root/'meta/info.json').read_text());task=0 if 'Pick_Box' in root.name else 1
        if info['robot_type']!='r1pro' or info['fps']!=30:raise ValueError('real_robot_or_fps_changed')
        archive_hashes.append(dict(path=entry['archive'],sha256=sha(entry['archive'])))
        rows=[json.loads(x) for x in (root/'meta/episodes.jsonl').read_text().splitlines()]
        if len(rows)!=info['total_episodes']:raise ValueError('real_episode_count_changed')
        for row in rows:
            if 'qualified' not in row['tasks']:raise ValueError('unqualified_real_episode_requires_explicit_exclusion')
            original=row['raw_file_name'];split=split_for(original);ep=row['episode_index'];chunk=ep//info['chunks_size']
            parquet=root/info['data_path'].format(episode_chunk=chunk,episode_index=ep);table=pq.read_table(parquet,columns=['timestamp']);indices=resample_indices(table['timestamp'].to_pylist())
            if (root.name,ep) in seen:raise ValueError('duplicate_real_episode')
            seen[root.name,ep]=split
            videos={c:str(root/info['video_path'].format(episode_chunk=chunk,episode_index=ep,video_key='observation.images.'+rc)) for c,rc in zip(CAMERAS,REAL_CAMERAS)}
            records[split].append(dict(domain='real',dataset=root.name,episode_index=ep,raw_file_name=original,split=split,task_index=task,prompt=PROMPTS[task],parquet=str(parquet),videos=videos,indices=indices.tolist(),original_frames=row['length'],info_sha256=sha(root/'meta/info.json')))
    if any(set(r['task_index'] for r in records[s])!={0,1} for s in records):raise ValueError('real_pick_and_place_each_split_required')
    groups={s:{r['raw_file_name'] for r in records[s]} for s in records}
    if any(groups[a]&groups[b] for a,b in [('train','val'),('train','test'),('val','test')]):raise ValueError('real_raw_recording_split_leak')
    info=json.loads((SIM/'datasets/train/meta/info.json').read_text());manifest=json.loads((SIM/'datasets/train/airport_training_manifest.json').read_text())
    if manifest.get('dataset_ready') is not True:raise ValueError('simulation_source_not_verified_ready')
    scenes=sorted({e['scene_id'] for e in manifest['episodes']})[:10];sim=[]
    for e in manifest['episodes']:
        if e['scene_id'] not in scenes:continue
        ep=e['episode_index'];chunk=ep//info['chunks_size']
        sim.append(dict(domain='simulation',scene_id=e['scene_id'],parent_scene_id=e.get('parent_scene_id'),split='train',episode_index=ep,task_index=e['task_index'],prompt=e['language_prompt'],parquet=str(SIM/'datasets/train'/info['data_path'].format(episode_chunk=chunk,episode_index=ep)),videos={c:str(SIM/'datasets/train'/info['video_path'].format(episode_chunk=chunk,episode_index=ep,video_key='observation.images.'+c)) for c in CAMERAS},indices=list(range(e['frames']))))
    write(run/'frozen_data_selection.json',dict(real=records,simulation=sim,archives=archive_hashes,simulation_training_manifest_sha256=sha(SIM/'datasets/train/airport_training_manifest.json'),real_split_policy='raw_recording_hash42_80_10_10_episode_holdout',simulation_sampling_fraction=.1,real_fraction=.9,simulation_full_source_count=len(scenes),real_counts={s:len(x) for s,x in records.items()},simulation_clip_count=len(sim)))
    for split,rows in [*records.items(),('simulation',sim)]:
        make_cache(rows,run/'cache'/split,on_progress=lambda p:write(run/'preparation_status.json',dict(stage='decoding',split=split,training_started=False,**p)))
    real=Cache(run/'cache/train');simcache=Cache(run/'cache/simulation');domains,indices=mixed_schedule(real.task,simcache.task)
    np.save(run/'cache/sample_domains.npy',domains);np.save(run/'cache/sample_indices.npy',indices)
    selected={}
    for key in ['state','action']:
        a=np.empty((domains.size,19),np.float32)
        for domain,cache in enumerate([real,simcache]):
            mask=domains.reshape(-1)==domain;a[mask]=getattr(cache,key)[indices.reshape(-1)[mask]]
        selected['actions' if key=='action' else key]=dict(mean=a.mean(0).tolist(),std=a.std(0).tolist(),q01=np.quantile(a,.01,axis=0).tolist(),q99=np.quantile(a,.99,axis=0).tolist())
    write(run/'cache/norm.json',selected)
    write(run/'normalization_provenance.json',dict(train_only=True,real_test_used=False,real_val_used=False,selection_sha256=sha(run/'frozen_data_selection.json'),schedule_domains_sha256=sha(run/'cache/sample_domains.npy'),schedule_indices_sha256=sha(run/'cache/sample_indices.npy'),norm_sha256=sha(run/'cache/norm.json'),sampling='exact90_percent_real10_percent_sim_balanced_tasks_within_domain'))
    write(run/'preparation_status.json',dict(stage='ready',training_started=False,real_counts={s:len(x) for s,x in records.items()},simulation_sources=10,simulation_clips=len(sim),real_train_frames=len(real.state)))


def mixed_config(run):
    from r1pro_teleop.vla.training import TrainingSpec,build_openpi_config
    from r1pro_teleop.vla.training_accelerated import vision_parameter_filter
    from flax import nnx
    parent=json.loads((OLD/'pi05/training_status.json').read_text())
    root=run/'training_input';selection=json.loads((run/'frozen_data_selection.json').read_text());real=Cache(run/'cache/train');sim=Cache(run/'cache/simulation');episodes=[*real.manifest['episodes'],*sim.manifest['episodes']]
    if any(e['split']!='train' for e in episodes):raise ValueError('mixed_descriptor_non_train_source')
    # Explicit descriptor for verified NumPy caches, not a fabricated LeRobot export.
    features={k:dict(shape=[19],dtype='float32') for k in ['observation.state','action']};features.update({'observation.images.'+c:dict(shape=[224,224,3],dtype='uint8') for c in CAMERAS})
    write(root/'meta/info.json',dict(format='project_verified_numpy_cache/1',fps=20,total_frames=len(real.state)+len(sim.state),features=features,cache_paths=[str(real.path),str(sim.path)],official_lerobot_export=False))
    write(root/'airport_training_manifest.json',dict(split='train',episodes=episodes,action_semantics='absolute_mobile19',state_semantics='measured_joint16_plus_base_origin_offset3',fps=20,source='real_world_plus_simulation',selection_sha256=sha(run/'frozen_data_selection.json'),cache_manifests_sha256=[sha(real.path/'manifest.json'),sha(sim.path/'manifest.json')],real_fraction=.9,simulation_fraction=.1))
    spec=TrainingSpec(dataset_root=str(root),dataset_repo_id='airport/real_sim_pickplace_v1',openpi_root=str(ROOT/'third_party/openpi'),base_params=str(Path(parent['checkpoint'])/'params'),run_dir=str(run/'pi05'),name='pi05_real_sim_pickplace',num_train_steps=10000,batch_size=8,save_interval=1000,action_horizon=20,num_workers=0,seed=42,lr_warmup_steps=500,prompt_mode='legacy')
    config=build_openpi_config(spec)
    return dataclasses.replace(config,freeze_filter=nnx.Any(config.freeze_filter,vision_parameter_filter),policy_metadata=dict(robot='r1pro',source='real_world_plus_simulation',action_semantics='absolute_mobile19',fps=20,prompt_mode='legacy',method='bc_lora',real_fraction=.9,sim_fraction=.1)),spec


def policy(run,name):
    if name in ('pi05','mixed_pi05'):
        from openpi.policies import policy_config
        b=bridge();config,_=b.pi_config() if name=='pi05' else mixed_config(run)
        status=json.loads(((OLD if name=='pi05' else run)/'pi05/training_status.json').read_text());checkpoint=status['checkpoint'];model=policy_config.create_trained_policy(config,checkpoint)
        def infer(sample):return np.asarray(model.infer({k:v for k,v in sample.items() if k!='actions'})['actions'])[:,:19]
    else:
        import torch
        from PIL import Image
        torch.manual_seed(42)
        b=bridge();model,_=b.afford_model();b.attach_afford_lora(model);status=json.loads((OLD/'affordvla/training_status.json').read_text());checkpoint=status['checkpoint'];saved=torch.load(checkpoint,map_location='cpu',weights_only=False);mismatch=model.load_state_dict(saved['state_dict'],strict=False)
        if mismatch.unexpected_keys or any(not k.startswith('qwen_vl_interface.') for k in mismatch.missing_keys):raise ValueError('afford_mse_checkpoint_mismatch')
        model.eval();model.region_pooling_mode_infer='hard_topk_pred';norm=json.loads((OLD/'cache/norm.json').read_text())
        def infer(sample):
            state=(sample['state']-np.array(norm['state']['mean']))/(np.array(norm['state']['std'])+1e-6)
            with torch.no_grad(),torch.autocast('cuda',dtype=torch.bfloat16):a=model.predict_action([dict(image=[Image.fromarray(sample['image/'+c]) for c in CAMERAS],lang=sample['prompt'],state=state.astype(np.float32)[None])])['normalized_actions'][0]
            return (a*(np.array(norm['actions']['std'])+1e-6)+np.array(norm['actions']['mean'])).astype(np.float32)
    return infer,str(checkpoint)


def mse(run,name):
    infer,checkpoint=policy(run,name);cache=Cache(run/'cache/test');acc={};rows=[]
    for e in cache.manifest['episodes']:
        sums=np.zeros(19);count=0;first_sums=np.zeros(19);calls=0
        for i in range(e['offset'],e['offset']+e['frames'],5):
            sample=cache.get(i);pred=infer(sample)
            if pred.shape!=(20,19) or not np.isfinite(pred).all():raise ValueError('nonfinite_or_invalid_mse_prediction')
            valid=min(20,int(cache.ends[i]-i));sums+=((pred[:valid]-sample['actions'][:valid])**2).sum(0);count+=valid;first_sums+=(pred[0]-sample['actions'][0])**2;calls+=1
        row=dict(dataset=e['dataset'],episode_index=e['episode_index'],raw_file_name=e['raw_file_name'],prompt=e['prompt'],evaluated_action_vectors=count,inference_calls=calls,chunk_mse_per_channel=(sums/count)[:16].tolist(),first_action_mse_per_channel=(first_sums/calls)[:16].tolist());rows.append(row)
        group=acc.setdefault(e['prompt'],dict(sums=np.zeros(19),count=0,first=np.zeros(19),calls=0,episodes=0));group['sums']+=sums;group['count']+=count;group['first']+=first_sums;group['calls']+=calls;group['episodes']+=1
        write(run/f'mse_{name}_progress.json',dict(model=name,evaluated_episodes=len(rows),total_episodes=len(cache.manifest['episodes']),training_started=False))
    report={}
    for prompt,g in acc.items():
        p=g['sums']/g['count'];report[prompt]=dict(episodes=g['episodes'],valid_target_vectors=g['count'],model_calls=g['calls'],arm_mse_rad2=float(p[ARMS].mean()),gripper_mse_m2=float(p[GRIPPERS].mean()),gripper_mse_mm2=float(p[GRIPPERS].mean()*1e6),per_channel_mse=p[:16].tolist(),first_action_arm_mse_rad2=float((g['first']/g['calls'])[ARMS].mean()))
    write(run/f'mse_{name}.json',dict(model=name,checkpoint=checkpoint,real_test_episode_holdout=True,scope='offline_action_prediction_not_real_robot_success',groups=report,episodes=rows,base_channels_excluded=True,tail_padded_targets_excluded=True,flow_noise_evaluation='one_seeded_pass_per_model_not_multi_seed_confidence_interval',source_selection_sha256=sha(run/'frozen_data_selection.json')))


def train(run):
    import jax,functools
    from r1pro_teleop.vla.training import AirportInputs,_load_script
    from openpi import transforms
    from openpi.shared import normalize
    from openpi.training import checkpoints,sharding
    from openpi.models import model
    config,spec=mixed_config(run);real=Cache(run/'cache/train');sim=Cache(run/'cache/simulation');domains=np.load(run/'cache/sample_domains.npy');indices=np.load(run/'cache/sample_indices.npy');stats=json.loads((run/'cache/norm.json').read_text());norm={k:normalize.NormStats(**{field:np.asarray(v) for field,v in row.items()}) for k,row in stats.items()};normalize.save(config.assets_dirs/spec.dataset_repo_id,norm);data=config.data.create(config.assets_dirs,config.model);transform=transforms.compose([AirportInputs('legacy'),transforms.Normalize(norm,use_quantiles=True),*data.model_transforms.inputs])
    if jax.device_count()!=1:raise ValueError('independent_mix_requires_one_reserved_gpu')
    mesh=sharding.make_mesh(1);rep=jax.sharding.NamedSharding(mesh,jax.sharding.PartitionSpec());ds=jax.sharding.NamedSharding(mesh,jax.sharding.PartitionSpec(sharding.DATA_AXIS));official=_load_script(ROOT/'third_party/openpi','train.py');rng,init=jax.random.split(jax.random.key(42));status=dict(stage='initializing',training_started=False,updates=0,target_updates=10000,pid=os.getpid(),source='real_world_plus_simulation',method='BC_LoRA',spec=dataclasses.asdict(spec),real_sampling_fraction=.9,sim_sampling_fraction=.1,parent_weights_only_new_optimizer=True)
    write(run/'pi05/training_status.json',status);state,state_sharding=official.init_train_state(config,init,mesh,resume=False);manager,_=checkpoints.initialize_checkpoint_dir(config.checkpoint_dir,keep_period=1000,overwrite=False,resume=False)
    class Loader:
        def data_config(self):return data
    update=jax.jit(functools.partial(official.train_step,config),in_shardings=(rep,state_sharding,ds),out_shardings=(state_sharding,rep),donate_argnums=(1,));started=time.monotonic();ema=None
    for step in range(10000):
        tick=time.monotonic();samples=[(real if domain==0 else sim).get(int(index)) for domain,index in zip(domains[step],indices[step])];host=jax.tree.map(lambda *a:np.stack(a),*[transform(s) for s in samples]);batch=jax.device_put((model.Observation.from_dict(host),host['actions']),ds)
        with sharding.set_mesh(mesh):state,info=update(rng,state,batch)
        metrics={k:float(v) for k,v in jax.device_get(info).items()}
        if not all(np.isfinite(v) for v in metrics.values()):raise ValueError('nonfinite_real_mix_update')
        duration=time.monotonic()-tick;ema=duration if ema is None else .1*duration+.9*ema;status.update(stage='training',training_started=True,updates=step+1,metrics=metrics,elapsed_seconds=time.monotonic()-started,seconds_per_update_ema=ema,eta_seconds=(9999-step)*ema,heartbeat_unix=time.time());write(run/'pi05/training_status.json',status)
        if (step+1)%1000==0:
            checkpoints.save_state(manager,state,Loader(),step);manager.wait_until_finished();write(run/'pi05'/f'checkpoint_{step+1:06d}.json',dict(status,checkpoint=str(config.checkpoint_dir/str(step))))
    manager.close();write(run/'pi05/training_status.json',dict(status,stage='trained',checkpoint=str(config.checkpoint_dir/'9999')))


def simulate(run):
    import mujoco,h5py
    from openpi_client.image_tools import resize_with_pad
    from r1pro_teleop.airport_fsm.contracts import Config
    from r1pro_teleop.airport_fsm.trace import Trace
    from r1pro_teleop.single_tray_3table.control import ThreeTableRuntime
    from r1pro_teleop.single_tray_3table.learned import contact_snapshot,opposed_contact,place_completion
    from r1pro_teleop.single_tray_3table.observer import table_front_region_violation
    from r1pro_teleop.vla.observations import model_render_shape
    b=bridge();sys.path.insert(0,str(Path(b.__file__).parent));from run_vla_fixed_scene import restore_stage,advance_interval,DiagnosticVideoWriter
    infer,checkpoint=policy(run,'mixed_pi05');sources=[json.loads(l) for l in (SIM/'source_records.jsonl').read_text().splitlines() if json.loads(l)['source']['split']=='test'];out=run/'sim_evaluations';out.mkdir(exist_ok=False);results=[]
    for entry in sources:
        source=entry['source'];scene=json.loads(Path(source['scene_json']).read_text())
        for segment in entry['plan']['segments'][:2]:
            task=segment['task_index'];case=out/f"{source['scene_id']}_{task}";case.mkdir();(case/'videos').mkdir();result=dict(scene_id=source['scene_id'],action=PROMPTS[task],success=False,frames=0,inference_calls=0,teacher_fallback=False,inverse_solver_calls=0,checkpoint=checkpoint,scope='independent_action_from_recorded_physical_initial_state_not_full_task');runtime=None;trace=None;writers={}
            try:
                with h5py.File(source['trace']) as f:meta=json.loads(f.attrs['metadata_json'])
                write(case/'config.json',meta['config']);runtime=ThreeTableRuntime(scene,Config.load(case/'config.json'),render=True);origin,_,_=restore_stage(runtime,source['trace'],segment['start_frame']);trace=Trace(case/'attempt',dict(config=runtime.cfg.dump(),source='simulation/program_generated',controller_source='vla_generated',checkpoint=checkpoint,fps=20));initial=float(runtime.observation()['min_z'][0]);held=0;seen=False;chunk=None;cursor=0;renderers={}
                for c in CAMERAS:
                    h,w,_=model_render_shape(runtime.sim.camera_shapes[c],224);renderer=mujoco.Renderer(runtime.m,height=h,width=w);runtime.sim._camera_renderers[('real_mix_eval',c)]=renderer;renderers[c]=renderer;writers[c]=DiagnosticVideoWriter(case/'videos'/f'{c}.mp4',(224,224,3))
                for frame in range(1000):
                    images={}
                    for c,renderer in renderers.items():
                        renderer.update_scene(runtime.d,camera=c,scene_option=runtime.sim.options);images[c]=resize_with_pad(renderer.render().copy(),224,224);writers[c].write(images[c])
                    if chunk is None or cursor==5:
                        state=np.r_[runtime.sim.state(),runtime.sim.base_joint_state()-origin].astype(np.float32);chunk=infer(dict(state=state,prompt=PROMPTS[task],**{'image/'+c:images[c] for c in CAMERAS}));cursor=0;result['inference_calls']+=1;np.savez_compressed(case/f'decision_{frame:04d}.npz',raw_actions=chunk,state=state)
                    row,error=advance_interval(runtime,chunk[cursor],origin,frame);trace.append(row);cursor+=1;result['frames']=trace.count
                    if error:raise error
                    obs=runtime.observation();contact=contact_snapshot(runtime,scene);opposed=opposed_contact(contact,scene['tray']['size']);seen=seen or opposed
                    if task==0:valid=bool(opposed and np.all(obs['gripper_contact_force'][0]>runtime.cfg.criteria.contact_n) and obs['table_contact'][0]==0 and obs['floor_contact'][0]==0 and obs['min_z'][0]-initial>=runtime.cfg.criteria.lifted_m)
                    else:
                        table=next(t for t in scene['tables'] if t['table_id']==scene['target_table']) if isinstance(scene['tables'],list) else scene['tables'][scene['target_table']];side=table_front_region_violation(table,runtime.d.body('base_link').xpos);valid=place_completion(contact,obs,scene,opposed_seen=seen,released=bool(np.all(obs['gripper_contact_force'][0]<runtime.cfg.criteria.contact_n)),front_violation=side)
                    held=held+1 if valid else 0
                    if held>=20:result['success']=True;break
            except Exception as error:result['error']=repr(error);result['infrastructure_error']=isinstance(error,(KeyError,AttributeError,ImportError,TypeError));(case/'exception.txt').write_text(traceback.format_exc())
            finally:
                for writer in writers.values():writer.close()
                if trace:trace.close(dict(qpos=runtime.d.qpos,qvel=runtime.d.qvel,time=float(runtime.d.time)))
                if runtime:result['inverse_solver_calls']=int(runtime.id_calls);runtime.sim.close()
                if result['inverse_solver_calls']:raise ValueError('forbidden_real_mix_teacher_inverse_fallback')
                write(case/'result.json',result);results.append(result);(case/'viewer.html').write_text('<meta charset="utf-8">'+''.join(f'<video controls width="320" src="videos/{c}.mp4"></video>' for c in CAMERAS));write(out/'progress.json',dict(completed=len(results),target=20,successes=sum(x['success'] for x in results)))
    write(out/'summary.json',dict(cases=results,groups={p:dict(tested=sum(x['action']==p for x in results),successes=sum(x['action']==p and x['success'] for x in results)) for p in PROMPTS[:2]},infrastructure_failures=sum(x.get('infrastructure_error',False) for x in results),whole_three_action_success_not_measured=True))


def supervise(run):
    import fcntl
    lock=(run/'pipeline.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);script=str(Path(__file__).resolve());py='/home/michelle/miniconda3/envs/r1pro-vla/bin/python';aff=str(OLD/'conda/affordvla/bin/python');status=dict(stage='starting',pid=os.getpid(),training_started=False)
    env=dict(os.environ,CUDA_VISIBLE_DEVICES='GPU-c8e2826c-b460-18ba-dab5-ccd8c1da8b6c',MUJOCO_GL='egl',MUJOCO_EGL_DEVICE_ID='0',XLA_PYTHON_CLIENT_MEM_FRACTION='.85',OMP_NUM_THREADS='2',OPENBLAS_NUM_THREADS='2',MKL_NUM_THREADS='2',WANDB_MODE='disabled',TOKENIZERS_PARALLELISM='false')
    try:
        for mode,model,python in [('prepare',None,py),('mse','pi05',py),('mse','affordvla',aff),('train',None,py),('mse','mixed_pi05',py),('simulate',None,py)]:
            label=mode+('_'+model if model else '');argv=[python,script,'--run',str(run),'--mode',mode]+(['--model',model] if model else [])
            reuse=run/'verified_stage_import.json'
            imported=json.loads(reuse.read_text()).get(label) if reuse.exists() else None
            if imported:
                receipt=json.loads(Path(imported['exit']).read_text())
                if sha(imported['exit'])!=imported['exit_sha256'] or receipt.get('returncode')!=0 or receipt.get('actual_child_wait') is not True or any(sha(p)!=h for p,h in imported['artifacts'].items()):raise ValueError('reused_stage_exit_or_artifact_changed')
                write(run/'logs'/f'{label}.import.json',imported);continue
            with (run/'logs'/f'{label}.log').open('x') as f:child=subprocess.Popen(argv,cwd=ROOT,env=env,stdin=subprocess.DEVNULL,stdout=f,stderr=subprocess.STDOUT,start_new_session=True)
            write(run/'logs'/f'{label}.launch.json',dict(pid=child.pid,argv=argv,cwd=str(ROOT),start_ticks=Path(f'/proc/{child.pid}/stat').read_text().rsplit(')',1)[1].split()[19]));status.update(stage=label,active_pid=child.pid)
            while child.poll() is None:
                trained=run/'pi05/training_status.json';data=json.loads(trained.read_text()) if trained.exists() else {};status.update(heartbeat_unix=time.time(),training_started=bool(data.get('training_started',False)),actual_updates=data.get('updates',0));write(run/'pipeline_status.json',status);time.sleep(5)
            code=child.wait();write(run/'logs'/f'{label}.exit.json',dict(pid=child.pid,returncode=code,actual_child_wait=True))
            if code:raise RuntimeError(f'{label}: actual exit{code}')
        write(run/'pipeline_status.json',dict(status,stage='complete',active_pid=None,heartbeat_unix=time.time()))
    except BaseException as error:write(run/'pipeline_status.json',dict(status,stage='failed_preserving_sources_and_checkpoints',error=repr(error),heartbeat_unix=time.time()));raise


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--run',required=True);p.add_argument('--mode',choices=['prepare','mse','train','simulate','supervise'],required=True);p.add_argument('--model',choices=['pi05','affordvla','mixed_pi05']);a=p.parse_args();run=Path(a.run)
    if a.mode=='mse':mse(run,a.model)
    else:globals()[a.mode](run)
