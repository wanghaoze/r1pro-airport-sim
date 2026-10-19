"""Independent contiguous-skill derivatives; immutable phase/source evidence."""
from __future__ import annotations
import copy
import hashlib
import json
import math
import numbers
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

SCHEMA = 'airport_vla_skill_contiguous_segments/1'
MERGE_KEYS = ('scene_id', 'split', 'trace', 'trace_sha256', 'collection',
              'collection_fingerprint', 'attempt', 'scene_source_sha256',
              'operation_index', 'skill', 'language_prompt', 'action_layout',
              'action_names', 'action_semantics', 'observation_semantics', 'fps',
              'quality_class', 'episode_strict_success', 'acceptance_profile',
              'strict_deviations', 'approximate_deviation_counts')


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def record_sha256(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def coverage_span_identity(span,base_qpos_indices,scene_identity):
    """Semantic identity excludes relocated media; media has independent hashes."""
    from .data_lineage import QUALITY_KEYS
    return canonical(dict(scene_id=span['scene_id'],source_trace_sha256=scene_identity['trace_sha256'],
        source_scene_xml_sha256=scene_identity['scene_xml_sha256'],source_scene_json_sha256=scene_identity['scene_json_sha256'],
        source_segment_id=span['source_segment_id'],source_interval=[span['start_frame'],span['end_frame']],
        collection_fingerprint=span['collection_fingerprint'],skill=span['skill'],phase=span['phase'],
        operation_index=span['operation_index'],language_prompt=span['language_prompt'],
        base_qpos_indices=list(base_qpos_indices),fps=20,action_layout=span['action_layout'],
        state_semantics='measured_joint16_plus_base_origin_offset3',action_semantics='absolute_mobile19',
        quality={k:span.get(k) for k in QUALITY_KEYS}))


def coverage_binding_hash(parent_identities,child_mappings):
    return record_sha256(dict(parent_constituent_identities=sorted(parent_identities),
        child_constituent_mappings=sorted(child_mappings,key=lambda row:canonical(row))))


def derived_resource_inventory(dataset):
    from .data import digest
    root=Path(dataset).resolve(); result=[]
    for scope in ('data','meta','videos'):
        for path in sorted((root/scope).rglob('*')):
            if not path.is_file():continue
            if not path.resolve().is_relative_to(root):raise ValueError('derived_resource_escapes_dataset')
            before=path.stat(); checksum=digest(path); after=path.stat()
            if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):
                raise ValueError('derived_resource_changed_during_audit')
            result.append(dict(path=path.relative_to(root).as_posix(),sha256=checksum,bytes=after.st_size))
    return sorted(result,key=lambda entry:entry['path'])


def audit_constituent_qualifications(path, authoritative_source_manifest):
    """Count qualifications from real constituents, never merged placeholder flags."""
    rows=[json.loads(line) for line in Path(path).read_text().splitlines()]
    if not rows or any(row.get('schema')!=SCHEMA for row in rows):
        raise ValueError('constituent_quality_requires_skill_contiguous_schema')
    spans=[span for row in rows for span in row['constituent_phase_spans']]
    if any(not eligible(span) for span in spans):raise ValueError('ineligible_quality_constituent')
    scenes={row['scene_id'] for row in rows}
    initialize={sid:sum(s['skill']=='initialize_posture' and
        (s.get('initial_posture_qualification') or {}).get('qualification')=='initial_tuck_after_physical_settle'
        for s in spans if s['scene_id']==sid) for sid in scenes}
    lifts=[s for s in spans if s['skill']=='grasp_lift_tray' and s['phase']=='lift']
    original=[json.loads(line) for line in Path(authoritative_source_manifest).read_text().splitlines()]
    expected_lifts={s['source_segment_id'] for s in original if s['scene_id'] in scenes
                    and s['skill']=='grasp_lift_tray' and s['phase']=='lift'}
    actual_lifts={s['source_segment_id'] for s in lifts}
    return dict(schema='airport_vla_constituent_quality/1',scene_count=len(scenes),
        merged_episodes=len(rows),source_constituents=len(spans),frames=sum(r['frames'] for r in rows),
        all_scenes_initialize=all(n==1 for n in initialize.values()),initializations=sum(initialize.values()),
        qualified_lift_operations=len(lifts),all_source_lifts_qualified=actual_lifts==expected_lifts,
        source_lift_operations=len(expected_lifts),missing_source_lift_ids=sorted(expected_lifts-actual_lifts),
        source_lift_ids=[s['source_segment_id'] for s in lifts],
        immutable_constituent_record_sha256=record_sha256([record_sha256(s) for s in spans]),
        by_skill=padding_summary(rows))


