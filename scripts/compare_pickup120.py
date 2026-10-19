"""Isolated server BC comparison: exactly120 pickup episodes, same50 heldout poses.

No current collection or service is modified. Official model implementations
are used without editing vendor files. This experiment is not DAgger.
"""
from __future__ import annotations
import argparse, dataclasses, hashlib, importlib.util, json, os, shutil, subprocess, sys, time, traceback
from pathlib import Path
import numpy as np

PROJECT=Path(os.environ.get('AIRPORT_PROJECT','/home/michelle/haoze/r1pro-airport-sim'))
RUN=Path(os.environ.get('AIRPORT_COMPARISON_RUN',str(PROJECT/'runs/afford_pi05_pickup120_20261007_v1')))
RUNTIME=PROJECT/'releases/three_table_single_tray_v34_eval_audit_20261006'
SOURCE=PROJECT/'runs/pickup_camera_shells_hidden_20261007_v2'
OPENPI=PROJECT/'third_party/openpi'
sys.path.insert(0,str(RUNTIME));sys.path.insert(0,str(OPENPI/'src'))
sys.path.insert(0,str(OPENPI/'packages/openpi-client/src'))
CAMERAS=('head_left','left_wrist','right_wrist')
PROMPT='Pick up the tray'
REPO='airport/pickup120_no_camera_shell_v1'
VLA_PY='/home/michelle/miniconda3/envs/r1pro-vla/bin/python'

def write(path,obj):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix('.tmp');temp.write_text(json.dumps(obj,indent=2,allow_nan=False,default=str));temp.replace(path)

def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(8*1024*1024),b''):h.update(block)
    return h.hexdigest()

