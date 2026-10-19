"""Official LeRobot v3 export via pinned 0.4.4, native RGB, one canonical store.

Export is NOT a pose animation: initialize replay once, then re-execute every
accepted command. Never reset qpos at every frame to hide simulation divergence.
"""
from __future__ import annotations
from pathlib import Path
from collections import Counter, defaultdict
import contextlib
import importlib.metadata
import json
import math
import os
import shutil
import uuid
import h5py
import numpy as np
from .contracts import CAMERAS, NAMES, BASE_NAMES, ARM_COLUMNS, Fault, atomic_json, fingerprint, sha256_file, camera_shapes
from .registry import config_for, scene_rows, coverage
from .batch import assert_environment
from .geometry import Geometry, placement_ok


def choose_attempts(root):
    root=Path(root);cfg=config_for(root);selected=[]
    for row in scene_rows(root):
        n=0
        for p in sorted((root/'attempts'/row['scene_id']).glob('a*/result.json')):
            result=json.loads(p.read_text())
            if not result.get('physics_success') or result.get('recovery_used') or result.get('diagnostic_only'):continue
            directory=p.parent
            if not (directory/'trace.h5').is_file():continue
            quality=directory/'export_quality.json'
            if quality.exists() and json.loads(quality.read_text()).get('status')=='rejected':continue
            selected.append({'scene_id':row['scene_id'],'split':row['split'],'attempt':directory.name,
                             'trace':str(directory/'trace.h5'),'trace_sha256':sha256_file(directory/'trace.h5'),
                             'result':str(p),'result_sha256':sha256_file(p)})
            n+=1
            if n>=cfg.successes_per_scene:break
    return selected


def validate_trace(path, spec, cfg):
    with h5py.File(path) as f:
        schema=f.attrs.get('schema')
        if schema not in ('airport_fsm_raw/1','airport_fsm_raw/2'):raise Fault('raw_schema_mismatch')
        metadata=json.loads(f.attrs['metadata_json'])
        expected_schema='airport_fsm_raw/2' if (metadata.get('config',{}).get('substep_control_enabled',False) or metadata.get('recorded_substep_controls_without_interpolation') is True) else 'airport_fsm_raw/1'
        if schema!=expected_schema:raise Fault('raw_control_semantics_mismatch')
        if metadata['scene_id']!=spec['scene_id'] or metadata['split']!=spec['split']:raise Fault('raw_scene_identity_mismatch')
        if fingerprint(metadata['scene'])!=fingerprint(spec):raise Fault('raw_scene_spec_changed')
        n=int(f.attrs['num_frames'])
        if n<2 or any(len(v)!=n for v in f.values()):raise Fault('raw_length_mismatch')
        for key in ('qpos','qvel','qacc_warmstart','integration_state','state','action','base_action','timestamp','tray_pose'):
            if not np.isfinite(f[key][:]).all():raise Fault('nonfinite_raw',key)
        if not np.all(f['transition_completed'][:]):raise Fault('incomplete_control_interval')
        if schema=='airport_fsm_raw/2':
            substeps=int(metadata.get('substeps_per_frame',0))
            if (substeps<1 or 'ctrl_substeps' not in f or 'executed_substeps' not in f or
                    f['ctrl_substeps'].ndim!=3 or f['ctrl_substeps'].shape[:2]!=(n,substeps) or
                    f['ctrl_substeps'].dtype!=np.dtype('float64') or
                    f['executed_substeps'].shape!=(n,) or
                    not np.all(f['executed_substeps'][:]==substeps) or
                    not np.isfinite(f['ctrl_substeps'][:]).all()):
                raise Fault('invalid_substep_control_trace')
        if f['state'].shape!=(n,16) or f['action'].shape!=(n,16) or f['base_action'].shape!=(n,3):raise Fault('action_shape_mismatch')
        if f['state'].dtype!=np.float32 or f['action'].dtype!=np.float32:raise Fault('action_dtype_mismatch')
        if not np.allclose(f['timestamp'][:],np.arange(n)/20,atol=1e-8):raise Fault('timestamp_grid_mismatch')
        if not np.allclose(np.diff(f['sim_time'][:]),.05,atol=1e-8):raise Fault('simulation_time_grid_mismatch')
        for name in ('state','action'):
            a=f[name][:,[7,15]]
            if np.any(a<0) or np.any(a>.105):raise Fault('invalid_gripper_units_or_opening',name)
        values={k:v[:] for k,v in f.items() if k in ('qpos','qvel','action','base_action','tray_pose','floor_contact','illegal_collision','max_penetration','wrist_violation','transition_completed','table_contact','gripper_contact_force','state')}
        passed,report=placement_ok(values,Geometry(spec),cfg.criteria,20)
        if not passed:raise Fault('export_task_revalidation_failed',report)
        return {'frames':n,'metadata':metadata,'acceptance':report}


