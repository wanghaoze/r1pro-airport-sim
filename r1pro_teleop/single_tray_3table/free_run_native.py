"""Native continuous replay/publication for an explicitly nontraining free run."""
from pathlib import Path
from types import SimpleNamespace
from fractions import Fraction
import json,html,os,subprocess,time
import xml.etree.ElementTree as ET
import h5py,numpy as np
from ..airport_fsm.exporter import Replay
from ..airport_fsm.contracts import Config,fingerprint,sha256_file,Fault,camera_shapes
from ..airport_fsm.geometry import Geometry
from ..single_tray_lab.replay import SingleTrayReplay
from .campaign import atomic_json

FREE_SCOPE='free_run_diagnostic'
NATIVE_SHAPES={'head_left':(1536,1920,3),'head_right':(1536,1920,3),'left_wrist':(720,1280,3),'right_wrist':(720,1280,3)}
ERROR_KEYS={'qpos','qvel','time','terminal_qpos','terminal_qvel','terminal_time'}


from scripts.render_three_table_original_trace import NativeWriter as OriginalNativeWriter


class FreeRunNativeWriter(OriginalNativeWriter):
    """Original H264 settings, with MP4 metadata before video for HTTP playback."""
    def __init__(self,path,shape):
        import av
        self.av=av;self.closed=False
        self.container=av.open(str(path),'w',options={'movflags':'+faststart'})
        self.stream=self.container.add_stream('libx264',rate=20)
        self.stream.width=shape[1];self.stream.height=shape[0];self.stream.pix_fmt='yuv420p'
        self.stream.options={'crf':'18','preset':'fast','threads':'1'}


def is_free_run(value):
    return value.get('run_scope')==FREE_SCOPE or value.get('run_kind')==FREE_SCOPE or value.get('free_run_diagnostic') is True


def require_free_run_metadata(metadata):
    if not is_free_run(metadata) or metadata.get('training_eligible') is not False or metadata.get('task_completed') not in (None,False):
        raise ValueError('explicit_nontraining_free_run_source_required')
    if metadata.get('formal_evaluation') is True:raise ValueError('free_run_not_formal_evaluation')


def environment_events(rows,frames,*,payload_frame=8000):
    events={}
    for row in rows:
        evidence=row.get('environment_evidence');data=row.get('environment_data')
        if evidence is not None and data is not None and evidence!=data:raise ValueError('ambiguous_free_run_environment_journal')
        event=evidence if evidence is not None else data
        if event is None:continue
        frame=row.get('frame')
        if row.get('event')!='passenger_payload_initialized' or event.get('schema')!='airport_passenger_environment_transition/1' or type(frame) is not int or frame!=payload_frame or frame>frames:
            raise ValueError('free_run_payload_event_must_be_actual_400s_boundary')
        if frame in events:raise ValueError('duplicate_free_run_payload_event')
        events[frame]=[event]
    if frames>payload_frame and payload_frame not in events:raise ValueError('recorded_free_run_payload_transition_required')
    return events


def verify_model_parameters(model,metadata):
    params=metadata.get('source_model_parameters')
    if params is None:raise ValueError('actual_free_run_initial_model_parameters_required')
    values=dict(params.get('unchanged_xml_parameter_arrays',{}))
    for key in ('actuator_forcerange','actuator_forcelimited','actuator_ctrllimited','actuator_gear','actuator_gainprm','actuator_biasprm','actuator_ctrlrange','cam_pos','cam_quat','cam_fovy','cam_ipd'):
        if key in params:values[key]=params[key]
    required={'actuator_forcerange','actuator_gainprm','actuator_biasprm','actuator_ctrlrange','cam_pos','cam_quat','cam_fovy','cam_ipd'}
    if not required.issubset(values):raise ValueError('complete_free_run_model_and_camera_parameters_required')
    for key,value in values.items():
        if key not in required|{'actuator_forcelimited','actuator_ctrllimited','actuator_gear'}:raise ValueError('unexpected_free_run_model_snapshot_array')
        actual=getattr(model,key);source=np.asarray(value,dtype=actual.dtype)
        if source.shape!=actual.shape or not np.array_equal(source,actual):raise ValueError('free_run_replay_model_parameter_mismatch:'+key)
    return sorted(values)


