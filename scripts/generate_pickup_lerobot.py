"""Independent parallel pickup-only teacher data, single-writer LeRobot v2.1.

Successful episodes contain approach, physical opposed grasp and actual lift.
They are NOT completed three-action tasks. No current campaign is modified.
"""
from __future__ import annotations
import argparse, copy, hashlib, json, math, os, subprocess, sys, time, traceback
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, os.environ.get('VLA_CODE_ROOT', str(ROOT)))
PROMPT = 'Pick up the tray'
CAMERAS = ('head_left', 'left_wrist', 'right_wrist')


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(8*1024*1024),b''):h.update(b)
    return h.hexdigest()


def write(path, value):
    p=Path(path);tmp=p.with_suffix('.tmp')
    tmp.write_text(json.dumps(value,indent=2,allow_nan=False));tmp.replace(p)


def variant(template, directory, index, seed):
    import mujoco
    from r1pro_teleop.airport_fsm.geometry import rectangle,rz
    scene=copy.deepcopy(template);rng=np.random.default_rng(seed+index)
    source_xml=Path(template['xml']);root=ET.parse(source_xml).getroot()
    model=mujoco.MjModel.from_xml_path(str(source_xml))
    table=next(t for t in scene['tables'] if t['table_id']==scene['source_table'])
    center=np.asarray(table['center_world'][:2]);rotation=rz(table['yaw_world'])[:2,:2]
    original=np.asarray(template['initial_tray_pose']['position_world'])
    for _ in range(100):
        position=original+rng.uniform([-.003,-.08,0],[.003,.08,0])
        yaw=template['initial_tray_pose']['yaw_world']+rng.uniform(-math.radians(2),math.radians(2))
        corners=rectangle(position,yaw,scene['tray']['size'])
        if np.all(np.abs((corners-center)@rotation)<=np.asarray(table['dimensions_m'][:2])/2-.008):break
    else:raise ValueError('pickup_variant_table_footprint_sampling_failed')
    quat=[math.cos(yaw/2),0,0,math.sin(yaw/2)]
    fmt=lambda a:' '.join(format(float(v),'.15g') for v in a)
    root.find('.//body[@name="tray"]').set('pos',fmt(position))
    root.find('.//body[@name="tray"]').set('quat',fmt(quat))
    # Track tray translation in the declared table-front base INITIAL station.
    base=np.asarray(template['initial_robot_pose']['position_world'])+position-original
    base[2]=0
    root.find('.//body[@name="base_link"]').set('pos',fmt(base))
    qadr=int(model.jnt_qposadr[model.joint(scene['tray']['joint']).id])
    for key in root.findall('./keyframe/key'):
        q=np.fromstring(key.get('qpos',''),sep=' ')
        if q.size!=model.nq:raise ValueError('pickup_full_initial_keyframe_required')
        q[qadr:qadr+7]=np.r_[position,quat];key.set('qpos',fmt(q))
    compiler=root.find('compiler')
    for key in ('meshdir','texturedir'):
        if compiler is not None and compiler.get(key):
            compiler.set(key,str((source_xml.parent/compiler.get(key)).resolve()))
    for node in root.findall('.//include'):
        if node.get('file'):node.set('file',str((source_xml.parent/node.get('file')).resolve()))
    for node in root.iter():
        file=node.get('file')
        if file and not Path(file).is_absolute():
            asset_base=source_xml.parent
            directory_key={'mesh':'meshdir','texture':'texturedir'}.get(node.tag)
            if directory_key and compiler is not None and compiler.get(directory_key):asset_base=Path(compiler.get(directory_key))
            node.set('file',str((asset_base/file).resolve()))
    path=directory/'mobile.xml';ET.ElementTree(root).write(path,encoding='unicode')
    scene['xml']=str(path.resolve());scene['xml_sha256']=sha(path)
    scene['scene_id']=template['scene_id']+'__pickup_'+str(seed+index)
    scene['seed']=seed+index
    scene['initial_tray_pose'].update(position_world=position.tolist(),yaw_world=float(yaw))
    scene['initial_robot_pose']['position_world']=base.tolist()
    scene['tray'].update(position=position.tolist(),yaw=float(yaw))
    scene['legacy_spec'].update(xml=scene['xml'],xml_sha256=scene['xml_sha256'],scene_id=scene['scene_id'],seed=scene['seed'])
    scene['legacy_spec']['trays'][0].update(position_world=position.tolist(),yaw_world=float(yaw))
    scene['pickup_scope']=dict(scope='pickup_only_partial_task_v1',parent_scene_id=template['scene_id'],split=template['split'],position_xy_range_m=[.003,.08],yaw_delta_degrees=2,base_follows_initial_tray_translation=True)
    write(directory/'scene.json',scene)
    return scene