class Replay:
    def __init__(self, root, source, *, diagnostic=False, spec=None, cfg=None, xml=None, geometry=None, render=True, before_frame=None):
        from .runtime import Runtime
        self.root=Path(root);self.source=source;self.path=Path(source['trace'])
        self.spec=json.loads((self.root/'scenes'/source['scene_id']/'scene.json').read_text()) if spec is None else spec
        self.cfg=config_for(root) if cfg is None else cfg
        self.shapes=camera_shapes(self.spec)
        runtime_kwargs={'render':render}
        if geometry is not None:runtime_kwargs['geometry']=geometry
        self.runtime=Runtime(self.spec,self.root/'scenes'/source['scene_id']/'mobile.xml' if xml is None else xml,self.cfg,**runtime_kwargs)
        self.f=h5py.File(self.path,'r')
        self.schema=self.f.attrs.get('schema')
        if self.schema not in ('airport_fsm_raw/1','airport_fsm_raw/2'):
            raise Fault('raw_schema_mismatch')
        self.n=int(self.f.attrs['num_frames']);self.maximum_error=0.;self.blank=Counter();self.diagnostic=diagnostic
        self.errors={key:0. for key in ('qpos','qvel','time','terminal_qpos','terminal_qvel','terminal_time')}
        self.terminal_checked=False
        self.before_frame=before_frame
        self.render_images=render
        self.camera_checks={name:{'frames':0,'shape':list(self.shapes[name]),'blank_frames':0} for name in self.shapes}
        r=self.runtime
        metadata=json.loads(self.f.attrs['metadata_json'])
        expected_schema='airport_fsm_raw/2' if (metadata.get('config',{}).get('substep_control_enabled',False) or metadata.get('recorded_substep_controls_without_interpolation') is True) else 'airport_fsm_raw/1'
        if self.schema!=expected_schema:raise Fault('raw_control_semantics_mismatch')
        if self.schema=='airport_fsm_raw/2':
            if ('ctrl_substeps' not in self.f or 'executed_substeps' not in self.f or
                    self.f['ctrl_substeps'].shape!=(self.n,r.sim.nstep,r.m.nu) or
                    self.f['ctrl_substeps'].dtype!=np.dtype('float64') or
                    self.f['executed_substeps'].shape!=(self.n,) or
                    metadata.get('substeps_per_frame')!=r.sim.nstep or
                    not np.isclose(metadata.get('physics_timestep_s',0),r.m.opt.timestep,rtol=0,atol=1e-12)):
                raise Fault('invalid_substep_control_trace')
        if metadata['scene_xml_sha256']!=sha256_file(r.sim.scene):raise Fault('replay_scene_hash_mismatch')
        if fingerprint(metadata['limits'])!=fingerprint(r.limits):raise Fault('replay_limit_profile_mismatch')
        # Exact initial integration state includes ctrl, actuator activation,
        # warmstart, mocap and applied forces where present in the model.
        r.mj.mj_setState(r.m,r.d,self.f['integration_state'][0],r.integration_spec)
        r.mj.mj_forward(r.m,r.d)
        r.d.qacc_warmstart[:]=self.f['qacc_warmstart'][0]

    def __iter__(self):
        r=self.runtime
        for i in range(self.n):
            if self.before_frame is not None:self.before_frame(i,r)
            error=float(np.max(np.abs(r.d.qpos-self.f['qpos'][i])))
            velocity_error=float(np.max(np.abs(r.d.qvel-self.f['qvel'][i])))
            self.errors['qpos']=max(self.errors['qpos'],error);self.errors['qvel']=max(self.errors['qvel'],velocity_error)
            self.errors['time']=max(self.errors['time'],abs(r.d.time-float(self.f['sim_time'][i])))
            self.maximum_error=max(self.maximum_error,error)
            if error>self.cfg.replay_tolerance or velocity_error>self.cfg.replay_tolerance*10:
                raise Fault('replay_diverged',{'frame':i,'qpos_error':error,'qvel_error':velocity_error})
            if abs(r.d.time-float(self.f['sim_time'][i]))>1e-8:raise Fault('replay_time_mismatch',i)
            images={}
            for name in self.shapes if self.render_images else ():
                image=r.sim.image(name)
                if image.shape!=self.shapes[name] or image.dtype!=np.uint8:raise Fault('render_native_contract_mismatch',name)
                self.camera_checks[name]['frames']+=1
                if float(image.std())<2:
                    self.camera_checks[name]['blank_frames']+=1
                    self.blank[name]+=1
                    if not self.diagnostic:raise Fault('camera_low_texture_needs_review',{'camera':name,'frame':i,'note':'No crop, replacement, black-frame removal or relabelling was performed'})
                images[name]=image
            yield i,images
            # Failed diagnostic intervals are kept as the final visible source
            # observation; they are never eligible for training export.
            if not bool(self.f['transition_completed'][i]):
                if self.diagnostic:
                    if self.schema=='airport_fsm_raw/2':self._replay_substeps(i,complete=False)
                    break
                raise Fault('incomplete_control_interval',i)
            r.sim.target=self.f['action'][i].astype(np.float32)
            r.sim.base_target=self.f['base_action'][i].astype(np.float32)
            if self.schema=='airport_fsm_raw/2':
                self._replay_substeps(i,complete=True)
            else:
                r.sim.apply_target()
                for _ in range(r.sim.nstep):
                    r.mj.mj_step(r.m,r.d)
                    r.mj.mj_forward(r.m,r.d)
            if not np.isfinite(r.d.qpos).all():raise Fault('nonfinite_replay')
        if self.before_frame is not None:self.before_frame(self.n,r)
        terminal=json.loads(self.f.attrs['terminal_snapshot_json'])
        if bool(np.all(self.f['transition_completed'][:])) or self.schema=='airport_fsm_raw/2':
            self.errors['terminal_qpos']=float(np.max(np.abs(r.d.qpos-np.asarray(terminal['qpos']))))
            self.errors['terminal_qvel']=float(np.max(np.abs(r.d.qvel-np.asarray(terminal['qvel']))))
            self.errors['terminal_time']=abs(r.d.time-float(terminal['time']))
            self.terminal_checked=True
            if self.errors['terminal_qpos']>self.cfg.replay_tolerance or self.errors['terminal_qvel']>self.cfg.replay_tolerance*10 or self.errors['terminal_time']>1e-8:raise Fault('terminal_replay_diverged',self.errors)
        if not self.diagnostic or self.schema=='airport_fsm_raw/2':
            err=float(np.max(np.abs(r.d.qpos-np.asarray(terminal['qpos']))))
            self.maximum_error=max(self.maximum_error,err)
            if err>self.cfg.replay_tolerance:raise Fault('terminal_replay_diverged',err)
            if self.schema=='airport_fsm_raw/2':
                if (np.max(np.abs(r.d.qvel-np.asarray(terminal['qvel'])))>self.cfg.replay_tolerance*10 or
                        abs(r.d.time-float(terminal['time']))>1e-8):
                    raise Fault('terminal_replay_diverged','velocity_or_time')

    def close(self):
        self.f.close();self.runtime.close()

    def _replay_substeps(self,index,*,complete):
        r=self.runtime
        count=int(self.f['executed_substeps'][index])
        controls=self.f['ctrl_substeps'][index]
        if (count<0 or count>r.sim.nstep or (complete and count!=r.sim.nstep) or
                not np.isfinite(controls[:count]).all()):
            raise Fault('invalid_substep_control_trace',{'frame':index,'count':count})
        for control in controls[:count]:
            r.d.ctrl[:]=control
            r.mj.mj_step(r.m,r.d)
            r.mj.mj_forward(r.m,r.d)
    def __enter__(self):return self
    def __exit__(self,*_):self.close()