def finite_number(value):
    return isinstance(value,numbers.Real) and not isinstance(value,bool) and math.isfinite(value)


def eligible(row):
    """Do not requalify a record: unresolved review cannot become expert data."""
    if (row.get('schema') != 'airport_vla_segments/1' or row.get('split') != 'train'
            or row.get('training_ready') is not True or row.get('supervision_eligible') is not True
            or row.get('quality_class') != 'complete_task'
            or row.get('environment_source') != 'simulation'
            or row.get('controller_source') != 'program_generated'
            or row.get('human_demonstration') is not False):
        return False
    if any(row.get('videos',{}).get(camera,{}).get('verified') is not True
           or row.get('videos',{}).get(camera,{}).get('exists') is not True
           for camera in ('head_left','head_right','left_wrist','right_wrist')):
        return False
    if row.get('source_needs_review'):
        lift = row.get('verified_lift_takeoff') or {}
        init = row.get('initial_posture_qualification') or {}
        numeric_keys=('bilateral_min_force_n','endpoint_clearance_m','declared_lift_min_m')
        verified_lift = (lift.get('qualification') == 'verified_lift_takeoff'
            and type(lift.get('rule_version')) is int and lift.get('rule_version') == 2
            and all(finite_number(lift.get(k)) for k in numeric_keys)
            and lift.get('source_needs_review_preserved') is True
            and lift.get('source') == 'simulation/program_generated'
            and lift.get('source_interval') == [row['start_frame'], row['end_frame']]
            and lift.get('endpoint_observation_frame') == row['end_frame']
            and type(lift.get('endpoint_support_contact')) is int and lift.get('endpoint_support_contact') == 0
            and lift.get('bilateral_min_force_n',0) >= 0.5
            and type(lift.get('airborne_tail_interval_frames')) is int and lift.get('airborne_tail_interval_frames',0) > 0
            and lift.get('declared_lift_min_m',0) > 0
            and lift.get('endpoint_clearance_m',-1) >= lift.get('declared_lift_min_m',float('inf')))
        verified_init = (init.get('qualification') == 'initial_tuck_after_physical_settle'
            and init.get('settle_end_frame') == row['start_frame']
            and init.get('first_operation_frame') == row['end_frame'])
        if not (verified_lift or verified_init):
            return False
    return True


def can_merge(previous, following):
    if not eligible(previous) or not eligible(following):
        return False
    if previous['end_frame'] != following['start_frame']:
        return False
    if any(previous.get(key) != following.get(key) for key in MERGE_KEYS):
        return False
    for camera in ('head_left', 'head_right', 'left_wrist', 'right_wrist'):
        left = previous.get('videos', {}).get(camera, {})
        right = following.get('videos', {}).get(camera, {})
        if (left.get('verified') is not True or right.get('verified') is not True
                or any(left.get(key) != right.get(key) for key in ('path', 'sha256', 'measured'))):
            return False
    return True