class FreeRunTraceReplay(Replay):
    def __init__(self,case,*,render=True):
        case=Path(case);scene_path=case/'scene/scene.json';manifest=json.loads(scene_path.read_text());trace=case/'attempt/trace.h5';events_path=case/'attempt/events.jsonl'
        if manifest.get('schema')!='airport_three_table_single_tray_scene/1' or manifest.get('task_profile')!='three_table_single_tray_action3_v1':raise ValueError('free_run_three_table_geometry_required')
        with h5py.File(trace,'r') as file:
            metadata=json.loads(file.attrs['metadata_json']);require_free_run_metadata(metadata)
            from .free_run import stage_frames
            self.planned_frames=3*stage_frames(metadata.get('requested_stage_seconds',200))
            self.payload_frame=self.planned_frames//3*2
            if metadata.get('planned_frames',self.planned_frames)!=self.planned_frames or metadata.get('payload_event_frame',self.payload_frame)!=self.payload_frame:raise ValueError('free_run_source_schedule_binding_mismatch')
            self.source_terminal=json.loads(file.attrs['terminal_snapshot_json'])
            self.invalid_terminal=self.source_terminal.get('invalid') is True
            if file.attrs.get('schema')!='airport_fsm_raw/2':raise ValueError('free_run_actual_raw2_controls_required')
            frames=int(file.attrs['num_frames']);completed=np.asarray(file['transition_completed'][:],bool)
            if frames<1 or frames>self.planned_frames or len(completed)!=frames or np.any(~completed[:-1]):raise ValueError('free_run_complete_prefix_with_only_final_partial_allowed')
        spec=metadata['scene']
        if fingerprint(spec)!=fingerprint(manifest['legacy_spec']) or metadata['scene_id']!=manifest['scene_id'] or sha256_file(manifest['xml'])!=metadata['scene_xml_sha256']:raise ValueError('free_run_original_scene_identity_required')
        if camera_shapes(spec)!=NATIVE_SHAPES:raise ValueError('free_run_original_four_native_camera_shapes_required')
        self.manifest=manifest;self.environment_event_count=0;self.frame_count=frames
        self.environment_events=environment_events([json.loads(x) for x in events_path.read_text().splitlines() if x.strip()],frames,payload_frame=self.payload_frame)
        def apply_environment(frame,runtime):
            context=SimpleNamespace(mj=runtime.mj,model=runtime.m,data=runtime.d,meta={'scene':manifest})
            for event in self.environment_events.get(frame,[]):
                # This verifier limits q/v and visual changes to declared
                # payload bodies/flex nodes; robot/tray/time/ctrl are untouched.
                SingleTrayReplay.environment(context,event);self.environment_event_count+=1
        super().__init__(case,{'trace':str(trace),'scene_id':manifest['scene_id']},diagnostic=True,spec=spec,cfg=Config(**metadata['config']).validate(),xml=manifest['xml'],geometry=Geometry(spec,expected_trays=1),render=render,before_frame=apply_environment)
        try:self.verified_model_arrays=verify_model_parameters(self.runtime.m,metadata)
        except BaseException:self.close();raise
        self.metadata=metadata
        self.source_files=dict(trace=str(trace),events=str(events_path),scene_json=str(scene_path),scene_xml=manifest['xml'])

    def __iter__(self):
        if not self.invalid_terminal:
            yield from super().__iter__();return
        # A nonfinite terminal has no q/v/time target. Only the finite PRE
        # observations are publishable. Never integrate the unverifiable last
        # interval or invent a terminal state/error for it.
        for key in ('terminal_qpos','terminal_qvel','terminal_time'):self.errors[key]=None
        r=self.runtime
        for i in range(self.n):
            self.before_frame(i,r)
            for key,target in (('qpos',r.d.qpos),('qvel',r.d.qvel),('time',r.d.time)):
                source=np.asarray(self.f['sim_time' if key=='time' else key][i])
                if not np.isfinite(source).all() or not np.isfinite(target).all():raise ValueError('free_run_prefix_observation_not_finite')
                error=float(np.max(np.abs(np.asarray(target)-source)));self.errors[key]=max(self.errors[key],error)
                limit=1e-8 if key=='time' else self.cfg.replay_tolerance*(10 if key=='qvel' else 1)
                if error>limit:raise ValueError('free_run_recorded_prefix_diverged:'+key)
            images={}
            for camera in self.shapes if self.render_images else ():
                image=r.sim.image(camera)
                if image.shape!=self.shapes[camera] or image.dtype!=np.uint8:raise ValueError('free_run_native_camera_shape_changed')
                self.camera_checks[camera]['frames']+=1
                if float(image.std())<2:self.camera_checks[camera]['blank_frames']+=1
                images[camera]=image
            yield i,images
            if i<self.n-1:self._replay_substeps(i,complete=True)