def prepare():
    import pandas as pd,av
    if json.loads((SOURCE/'status.json').read_text())['stage']!='ready':raise ValueError('comparison_source_not_ready')
    original=[json.loads(line) for line in (SOURCE/'episodes.jsonl').read_text().splitlines()]
    if len(original)!=200:raise ValueError('comparison_source_200_required')
    training=original[:120];heldout=original[120:170]
    if set(r['scene_id'] for r in training)&set(r['scene_id'] for r in heldout):raise ValueError('comparison_episode_overlap')
    dataset=RUN/'data'/REPO;dataset.mkdir(parents=True,exist_ok=False)
    (dataset/'meta').mkdir()
    old=SOURCE/'lerobot';info=json.loads((old/'meta/info.json').read_text())
    info.update(total_episodes=120,total_frames=sum(r['frames'] for r in training),total_videos=360,splits={'train':'0:120'})
    write(dataset/'meta/info.json',info)
    shutil.copyfile(old/'meta/tasks.jsonl',dataset/'meta/tasks.jsonl')
    for name in ('episodes.jsonl','episodes_stats.jsonl'):
        lines=(old/'meta'/name).read_text().splitlines()[:120];(dataset/'meta'/name).write_text('\n'.join(lines)+'\n')
    manifest=dict(schema='pickup120_bc_comparison_train/1',split='train',episodes=training,fps=20,
        action_semantics='absolute_mobile19',state_semantics='measured_joint16_plus_base_origin_offset3',
        source='simulation/program_generated',scope='pickup_only_partial_task_v1',prompt=PROMPT)
    write(dataset/'airport_training_manifest.json',manifest)
    protocol=dict(schema='pickup120_paired_within_parent_pose_comparison/1',train=training,heldout=heldout,
        train_episodes=120,test_episodes=50,prompt=PROMPT,action_horizon=20,execute_steps=5,fps=20,
        bc_action_updates=10000,affordance_stage1_updates=1000,batch_size=8,
        same_parent_scene=True,unseen_scene_generalization=False,source_collection_split='train',
        heldout_scope='episode_and_pose_holdout_only_not_registry_test_split',physics_budget_seconds=25,
        pickup_endpoint='same_teacher_opposed_long_rims_contact_and_lift_then_1second_stability',
        teacher_or_ik_fallback=False,affordance_supervision='visible_tray_target_silhouette_from_sim_geometry_not_RAGNet',
        precision='model_BF16_optimizer_FP32',gpu='physical_GPU1_only',dataset_manifest_sha256=sha(dataset/'airport_training_manifest.json'))
    write(RUN/'protocol.json',protocol)
    cache=RUN/'cache';cache.mkdir();n=info['total_frames'];offset=0;numeric=[];states=[];ends=[]
    rgb={c:np.lib.format.open_memmap(cache/(c+'.npy'),mode='w+',dtype=np.uint8,shape=(n,224,224,3)) for c in CAMERAS}
    for i,row in enumerate(training):
        relative=Path(f'data/chunk-000/episode_{i:06d}.parquet');target=dataset/relative;target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(old/relative,target);data=pd.read_parquet(target)
        numeric.append(np.stack(data['action']).astype(np.float32));states.append(np.stack(data['observation.state']).astype(np.float32));ends.extend([offset+len(data)]*len(data))
        for c in CAMERAS:
            rel=Path(f'videos/chunk-000/observation.images.{c}/episode_{i:06d}.mp4');v=dataset/rel;v.parent.mkdir(parents=True,exist_ok=True);v.symlink_to(old/rel)
            count=0
            with av.open(str(v)) as container:
                for frame in container.decode(video=0):rgb[c][offset+count]=frame.to_ndarray(format='rgb24');count+=1
            if count!=len(data):raise ValueError('comparison_video_frame_alignment_failed')
        offset+=len(data);write(RUN/'preparation_status.json',dict(stage='caching',episodes=i+1,target=120,training_started=False))
    for array in rgb.values():array.flush()
    action=np.concatenate(numeric);state=np.concatenate(states)
    np.save(cache/'action.npy',action);np.save(cache/'state.npy',state);np.save(cache/'end.npy',np.asarray(ends))
    norm={k:dict(mean=a.mean(0).tolist(),std=a.std(0).tolist(),q01=np.quantile(a,.01,axis=0).tolist(),q99=np.quantile(a,.99,axis=0).tolist()) for k,a in [('state',state),('actions',action)]}
    write(cache/'norm.json',norm)
    from lerobot.common.datasets.lerobot_dataset import LeRobotDataset
    loaded=LeRobotDataset(REPO,root=dataset,video_backend='pyav')
    if loaded.num_episodes!=120 or len(loaded)!=n:raise ValueError('comparison_official_loader_count_failed')
    for j in (0,n//2,n-1):
        if tuple(loaded[j]['observation.images.head_left'].shape)!=(3,224,224):raise ValueError('comparison_official_loader_image_failed')
    write(RUN/'preparation_status.json',dict(stage='ready',episodes=120,frames=n,official_loader_verified=True,dataset=str(dataset),training_started=False))
    base=RUN/'models/pi05_base';base.parent.mkdir(parents=True,exist_ok=True)
    shutil.copytree('/home/michelle/haoze/pi05/model_cache/openpi-assets/checkpoints/pi05_base',base)

class Samples:
    def __init__(self):
        self.cache=RUN/'cache';self.actions=np.load(self.cache/'action.npy',mmap_mode='r');self.states=np.load(self.cache/'state.npy',mmap_mode='r')
        self.ends=np.load(self.cache/'end.npy',mmap_mode='r');self.images={c:np.load(self.cache/(c+'.npy'),mmap_mode='r') for c in CAMERAS}
        self.norm=json.loads((self.cache/'norm.json').read_text())
    def get(self,index):
        chunk=np.minimum(index+np.arange(20),self.ends[index]-1)
        return dict(state=np.asarray(self.states[index]),actions=np.asarray(self.actions[chunk]),prompt=PROMPT,
                    **{'image/'+c:np.asarray(self.images[c][index]) for c in CAMERAS})
    def standard(self,key,array):
        stats=self.norm[key];return ((array-np.asarray(stats['mean']))/(np.asarray(stats['std'])+1e-6)).astype(np.float32)

def pi_config():
    from r1pro_teleop.vla.training import TrainingSpec,build_openpi_config
    from flax import nnx
    from r1pro_teleop.vla.training_accelerated import vision_parameter_filter
    spec=TrainingSpec(dataset_root=str(RUN/'data'/REPO),dataset_repo_id=REPO,openpi_root=str(OPENPI),
        base_params=str(RUN/'models/pi05_base/params'),
        run_dir=str(RUN/'pi05'),name='pi05_pickup120',num_train_steps=10000,batch_size=8,save_interval=1000,
        action_horizon=20,num_workers=0,seed=42,lr_warmup_steps=500,prompt_mode='legacy')
    config=build_openpi_config(spec)
    return dataclasses.replace(config,freeze_filter=nnx.Any(config.freeze_filter,vision_parameter_filter)),spec

def train_pi():
    import jax,functools
    from r1pro_teleop.vla.training import AirportInputs,_load_script
    from openpi import transforms
    from openpi.shared import normalize
    from openpi.training import checkpoints,sharding
    from openpi.models import model
    config,spec=pi_config();samples=Samples();norm={k:normalize.NormStats(**{field:np.asarray(value) for field,value in v.items()}) for k,v in samples.norm.items()}
    normalize.save(config.assets_dirs/REPO,norm)
    data_config=config.data.create(config.assets_dirs,config.model)
    transform=transforms.compose([AirportInputs('legacy'),transforms.Normalize(norm,use_quantiles=True),*data_config.model_transforms.inputs])
    status=dict(stage='initializing',model='pi05',training_started=False,updates=0,episodes=120,method='BC_LoRA',source='simulation/program_generated',spec=dataclasses.asdict(spec))
    target=RUN/'pi05/training_status.json';write(target,status)
    if jax.device_count()!=1:raise ValueError('comparison_requires_one_reserved_GPU')
    mesh=sharding.make_mesh(1);rep=jax.sharding.NamedSharding(mesh,jax.sharding.PartitionSpec());batch_sharding=jax.sharding.NamedSharding(mesh,jax.sharding.PartitionSpec(sharding.DATA_AXIS))
    script=_load_script(OPENPI,'train.py');rng,init=jax.random.split(jax.random.key(42));state,state_sharding=script.init_train_state(config,init,mesh,resume=False)
    manager,_=checkpoints.initialize_checkpoint_dir(config.checkpoint_dir,keep_period=1000,overwrite=False,resume=False)
    class Loader:
        def data_config(self):return data_config
    update=jax.jit(functools.partial(script.train_step,config),in_shardings=(rep,state_sharding,batch_sharding),out_shardings=(state_sharding,rep),donate_argnums=(1,))
    generator=np.random.default_rng(42);started=time.monotonic()
    for step in range(10000):
        ids=generator.integers(len(samples.actions),size=8);batch=jax.tree.map(lambda *a:np.stack(a),*[transform(samples.get(int(i))) for i in ids])
        observation=model.Observation.from_dict(batch);inputs=jax.device_put((observation,batch['actions']),batch_sharding)
        with sharding.set_mesh(mesh):state,metrics=update(rng,state,inputs)
        metrics={k:float(v) for k,v in jax.device_get(metrics).items()}
        if not all(np.isfinite(v) for v in metrics.values()):raise ValueError('comparison_pi_nonfinite_gradient')
        status.update(stage='training',training_started=True,updates=step+1,metrics=metrics,elapsed_seconds=time.monotonic()-started);write(target,status)
        if (step+1)%1000==0:
            checkpoints.save_state(manager,state,Loader(),step);manager.wait_until_finished()
            write(RUN/'pi05'/f'checkpoint_{step+1:06d}.json',dict(status,checkpoint=str(config.checkpoint_dir/str(step))))
    manager.close();write(target,dict(status,stage='trained',checkpoint=str(config.checkpoint_dir/'9999')))

def masks():
    import h5py,mujoco
    from r1pro_teleop.single_tray_3table.control import ThreeTableRuntime
    from r1pro_teleop.airport_fsm.contracts import Config
    from r1pro_teleop.vla.observations import model_render_shape
    from PIL import Image
    sys.path.insert(0,str(Path(__file__).resolve().parent))
    from rerender_pickup_camera_shells import shell_ids,hide_scene_shells
    protocol=json.loads((RUN/'protocol.json').read_text());n=len(np.load(RUN/'cache/action.npy',mmap_mode='r'))
    arrays={c:np.lib.format.open_memmap(RUN/'cache'/f'mask_{c}.npy',mode='w+',dtype=np.uint8,shape=(n,224,224)) for c in CAMERAS};offset=0
    for row in protocol['train']:
        # Re-rendered case links the original immutable trace and scene XML.
        case=Path(row['source_case']);scene=json.loads((case/'scene.json').read_text())
        with h5py.File(case/'attempt/trace.h5') as f:
            meta=json.loads(f.attrs['metadata_json']);cfgfile=RUN/'mask_source_config.json';write(cfgfile,meta['config'])
            runtime=ThreeTableRuntime(scene,Config.load(cfgfile),render=True)
            try:
                ids=shell_ids(runtime.m);tray=runtime.m.body('tray').id;tray_geoms=set(np.flatnonzero(runtime.m.geom_bodyid==tray).tolist())
                renderers={}
                for c in CAMERAS:
                    h,w,_=model_render_shape(runtime.sim.camera_shapes[c],224);r=mujoco.Renderer(runtime.m,height=h,width=w);r.enable_segmentation_rendering();runtime.sim._camera_renderers[('mask',c)]=r;renderers[c]=r
                for frame in range(row['frames']):
                    mujoco.mj_setState(runtime.m,runtime.d,np.asarray(f['integration_state'][frame]),runtime.integration_spec);mujoco.mj_forward(runtime.m,runtime.d)
                    for c,r in renderers.items():
                        r.update_scene(runtime.d,camera=c,scene_option=runtime.sim.options);hide_scene_shells(r.scene,ids,int(mujoco.mjtObj.mjOBJ_GEOM));seg=r.render()
                        mask=(np.isin(seg[...,0],list(tray_geoms))&(seg[...,1]==int(mujoco.mjtObj.mjOBJ_GEOM))).astype(np.uint8)
                        image=Image.fromarray(mask);w,h=image.size;scale=min(224/w,224/h);size=(round(w*scale),round(h*scale));small=image.resize(size,Image.Resampling.NEAREST);padded=Image.new('L',(224,224));padded.paste(small,((224-size[0])//2,(224-size[1])//2));arrays[c][offset+frame]=np.asarray(padded)
            finally:runtime.sim.close()
        offset+=row['frames'];write(RUN/'affordvla/mask_status.json',dict(stage='annotating',frames=offset,target=n,method='simulation_visible_target_tray_silhouette'))
    for array in arrays.values():array.flush()
    write(RUN/'affordvla/mask_status.json',dict(stage='ready',frames=n,method='simulation_visible_target_tray_silhouette',not_RAGNet=True))

def afford_model():
    import torch
    from omegaconf import OmegaConf
    source=RUN/'source/AffordVLA';sys.path.insert(0,str(source))
    from affordvla.model.framework.affordvla import Afford_VLA
    cfg=OmegaConf.load(source/'examples/LIBERO/train_files/affordvla_libero.yaml')
    cfg.framework.qwenvl.base_vlm=str(RUN/'models/Qwen3-VL-4B-Instruct');cfg.framework.qwenvl.attn_implementation='sdpa'
    cfg.framework.action_model.action_dim=19;cfg.framework.action_model.state_dim=19
    cfg.framework.action_model.action_horizon=20;cfg.framework.action_model.future_action_window_size=19
    cfg.framework.affordance_head.max_num_views=3;cfg.trainer.repeated_diffusion_steps=1
    cfg.datasets.vla_data.image_size=[224,224]
    model=Afford_VLA(cfg).cuda();model.qwen_vl_interface.model.config.use_cache=False
    return model,cfg

def attach_afford_lora(model):
    import torch,types
    from peft import LoraConfig,get_peft_model
    base=model.qwen_vl_interface.model
    base.gradient_checkpointing_enable(gradient_checkpointing_kwargs={'use_reentrant':False})
    base.enable_input_require_grads()
    base.model.language_model=get_peft_model(base.model.language_model,LoraConfig(r=16,lora_alpha=32,target_modules=['q_proj','k_proj','v_proj','o_proj'],lora_dropout=0.,bias='none'))
    original_forward=model.action_model.forward;original_predict=model.action_model.predict_action
    # Upstream disables autocast around the action head and converts BF16
    # predictions to NumPy. Owned wrappers restore mixed compute and return FP32.
    def forward(this,*args,**kwargs):
        with torch.autocast('cuda',dtype=torch.bfloat16):return original_forward(*args,**kwargs)
    def predict(this,*args,**kwargs):
        with torch.autocast('cuda',dtype=torch.bfloat16):return original_predict(*args,**kwargs).float()
    model.action_model.forward=types.MethodType(forward,model.action_model)
    model.action_model.predict_action=types.MethodType(predict,model.action_model)
    return model

def train_afford():
    import torch
    from PIL import Image
    torch.manual_seed(42);samples=Samples();model,cfg=afford_model()
    # PEFT variant: actual released Afford-VLA heads/pooling; Qwen LoRA stage2.
    attach_afford_lora(model)
    mask_arrays={c:np.load(RUN/'cache'/f'mask_{c}.npy',mmap_mode='r') for c in CAMERAS}
    generator=np.random.default_rng(42);directory=RUN/'affordvla';directory.mkdir(exist_ok=True)
    from omegaconf import OmegaConf
    OmegaConf.save(cfg,directory/'config.yaml')
    status=dict(stage='initializing',model='AffordVLA',training_started=False,episodes=120,method='two_stage_BC_Qwen_LoRA',source='simulation/program_generated',affordance_supervision='sim_target_silhouette_not_RAGNet',pid=os.getpid(),heartbeat_unix=time.time(),total_target_updates=11000)
    write(directory/'training_status.json',status)
    for stage,steps in ((1,1000),(2,10000)):
        cfg.framework.affordance_head.region_pooling_mode_train=model.region_pooling_mode_train='hard_gt' if stage==1 else 'hard_topk_st_pred'
        cfg.framework.affordance_head.region_pooling_mode_infer=model.region_pooling_mode_infer='hard_topk_pred'
        for name,param in model.named_parameters():
            param.requires_grad_(('affordance_head' in name or name.startswith('aff_queries') or name.startswith('aff_view_embed')) if stage==1 else ('qwen_vl_interface' not in name or 'lora_' in name))
        optimizer=torch.optim.AdamW([p for p in model.parameters() if p.requires_grad],lr=1e-4 if stage==1 else 2.5e-5,betas=(.9,.95),weight_decay=1e-8)
        model.train();started=time.monotonic();rate=None
        status.update(training_stage=stage,stage_updates=0,target_updates=steps,total_completed_updates=0 if stage==1 else 1000,eta_seconds=None)
        write(directory/'training_status.json',status)
        for step in range(steps):
            update_started=time.monotonic()
            optimizer.zero_grad(set_to_none=True);losses=[]
            for micro in range(4):
                ids=generator.integers(len(samples.actions),size=2);examples=[]
                for index in ids:
                    sample=samples.get(int(index));examples.append(dict(image=[Image.fromarray(sample['image/'+c]) for c in CAMERAS],lang=PROMPT,
                        action=samples.standard('actions',sample['actions']),state=samples.standard('state',sample['state'])[None],
                        affordance_mask=[torch.from_numpy(np.asarray(mask_arrays[c][index]).copy()).float().cuda() for c in CAMERAS]))
                with torch.autocast('cuda',dtype=torch.bfloat16):result=model(examples=examples);loss=result['total_loss']/4
                if not torch.isfinite(loss):raise ValueError('comparison_afford_nonfinite_gradient')
                loss.backward();losses.append(float(loss.detach()))
            grad_norm=torch.nn.utils.clip_grad_norm_([p for p in model.parameters() if p.requires_grad],1.)
            if not torch.isfinite(grad_norm):raise ValueError('comparison_afford_nonfinite_grad_norm')
            optimizer.step();torch.cuda.synchronize()
            duration=time.monotonic()-update_started
            rate=duration if rate is None else .1*duration+.9*rate
            status.update(stage='training',training_started=True,training_stage=stage,stage_updates=step+1,target_updates=steps,total_completed_updates=(0 if stage==1 else 1000)+step+1,loss=sum(losses),grad_norm=float(grad_norm),elapsed_seconds=time.monotonic()-started,seconds_per_update_ema=rate,eta_seconds=(steps-step-1)*rate,eta_scope='current_training_stage_only_excludes_evaluation',heartbeat_unix=time.time());write(directory/'training_status.json',status)
            if (step+1)%1000==0:
                checkpoint=directory/f'stage{stage}_{step+1:06d}.pt';temporary=checkpoint.with_suffix('.tmp')
                # Frozen base lives in downloaded model; save all non-Qwen modules
                # and learned Qwen adapters, not a fabricated pretrained model.
                state={k:v.cpu() for k,v in model.state_dict().items() if not k.startswith('qwen_vl_interface.') or 'lora_' in k}
                torch.save(dict(state_dict=state,optimizer=optimizer.state_dict(),stage=stage,updates=step+1,config=OmegaConf.to_container(cfg,resolve=True),normalization=samples.norm),temporary);temporary.replace(checkpoint)
                write(directory/f'checkpoint_stage{stage}_{step+1:06d}.json',dict(status,checkpoint=str(checkpoint),base=str(RUN/'models/Qwen3-VL-4B-Instruct')))
        del optimizer
    write(directory/'training_status.json',dict(status,stage='trained',checkpoint=str(directory/'stage2_010000.pt')))

def evaluate(name):
    import h5py,mujoco
    from r1pro_teleop.airport_fsm.contracts import Config
    from r1pro_teleop.airport_fsm.trace import Trace
    from r1pro_teleop.single_tray_3table.control import ThreeTableRuntime
    from r1pro_teleop.single_tray_3table.learned import contact_snapshot,opposed_contact
    from r1pro_teleop.vla.observations import model_render_shape
    from openpi_client.image_tools import resize_with_pad
    sys.path.insert(0,str(Path(__file__).resolve().parent))
    from rerender_pickup_camera_shells import shell_ids,hide_scene_shells
    from run_vla_fixed_scene import restore_stage,advance_interval,DiagnosticVideoWriter
    protocol=json.loads((RUN/'protocol.json').read_text());samples=Samples()
    if name=='pi05':
        from openpi.policies import policy_config
        config,spec=pi_config();checkpoint=Path(json.loads((RUN/'pi05/training_status.json').read_text())['checkpoint'])
        policy=policy_config.create_trained_policy(config,checkpoint)
        def infer(state,images):return np.asarray(policy.infer(dict(state=state,prompt=PROMPT,**{'image/'+c:images[c] for c in CAMERAS}))['actions'])[:,:19]
    else:
        import torch
        from PIL import Image
        checkpoint=Path(json.loads((RUN/'affordvla/training_status.json').read_text())['checkpoint']);model,cfg=afford_model();attach_afford_lora(model)
        saved=torch.load(checkpoint,map_location='cpu',weights_only=False)
        mismatch=model.load_state_dict(saved['state_dict'],strict=False)
        if mismatch.unexpected_keys or any(not k.startswith('qwen_vl_interface.') for k in mismatch.missing_keys):raise ValueError('comparison_afford_checkpoint_incompatible')
        model.eval();model.region_pooling_mode_infer='hard_topk_pred'
        def infer(state,images):
            with torch.no_grad(),torch.autocast('cuda',dtype=torch.bfloat16):
                predicted=model.predict_action([dict(image=[Image.fromarray(images[c]) for c in CAMERAS],lang=PROMPT,state=samples.standard('state',state)[None])])['normalized_actions'][0]
            norm=samples.norm['actions'];return (predicted*(np.asarray(norm['std'])+1e-6)+np.asarray(norm['mean'])).astype(np.float32)
    destination=RUN/'evaluations'/name;destination.mkdir(parents=True,exist_ok=False);results=[]
    for number,source in enumerate(protocol['heldout']):
        original=Path(source['source_case']);scene=json.loads((original/'scene.json').read_text());case=destination/f'case_{number:03d}';case.mkdir();(case/'videos').mkdir()
        with h5py.File(original/'attempt/trace.h5') as file:metadata=json.loads(file.attrs['metadata_json'])
        configfile=case/'source_config.json';write(configfile,metadata['config']);runtime=None;trace=None;writers={};started=time.monotonic()
        result=dict(model=name,case=number,scene_id=source['scene_id'],checkpoint=str(checkpoint),success=False,strict_success=None,strict_endpoint_success=False,inverse_solver_calls=0,teacher_fallback=False,frames=0,inference_calls=0,source='simulation/program_generated')
        try:
            runtime=ThreeTableRuntime(scene,Config.load(configfile),render=True);origin,_,_=restore_stage(runtime,original/'attempt/trace.h5',0)
            ids=shell_ids(runtime.m);renderers={}
            for c in CAMERAS:
                h,w,_=model_render_shape(runtime.sim.camera_shapes[c],224);r=mujoco.Renderer(runtime.m,height=h,width=w);runtime.sim._camera_renderers[('evaluation',c)]=r;renderers[c]=r
                writers[c]=DiagnosticVideoWriter(case/'videos'/f'{c}.mp4',(224,224,3))
            trace=Trace(case/'attempt',dict(config=runtime.cfg.dump(),scene=scene,source='simulation/program_generated',controller_source='vla_generated',model=name,checkpoint=str(checkpoint),fps=20,integration_state_spec=int(runtime.integration_spec),base_origin=origin.tolist()))
            trace.file.attrs['schema']='airport_pickup120_vla_evaluation_raw/1'
            held=0;chunk=None;cursor=0
            for frame in range(500):
                images={}
                for c,r in renderers.items():
                    r.update_scene(runtime.d,camera=c,scene_option=runtime.sim.options)
                    for flag in (mujoco.mjtRndFlag.mjRND_SHADOW,mujoco.mjtRndFlag.mjRND_REFLECTION):r.scene.flags[flag]=False
                    hide_scene_shells(r.scene,ids,int(mujoco.mjtObj.mjOBJ_GEOM));images[c]=resize_with_pad(r.render().copy(),224,224);writers[c].write(images[c])
                if chunk is None or cursor==5:
                    state=np.r_[runtime.sim.state(),runtime.sim.base_joint_state()-origin].astype(np.float32);chunk=infer(state,images);cursor=0;result['inference_calls']+=1
                    if chunk.shape!=(20,19) or not np.isfinite(chunk).all():raise ValueError('comparison_invalid_model_action_chunk')
                    np.savez_compressed(case/f'decision_{frame:04d}.npz',state=state,raw_actions=chunk,frame=frame)
                row,error=advance_interval(runtime,chunk[cursor],origin,frame);trace.append(row);cursor+=1;result['frames']=trace.count
                if error is not None:raise error
                obs=runtime.observation();contact=contact_snapshot(runtime,scene);clearance=float(obs['min_z'][0]-runtime.initial_bottom[0])
                valid=bool(np.all(obs['gripper_contact_force'][0]>runtime.cfg.criteria.contact_n) and obs['table_contact'][0]==0 and obs['floor_contact'][0]==0 and clearance>=runtime.cfg.criteria.lifted_m and opposed_contact(contact,scene['tray']['size']))
                held=held+1 if valid else 0
                result.update(clearance_m=clearance,held_frames=held)
                if held>=20:
                    result['success']=True
                    tilt=float(np.arccos(np.clip(runtime.d.body('tray').xmat.reshape(3,3)[2,2],-1,1)))
                    result['strict_endpoint_success']=bool(clearance>=runtime.cfg.primitive_lift_m and tilt<=np.deg2rad(runtime.cfg.criteria.tilt_deg))
                    break
        except Exception as error:
            result['error']=repr(error);result['infrastructure_error']=isinstance(error,(KeyError,AttributeError,ImportError,TypeError));(case/'exception.txt').write_text(traceback.format_exc())
        finally:
            for writer in writers.values():writer.close()
            if trace is not None:trace.close(dict(qpos=runtime.d.qpos,qvel=runtime.d.qvel,time=float(runtime.d.time)))
            if runtime is not None:result['inverse_solver_calls']=int(runtime.id_calls);runtime.sim.close()
            result.update(wall_seconds=time.monotonic()-started,sim_seconds=result['frames']/20)
            if result['inverse_solver_calls']:raise ValueError('comparison_forbidden_inverse_fallback')
            write(case/'result.json',result);results.append(result)
            (case/'viewer.html').write_text('<meta charset="utf-8"><h2>'+name+' '+PROMPT+'</h2>'+''.join(f'<video controls width="320" src="videos/{c}.mp4"></video>' for c in CAMERAS))
            write(destination/'progress.json',dict(evaluated=len(results),target=50,successes=sum(r['success'] for r in results)))
    summary=dict(model=name,checkpoint=str(checkpoint),tested=len(results),denominator=50,successes=sum(r['success'] for r in results),strict_successes=None,strict_endpoint_successes=sum(r['strict_endpoint_success'] for r in results),success_rate=sum(r['success'] for r in results)/50,
        scope='pickup_only_same_parent_pose_holdout',teacher_or_ik_fallback=False,video_and_trajectory_directory=str(destination),mean_sim_seconds=float(np.mean([r['sim_seconds'] for r in results])),infrastructure_failures=sum(r.get('infrastructure_error',False) for r in results),valid_model_comparison=not any(r.get('infrastructure_error',False) for r in results),results=results)
    write(destination/'summary.json',summary)

def command(argv,log,env=None):
    with Path(log).open('a') as handle:
        child=subprocess.Popen(argv,env=env,stdin=subprocess.DEVNULL,stdout=handle,stderr=subprocess.STDOUT)
        write(Path(log).with_suffix('.process.json'),dict(pid=child.pid,argv=argv,start_unix=time.time()))
        code=child.wait()
    if code:raise RuntimeError('comparison_child_failed:'+str(code)+':'+str(log))

def setup_afford():
    source=RUN/'source/AffordVLA';source.parent.mkdir(parents=True,exist_ok=True)
    command(['git','clone','--depth','1','https://github.com/RZkiller/AffordVLA.git',str(source)],RUN/'logs/afford_setup.log')
    commit=subprocess.check_output(['git','-C',str(source),'rev-parse','HEAD'],text=True).strip()
    if commit!='870e895931896243fbc784d16d6c278bfec450cd':raise ValueError('afford_reviewed_source_commit_changed')
    envpath=RUN/'conda/affordvla'
    command(['/home/michelle/miniconda3/bin/conda','create','-y','-p',str(envpath),'--clone','/home/michelle/miniconda3/envs/r1pro-vla'],RUN/'logs/afford_setup.log')
    py=str(envpath/'bin/python')
    command([py,'-m','pip','install','transformers==4.57.0','accelerate==1.5.2','peft==0.17.1','qwen-vl-utils','rich','einops','diffusers==0.33.1'],RUN/'logs/afford_setup.log')
    modeldir=RUN/'models/Qwen3-VL-4B-Instruct'
    command([py,'-c',"from huggingface_hub import snapshot_download; snapshot_download('Qwen/Qwen3-VL-4B-Instruct',local_dir="+repr(str(modeldir))+",max_workers=4)"],RUN/'logs/afford_setup.log')
    write(RUN/'afford_setup_status.json',dict(stage='ready',python=py,source_commit=subprocess.check_output(['git','-C',str(source),'rev-parse','HEAD'],text=True).strip(),base_model=str(modeldir)))

def supervise():
    import threading
    RUN.mkdir(parents=True,exist_ok=False);(RUN/'logs').mkdir()
    env=dict(os.environ,CUDA_VISIBLE_DEVICES='1',MUJOCO_GL='egl',MUJOCO_EGL_DEVICE_ID='0',OMP_NUM_THREADS='2',OPENBLAS_NUM_THREADS='2',MKL_NUM_THREADS='2',XLA_PYTHON_CLIENT_MEM_FRACTION='.85',WANDB_MODE='disabled',TOKENIZERS_PARALLELISM='false',JAX_COMPILATION_CACHE_DIR=str(RUN/'jax_cache'))
    status=dict(stage='preparing',training_started=False,server_independent=True,pid=os.getpid(),start_unix=time.time(),models=['pi05','AffordVLA'],train_episodes=120,test_episodes=50)
    write(RUN/'pipeline_status.json',status)
    setup_error=[]
    def setup():
        try:setup_afford()
        except BaseException as error:
            setup_error.append(repr(error));write(RUN/'afford_setup_status.json',dict(stage='failed',error=repr(error)))
    thread=threading.Thread(target=setup);thread.start()
    script=str(Path(__file__).resolve())
    try:
        command([VLA_PY,script,'prepare'],RUN/'logs/prepare.log',env)
        status.update(stage='pi05_initialization_and_training',active_model='pi05');write(RUN/'pipeline_status.json',status)
        command([VLA_PY,script,'pi05'],RUN/'logs/pi05_train.log',env)
        status.update(stage='pi05_evaluation',training_started=True);write(RUN/'pipeline_status.json',status)
        command([VLA_PY,script,'evaluate','--model','pi05'],RUN/'logs/pi05_eval.log',env)
        status.update(stage='waiting_afford_dependencies');write(RUN/'pipeline_status.json',status);thread.join()
        if setup_error:raise RuntimeError(setup_error[0])
        command([VLA_PY,script,'masks'],RUN/'logs/afford_masks.log',env)
        py=json.loads((RUN/'afford_setup_status.json').read_text())['python']
        status.update(stage='affordvla_training',active_model='AffordVLA');write(RUN/'pipeline_status.json',status)
        command([py,script,'affordvla'],RUN/'logs/afford_train.log',env)
        status.update(stage='affordvla_evaluation');write(RUN/'pipeline_status.json',status)
        command([py,script,'evaluate','--model','affordvla'],RUN/'logs/afford_eval.log',env)
        comparison={name:json.loads((RUN/'evaluations'/name/'summary.json').read_text()) for name in ('pi05','affordvla')}
        write(RUN/'comparison.json',comparison);write(RUN/'pipeline_status.json',dict(status,stage='complete',finished_unix=time.time()))
    except BaseException as error:
        write(RUN/'pipeline_status.json',dict(status,stage='failed_preserving_checkpoints_and_evidence',error=repr(error),traceback=traceback.format_exc()))
        raise

def main():
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['supervise','prepare','pi05','masks','affordvla','evaluate']);p.add_argument('--model',choices=['pi05','affordvla']);args=p.parse_args()
    if args.mode=='evaluate':evaluate(args.model)
    else:{'supervise':supervise,'prepare':prepare,'pi05':train_pi,'masks':masks,'affordvla':train_afford}[args.mode]()

if __name__=='__main__':main()