def merge_ready_records(records):
    """Retain full constituent records; merge only accepted contiguous intervals."""
    groups = []
    seen = set()
    previous_ends = {}
    fenced = True
    for row in records:
        if row['segment_id'] in seen:
            raise ValueError('duplicate_source_segment')
        seen.add(row['segment_id'])
        a, b = row['start_frame'], row['end_frame']
        if type(a) is not int or type(b) is not int or not 0 <= a < b or row['frames'] != b-a:
            raise ValueError('invalid_source_interval')
        trace_key=(row['scene_id'],row['trace'])
        if a < previous_ends.get(trace_key,0):
            raise ValueError('overlapping_or_out_of_order_source_intervals')
        previous_ends[trace_key]=b
        if not eligible(row):
            fenced = True
            continue
        if not fenced and groups and can_merge(groups[-1][-1], row):
            groups[-1].append(row)
        else:
            groups.append([row])
        fenced = False
    merged = []
    for spans in groups:
        row = copy.deepcopy(spans[0])
        row['schema'] = SCHEMA
        row['constituent_phase_spans'] = copy.deepcopy(spans)
        row['constituent_record_sha256'] = [record_sha256(s) for s in spans]
        row['segment_id'] = 'skill_contiguous_' + record_sha256(row['constituent_record_sha256'])[:24]
        row['source_segment_id'] = row['segment_id']
        row['phase'] = 'skill_contiguous'
        row['source_phase'] = 'constituent_phase_spans'
        row['end_frame'] = spans[-1]['end_frame']
        row['frames'] = row['end_frame']-row['start_frame']
        row['end_time_s'] = row['end_frame']/row['fps']
        row['source_needs_review'] = any(s.get('source_needs_review', False) for s in spans)
        row['verified_lift_takeoff'] = None
        row['initial_posture_qualification'] = None
        row['quality_aggregation'] = 'constituent_records_preserved_without_requalification'
        for video in row['videos'].values():
            video['end_frame'] = row['end_frame']
            video['source_end_frame'] = row['end_frame']
            video['end_time_s'] = row['end_time_s']
        merged.append(row)
    return merged


def padding_summary(rows, horizon=20):
    skills = {}
    for row in rows:
        n = row['frames']
        skill = skills.setdefault(row['skill'], dict(episodes=0, frames=0, short_episodes=0,
                                                     padded_action_positions=0))
        skill['episodes'] += 1
        skill['frames'] += n
        skill['short_episodes'] += n < horizon
        skill['padded_action_positions'] += sum(max(0, horizon-n+i) for i in range(n))
    for skill in skills.values():
        skill['padded_supervision_fraction_uniform_frame_sampling'] = skill['padded_action_positions']/(horizon*skill['frames'])
    return skills


def plan_manifest(path):
    records = [json.loads(line) for line in Path(path).read_text(encoding='utf-8').splitlines()]
    source = [row for row in records if eligible(row)]
    merged = merge_ready_records(records)
    return dict(schema=SCHEMA, source_eligible_episodes=len(source), merged_episodes=len(merged),
                frames=sum(row['frames'] for row in merged), scenes=len({row['scene_id'] for row in merged}),
                source_padding=padding_summary(source), merged_padding=padding_summary(merged))


def video_signature(path):
    entries = 'codec_name,pix_fmt,width,height,r_frame_rate,time_base,extradata_hash'
    result = subprocess.check_output(['ffprobe','-v','error','-select_streams','v:0',
        '-show_data_hash','sha256','-show_entries','stream='+entries,'-of','json',str(path)],text=True)
    stream=json.loads(result)['streams'][0]
    if (stream.get('codec_name')!='h264' or stream.get('pix_fmt')!='yuv420p'
            or stream.get('width')!=224 or stream.get('height')!=224
            or stream.get('r_frame_rate')!='20/1' or not stream.get('extradata_hash')):
        raise ValueError('incompatible_training_video_for_lossless_concat')
    return stream


def decoded_frame_hashes(path):
    result=subprocess.check_output(['ffmpeg','-v','error','-threads','1','-i',str(path),
        '-map','0:v:0','-fps_mode','passthrough','-f','framemd5','-'],text=True)
    return [line.split(',')[-1].strip() for line in result.splitlines()
            if line.strip() and not line.startswith('#')]