def video_metadata(directory, shapes):
    import av
    result=[]
    for p in sorted(Path(directory).rglob('*.mp4')):
        with av.open(str(p)) as container:
            stream=container.streams.video[0]
            fps=float(stream.average_rate) if stream.average_rate else None
            key=next((name for name in shapes if name in p.as_posix()),None)
            if key is None:raise Fault('encoded_video_camera_unknown',str(p))
            height,width,_=shapes[key]
            if (stream.width,stream.height)!=(width,height) or fps!=20. or stream.codec_context.name!='h264':
                raise Fault('encoded_video_contract_mismatch',str(p))
            frames=int(stream.frames)
            if frames<=0:frames=sum(1 for _ in container.decode(video=0))
            result.append({'file':p.relative_to(directory).as_posix(),'camera':key,'width':stream.width,'height':stream.height,
                           'fps':fps,'frames':frames,'codec':stream.codec_context.name})
    if not result:raise Fault('no_encoded_videos')
    return result


# 只导出有来源证据的 Episode；官方 loader 和原生视频检查通过后才发布。
def export_shard(root, sources, *, layout, repo_prefix):
    from lerobot.datasets.lerobot_dataset import LeRobotDataset
    root=Path(root);cfg=config_for(root)
    if len({s['split'] for s in sources})!=1:raise Fault('mixed_split_shard')
    split=sources[0]['split']
    identity=fingerprint({'sources':sources,'layout':layout,'version':1,'collection':json.loads((root/'collection.json').read_text())['fingerprint']})[:16]
    name=f'shard_{identity}';parent=root/'datasets'/layout/split;parent.mkdir(parents=True,exist_ok=True)
    destination=parent/name
    if destination.exists():
        manifest=destination/'source_manifest.json'
        if manifest.exists():return json.loads(manifest.read_text())
        raise Fault('unfinalized_existing_shard',str(destination))
    temporary=parent/(name+'.partial_'+uuid.uuid4().hex[:8])
    repo_id=repo_prefix.rstrip('/')+'-'+split+'-'+identity
    dim=16 if layout=='legacy16' else 19
    first_spec=json.loads((root/'scenes'/sources[0]['scene_id']/'scene.json').read_text())
    shapes=camera_shapes(first_spec)
    for source in sources[1:]:
        spec=json.loads((root/'scenes'/source['scene_id']/'scene.json').read_text())
        if camera_shapes(spec)!=shapes:raise Fault('mixed_camera_contract_shard',source['scene_id'])
    features={'observation.state':{'dtype':'float32','shape':(16,),'names':NAMES},
              'action':{'dtype':'float32','shape':(dim,),'names':NAMES+(BASE_NAMES if dim==19 else [])}}
    if dim==16:features['action.base']={'dtype':'float32','shape':(3,),'names':BASE_NAMES}
    for name in shapes:
        features['observation.images.'+name]={'dtype':'video','shape':shapes[name],'names':['height','width','channels']}
    ds=None;episode_sources=[];offset=0;current_source=None
    try:
        ds=LeRobotDataset.create(repo_id=repo_id,fps=20,root=temporary,robot_type='r1pro_mujoco_sim',
                                 features=features,use_videos=True,vcodec='h264',video_backend='pyav',
                                 image_writer_threads=2,streaming_encoding=True)
        encoder=getattr(ds,'_streaming_encoder',None)
        if encoder is None or not hasattr(encoder,'crf'):raise Fault('pinned_lerobot_encoder_api_changed')
        encoder.crf=18
        for episode_index,source in enumerate(sources):
            current_source=source
            spec=json.loads((root/'scenes'/source['scene_id']/'scene.json').read_text())
            checked=validate_trace(source['trace'],spec,cfg)
            with Replay(root,source) as replay:
                for i,images in replay:
                    state=replay.f['state'][i]
                    arm=replay.f['action'][i]
                    base=replay.f['base_action'][i]
                    frame={'observation.state':state,'action':np.r_[arm,base].astype(np.float32) if dim==19 else arm,
                           'task':'Arrange all three empty airport security trays into the left-aligned belt slots'}
                    if dim==16:frame['action.base']=base
                    frame.update({'observation.images.'+k:v for k,v in images.items()})
                    ds.add_frame(frame)
                ds.save_episode()
                entry={**source,'episode_index':episode_index,'dataset_start_frame':offset,
                       'dataset_end_frame':offset+replay.n,'frames':replay.n,
                       'replay_max_qpos_error':replay.maximum_error,'cameras':replay.camera_checks,
                       'raw_schema':replay.schema,
                       'action_semantics':str(replay.f.attrs['observation_semantics']),
                       'exact_actuator_replay_source':('raw ctrl_substeps with executed_substeps' if replay.schema=='airport_fsm_raw/2' else 'held 20Hz action')}
                episode_sources.append(entry);offset+=replay.n
        ds.finalize()
        ds.stop_image_writer();ds=None
        # Validate official loader at BOTH ends of EVERY episode, not only files.
        loaded=LeRobotDataset(repo_id=repo_id,root=temporary,video_backend='pyav')
        if len(loaded)!=offset:raise Fault('lerobot_frame_count_mismatch')
        for e in episode_sources:
            for index in (e['dataset_start_frame'],e['dataset_end_frame']-1):
                sample=loaded[index]
                if tuple(sample['action'].shape)!=(dim,):raise Fault('loader_action_shape')
                for camera in shapes:
                    h,w,_=shapes[camera]
                    if tuple(sample['observation.images.'+camera].shape)!=(3,h,w):raise Fault('loader_native_resolution')
        videos=video_metadata(temporary,shapes)
        total_video_frames=sum(v['frames'] for v in videos)
        if total_video_frames!=len(shapes)*offset:raise Fault('encoded_frame_count_mismatch',{'actual':total_video_frames,'expected':len(shapes)*offset})
        result={'schema':'airport_fsm_lerobot_shard/1','complete':True,'path':str(destination.relative_to(root)),
                'repo_id':repo_id,'split':split,'scene_ids':[e['scene_id'] for e in episode_sources],
                'sources':episode_sources,'frames':offset,'episodes':len(sources),
                'controller_source':'program_generated','environment_source':'simulation','human_demonstration':False,
                'lerobot_version':'0.4.4','dataset_format':'v3','loader_every_episode_first_last':True,
                'action_layout':layout,'action_dimension':dim,'raw_arm_action_dimension':16,
                'action_control_semantics':'See each source action_semantics; raw/2 endpoint reference is not a zero-order-held actuator command. Preserve raw actuator journal for exact physics replay.',
                'base_action_semantics':'simulated planar joint absolute targets: world dx/dy from initial origin, yaw offset from initial heading; NOT real chassis cmd_vel',
                'base_action_consumed_by_default_16d_policy':False if dim==16 else None,
                'real_base_driver_available':False,'privileged_state_as_observation':False,
                'native_camera_contract':{'streams':{k:{'width':v[1],'height':v[0]} for k,v in shapes.items()},'fps':20,'codec':'h264','crf':18,'crop':False,'resize':False,'speedup':False,'overlay':False},
                'camera_calibration':first_spec.get('camera',{}),
                'videos':videos,'normalization':'Compute from train shards only; validation/test remain separate',
                'recovery_episodes_in_ordinary_bc':False,'physics_engine':json.loads((root/'dependencies.json').read_text())['physics_environment']}
        result['files'] = {p.relative_to(temporary).as_posix(): {'sha256': sha256_file(p), 'bytes': p.stat().st_size}
                           for p in sorted(temporary.rglob('*')) if p.is_file()}
        atomic_json(temporary/'source_manifest.json',result)
        del loaded
        os.replace(temporary,destination)
        for e in episode_sources:
            attempt=Path(e['trace']).parent
            atomic_json(attempt/'media_reference.json',{'dataset':result['path'],'repo_id':repo_id,
                        'episode_index':e['episode_index'],'source_frame_interval':[0,e['frames']],
                        'dataset_frame_interval':[e['dataset_start_frame'],e['dataset_end_frame']],
                        'camera_keys':['observation.images.'+c for c in shapes],
                        'canonical_video_storage':True,'additional_skill_video_copies':False})
            atomic_json(attempt/'export_quality.json',{'status':'accepted','scene_id':e['scene_id'],'split':split,
                        'loader_every_episode_first_last':True,'replay_max_qpos_error':e['replay_max_qpos_error'],
                        'cameras':e['cameras'],'training_candidate':True})
        return result
    except Exception as exc:
        atomic_json(temporary.with_suffix('.failure.json'),{'error':str(exc),'failure_code':exc.code if isinstance(exc,Fault) else 'export_exception','source':current_source,'quarantined_path':str(temporary)})
        if current_source and isinstance(exc,Fault) and exc.code in ('camera_low_texture_needs_review','replay_diverged','terminal_replay_diverged','export_task_revalidation_failed','invalid_gripper_units_or_opening'):
            atomic_json(Path(current_source['trace']).parent/'export_quality.json',{'status':'rejected','failure_code':exc.code,'error':str(exc),'training_candidate':False})
        raise
    finally:
        if ds is not None:
            with contextlib.suppress(Exception):ds.stop_image_writer()