def closure(replay,frames,source_hashes,*,audit_only):
    prefix_only=replay.invalid_terminal
    if frames!=replay.n or (not prefix_only and not replay.terminal_checked) or set(replay.errors)!=ERROR_KEYS:raise ValueError('complete_recorded_free_run_replay_required')
    cfg=replay.cfg
    for key,error in replay.errors.items():
        if prefix_only and key.startswith('terminal_'):
            if error is not None:raise ValueError('invalid_free_run_terminal_error_must_be_unavailable')
            continue
        limit=1e-8 if 'time' in key else cfg.replay_tolerance*(10 if 'qvel' in key else 1)
        if not np.isfinite(error) or error<0 or error>limit:raise ValueError('free_run_continuous_replay_diverged')
    if source_hashes!={k:sha256_file(v) for k,v in replay.source_files.items()}:raise ValueError('free_run_original_source_changed')
    seconds=float(np.sum(replay.f['executed_substeps'][:])*replay.runtime.m.opt.timestep)
    requested=(not prefix_only and frames==replay.planned_frames and bool(np.all(replay.f['transition_completed'][:])) and abs(seconds-replay.planned_frames/20.)<=1e-8)
    full=(requested and replay.planned_frames==12000)
    return dict(schema='airport_three_table_free_run_native_replay/1',run_scope=FREE_SCOPE,run_kind=FREE_SCOPE,task_profile=FREE_SCOPE,source_task_profile='three_table_single_tray_action3_v1',
        diagnostic_only=True,free_run_diagnostic=True,task_completed=False,training_eligible=False,training_ready=False,formal_evaluation=False,source='simulation/program_generated',
        frames=frames,recorded_frames=frames,planned_frames=replay.planned_frames,requested_duration_recording_complete=requested,full_duration_recording=full,recorded_physics_seconds=seconds,payload_event_frame=replay.payload_frame,
        source_files=replay.source_files,source_sha256=source_hashes,source_schema=replay.schema,errors=replay.errors,terminal_checked=replay.terminal_checked,recorded_prefix_video_only=prefix_only,
        terminal_unavailable_reason=replay.source_terminal.get('reason') if prefix_only else None,last_interval_replayed=not prefix_only,initial_restore_count=1,pose_resets_during_replay=0,
        teacher_calls=0,inverse_solver_calls=0,environment_event_count=replay.environment_event_count,model_parameter_arrays_verified=replay.verified_model_arrays,camera_checks=replay.camera_checks,audit_only=audit_only)


def publish(output,receipt,*,probe=None):
    output=Path(output)
    if receipt.get('schema')!='airport_three_table_free_run_native_replay/1' or receipt.get('run_scope')!=FREE_SCOPE or receipt.get('task_completed') is not False or receipt.get('training_eligible') is not False or receipt.get('formal_evaluation') is not False or receipt.get('audit_only') is not False:raise ValueError('nontraining_free_run_video_receipt_required')
    rows=[]
    for camera,(height,width,_) in NATIVE_SHAPES.items():
        path=output/(camera+'.mp4')
        if probe is None:
            doc=json.loads(subprocess.check_output(['ffprobe','-v','error','-count_frames','-select_streams','v:0','-show_entries','stream=codec_name,width,height,r_frame_rate,nb_read_frames','-of','json',str(path)],text=True))
            stream=doc['streams'][0]
        else:stream=probe(path)
        if (stream['width'],stream['height'])!=(width,height) or Fraction(stream['r_frame_rate'])!=20 or int(stream['nb_read_frames'])!=receipt['recorded_frames'] or stream['codec_name']!='h264':raise ValueError('actual_free_run_four_native_video_contract_required')
        rows.append(dict(camera=camera,path=str(path.resolve()),sha256=sha256_file(path),header=stream))
    published=dict(receipt,videos=rows,video_closure_verified=True,ffprobe_verified=probe is None,
                   video_probe_source='ffprobe_full_decode' if probe is None else 'provided_probe_for_tests')
    atomic_json(output/'video_closure.json',published)
    (output/'VIDEO_PATHS.txt').write_text(''.join(x['path']+'\n' for x in rows),encoding='utf-8')
    cards=''.join('<h2>'+html.escape(x['camera'])+'</h2><video controls preload="metadata" width="480" src="'+x['camera']+'.mp4"></video>' for x in rows)
    (output/'viewer.html').write_text('<!doctype html><meta charset="utf-8"><title>Free-run diagnostic</title><h1>Free-run diagnostic, not formal task evaluation</h1><p>Source '+str(receipt['recorded_frames'])+'/'+str(receipt.get('planned_frames',12000))+' frames. Task success and training eligibility are false.</p>'+cards,encoding='utf-8')
    return published