def concat_videos_losslessly(paths, destination, expected_frames):
    """Copy H264 packets, then compare every decoded image to source clips."""
    from .data import digest
    paths=[Path(p).resolve() for p in paths]; destination=Path(destination)
    if destination.exists(): raise ValueError('refuse_existing_concatenated_video')
    signatures=[video_signature(p) for p in paths]
    if any(s!=signatures[0] for s in signatures[1:]):
        raise ValueError('concat_stream_parameters_or_sps_differ')
    source_hashes=[digest(p) for p in paths]
    destination.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='skill_concat_',dir=destination.parent) as temp:
        concat=Path(temp)/'inputs.ffconcat'
        # ffconcat's quoted path grammar; reject newlines instead of creating directives.
        if any('\n' in str(p) or '\r' in str(p) for p in paths):
            raise ValueError('invalid_concat_path')
        concat.write_text('ffconcat version 1.0\n'+''.join("file '"+str(p).replace("'","'\\''")+"'\n" for p in paths))
        subprocess.run(['ffmpeg','-v','error','-n','-f','concat','-safe','0','-i',str(concat),
                        '-map','0:v:0','-c','copy',str(destination)],check=True)
    actual=decoded_frame_hashes(destination)
    reference=[h for p in paths for h in decoded_frame_hashes(p)]
    if len(actual)!=expected_frames or actual!=reference:
        raise ValueError('lossless_concat_decoded_frame_identity_mismatch')
    if [digest(p) for p in paths]!=source_hashes:
        raise ValueError('source_video_changed_during_concat')
    if video_signature(destination)!=signatures[0]:
        raise ValueError('lossless_concat_output_stream_identity_changed')
    return dict(codec='h264', method='ffmpeg_concat_stream_copy', reencoded=False,
                every_decoded_frame_verified=True, frames=len(actual),
                decoded_frame_identity_sha256=record_sha256(actual),sha256=digest(destination),
                source_paths=[str(p) for p in paths],source_sha256=source_hashes)