def export_collection(root, *, shard_size=8, layout='mobile19', repo_prefix='local/r1pro-airport'):
    root=Path(root).resolve();assert_environment(root)
    if importlib.metadata.version('lerobot')!='0.4.4':raise Fault('lerobot_version_mismatch','Use the existing pinned lerobot==0.4.4 environment')
    if layout not in ('legacy16','mobile19'):raise ValueError('Unknown action layout')
    catalog_path=root/'datasets/catalog.json'
    catalog=json.loads(catalog_path.read_text()) if catalog_path.exists() else {'action_layout':layout,'shards':[],'failures':[]}
    if catalog['action_layout']!=layout:raise Fault('mixed_action_layout','Use a new collection for a different training action schema')
    known={(e['scene_id'],e['attempt']) for s in catalog['shards'] for e in s['sources']}
    pending=[e for e in choose_attempts(root) if (e['scene_id'],e['attempt']) not in known]
    failures=[]
    for split in ('train','val','test'):
        entries=[e for e in pending if e['split']==split]
        for offset in range(0,len(entries),shard_size):
            group=entries[offset:offset+shard_size]
            try:
                shard=export_shard(root,group,layout=layout,repo_prefix=repo_prefix)
                catalog['shards'].append(shard);atomic_json(catalog_path,catalog)
                print(json.dumps({'exported_shard':shard['path'],'scenes':shard['scene_ids'],'frames':shard['frames']}),flush=True)
            except Exception as exc:
                # Isolate the faulty scene; do not discard seven healthy episodes
                # just because one scene in an eight-episode shard was rejected.
                for entry in group:
                    if len(group)==1:
                        error=exc
                    else:
                        try:
                            shard=export_shard(root,[entry],layout=layout,repo_prefix=repo_prefix)
                            catalog['shards'].append(shard);atomic_json(catalog_path,catalog);continue
                        except Exception as single:error=single
                    failures.append({'scene_id':entry['scene_id'],'attempt':entry['attempt'],'error':str(error)})
                catalog['failures']=failures;atomic_json(catalog_path,catalog)
    aggregate_views(root)
    report=coverage(root);report['export_failures_this_run']=failures
    atomic_json(root/'quality/export_summary.json',report)
    return report