def render(case,output,*,audit_only=False):
    output=Path(output);output.mkdir(parents=True,exist_ok=False);replay=FreeRunTraceReplay(case,render=not audit_only);writers={};frames=0;gpu=[]
    source={k:sha256_file(v) for k,v in replay.source_files.items()}
    try:
        if not audit_only:writers={camera:FreeRunNativeWriter(output/(camera+'.mp4'),shape) for camera,shape in NATIVE_SHAPES.items()}
        for _,images in replay:
            for camera,image in images.items():writers[camera].write(image)
            frames+=1
            if frames==1 and not audit_only:
                doc=ET.fromstring(subprocess.check_output(['nvidia-smi','-q','-x'],text=True))
                gpu=[dict(pid=os.getpid(),gpu_uuid=g.findtext('uuid'),type=p.findtext('type'),used_memory=p.findtext('used_memory')) for g in doc.findall('gpu') for p in g.findall('./processes/process_info') if p.findtext('pid')==str(os.getpid())]
            if frames==1 or frames%100==0:
                progress=dict(stage='continuous_free_run_native_replay',frames=frames,source_frames=replay.n,planned_frames=replay.planned_frames,
                    camera_frames={camera:row['frames'] for camera,row in replay.camera_checks.items()},errors={key:(value if replay.terminal_checked or not key.startswith('terminal_') else None) for key,value in replay.errors.items()},terminal_checked=replay.terminal_checked,
                    heartbeat_unix=time.time(),pid=os.getpid(),run_scope=FREE_SCOPE,run_kind=FREE_SCOPE,diagnostic_only=True,task_completed=False,training_eligible=False)
                atomic_json(output/'progress.json',progress);atomic_json(output/'status.json',progress)
        for writer in writers.values():writer.close()
        receipt=dict(closure(replay,frames,source,audit_only=audit_only),actual_own_gpu_rows=gpu);atomic_json(output/'manifest.json',receipt)
        if not audit_only:
            receipt=publish(output,receipt);atomic_json(output/'manifest.json',receipt)
        atomic_json(output/'progress.json',dict(stage='free_run_recorded_prefix_video_verified' if receipt['recorded_prefix_video_only'] else 'free_run_native_verified',frames=frames,camera_frames={camera:row['frames'] for camera,row in replay.camera_checks.items()},errors=receipt['errors'],terminal_checked=receipt['terminal_checked'],recorded_prefix_video_only=receipt['recorded_prefix_video_only'],heartbeat_unix=time.time(),run_kind=FREE_SCOPE,diagnostic_only=True,training_eligible=False))
        atomic_json(output/'status.json',dict(stage='free_run_native_verified' if not audit_only else 'free_run_replay_audit_verified',receipt=receipt,pid=os.getpid(),heartbeat_unix=time.time(),run_scope=FREE_SCOPE,task_completed=False,training_eligible=False))
        return receipt
    except BaseException as error:
        atomic_json(output/'status.json',dict(stage='failed_free_run_native_preserving_partial',frames=frames,error=repr(error),run_scope=FREE_SCOPE,task_completed=False,training_eligible=False));raise
    finally:
        for writer in writers.values():writer.close()
        replay.close()
