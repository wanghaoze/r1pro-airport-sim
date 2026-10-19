"""Fresh whole-action datasets from complete simulation tasks and full native media.

No controller, vendor, source collection or prior dataset is modified. Native
inspection clips use FFV1 RGB lossless encoding; training views are separately
identified 224-pixel H264 derivatives. Task classes come from a bound vocabulary.
"""
from __future__ import annotations
from pathlib import Path
from fractions import Fraction
import hashlib
import json
import os
import shutil
import numpy as np
import h5py
from .data import digest, base_qpos_projection
from .data_lerobot import MODEL_CAMERAS, STATE_SEMANTICS, TRAINING_VIDEO_ENCODING, model_image, project_dataset_class, validate_training_encoding
from r1pro_teleop.airport_fsm.contracts import NAMES, BASE_NAMES

NATIVE_CAMERAS=('head_left','head_right','left_wrist','right_wrist')


def record_hash(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def action_vocabulary(rows):
    """An ordered manifest vocabulary, never a guessed carry destination."""
    if not isinstance(rows,list) or not rows:
        raise ValueError('whole_action_vocabulary_required')
    labels=[];prompts=[]
    for row in rows:
        if (not isinstance(row,dict) or any(not isinstance(row.get(key),str) or not row[key].strip()
                for key in ('action_label','base_skill','language_prompt'))):
            raise ValueError('invalid_whole_action_vocabulary')
        if row['base_skill'] not in ('initialize_posture','navigate_to_tray','push_adjust_tray','grasp_lift_tray','carry_tray','place_release_tray'):
            raise ValueError('unsupported_whole_action_base_skill')
        labels.append(row['action_label']);prompts.append(row['language_prompt'])
    if len(set(labels))!=len(labels) or len(set(prompts))!=len(prompts):
        raise ValueError('duplicate_whole_action_vocabulary')
    return {row['action_label']:dict(row,task_index=index) for index,row in enumerate(rows)}


def read_action_arrays(task, span, *, projection_cache=None, trace_hash_cache=None):
    """Keep the original mobile XML qpos origin across every action slice."""
    a,b=span['start_frame'],span['end_frame']
    if type(a) is not int or type(b) is not int or not 0<=a<b<=task['frames']:
        raise ValueError('invalid_whole_action_source_interval')
    stat=Path(task['trace']).stat();signature=(stat.st_size,stat.st_mtime_ns,task['trace_sha256'])
    if trace_hash_cache is None or trace_hash_cache.get(task['trace'])!=signature:
        if digest(task['trace'])!=task['trace_sha256']:raise ValueError('complete_task_trace_changed')
        if trace_hash_cache is not None:trace_hash_cache[task['trace']]=signature
    columns=base_qpos_projection(task,cache=projection_cache)
    with h5py.File(task['trace'],'r') as f:
        state=np.concatenate((f['state'][a:b],f['qpos'][a:b][:,columns]),axis=1).astype(np.float32)
        action=np.concatenate((f['action'][a:b],f['base_action'][a:b]),axis=1).astype(np.float32)
    if state.shape!=(b-a,19) or action.shape!=(b-a,19) or not np.isfinite(state).all() or not np.isfinite(action).all():
        raise ValueError('whole_action_mobile19_values_invalid')
    return state,action,columns


def preserve_full_task(task, directory):
    """Hardlink or copy exact complete source bytes, without changing permissions."""
    directory=Path(directory)
    if directory.exists():raise ValueError('refuse_existing_full_task_archive')
    directory.mkdir(parents=True)
    records=[]
    resources=[('trace.h5','trace','trace_sha256'),('result.json','result','result_sha256'),
        ('segments.json','segments','segments_sha256'),('events.jsonl','events','events_sha256'),
        ('physical_events.json','physical_events','physical_events_sha256'),('mobile.xml','scene_xml','scene_xml_sha256'),
        ('scene.json','scene_json','scene_json_sha256')]
    for name,key,hash_key in resources:
        if key not in task:
            if key in ('trace','result','segments','scene_xml','scene_json'):raise ValueError('complete_task_archive_missing:'+key)
            continue
        source=Path(task[key]);sha=digest(source)
        if sha!=task[hash_key]:raise ValueError('complete_task_resource_changed:'+key)
        target=directory/name
        try:os.link(source,target);method='hardlink'
        except OSError:shutil.copyfile(source,target);method='copy'
        if digest(target)!=sha:raise ValueError('complete_task_archive_copy_mismatch')
        records.append(dict(kind=key,source=str(source),path=str(target),sha256=sha,method=method))
    for ref in task.get('native_videos',[]):
        if ref['camera'] not in NATIVE_CAMERAS:raise ValueError('unknown_full_native_camera')
        source=Path(ref['path']);sha=digest(source)
        if sha!=ref['sha256']:raise ValueError('native_full_source_changed')
        target=directory/'native'/ (ref['camera']+source.suffix);target.parent.mkdir(exist_ok=True)
        try:os.link(source,target);method='hardlink'
        except OSError:shutil.copyfile(source,target);method='copy'
        if digest(target)!=sha:raise ValueError('full_native_archive_copy_mismatch')
        records.append(dict(kind='full_native_video',camera=ref['camera'],source=str(source),path=str(target),sha256=sha,method=method))
    manifest=dict(schema='airport_complete_task_archive/1',task=task,resources=records,
        qualification='Complete raw task retained, including settling and verification outside supervised action spans; source inode permissions unchanged')
    (directory/'source_manifest.json').write_text(json.dumps(manifest,indent=2,allow_nan=False),encoding='utf-8')
    return manifest


def decoded_rgb(path):
    import av
    with av.open(str(path)) as container:
        container.streams.video[0].codec_context.thread_count=2
        for frame in container.decode(video=0):yield frame.to_ndarray(format='rgb24')


def encode_ffv1(frames, path, fps=20):
    import av
    path=Path(path)
    if path.exists():raise ValueError('refuse_existing_native_action_clip')
    count=0;stream=None
    with av.open(str(path),'w',format='matroska') as container:
        for image in frames:
            if stream is None:
                stream=container.add_stream('ffv1',rate=fps);stream.width=image.shape[1];stream.height=image.shape[0];stream.pix_fmt='bgr0'
            frame=av.VideoFrame.from_ndarray(image,format='rgb24');frame.pts=count;frame.time_base=Fraction(1,fps)
            for packet in stream.encode(frame):container.mux(packet)
            count+=1
        if stream is None:raise ValueError('empty_native_action_clip')
        for packet in stream.encode():container.mux(packet)
    return count


def cut_native_action(reference, destination, start, end, *, decoder=None, encoder=None):
    """Decode source absolute [a,b), re-encode RGB losslessly and verify all frames."""
    decoder=decoded_rgb if decoder is None else decoder;encoder=encode_ffv1 if encoder is None else encoder
    if (type(start) is not int or type(end) is not int or not 0<=start<end
            or digest(reference['path'])!=reference['sha256']):
        raise ValueError('native_action_source_or_interval_invalid')
    destination=Path(destination);destination.parent.mkdir(parents=True,exist_ok=True)
    if destination.exists():raise ValueError('refuse_existing_native_action_clip')
    source_hash=hashlib.sha256();shape=None;source_count=0
    def source_frames():
        nonlocal shape,source_count
        for index,image in enumerate(decoder(reference['path'])):
            if index>=end:break
            if index<start:continue
            image=np.asarray(image)
            if image.dtype!=np.uint8 or image.ndim!=3 or image.shape[-1]!=3:raise ValueError('native_rgb_frame_invalid')
            if shape is None:shape=image.shape
            if image.shape!=shape:raise ValueError('native_source_resolution_changed')
            source_hash.update(np.ascontiguousarray(image).tobytes());source_count+=1
            yield image
        if source_count!=end-start:raise ValueError('native_source_frame_range_missing')
    encoded=encoder(source_frames(),destination,20)
    output_hash=hashlib.sha256();decoded_count=0
    for image in decoder(destination):
        if np.asarray(image).shape!=shape:raise ValueError('native_clip_resolution_changed')
        output_hash.update(np.ascontiguousarray(image).tobytes());decoded_count+=1
    if encoded!=end-start or decoded_count!=end-start or source_hash.digest()!=output_hash.digest():
        raise ValueError('native_clip_rgb_or_frame_alignment_changed')
    return dict(path=str(destination.resolve()),sha256=digest(destination),source_path=str(Path(reference['path']).resolve()),
        source_sha256=reference['sha256'],source_start_frame=start,source_end_frame=end,frames=end-start,
        fps=20,width=shape[1],height=shape[0],codec='ffv1',container='matroska',pixel_format='bgr0',
        decoded_rgb_sha256=output_hash.hexdigest(),all_decoded_rgb_frames_equal_source=True,native_resolution_preserved=True)


def interval_statistics(intervals):
    ordered=sorted(intervals)
    total=sum(b-a for a,b in ordered)
    end=0;unique=0
    for a,b in ordered:
        if type(a) is not int or type(b) is not int or not 0<=a<b:
            raise ValueError('invalid_interval_statistics')
        unique+=max(0,b-max(a,end));end=max(end,b)
    return dict(supervised_frames=total,unique_source_action_frames=unique,
                duplicate_source_action_frames=total-unique)


def validate_labeled_plan(task,plan,vocabulary):
    if (task.get('task_completed') is not True or task.get('physics_success') is not True
            or task.get('source')!='simulation/program_generated'
            or task.get('split') not in ('train','val','test')
            or plan.get('schema')!='airport_complete_action_plan/1'
            or plan.get('source_task_completed') is not True or plan.get('raw_frames')!=task['frames']):
        raise ValueError('whole_task_source_not_verified_complete')
    if digest(task['result'])!=task['result_sha256']:raise ValueError('complete_task_result_changed')
    result=json.loads(Path(task['result']).read_text())
    if result.get('task_completed',result.get('physics_success')) is not True or result.get('physics_success') is not True:
        raise ValueError('authoritative_whole_task_result_failed')
    intervals=[]
    for row in plan['segments']:
        label=row.get('action_label');entry=vocabulary.get(label)
        base=row.get('base_skill',row.get('skill'))
        if (entry is None or row.get('training_eligible') is not True
                or base!=entry['base_skill'] or row['language_prompt']!=entry['language_prompt']
                or row.get('boundary_semantics')!='complete_action_original_frames'
                or row.get('task_completed') is not True):
            raise ValueError('whole_action_label_or_qualification_invalid')
        for key in ('scene_id','split','trace_sha256','result_sha256'):
            if row.get(key)!=task[key]:raise ValueError('whole_action_source_binding_changed:'+key)
        a,b=row['start_frame'],row['end_frame']
        if type(a) is not int or type(b) is not int or not 0<=a<b<=task['frames'] or row['frames']!=b-a:
            raise ValueError('whole_action_interval_invalid')
        if record_hash(row['source_constituents'])!=row['source_constituents_sha256']:
            raise ValueError('whole_action_original_constituents_changed')
        if base=='carry_tray' and row.get('temporary'):
            raise ValueError('temporary_carry_cannot_be_final_position_label')
        if base=='place_release_tray' and row.get('full_bilateral_release_claimed') is False:
            raise ValueError('retained_place_is_not_complete_release')
        intervals.append((a,b))
    coverage=sorted(intervals+[(item['start_frame'],item['end_frame']) for item in plan['inventory']])
    end=0
    for a,b in coverage:
        if type(a) is not int or type(b) is not int or not 0<=a<b<=task['frames'] or a>end:
            raise ValueError('whole_task_unaccounted_original_frames')
        end=max(end,b)
    if end!=task['frames']:raise ValueError('whole_task_unaccounted_original_tail')
    return interval_statistics(intervals)


def materialize_complete_task_split(plans_path,label_spec_path,destination,repo_id,*,split,
                                    max_scenes=None,native_overrides=None,dataset_class=None,
                                    native_cut=None,camera_reader_factory=None,native_camera_workers=4):
    """Build one explicit original split in a fresh directory; never train."""
    from PIL import Image
    from .data_lerobot import CameraFrameReader
    if split not in ('train','val','test'):raise ValueError('invalid_task_dataset_split')
    destination=Path(destination).resolve()
    if destination.exists():raise ValueError('refuse_existing_whole_task_dataset')
    specification=json.loads(Path(label_spec_path).read_text(encoding='utf-8'))
    vocabulary=action_vocabulary(specification['action_vocabulary'])
    if specification.get('mapping_status')!='user_confirmed':raise ValueError('action_position_mapping_not_confirmed')
    if specification.get('label_profile')!='task_complete_action8_v1':
        raise ValueError('unsupported_complete_task_label_profile')
    cases=[json.loads(line) for line in Path(plans_path).read_text(encoding='utf-8').splitlines() if line.strip()]
    cases=[case for case in cases if case['original_inventory']['split']==split]
    if max_scenes is not None:
        if type(max_scenes) is not int or max_scenes<1:raise ValueError('invalid_task_dataset_max_scenes')
        cases=cases[:max_scenes]
    if not cases:raise ValueError('no_complete_cases_in_requested_split')
    if len({case['original_inventory']['scene_id'] for case in cases})!=len(cases):raise ValueError('duplicate_complete_source_scene')
    official=dataset_class is None
    if dataset_class is None:
        from importlib.metadata import version
        if version('lerobot')!='0.1.0':raise ValueError('pinned_lerobot_0_1_0_required')
        dataset_class=project_dataset_class()
    native_cut=cut_native_action if native_cut is None else native_cut
    reader_factory=CameraFrameReader if camera_reader_factory is None else camera_reader_factory
    features={'observation.state':{'dtype':'float32','shape':(19,),'names':NAMES+BASE_NAMES},
              'action':{'dtype':'float32','shape':(19,),'names':NAMES+BASE_NAMES}}
    features.update({'observation.images.'+camera:{'dtype':'video','shape':(3,224,224),'names':['channels','height','width']} for camera in MODEL_CAMERAS})
    # Validate complete source and all media before creating the dataset directory.
    selected=[]
    for case in cases:
        task=dict(case['original_inventory']);plan=case['plan'];counts=validate_labeled_plan(task,plan,vocabulary)
        if native_overrides and task['scene_id'] in native_overrides:
            override=native_overrides[task['scene_id']]
            if override['trace_sha256']!=task['trace_sha256']:raise ValueError('native_override_source_trace_mismatch')
            task['native_videos']=override['native_videos']
        views={ref['camera']:ref for ref in task['native_videos']}
        if len(task['native_videos'])!=4 or set(views)!=set(NATIVE_CAMERAS):raise ValueError('whole_task_four_full_native_views_required:'+task['scene_id'])
        for camera,ref in views.items():
            if digest(ref['path'])!=ref['sha256']:raise ValueError('whole_task_full_native_video_changed')
            header=ref['header']
            if Fraction(header['avg_frame_rate'])!=20 or int(header['nb_frames'])!=task['frames']:
                raise ValueError('whole_task_native_frame_contract_mismatch')
            if digest(ref['manifest'])!=ref['manifest_sha256']:raise ValueError('whole_task_native_replay_manifest_changed')
        selected.append((task,plan,views,counts))
    ds=None;reader=None;episodes=[];rows=[];archives=[];projections={};trace_hash_cache={}
    try:
        ds=dataset_class.create(repo_id=repo_id,fps=20,root=destination,robot_type='r1pro_mujoco_sim_mobile19',features=features,use_videos=True,image_writer_threads=4,video_backend='pyav')
        for entry in vocabulary.values():
            if ds.meta.get_task_index(entry['language_prompt']) is None:ds.meta.add_task(entry['language_prompt'])
            if ds.meta.get_task_index(entry['language_prompt'])!=entry['task_index']:
                raise ValueError('fixed_action_vocabulary_task_index_changed')
        reader=reader_factory()
        for task,plan,views,counts in selected:
            archive=preserve_full_task(task,destination.parent/(destination.name+'_full_tasks')/task['scene_id']);archives.append(archive)
            archive['plan']=plan
            (destination.parent/(destination.name+'_full_tasks')/task['scene_id']/'action_plan.json').write_text(json.dumps(plan,indent=2,allow_nan=False),encoding='utf-8')
            batch_clips={}
            if native_cut is cut_native_action:
                windows_by_camera={camera:[dict(segment_id=source_segment_identity(task,row),start_frame=row['start_frame'],end_frame=row['end_frame'],path=destination/'native_action_clips'/row['action_label']/task['scene_id']/source_segment_identity(task,row)/(camera+'.mkv')) for row in plan['segments']] for camera in NATIVE_CAMERAS}
                batch_clips=cut_case_native_windows(views,windows_by_camera,expected_source_frames=task['frames'],workers=native_camera_workers)
            for row in plan['segments']:
                a,b=row['start_frame'],row['end_frame'];entry=vocabulary[row['action_label']]
                identity=record_hash(dict(trace_sha256=task['trace_sha256'],result_sha256=task['result_sha256'],scene_xml_sha256=task['scene_xml_sha256'],start=a,end=b,operation_index=row['operation_index'],action_label=row['action_label'],source_constituents_sha256=row['source_constituents_sha256']))
                segment_id=source_segment_identity(task,row)
                clips={}
                for camera in NATIVE_CAMERAS:
                    path=destination/'native_action_clips'/row['action_label']/task['scene_id']/segment_id/(camera+'.mkv')
                    clips[camera]=batch_clips[camera][segment_id] if batch_clips else native_cut(views[camera],path,a,b)
                arrays=read_action_arrays(task,row,projection_cache=projections,trace_hash_cache=trace_hash_cache);states,actions,columns=arrays
                training_refs={camera:dict(path=clips[camera]['path'],start_frame=0,end_frame=b-a,sha256=clips[camera]['sha256'],verified=True) for camera in MODEL_CAMERAS}
                preencode={camera:hashlib.sha256() for camera in MODEL_CAMERAS}
                for offset in range(b-a):
                    images=reader.read(training_refs,offset)
                    frame={'observation.state':states[offset],'action':actions[offset],'task':entry['language_prompt']}
                    for camera in MODEL_CAMERAS:
                        preencode[camera].update(np.ascontiguousarray(images[camera]).tobytes())
                        frame['observation.images.'+camera]=images[camera]
                    ds.add_frame(frame)
                ds.save_episode()
                source=dict(row,segment_id=segment_id,source_segment_id=segment_id,skill=row['action_label'],base_skill=row['base_skill'],phase='whole_action',collection=task['collection'],trace=task['trace'],trace_sha256=task['trace_sha256'],scene_xml_sha256=task['scene_xml_sha256'],scene_json_sha256=task['scene_json_sha256'],quality_class='whole_completed_task_physical_goal',episode_strict_success=task['strict_success'],acceptance_profile=task['acceptance_profile'],training_ready=True,fps=20,action_layout='mobile19')
                rows.append(source)
                episode=dict(episode_index=len(episodes),scene_id=task['scene_id'],split=split,segment_id=segment_id,source_trace=task['trace'],source_trace_sha256=task['trace_sha256'],source_start_frame=a,source_end_frame=b,frames=b-a,fps=20,action_semantics='absolute_mobile19',state_semantics=STATE_SEMANTICS,base_qpos_indices=columns,skill=row['action_label'],base_skill=row['base_skill'],phase='whole_action',operation_index=row['operation_index'],language_prompt=entry['language_prompt'],action_label=row['action_label'],task_index=entry['task_index'],quality_class=source['quality_class'],episode_strict_success=task['strict_success'],acceptance_profile=task['acceptance_profile'],original_task_result_sha256=task['result_sha256'],native_action_clips=clips,full_source_native_videos=task['native_videos'],source_constituents=row['source_constituents'],source_constituents_sha256=row['source_constituents_sha256'],included_auxiliary_skills=row.get('included_auxiliary_skills',[]),overlaps_allowed_explicit=row.get('overlaps_allowed_explicit',False),preencode_training_rgb_sha256={camera:hash.hexdigest() for camera,hash in preencode.items()},base_state_origin_policy='original_mobile_xml_qpos_origin_no_rebase')
                episodes.append(episode)
            update_action_video_index(destination,episodes,ds)
        if hasattr(ds,'stop_image_writer'):ds.stop_image_writer()
        encoding=dict(verified=False,reason='injected_test_dataset')
        frame_audit=dict(verified=False,reason='injected_test_dataset')
        image_audit=dict(verified=False,reason='injected_test_dataset')
        if official:
            encoding=validate_task_training_encoding(destination,len(episodes)*3)
            frame_audit=audit_task_parquet(destination,episodes,vocabulary,repo_id=repo_id)
            image_audit=audit_training_rgb_derivation(destination,episodes,ds)
        manifest_path=destination/'whole_action_source_manifest.jsonl'
        manifest_path.write_text(''.join(json.dumps(row,sort_keys=True,allow_nan=False)+'\n' for row in rows),encoding='utf-8')
        counts=dict(supervised_frames=sum(e['frames'] for e in episodes),unique_full_task_frames=sum(task['frames'] for task,_,_,_ in selected),unique_source_action_frames=sum(c['unique_source_action_frames'] for _,_,_,c in selected),duplicate_source_action_frames=sum(c['duplicate_source_action_frames'] for _,_,_,c in selected))
        manifest=dict(schema='airport_pi05_training/1',repo_id=repo_id,split=split,fps=20,action_semantics='absolute_mobile19',state_semantics=STATE_SEMANTICS,environment_source='simulation',controller_source='program_generated',human_demonstration=False,language_profile=specification['label_profile'],prompt_mode=specification['label_profile'],action_vocabulary=list(vocabulary.values()),label_spec_sha256=digest(label_spec_path),input_plan_sha256=digest(plans_path),source_manifest=str(manifest_path),source_manifest_sha256=digest(manifest_path),normalization_split='train_only' if split=='train' else 'excluded_from_optimization',episodes=episodes,full_task_archives=[str(destination.parent/(destination.name+'_full_tasks')/task['scene_id']/'source_manifest.json') for task,_,_,_ in selected],counts=counts,official_loader_every_episode_first_last=official,training_video_encoding=dict(TRAINING_VIDEO_ENCODING),training_video_encoding_verification=encoding,all_parquet_values_verified=frame_audit,actual_training_rgb_derivation=image_audit,image_derivation=dict(size=[224,224],resize='aspect_preserving_with_zero_padding',resample='bilinear',crop=False,source_native_preserved=True,native_video_export_claim=False),action_chunk_boundary='one_complete_goal_action_per_episode_with_explicit_goal_overlap')
        (destination/'airport_training_manifest.json').write_text(json.dumps(manifest,indent=2,allow_nan=False),encoding='utf-8')
        return dict(path=str(destination),repo_id=repo_id,split=split,scenes=len(selected),episodes=len(episodes),counts=counts,training_started=False)
    finally:
        if reader is not None:reader.close()
        if ds is not None and hasattr(ds,'stop_image_writer'):ds.stop_image_writer()


def audit_task_parquet(destination,episodes,vocabulary,*,repo_id):
    """Actual official loads plus every numeric row against source global frames."""
    import pyarrow.parquet as pq
    from lerobot.common.datasets.lerobot_dataset import LeRobotDataset
    destination=Path(destination);info=json.loads((destination/'meta/info.json').read_text())
    tasks=[json.loads(line) for line in (destination/'meta/tasks.jsonl').read_text().splitlines()]
    expected=[dict(task_index=entry['task_index'],task=entry['language_prompt']) for entry in vocabulary.values()]
    if sorted(tasks,key=lambda row:row['task_index'])!=expected:raise ValueError('official_tasks_are_not_fixed_action_vocabulary')
    loaded=LeRobotDataset(repo_id=repo_id,root=destination,video_backend='pyav')
    if len(loaded)!=sum(e['frames'] for e in episodes):raise ValueError('official_whole_action_frame_count_changed')
    chunked=LeRobotDataset(repo_id=repo_id,root=destination,video_backend='pyav',delta_timestamps={'action':[i/20 for i in range(20)]})
    horizon_checks=[]
    offset=0;projections={}
    for episode in episodes:
        chunk=episode['episode_index']//info.get('chunks_size',1000)
        path=destination/info['data_path'].format(episode_chunk=chunk,episode_index=episode['episode_index'])
        table=pq.read_table(path,columns=['observation.state','action','timestamp','frame_index','task_index'])
        # Columns were compiled from original XML before export; use those exact
        # columns and original frame interval, without a split-local base reset.
        a,b=episode['source_start_frame'],episode['source_end_frame']
        with h5py.File(episode['source_trace'],'r') as f:
            state=np.concatenate((f['state'][a:b],f['qpos'][a:b][:,episode['base_qpos_indices']]),axis=1).astype(np.float32)
            action=np.concatenate((f['action'][a:b],f['base_action'][a:b]),axis=1).astype(np.float32)
        if not np.array_equal(state,np.asarray(table['observation.state'].to_pylist(),dtype=np.float32)) or not np.array_equal(action,np.asarray(table['action'].to_pylist(),dtype=np.float32)):
            raise ValueError('whole_action_parquet_source_values_changed')
        if not np.allclose(table['timestamp'].to_numpy(),np.arange(b-a)/20,rtol=0,atol=1e-5) or not np.array_equal(table['frame_index'].to_numpy(),np.arange(b-a)) or not np.all(table['task_index'].to_numpy()==episode['task_index']):
            raise ValueError('whole_action_task_or_time_indices_changed')
        for index in (offset,offset+b-a-1):
            sample=loaded[index]
            if tuple(sample['observation.state'].shape)!=(19,) or tuple(sample['action'].shape)!=(19,):raise ValueError('official_whole_action_mobile19_shape_changed')
            for camera in MODEL_CAMERAS:
                if tuple(sample['observation.images.'+camera].shape)!=(3,224,224):raise ValueError('official_whole_action_image_shape_changed')
        for local_index in sorted(set((0,max(0,b-a-20),b-a-1))):
            sample=chunked[offset+local_index];indices=np.minimum(np.arange(local_index,local_index+20),b-a-1)
            expected_pad=np.arange(local_index,local_index+20)>=b-a
            if not np.array_equal(sample['action'].numpy(),action[indices]) or not np.array_equal(sample['action_is_pad'].numpy(),expected_pad):
                raise ValueError('whole_action_actual_h20_source_or_terminal_padding_changed')
            horizon_checks.append(dict(episode_index=episode['episode_index'],source_frame=a+local_index,padded_positions=int(expected_pad.sum()),action_sha256=hashlib.sha256(sample['action'].numpy().tobytes()).hexdigest()))
        offset+=b-a
    return dict(verified=True,actual_h20_verified=True,h20_samples=horizon_checks,frames=offset,episodes=len(episodes),all_numeric_source_values_equal=True,official_every_episode_first_last=True,task_count=len(vocabulary))


def validate_task_training_encoding(destination,expected_videos):
    # Full native MP4 archives are separate; count only official training media.
    from lerobot.common.datasets.video_utils import get_video_info
    destination=Path(destination);videos=sorted((destination/'videos').rglob('*.mp4'))
    if len(videos)!=expected_videos:raise ValueError('task_training_video_count_mismatch')
    expected={'video.codec':'h264','video.pix_fmt':'yuv420p','video.fps':20,'video.width':224,'video.height':224}
    for path in videos:
        info=get_video_info(path)
        if any(info.get(key)!=value for key,value in expected.items()):raise ValueError('task_training_video_contract_mismatch')
    metadata=json.loads((destination/'meta/info.json').read_text())
    for camera in MODEL_CAMERAS:
        actual=metadata['features']['observation.images.'+camera].get('info',{})
        if any(actual.get(key)!=value for key,value in expected.items()):raise ValueError('task_training_video_metadata_mismatch')
    return dict(verified=True,videos=len(videos),actual_codec='h264',full_native_archives_counted_as_training=False)


class FFV1WindowWriter:
    """One bounded encoder for an active source window, never a frame cache."""
    def __init__(self,path,fps=20):
        import av
        self.av=av;self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
        if self.path.exists():raise ValueError('refuse_existing_native_action_clip')
        self.container=av.open(str(self.path),'w',format='matroska');self.stream=None;self.count=0
    def write(self,image):
        if self.stream is None:
            self.stream=self.container.add_stream('ffv1',rate=20);self.stream.width=image.shape[1];self.stream.height=image.shape[0];self.stream.pix_fmt='bgr0';self.stream.codec_context.thread_count=2
        frame=self.av.VideoFrame.from_ndarray(image,format='rgb24');frame.pts=self.count;frame.time_base=Fraction(1,20)
        for packet in self.stream.encode(frame):self.container.mux(packet)
        self.count+=1
    def finish(self):
        if self.stream is None:raise ValueError('empty_native_action_clip')
        for packet in self.stream.encode():self.container.mux(packet)
        self.container.close();return self.count
    def abort(self):self.container.close()


def cut_native_windows(reference,windows,*,expected_source_frames,decoder=None,writer_factory=None):
    """Decode a full source once and route to explicitly overlapping windows."""
    decoder=decoded_rgb if decoder is None else decoder
    writer_factory=FFV1WindowWriter if writer_factory is None else writer_factory
    if digest(reference['path'])!=reference['sha256']:raise ValueError('native_full_source_changed')
    if not windows:return {}
    entries={}
    for window in windows:
        key=window['segment_id'];a,b=window['start_frame'],window['end_frame']
        if key in entries or type(a) is not int or type(b) is not int or not 0<=a<b<=expected_source_frames:
            raise ValueError('native_window_identity_or_range_invalid')
        entries[key]=dict(window=window,hash=hashlib.sha256(),count=0,shape=None,writer=None)
    starts={};ends={}
    for key,item in entries.items():
        starts.setdefault(item['window']['start_frame'],[]).append(key)
        ends.setdefault(item['window']['end_frame'],[]).append(key)
    active={};decoded=0;maximum_active=0
    try:
        for index,image in enumerate(decoder(reference['path'])):
            if index>=expected_source_frames:raise ValueError('native_full_source_has_extra_frames')
            image=np.asarray(image)
            if image.dtype!=np.uint8 or image.ndim!=3 or image.shape[-1]!=3:raise ValueError('native_rgb_frame_invalid')
            for key in starts.get(index,[]):
                item=entries[key];item['writer']=writer_factory(item['window']['path'],20);active[key]=item
            maximum_active=max(maximum_active,len(active))
            for key,item in active.items():
                if item['shape'] is None:item['shape']=image.shape
                if item['shape']!=image.shape:raise ValueError('native_source_resolution_changed')
                item['hash'].update(np.ascontiguousarray(image).tobytes());item['writer'].write(image);item['count']+=1
            for key in ends.get(index+1,[]):
                item=active.pop(key)
                if item['writer'].finish()!=item['count']:raise ValueError('native_encoded_frame_count_changed')
                item['writer']=None
            decoded+=1
        if decoded!=expected_source_frames or active:raise ValueError('native_full_source_frame_count_changed')
    finally:
        for item in entries.values():
            if item['writer'] is not None:item['writer'].abort()
    output={}
    for key,item in entries.items():
        window=item['window'];sha=hashlib.sha256();count=0
        for image in decoder(window['path']):
            if np.asarray(image).shape!=item['shape']:raise ValueError('native_clip_resolution_changed')
            sha.update(np.ascontiguousarray(image).tobytes());count+=1
        if count!=window['end_frame']-window['start_frame'] or sha.digest()!=item['hash'].digest():
            raise ValueError('native_clip_rgb_or_frame_alignment_changed')
        output[key]=dict(path=str(Path(window['path']).resolve()),sha256=digest(window['path']),source_path=str(Path(reference['path']).resolve()),source_sha256=reference['sha256'],source_start_frame=window['start_frame'],source_end_frame=window['end_frame'],frames=count,fps=20,width=item['shape'][1],height=item['shape'][0],codec='ffv1',container='matroska',pixel_format='bgr0',decoded_rgb_sha256=sha.hexdigest(),all_decoded_rgb_frames_equal_source=True,native_resolution_preserved=True,full_source_decoded_frames=decoded,source_decode_passes=1,maximum_active_window_encoders=maximum_active,whole_source_rgb_not_cached=True)
    return output


def source_segment_identity(task,row):
    return 'whole_action_'+record_hash(dict(trace_sha256=task['trace_sha256'],result_sha256=task['result_sha256'],scene_xml_sha256=task['scene_xml_sha256'],start=row['start_frame'],end=row['end_frame'],operation_index=row['operation_index'],action_label=row['action_label'],source_constituents_sha256=row['source_constituents_sha256']))[:24]


def cut_case_native_windows(views,windows_by_camera,*,expected_source_frames,workers=4,cutter=None):
    """Four independent bounded decoders/writers; metadata stays on caller thread."""
    from concurrent.futures import ThreadPoolExecutor
    if type(workers) is not int or not 1<=workers<=4:raise ValueError('native_camera_workers_must_be_between_one_and_four')
    if set(views)!=set(NATIVE_CAMERAS) or set(windows_by_camera)!=set(NATIVE_CAMERAS):
        raise ValueError('parallel_native_four_camera_contract_required')
    paths=[str(Path(window['path']).resolve()) for camera in NATIVE_CAMERAS for window in windows_by_camera[camera]]
    if len(paths)!=len(set(paths)):raise ValueError('parallel_native_output_paths_overlap')
    cutter=cut_native_windows if cutter is None else cutter
    def cut(camera):
        return cutter(views[camera],windows_by_camera[camera],expected_source_frames=expected_source_frames)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results=list(pool.map(cut,NATIVE_CAMERAS))
    return dict(zip(NATIVE_CAMERAS,results,strict=True))


def update_action_video_index(destination,episodes,dataset):
    destination=Path(destination);lines=['split\tscene_id\taction_label\trole\tcamera\tsource_start_frame\tsource_end_frame\tfps\tframes\tpath']
    text=[]
    for episode in episodes:
        refs=[('native_inspection',camera,ref['path']) for camera,ref in episode['native_action_clips'].items()]
        refs += [('training_h264_224',camera,str(destination/dataset.meta.get_video_file_path(episode['episode_index'],'observation.images.'+camera))) for camera in MODEL_CAMERAS]
        for role,camera,path in refs:
            if not Path(path).is_file():continue
            lines.append('\t'.join(str(value) for value in (episode['split'],episode['scene_id'],episode['action_label'],role,camera,episode['source_start_frame'],episode['source_end_frame'],20,episode['frames'],path)))
            text.append(path)
    for name,content in [('COMPLETE_ACTION_VIDEO_INDEX.tsv','\n'.join(lines)+'\n'),('COMPLETE_ACTION_VIDEO_INDEX.txt','\n'.join(text)+'\n')]:
        temporary=destination/(name+'.tmp');temporary.write_text(content,encoding='utf-8');temporary.replace(destination/name)


def available_native_overrides(cases,references,*,verification_cache=None):
    """Consume only complete four-view full-source publications, never partial cases."""
    grouped={}
    for ref in references:
        grouped.setdefault(ref.get('trace_sha256'),[]).append(ref)
    result={}
    for case in cases:
        task=case['original_inventory'];refs=grouped.get(task['trace_sha256'],[])
        views={ref['camera']:ref for ref in refs}
        if set(views)!=set(NATIVE_CAMERAS):continue
        normalized=[]
        for camera in NATIVE_CAMERAS:
            ref=dict(views[camera])
            known=None
            if ref.get('source_start_frame',0)!=0 or ref.get('video_start_frame',0)!=0 or ref.get('frames')!=task['frames'] or ref.get('native') is not True:
                raise ValueError('native_publication_is_not_full_source')
            manifest=Path(ref.get('source_manifest',str(Path(ref['path']).parent/'manifest.json')))
            body=json.loads(manifest.read_text(encoding='utf-8'))
            if body.get('schema')=='airport_complete_task_native_replay/1':
                for left,right in [('trace_sha256','trace_sha256'),('source_result_sha256','result_sha256'),('scene_xml_sha256','scene_xml_sha256'),('source_scene_json_sha256','scene_json_sha256')]:
                    if body.get(left)!=task[right]:raise ValueError('native_replay_source_binding_changed:'+left)
                if body.get('status')!='complete' or body.get('task_completed') is not True or body.get('camera_texture_quality_passed') is not True or body.get('per_frame_state_reset') is not False:
                    raise ValueError('new_full_native_replay_not_qualified')
                if any(body.get(section,{}).get(k)!=0 for section in ('prefix_errors','terminal_errors') for k in ('qpos','qvel','time')):
                    raise ValueError('native_replay_state_errors')
            else:
                # Original source inventories already bind these historical manifests.
                known=next((old for old in task.get('native_videos',[]) if old['camera']==camera and old['path']==ref['path']),None)
                if known is None:raise ValueError('unrecognized_native_replay_schema')
                if digest(manifest)!=known['manifest_sha256']:raise ValueError('historical_native_manifest_changed')
            header=ref.get('encoded_metadata')
            if header is None and known is not None and known.get('header') is not None:
                signature=(str(Path(ref['path']).resolve()),Path(ref['path']).stat().st_size,
                    Path(ref['path']).stat().st_mtime_ns,ref['sha256'],known['manifest_sha256'])
                if verification_cache is None or verification_cache.get(signature) is not True:
                    if digest(ref['path'])!=ref['sha256'] or known['sha256']!=ref['sha256']:
                        raise ValueError('native_metadata_reuse_video_bytes_changed')
                    if verification_cache is not None:verification_cache[signature]=True
                header=dict(known['header'])
                ref['header_verification_origin']='current_video_SHA_bound_to_original_verified_inventory_header_and_manifest_SHA; full_decode_repeated_by_case_cut'
            if header is None:
                import subprocess
                probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-select_streams','v:0','-count_frames','-show_entries','stream=codec_name,width,height,avg_frame_rate,nb_frames,nb_read_frames','-of','json',ref['path']],text=True))
                header=probe['streams'][0]
            header=dict(header);header['nb_frames']=header.get('nb_frames',header.get('nb_read_frames'))
            normalized.append(dict(ref,manifest=str(manifest),manifest_sha256=digest(manifest),header=header))
        result[task['scene_id']]=dict(trace_sha256=task['trace_sha256'],native_videos=normalized)
    return result


def assemble_complete_task_split(case_datasets,destination,repo_id,*,split,expected_scene_ids):
    """Reindex independently audited cases, preserving newly encoded media bytes."""
    import copy
    import pyarrow.parquet as pq
    from lerobot.common.datasets.lerobot_dataset import LeRobotDataset,LeRobotDatasetMetadata
    from lerobot.common.datasets.compute_stats import compute_episode_stats
    destination=Path(destination)
    if destination.exists():raise ValueError('refuse_existing_complete_task_split')
    sources=[Path(p) for p in case_datasets]
    manifests=[json.loads((p/'airport_training_manifest.json').read_text()) for p in sources]
    scene_ids=[m['episodes'][0]['scene_id'] for m in manifests]
    if len(scene_ids)!=len(set(scene_ids)) or set(scene_ids)!=set(expected_scene_ids):raise ValueError('full_split_case_coverage_incomplete')
    if any(m['split']!=split or m['prompt_mode']!='task_complete_action8_v1' or not m['all_parquet_values_verified']['verified'] for m in manifests):raise ValueError('case_dataset_not_verified_or_split_changed')
    vocabulary=action_vocabulary(manifests[0]['action_vocabulary'])
    if any(m['action_vocabulary']!=manifests[0]['action_vocabulary'] for m in manifests):raise ValueError('case_vocabularies_differ')
    metadata=LeRobotDatasetMetadata(manifests[0]['repo_id'],root=sources[0])
    defaults={'timestamp','frame_index','episode_index','index','task_index'}
    features={k:copy.deepcopy(v) for k,v in metadata.features.items() if k not in defaults}
    ds=LeRobotDataset.create(repo_id=repo_id,root=destination,fps=20,robot_type=metadata.info['robot_type'],features=features,use_videos=True,video_backend='pyav')
    for entry in vocabulary.values():ds.meta.add_task(entry['language_prompt'])
    episodes=[];offset=0;source_rows=[];archive_paths=[];case_image_audits=[];case_plan_identities=[];image_checks=[]
    for source,manifest in zip(sources,manifests):
        meta=LeRobotDatasetMetadata(manifest['repo_id'],root=source)
        image_audit=manifest.get('actual_training_rgb_derivation',{})
        if image_audit.get('verified') is not True or image_audit.get('preencode_all_source_rgb_exact') is not True:
            raise ValueError('assembled_case_training_RGB_audit_not_verified')
        case_image_audits.append(dict(training_manifest=str(source/'airport_training_manifest.json'),
            training_manifest_sha256=digest(source/'airport_training_manifest.json'),
            original_checks=len(image_audit.get('checks',[])),verified=True))
        case_plan_identities.append(dict(scene_id=manifest['episodes'][0]['scene_id'],input_plan_sha256=manifest['input_plan_sha256'],
            training_manifest_sha256=digest(source/'airport_training_manifest.json')))
        index_map={}
        for old in manifest['episodes']:
            index=len(episodes);n=old['frames'];table=pq.read_table(source/meta.get_data_file_path(old['episode_index']))
            arrays={key:np.asarray(table[key].to_pylist(),dtype=np.float32) for key in ('observation.state','action')}
            arrays.update(timestamp=np.arange(n)/20,frame_index=np.arange(n,dtype=np.int64),episode_index=np.full(n,index,dtype=np.int64),index=np.arange(offset,offset+n,dtype=np.int64),task_index=np.full(n,old['task_index'],dtype=np.int64))
            for camera in MODEL_CAMERAS:
                key='observation.images.'+camera;original=source/meta.get_video_file_path(old['episode_index'],key);target=destination/ds.meta.get_video_file_path(index,key)
                target.parent.mkdir(parents=True,exist_ok=True)
                try:os.link(original,target)
                except OSError:shutil.copy2(original,target)
                if digest(original)!=digest(target):raise ValueError('assembled_training_video_bytes_changed')
            ds._save_episode_table(arrays,index)
            numeric_features={k:v for k,v in ds.features.items() if v['dtype'] not in ('image','video')}
            statistics=compute_episode_stats(arrays,numeric_features)
            statistics.update({k:copy.deepcopy(v) for k,v in meta.episodes_stats[old['episode_index']].items() if k in meta.video_keys})
            ds.meta.save_episode(index,n,[old['language_prompt']],statistics)
            episode=copy.deepcopy(old);episode['episode_index']=index;episodes.append(episode);offset+=n
            index_map[old['episode_index']]=index
        if len(image_audit.get('checks',[]))!=len(manifest['episodes'])*3:
            raise ValueError('assembled_case_training_RGB_audit_camera_coverage_changed')
        for check in image_audit['checks']:
            entry=copy.deepcopy(check);entry['source_case_episode_index']=entry['episode_index']
            entry['episode_index']=index_map[entry['episode_index']];entry['source_case_training_manifest']=str(source/'airport_training_manifest.json')
            image_checks.append(entry)
        source_rows.extend(json.loads(line) for line in Path(manifest['source_manifest']).read_text().splitlines())
        archive_paths.extend(manifest['full_task_archives'])
    audit=audit_task_parquet(destination,episodes,vocabulary,repo_id=repo_id)
    encoding=validate_task_training_encoding(destination,len(episodes)*3)
    source_manifest=destination/'whole_action_source_manifest.jsonl';source_manifest.write_text(''.join(json.dumps(row,allow_nan=False)+'\n' for row in source_rows))
    result=copy.deepcopy(manifests[0]);counts={k:sum(m['counts'][k] for m in manifests) for k in manifests[0]['counts']}
    result.update(repo_id=repo_id,episodes=episodes,counts=counts,source_manifest=str(source_manifest),source_manifest_sha256=digest(source_manifest),full_task_archives=archive_paths,all_parquet_values_verified=audit,training_video_encoding_verification=encoding,complete_expected_scene_ids=sorted(expected_scene_ids),dataset_ready=True,derived_from_case_training_manifests=[dict(path=str(p/'airport_training_manifest.json'),sha256=digest(p/'airport_training_manifest.json')) for p in sources],training_started=False,
        actual_training_rgb_derivation=dict(verified=True,preencode_all_source_rgb_exact=True,h264_is_lossy=True,
            audit_scope='All constituent case audits bound by current manifest hashes; aggregate videos copied byte-exactly without re-encoding',
            constituent_case_audits=case_image_audits,checks=image_checks),
        input_plan_sha256=None,input_plan_scope='case_plan_hashes_individually_bound; full_input_plan_hash_published_by_assembler_controller',
        case_input_plan_identities=case_plan_identities)
    (destination/'airport_training_manifest.json').write_text(json.dumps(result,indent=2,allow_nan=False))
    update_action_video_index(destination,episodes,ds)
    return dict(path=str(destination),repo_id=repo_id,scenes=len(scene_ids),episodes=len(episodes),frames=offset,dataset_ready=True,training_started=False)


def audit_training_rgb_derivation(destination,episodes,dataset):
    """Lossy H264 is measured separately from exact native RGB preservation."""
    import itertools
    from PIL import Image
    checks=[]
    for episode in episodes:
        for camera in MODEL_CAMERAS:
            native=episode['native_action_clips'][camera]['path']
            encoded=Path(destination)/dataset.meta.get_video_file_path(episode['episode_index'],'observation.images.'+camera)
            sha=hashlib.sha256();count=0;absolute_sum=0;values=0;maximum=0
            for original,decoded in itertools.zip_longest(decoded_rgb(native),decoded_rgb(encoded)):
                if original is None or decoded is None:raise ValueError('training_rgb_frame_alignment_changed')
                expected=model_image(Image.fromarray(original));sha.update(np.ascontiguousarray(expected).tobytes())
                if expected.shape!=decoded.shape:raise ValueError('training_rgb_dimensions_changed')
                difference=np.abs(expected.astype(np.int16)-decoded.astype(np.int16))
                absolute_sum+=int(difference.sum());values+=difference.size;maximum=max(maximum,int(difference.max()));count+=1
            if count!=episode['frames'] or sha.hexdigest()!=episode['preencode_training_rgb_sha256'][camera]:raise ValueError('training_preencode_source_rgb_changed')
            mae=absolute_sum/values
            if mae>10:raise ValueError('training_h264_mean_absolute_rgb_error_exceeds_10_of_255')
            checks.append(dict(episode_index=episode['episode_index'],camera=camera,frames=count,preencode_rgb_exact=True,decoded_h264_pixel_exact_claim=False,decoded_mean_absolute_rgb_error=mae,decoded_maximum_absolute_rgb_error=maximum,declared_mean_absolute_tolerance=10))
    return dict(verified=True,preencode_all_source_rgb_exact=True,h264_is_lossy=True,checks=checks)