def materialize_skill_dataset(source_dataset, destination, repo_id, manifest_output, *, scene_ids=None):
    """Use official metadata/table APIs and lossless derived video concatenation.

    Source must already have passed its full loader/encoding/source checks. No
    image PNGs or new physical trajectories are created by this derivative.
    """
    import numpy as np
    import pyarrow.parquet as pq
    from lerobot.common.datasets.lerobot_dataset import LeRobotDataset, LeRobotDatasetMetadata
    from lerobot.common.datasets.compute_stats import aggregate_stats, compute_episode_stats
    from .data import digest
    from .data_lerobot import EPISODE_QUALITY_FIELDS, MODEL_CAMERAS, validate_training_encoding
    source=Path(source_dataset).resolve(); destination=Path(destination).resolve()
    manifest_output=Path(manifest_output).resolve()
    if destination.exists() or manifest_output.exists():
        raise ValueError('skill_merge_requires_new_output')
    training_path=source/'airport_training_manifest.json'
    original=json.loads(training_path.read_text())
    if (original.get('official_loader_every_episode_first_last') is not True
            or original.get('training_video_encoding_verification',{}).get('verified') is not True
            or original.get('split')!='train' or original.get('fps')!=20
            or original.get('controller_source')!='program_generated'
            or original.get('environment_source')!='simulation' or original.get('human_demonstration') is not False):
        raise ValueError('skill_merge_requires_completed_verified_source_dataset')
    source_manifest=Path(original['source_manifest'])
    if digest(source_manifest)!=original['source_manifest_sha256']:
        raise ValueError('skill_merge_source_manifest_changed')
    records=[json.loads(line) for line in source_manifest.read_text().splitlines()]
    if scene_ids is not None:
        selected=set(scene_ids)
        if not selected or not selected.issubset({r['scene_id'] for r in records}):
            raise ValueError('invalid_explicit_source_scene_subset')
        records=[r for r in records if r['scene_id'] in selected]
    merged=merge_ready_records(records)
    source_episodes={e['segment_id']:e for e in original['episodes']
                     if scene_ids is None or e['scene_id'] in selected}
    constituent_ids=[span['segment_id'] for row in merged for span in row['constituent_phase_spans']]
    if (len(constituent_ids)!=len(set(constituent_ids)) or set(constituent_ids)!=set(source_episodes)
            or sum(r['frames'] for r in merged)!=sum(e['frames'] for e in source_episodes.values())):
        raise ValueError('skill_merge_cannot_drop_source_training_frame_coverage')
    # Each full original row remains hash-bound to the source training manifest.
    for row in merged:
        for span in row['constituent_phase_spans']:
            e=source_episodes[span['segment_id']]
            if (e['source_start_frame']!=span['start_frame'] or e['source_end_frame']!=span['end_frame']
                    or e['source_trace_sha256']!=span['trace_sha256']
                    or any(e[k]!=span[k] for k in ('scene_id','split','skill','phase','operation_index','language_prompt'))
                    or any(e.get(k)!=span.get(k) for k in EPISODE_QUALITY_FIELDS)):
                raise ValueError('skill_merge_source_episode_identity_changed')
    manifest_output.parent.mkdir(parents=True,exist_ok=True)
    with manifest_output.open('x') as stream:
        for row in merged:stream.write(json.dumps(row,allow_nan=False)+'\n')
    meta=LeRobotDatasetMetadata(original['repo_id'],root=source)
    defaults={'timestamp','frame_index','episode_index','index','task_index'}
    features={k:copy.deepcopy(v) for k,v in meta.features.items() if k not in defaults}
    ds=LeRobotDataset.create(repo_id=repo_id,root=destination,fps=20,
        robot_type=meta.info['robot_type'],features=features,use_videos=True,video_backend='pyav')
    result_episodes=[]; all_video_checks=[]; global_offset=0
    for index,row in enumerate(merged):
        source_eps=[source_episodes[s['segment_id']] for s in row['constituent_phase_spans']]
        tables=[pq.read_table(source/meta.get_data_file_path(e['episode_index'])) for e in source_eps]
        arrays={key:np.concatenate([np.asarray(t[key].to_pylist(),dtype=np.float32) for t in tables])
                for key in ('observation.state','action')}
        n=row['frames']
        if any(a.shape!=(n,19) or not np.isfinite(a).all() for a in arrays.values()):
            raise ValueError('skill_merge_source_mobile19_frame_shape_or_values')
        prompt=row['language_prompt']
        if ds.meta.get_task_index(prompt) is None:ds.meta.add_task(prompt)
        task_index=ds.meta.get_task_index(prompt)
        arrays.update(timestamp=np.arange(n)/20,frame_index=np.arange(n,dtype=np.int64),
            episode_index=np.full(n,index,dtype=np.int64),index=np.arange(global_offset,global_offset+n,dtype=np.int64),
            task_index=np.full(n,task_index,dtype=np.int64))
        def process_camera(camera):
            key='observation.images.'+camera
            paths=[source/meta.get_video_file_path(e['episode_index'],key) for e in source_eps]
            target=destination/ds.meta.get_video_file_path(index,key)
            return camera,concat_videos_losslessly(paths,target,n)
        # Only independent video files are parallel. Official metadata stays sequential.
        with ThreadPoolExecutor(max_workers=3) as pool:
            video_checks=dict(pool.map(process_camera,MODEL_CAMERAS))
        all_video_checks.extend(video_checks.values())
        ds._save_episode_table(arrays,index)
        numeric_features={k:v for k,v in ds.features.items() if v['dtype'] not in ('image','video')}
        statistics=compute_episode_stats(arrays,numeric_features)
        image_stats=aggregate_stats([{key:value for key,value in meta.episodes_stats[e['episode_index']].items()
                                    if key in ds.meta.video_keys} for e in source_eps])
        statistics.update(image_stats)
        ds.meta.save_episode(index,n,[prompt],statistics)
        episode=copy.deepcopy(source_eps[0])
        episode.update(episode_index=index,segment_id=row['segment_id'],source_start_frame=row['start_frame'],
            source_end_frame=row['end_frame'],frames=n,phase='skill_contiguous',native_source_videos=row['videos'],
            constituent_phase_spans=row['constituent_phase_spans'],
            constituent_record_sha256=row['constituent_record_sha256'],
            derived_source_episodes=[e['episode_index'] for e in source_eps],
            lossless_video_concat_audit=video_checks,quality_aggregation=row['quality_aggregation'])
        for key in EPISODE_QUALITY_FIELDS:
            if key in row:episode[key]=copy.deepcopy(row[key])
        result_episodes.append(episode);global_offset+=n
        print(json.dumps(dict(stage='merging_skill_episode',episodes=len(result_episodes),frames=global_offset,
                             total_episodes=len(merged))),flush=True)
    loaded=LeRobotDataset(repo_id,root=destination,video_backend='pyav')
    if len(loaded)!=global_offset:raise ValueError('skill_merge_official_loader_frame_count')
    offset=0
    for e in result_episodes:
        for i in (offset,offset+e['frames']-1):
            sample=loaded[i]
            if tuple(sample['action'].shape)!=(19,) or tuple(sample['observation.state'].shape)!=(19,):
                raise ValueError('skill_merge_official_loader_mobile19')
            if any(tuple(sample['observation.images.'+c].shape)!=(3,224,224) for c in MODEL_CAMERAS):
                raise ValueError('skill_merge_official_loader_images')
        offset+=e['frames']
    check=validate_training_encoding(destination,len(result_episodes)*len(MODEL_CAMERAS))
    boundary_check=verify_actual_skill_chunks(destination,repo_id,result_episodes)
    result=copy.deepcopy(original)
    result.update(repo_id=repo_id,episodes=result_episodes,source_manifest=str(manifest_output),
        source_manifest_sha256=digest(manifest_output),source_manifest_schema=SCHEMA,
        official_loader_every_episode_first_last=True,training_video_encoding_verification=check,
        derived_from_training_dataset=str(source),derived_from_training_manifest_sha256=digest(training_path),
        derived_from_source_manifest_sha256=digest(source_manifest),
        action_chunk_boundary='one_strictly_contiguous_scene_operation_skill_prompt_per_episode',
        explicit_source_scene_subset=sorted(selected) if scene_ids is not None else None,
        actual_skill_boundary_action_chunks=boundary_check,
        lossless_concat=dict(every_decoded_frame_verified=True,source_training_frames_preserved=True,
            reencoded=False,derived_video_count=len(all_video_checks),
            image_stats='aggregate_unchanged_source_official_episode_statistics'),
        source_padding=padding_summary([s for r in merged for s in r['constituent_phase_spans']]),
        merged_padding=padding_summary(merged),
        constituent_quality_audit=audit_constituent_qualifications(manifest_output,source_manifest))
    (destination/'airport_training_manifest.json').write_text(json.dumps(result,indent=2,allow_nan=False))
    return dict(dataset=str(destination),repo_id=repo_id,episodes=len(merged),frames=global_offset,
                source_manifest=str(manifest_output),official_loader_verified=True)


