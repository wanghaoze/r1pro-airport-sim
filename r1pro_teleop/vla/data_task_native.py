"""Owned native-video wrapper around immutable controller Replay; no trajectory solving."""
from pathlib import Path
import hashlib,json,os,subprocess,time,inspect,sys,importlib.metadata
import numpy as np

CAMERAS=('head_left','head_right','left_wrist','right_wrist')
GPU_UUIDS={0:'GPU-97ac5ae8-1b03-fdf8-fca5-d1192c8fe27d',1:'GPU-c8e2826c-b460-18ba-dab5-ccd8c1da8b6c'}
EGL_ENUM={0:1,1:0}

def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()

def read(path):return json.loads(Path(path).read_text())
def atomic_json(path,value):
    path=Path(path);temporary=path.with_name(path.name+'.tmp')
    with temporary.open('x') as f:json.dump(value,f,indent=2,allow_nan=False)
    temporary.replace(path)

def verify_source(row):
    for path,expected in (('trace','trace_sha256'),('result','result_sha256'),('scene_xml','scene_xml_sha256'),
                           ('scene_json','scene_json_sha256'),('segments','segments_sha256'),('events','events_sha256'),
                           ('physical_events','physical_events_sha256')):
        if digest(row[path])!=row[expected]:raise ValueError('source_changed:'+path)
    result=read(row['result'])
    if (result.get('task_completed') is not True or result.get('physics_success') is not True
            or result.get('diagnostic_only') or result.get('failure_code') is not None
            or result.get('scene_id')!=row['scene_id'] or result.get('split')!=row['split']
            or result.get('frames')!=row['frames'] or result.get('controller_source')!='program_generated'
            or result.get('environment_source')!='simulation'):
        raise ValueError('not_a_complete_original_simulation_task')
    if row['split'] not in ('train','val','test'):raise ValueError('unknown_source_split')
    return result

def own_gpu_receipt(expected_index):
    rows=subprocess.check_output(['nvidia-smi','--query-gpu=index,uuid','--format=csv,noheader'],text=True)
    lookup={r.split(',')[1].strip():int(r.split(',')[0]) for r in rows.strip().splitlines()}
    lines=subprocess.check_output(['nvidia-smi','--query-compute-apps=pid,gpu_uuid,used_memory',
                                   '--format=csv,noheader,nounits'],text=True)
    # MuJoCo EGL appears as graphics; query the complete XML process list.
    import xml.etree.ElementTree as ET
    root=ET.fromstring(subprocess.check_output(['nvidia-smi','-q','-x'],text=True))
    found=[]
    for gpu in root.findall('gpu'):
        for process in gpu.findall('./processes/process_info'):
            if int(process.findtext('pid','-1'))==os.getpid():
                uuid=gpu.findtext('uuid');found.append(dict(pid=os.getpid(),uuid=uuid,
                    physical_index=lookup[uuid],memory=process.findtext('used_memory')))
    if not found or any(r['physical_index']!=expected_index or r['uuid']!=GPU_UUIDS[expected_index] for r in found):
        raise ValueError('renderer_actual_PID_GPU_binding_mismatch')
    return found

def native_video_metadata(path,shape,frames):
    header=json.loads(subprocess.check_output(['ffprobe','-v','error','-threads','1','-count_frames','-select_streams','v:0',
        '-show_entries','stream=codec_name,width,height,avg_frame_rate,nb_read_frames','-of','json',str(path)],text=True))['streams'][0]
    if ((header['height'],header['width'],3)!=tuple(shape) or header['avg_frame_rate']!='20/1'
            or int(header['nb_read_frames'])!=frames or header['codec_name']!='h264'):
        raise ValueError('encoded_native_dimensions_fps_or_complete_framecount_mismatch')
    return header

class NativeWriter:
    def __init__(self,path,shape):
        import av
        self.av=av;self.writer=av.open(str(path),'w');self.stream=self.writer.add_stream('libx264',rate=20)
        self.stream.width=shape[1];self.stream.height=shape[0];self.stream.pix_fmt='yuv420p'
        self.stream.options={'crf':'18','preset':'fast','threads':'1'}
    def add(self,index,image):
        frame=self.av.VideoFrame.from_ndarray(image,format='rgb24');frame.pts=index
        for packet in self.stream.encode(frame):self.writer.mux(packet)
    def close(self):
        if self.writer is not None:
            for packet in self.stream.encode(None):self.writer.mux(packet)
            self.writer.close();self.writer=None