def collect(args,index):
    import h5py
    from openpi_client.image_tools import resize_with_pad
    from r1pro_teleop.airport_fsm.contracts import Config,State
    from r1pro_teleop.single_tray_3table.control import ThreeTableRuntime,ThreeTableMachine
    from r1pro_teleop.single_tray_3table.learned import contact_snapshot,opposed_contact
    from r1pro_teleop.vla.observations import render_model_observation
    import importlib.util
    spec=importlib.util.spec_from_file_location('pickup_rgb_writer',ROOT/'scripts/run_vla_fixed_scene.py')
    helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)
    case=Path(args.output)/'cases'/f'case_{index:04d}';case.mkdir(parents=True,exist_ok=False)
    result=dict(scope='pickup_only_partial_task_v1',source='simulation/program_generated',prompt=PROMPT,pickup_success=False,task_completed=None,training_eligible=False,index=index,frames=0)
    runtime=machine=None;writers={};start=time.monotonic();pending={}
    try:
        template=json.loads((Path(args.template_source)/'scene/scene.json').read_text())
        scene=variant(template,case,index,args.seed);cfg=Config.load(args.config)
        runtime=ThreeTableRuntime(scene,cfg,render=True)
        runtime.record_ctrl_substeps=True
        machine=ThreeTableMachine(runtime,case/'attempt',scene)
        machine.log.file.attrs['schema']='airport_fsm_raw/2'
        metadata=json.loads(machine.log.file.attrs['metadata_json'])
        metadata.update(source='simulation/program_generated',scope='pickup_only_partial_task_v1',
                        integration_state_spec=int(runtime.integration_spec),recorded_substep_controls_without_interpolation=not cfg.substep_control_enabled)
        machine.log.file.attrs['metadata_json']=json.dumps(metadata)
        origin=runtime.sim.base_joint_state().copy();initial=runtime.d.body('tray').xpos.copy()
        if not np.allclose(initial,scene['initial_tray_pose']['position_world'],atol=1e-9,rtol=0):raise ValueError('pickup_variant_keyframe_not_applied')
        result.update(scene_id=scene['scene_id'],split=scene['split'],seed=scene['seed'],initial_tray_position=initial.tolist(),initial_yaw=scene['initial_tray_pose']['yaw_world'],xml_sha256=scene['xml_sha256'])
        (case/'videos').mkdir()
        for camera in CAMERAS:writers[camera]=helper.DiagnosticVideoWriter(case/'videos'/f'{camera}.mp4',(224,224,3))
        original_tick=runtime.tick;original_append=machine.log.append
        def append(row):
            row=dict(row,state19=pending['state'],action19=np.r_[row['action'],row['base_action']].astype(np.float32))
            original_append(row)
        machine.log.append=append
        def tick(**kwargs):
            pending['state']=np.r_[runtime.sim.state(),runtime.sim.base_joint_state()-origin].astype(np.float32)
            images={c:resize_with_pad(render_model_observation(runtime.sim,c,224),224,224) for c in CAMERAS}
            try:return original_tick(**kwargs)
            finally:
                for c,w in writers.items():w.write(images[c])
        runtime.tick=tick
        runtime.allowed_tray=0;runtime.target_slot=0
        machine.transition(State.ALIGN_BASE,'initial_posture',tray=0,slot=0)
        runtime.joints(runtime.tucked,minimum_seconds=.3)
        face,offset=machine.prepare_pick(0,0);machine.grasp(0,face,offset)
        for _ in range(3):runtime.tick()
        obs=runtime.observation();snapshot=contact_snapshot(runtime,scene)
        forces=np.asarray(obs['gripper_contact_force'])[0]
        clearance=float(obs['min_z'][0]-runtime.initial_bottom[0])
        complete=bool(np.all(forces>cfg.criteria.contact_n) and obs['table_contact'][0]==0 and obs['floor_contact'][0]==0 and clearance>=cfg.criteria.lifted_m and opposed_contact(snapshot,scene['tray']['size']))
        result.update(pickup_success=complete,training_eligible=complete,actual_opposed_long_rim_contact=bool(opposed_contact(snapshot,scene['tray']['size'])),actual_clearance_m=clearance,final_gripper_force_n=forces.tolist(),sim_seconds=float(runtime.d.time),teacher_inverse_calls=int(runtime.id_calls))
        if not complete:result['error']='actual_pickup_endpoint_not_verified'
    except Exception as error:
        result['error']=repr(error);(case/'exception.txt').write_text(traceback.format_exc())
    finally:
        for w in writers.values():w.close()
        if machine is not None:
            result['frames']=machine.log.count
            machine.log.close(dict(qpos=runtime.d.qpos,qvel=runtime.d.qvel,time=float(runtime.d.time)))
        if runtime is not None:runtime.sim.close()
        result['wall_seconds']=time.monotonic()-start
        result['case']=str(case.resolve())
        write(case/'result.json',result)
    return result