def verify_catalog(root):
    root = Path(root).resolve()
    path = root/'datasets/catalog.json'
    if not path.exists(): return {'shards':0,'verified_files':0}
    catalog = json.loads(path.read_text());count=0
    for shard in catalog['shards']:
        directory=(root/shard['path']).resolve()
        if not directory.is_relative_to(root/'datasets'): raise Fault('dataset_path_escape')
        if not shard.get('complete') or not shard.get('loader_every_episode_first_last'): raise Fault('unvalidated_catalog_shard')
        for name,info in shard.get('files',{}).items():
            file=(directory/name).resolve()
            if not file.is_relative_to(directory) or not file.is_file() or file.stat().st_size!=info['bytes'] or sha256_file(file)!=info['sha256']:
                raise Fault('dataset_artifact_checksum_mismatch',str(file))
            count+=1
        if not shard.get('files'):raise Fault('missing_dataset_checksums')
    result={'shards':len(catalog['shards']),'verified_files':count}
    atomic_json(root/'quality/dataset_hash_validation.json',result)
    return result


def aggregate_views(root):
    root=Path(root);views={k:[] for k in ('adjust','pick','place','full_arrangement','recovery')}
    counts=defaultdict(lambda:defaultdict(lambda:{'count':0,'duration_s':0.}))
    for row in scene_rows(root):
        for rp in sorted((root/'attempts'/row['scene_id']).glob('a*/result.json')):
            result=json.loads(rp.read_text());directory=rp.parent;sp=directory/'segments.json'
            if not sp.exists():continue
            segments=json.loads(sp.read_text());media=directory/'media_reference.json'
            q=directory/'export_quality.json'
            exported=media.exists() and q.exists() and json.loads(q.read_text()).get('status')=='accepted'
            reference=json.loads(media.read_text()) if exported else None
            views['full_arrangement'].append({'scene_id':row['scene_id'],'split':row['split'],'episode_id':row['scene_id']+'/'+directory.name,
                  'start_frame':0,'end_frame':result['frames'],'raw':str((directory/'trace.h5').relative_to(root)),
                  'media':reference,'physics_success':result.get('physics_success',False),'recovery':result.get('recovery_used',False),
                  'task_completed':result.get('task_completed',result.get('physics_success',False)),
                  'strict_success':result.get('strict_success',result.get('physics_success',False)),
                  'acceptance_profile':result.get('acceptance_profile','strict'),
                  'training_candidate':exported and result.get('training_candidate',False)})
            for seg in segments:
                seg['raw']=str((directory/'trace.h5').relative_to(root));seg['media']=reference
                seg['training_candidate']=bool(exported and seg.get('training_candidate'))
                if seg['primary_class'] in views:views[seg['primary_class']].append(seg)
                if seg['recovery']:views['recovery'].append(seg)
                duration=(seg['end_frame']-seg['start_frame'])/20
                for key in ('skill','phase','state','controller_source','environment_source'):
                    d=counts[key][str(seg[key])];d['count']+=1;d['duration_s']+=duration
    for name,value in views.items():atomic_json(root/'views'/(name+'.json'),value)
    atomic_json(root/'quality/segments.json',{'counts':dict(counts),'views':{k:len(v) for k,v in views.items()},'copied_skill_videos':False})
    return views