def verify_actual_skill_chunks(dataset_root,repo_id,episodes,horizon=20):
    """Actual official H20 loader checks at every removed phase boundary."""
    import h5py
    import numpy as np
    from lerobot.common.datasets.lerobot_dataset import LeRobotDataset
    loaded=LeRobotDataset(repo_id,root=Path(dataset_root),video_backend='pyav',
                         delta_timestamps={'action':[i/20 for i in range(horizon)]})
    offset=0; checks=[]
    for e in episodes:
        spans=e['constituent_phase_spans']
        frames=[(s['end_frame']-1,s['phase'],spans[i+1]['phase']) for i,s in enumerate(spans[:-1])]
        frames.append((e['source_end_frame']-1,'skill_end','terminal'))
        with h5py.File(e['source_trace'],'r') as trace:
            for frame,previous,next_phase in frames:
                idx=offset+frame-e['source_start_frame']
                sample=loaded[idx]
                source_indices=np.minimum(np.arange(frame,frame+horizon),e['source_end_frame']-1)
                # h5py fancy indexing disallows repeats; read whole accepted range first.
                a,b=e['source_start_frame'],e['source_end_frame']
                actions=np.concatenate((trace['action'][a:b],trace['base_action'][a:b]),axis=-1).astype(np.float32)
                expected=actions[source_indices-a]
                expected_mask=np.arange(frame,frame+horizon)>=e['source_end_frame']
                if (not np.array_equal(sample['action'].numpy(),expected)
                        or not np.array_equal(sample['action_is_pad'].numpy(),expected_mask)):
                    raise ValueError('merged_official_horizon_actions_or_pad_changed')
                checks.append(dict(episode_index=e['episode_index'],source_frame=frame,
                    previous_phase=previous,next_phase=next_phase,padded_positions=int(expected_mask.sum()),
                    actual_action_sha256=hashlib.sha256(sample['action'].numpy().tobytes()).hexdigest(),
                    continuous_source_verified=True))
        offset+=e['frames']
    return dict(verified=True,action_horizon=horizon,removed_phase_boundary_samples=sum(c['previous_phase']!='skill_end' for c in checks),
                real_skill_terminal_samples=len(episodes),samples=checks)