def frozen_replay_factory(controller):
    # CLI loads this module by file, then imports the original package exclusively.
    controller=Path(controller).resolve();sys.path.insert(0,str(controller))
    from r1pro_teleop.airport_fsm.exporter import Replay
    if not Path(inspect.getfile(Replay)).resolve().is_relative_to(controller):
        raise ValueError('Replay_did_not_come_from_declared_immutable_controller')
    return Replay

def render_source(row,output,controller,*,physical_gpu=0,allow_low_texture=False,
                  replay_factory=None,writer_factory=NativeWriter,video_checker=native_video_metadata,
                  gpu_checker=own_gpu_receipt):
    result=verify_source(row);start=time.monotonic()
    directory=Path(output)/row['scene_id']/Path(row['attempt']).name
    directory.mkdir(parents=True,exist_ok=False)
    writers={};maximum=dict(qpos=0.,qvel=0.,time=0.);receipt=None;count=0;last_progress=start
    source=dict(trace=row['trace'],scene_id=row['scene_id'])
    try:
        controller_paths=[Path(controller)/'r1pro_teleop'/name for name in
                          ('airport_fsm/exporter.py','airport_fsm/runtime.py','core.py','airport_recording.py')]
        controller_hashes={str(p):digest(p) for p in controller_paths}
        replay_factory=replay_factory or frozen_replay_factory(controller)
        with replay_factory(row['collection'],source,diagnostic=allow_low_texture) as replay:
            if set(replay.shapes)!=set(CAMERAS) or replay.n!=row['frames'] or replay.cfg.fps!=20:
                raise ValueError('native_source_camera_or_fps_or_frames_mismatch')
            if not np.all(replay.f['transition_completed'][:]):raise ValueError('incomplete_original_control_interval')
            if replay.f.attrs.get('schema') not in ('airport_fsm_raw/1','airport_fsm_raw/2'):
                raise ValueError('unsupported_original_raw_schema')
            for name in CAMERAS:writers[name]=writer_factory(directory/(name+'.mp4'),replay.shapes[name])
            for index,images in replay:
                if index!=count or set(images)!=set(CAMERAS):raise ValueError('source_frame_missing_reordered_or_camera_missing')
                runtime=replay.runtime
                errors=dict(qpos=float(np.max(np.abs(runtime.d.qpos-replay.f['qpos'][index]))),
                    qvel=float(np.max(np.abs(runtime.d.qvel-replay.f['qvel'][index]))),
                    time=abs(float(runtime.d.time)-float(replay.f['sim_time'][index])))
                for key,error in errors.items():maximum[key]=max(maximum[key],error)
                if (not np.isfinite(list(errors.values())).all() or errors['qpos']>replay.cfg.replay_tolerance
                    or errors['qvel']>replay.cfg.replay_tolerance*10 or errors['time']>1e-8):
                    raise ValueError('continuous_prefix_replay_diverged')
                if receipt is None:
                    receipt=gpu_checker(physical_gpu)
                    atomic_json(directory/'gpu_receipt.json',dict(physical_gpu=physical_gpu,receipt=receipt,
                        egl_enum=EGL_ENUM[physical_gpu],cuda_visible_devices=os.environ.get('CUDA_VISIBLE_DEVICES')))
                for name,image in images.items():
                    if image.shape!=tuple(replay.shapes[name]) or image.dtype!=np.uint8:raise ValueError('native_RGB_contract_mismatch')
                    writers[name].add(index,image)
                count+=1
                now=time.monotonic()
                if count%512==0 or now-last_progress>=10:
                    progress=dict(stage='continuous_replay',frames=count,expected_frames=replay.n,
                        source_scene_id=row['scene_id'],elapsed_seconds=now-start,prefix_errors=dict(maximum))
                    atomic_json(directory/'progress.json',progress);print(json.dumps(progress),flush=True);last_progress=now
            terminal=json.loads(replay.f.attrs['terminal_snapshot_json']);runtime=replay.runtime
            terminal_errors=dict(qpos=float(np.max(np.abs(runtime.d.qpos-np.asarray(terminal['qpos'])))),
                qvel=float(np.max(np.abs(runtime.d.qvel-np.asarray(terminal['qvel'])))),time=abs(float(runtime.d.time)-float(terminal['time'])))
            if (count!=replay.n or not np.isfinite(list(terminal_errors.values())).all()
                or terminal_errors['qpos']>replay.cfg.replay_tolerance or terminal_errors['qvel']>replay.cfg.replay_tolerance*10
                or terminal_errors['time']>1e-8):raise ValueError('complete_terminal_replay_not_verified')
            for writer in writers.values():writer.close()
            writers.clear();references=[]
            for name in CAMERAS:
                path=directory/(name+'.mp4');header=video_checker(path,replay.shapes[name],count)
                references.append(dict(trace=row['trace'],trace_sha256=row['trace_sha256'],camera=name,path=str(path),
                    source_start_frame=0,video_start_frame=0,frames=count,sha256=digest(path),native=True,
                    encoded_metadata=header,bytes=path.stat().st_size))
            verify_source(row)
            if any(digest(p)!=expected for p,expected in controller_hashes.items()):raise ValueError('immutable_controller_changed_during_replay')
            camera_checks=replay.camera_checks
            texture_pass=all(c.get('blank_frames',0)==0 and c.get('frames')==count for c in camera_checks.values())
            environment=dict(python=sys.version,numpy=np.__version__)
            for package in ('mujoco','av','scipy'):
                try:environment[package]=importlib.metadata.version(package)
                except importlib.metadata.PackageNotFoundError:environment[package]='not_installed_fixture'
            dependency_path=Path(row['collection'])/'dependencies.json'
            declared=read(dependency_path) if dependency_path.is_file() else {}
            manifest=dict(schema='airport_complete_task_native_replay/1',status='complete',purpose='training_source_native_video',
                scene_id=row['scene_id'],split=row['split'],attempt=Path(row['attempt']).name,trace=row['trace'],
                trace_sha256=row['trace_sha256'],source_result=row['result'],source_result_sha256=row['result_sha256'],
                scene_xml_sha256=row['scene_xml_sha256'],source_scene_json_sha256=row['scene_json_sha256'],
                source='simulation/program_generated',task_completed=True,strict_success=result.get('strict_success'),
                acceptance_profile=result.get('effective_acceptance_profile'),frames=count,fps=20,references=references,
                base_qpos_indices=replay.runtime.base_qids.tolist(),camera_checks=camera_checks,
                camera_orientation_preserved_by_immutable_XML=True,native_shapes={k:list(v) for k,v in replay.shapes.items()},
                camera_texture_quality_passed=texture_pass,allow_low_texture=allow_low_texture,
                training_ready=False,training_ready_reason='complete_action_annotation_and_dataset_audit_not_yet_performed',
                control_replay='continuous_initial_restore_only',source_raw_schema=replay.schema,
                control_semantics='raw2_exact_substeps' if replay.schema=='airport_fsm_raw/2' else 'raw1_frozen_servo_reconstruction',
                prefix_errors=maximum,terminal_errors=terminal_errors,gpu_receipt=receipt,
                controller_root=str(Path(controller).resolve()),controller_exporter_sha256=digest(Path(controller)/'r1pro_teleop/airport_fsm/exporter.py'),
                controller_source_hashes_before_after=controller_hashes,
                actual_replay_environment=environment,source_dependencies_path=str(dependency_path),
                source_dependencies_sha256=digest(dependency_path) if dependency_path.is_file() else None,
                source_declared_environment={k:v for k,v in declared.items() if k in ('python','numpy','mujoco','versions','packages','environment','physics_environment')},
                initial_restore_count=1,per_frame_state_reset=False,IK_calls=0,source_hashes_before_after_verified=True,
                wall_seconds=time.monotonic()-start,render_frames_per_wall_second=count/(time.monotonic()-start))
            atomic_json(directory/'manifest.json',manifest);return manifest
    except BaseException as exc:
        for writer in writers.values():
            try:writer.close()
            except Exception:pass
        atomic_json(directory/'failure.json',dict(status='failed',error=repr(exc),frames_written=count,
            source_trace=row['trace'],source_trace_sha256=row['trace_sha256'],retained_partial=True,wall_seconds=time.monotonic()-start))
        raise