def export(args,results):
    """Official single writer; video encoder consumes already recorded224 streams."""
    import av,h5py
    from r1pro_teleop.airport_fsm.contracts import NAMES,BASE_NAMES
    from lerobot.common.datasets.lerobot_dataset import LeRobotDataset
    from lerobot.common.datasets.compute_stats import sample_indices
    root=Path(args.output);destination=root/'lerobot'
    features={key:dict(dtype='float32',shape=(19,),names=NAMES+BASE_NAMES) for key in ['observation.state','action']}
    features.update({'observation.images.'+c:dict(dtype='video',shape=(3,224,224),names=['channels','height','width']) for c in CAMERAS})
    class RecordedVideoDataset(LeRobotDataset):
        def _save_image(self,image,path):
            if not getattr(self,'recorded_video_ready',False):raise ValueError('pickup_preencoded_video_not_ready')
            # add_frame still validates all features; actual recorded videos are
            # remuxed below. Only the exact official statistics samples need PNG.
            if self.episode_buffer['size'] in self.statistics_frames:super()._save_image(image,path)
    dataset=RecordedVideoDataset.create(repo_id='airport/pickup200_20261007',fps=20,root=destination,robot_type='r1pro_mujoco_sim_mobile19',features=features,use_videos=True,image_writer_threads=0,video_backend='pyav')
    episodes=[]
    for result in results:
        case=Path(result['case'])
        for c in CAMERAS:
            video=destination/dataset.meta.get_video_file_path(len(episodes),'observation.images.'+c)
            video.parent.mkdir(parents=True,exist_ok=True)
            subprocess.run(['ffmpeg','-nostdin','-v','error','-i',str(case/'videos'/f'{c}.mp4'),'-map','0:v:0','-c','copy','-movflags','+faststart',str(video)],check=True)
        dataset.recorded_video_ready=True
        dataset.statistics_frames=set(sample_indices(result['frames']))
        readers=[av.open(str(case/'videos'/f'{c}.mp4')) for c in CAMERAS]
        frames=[r.decode(video=0) for r in readers]
        with h5py.File(case/'attempt/trace.h5') as raw:
            if raw.attrs['num_frames']!=result['frames'] or not np.all(raw['transition_completed'][:]):raise ValueError('pickup_actual_full_control_prefix_required')
            if 'ctrl_substeps' in raw and not np.all(raw['executed_substeps'][:]==raw['ctrl_substeps'].shape[1]):raise ValueError('pickup_actual_substep_journal_incomplete')
            for i in range(result['frames']):
                frame={'observation.state':raw['state19'][i],'action':raw['action19'][i],'task':PROMPT}
                for c,reader in zip(CAMERAS,frames):frame['observation.images.'+c]=next(reader).to_ndarray(format='rgb24')
                dataset.add_frame(frame)
        for iterator in frames:
            if next(iterator,None) is not None:raise ValueError('pickup_recorded_video_has_extra_frames')
        for reader in readers:reader.close()
        dataset.save_episode()
        episodes.append(dict(episode_index=len(episodes),scene_id=result['scene_id'],source_case=str(case),source_result_sha256=sha(case/'result.json'),source_trace_sha256=sha(case/'attempt/trace.h5'),frames=result['frames'],prompt=PROMPT,split=result['split'],scope='pickup_only_partial_task_v1'))
        write(root/'export_status.json',dict(stage='exporting',episodes=len(episodes),target=args.target,heartbeat_unix=time.time()))
    loaded=LeRobotDataset('airport/pickup200_20261007',root=destination,video_backend='pyav')
    if loaded.num_episodes!=len(episodes):raise ValueError('pickup_official_episode_count_mismatch')
    for i in sorted(set([0,len(loaded)//2,len(loaded)-1])):
        sample=loaded[i]
        for c in CAMERAS:
            if tuple(sample['observation.images.'+c].shape)!=(3,224,224):raise ValueError('pickup_official_rgb_shape_mismatch')
    (root/'episodes.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in episodes))
    write(root/'export_status.json',dict(stage='ready',episodes=len(episodes),dataset=str(destination),official_loader_verified=True,all_pickup_success=True,whole_three_action_tasks=False,task_completed=None,scope='pickup_only_partial_task_v1',prompt=PROMPT,frames=len(loaded)))
    return len(episodes)


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('template-source','config','output'):p.add_argument('--'+key,required=True)
    p.add_argument('--target',type=int,default=200);p.add_argument('--workers',type=int,default=16)
    p.add_argument('--max-attempts',type=int,default=300);p.add_argument('--deadline-seconds',type=float,default=1800)
    p.add_argument('--seed',type=int,default=202610071800);p.add_argument('--worker',type=int)
    p.add_argument('--sim-python',default='/home/michelle/miniconda3/envs/r1pro-tray/bin/python')
    a=p.parse_args(argv)
    if a.worker is not None:
        result=collect(a,a.worker);print(json.dumps(result));return 0 if result['pickup_success'] else 2
    if not 1<=a.workers<=24 or a.target<1 or a.max_attempts<a.target:raise ValueError('pickup_parallel_budget_invalid')
    out=Path(a.output);out.mkdir(parents=True,exist_ok=False);(out/'logs').mkdir();(out/'cases').mkdir()
    start=time.monotonic();successful=[];failures=[];submitted=0
    def run(index):
        argv=[a.sim_python,str(Path(__file__).resolve()),'--template-source',a.template_source,'--config',a.config,'--output',a.output,'--seed',str(a.seed),'--worker',str(index)]
        env=dict(os.environ,OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1',CUDA_VISIBLE_DEVICES='0',MUJOCO_GL='egl',MUJOCO_EGL_DEVICE_ID='0')
        with (out/'logs'/f'case_{index:04d}.log').open('x') as log:
            proc=subprocess.Popen(argv,env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            write(out/'logs'/f'case_{index:04d}_process.json',dict(pid=proc.pid,argv=argv))
            code=proc.wait()
        result=out/'cases'/f'case_{index:04d}'/'result.json'
        return json.loads(result.read_text()) if result.exists() else dict(index=index,pickup_success=False,error='worker_exited:'+str(code))
    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        active={}
        def fill():
            nonlocal submitted
            while len(active)<a.workers and submitted<a.max_attempts and len(successful)<a.target and time.monotonic()-start<a.deadline_seconds:
                job=pool.submit(run,submitted);active[job]=submitted;submitted+=1
        fill()
        while active:
            done,_=wait(active,timeout=10,return_when=FIRST_COMPLETED)
            for job in done:
                index=active.pop(job)
                try:result=job.result()
                except Exception as error:result=dict(index=index,pickup_success=False,error=repr(error))
                if result.get('pickup_success'):successful.append(result)
                else:failures.append(result)
            write(out/'status.json',dict(stage='collecting',target=a.target,successful=len(successful),failed=len(failures),submitted=submitted,active=len(active),elapsed_seconds=time.monotonic()-start,heartbeat_unix=time.time(),deadline_seconds=a.deadline_seconds,failures=failures[-10:]))
            fill()
    selected=successful[:a.target]
    write(out/'collection_results.json',dict(successful=successful,failures=failures))
    write(out/'status.json',dict(stage='exporting',successful=len(selected),failed=len(failures),target=a.target,elapsed_seconds=time.monotonic()-start))
    try:
        count=export(a,selected) if selected else 0
        write(out/'status.json',dict(stage='ready' if count==a.target else 'partial_ready',episodes=count,target=a.target,elapsed_seconds=time.monotonic()-start,dataset=str(out/'lerobot'),scope='pickup_only_partial_task_v1',official_loader_verified=bool(count)))
        return 0 if count==a.target else 2
    except Exception as error:
        write(out/'status.json',dict(stage='export_failed_preserving_sources',successful=len(selected),error=repr(error),elapsed_seconds=time.monotonic()-start));raise


if __name__=='__main__':raise SystemExit(main())