def diagnostic_video(root, scene_id, attempt):
    """Original-resolution failure replay; separate from all training manifests."""
    import av
    root=Path(root);directory=root/'attempts'/scene_id/attempt
    out=directory/'diagnostic_native_video';out.mkdir(exist_ok=False)
    source={'scene_id':scene_id,'trace':str(directory/'trace.h5')}
    spec=json.loads((root/'scenes'/scene_id/'scene.json').read_text());shapes=camera_shapes(spec)
    containers={};streams={}
    try:
        for camera in shapes:
            container=av.open(str(out/(camera+'.mp4')),mode='w')
            height,width,_=shapes[camera]
            stream=container.add_stream('libx264',rate=20);stream.width=width;stream.height=height
            stream.pix_fmt='yuv420p';stream.options={'crf':'18','preset':'fast'}
            containers[camera]=container;streams[camera]=stream
        with Replay(root,source,diagnostic=True) as replay:
            for i,images in replay:
                for camera,image in images.items():
                    frame=av.VideoFrame.from_ndarray(image,format='rgb24');frame.pts=i
                    for packet in streams[camera].encode(frame):containers[camera].mux(packet)
            for camera in shapes:
                for packet in streams[camera].encode():containers[camera].mux(packet)
            atomic_json(out/'source.json',{'source_trace':str(directory/'trace.h5'),'fps':20,
                         'streams':{k:{'width':v[1],'height':v[0]} for k,v in shapes.items()},
                         'training_candidate':False,'blank_frames_retained':dict(replay.blank),'crop':False,'resize':False,'speedup':False})
    finally:
        for container in containers.values():container.close()
