"""Immutable two-action Isaac inputs for real/sim BC; no reward or RL claim."""
import json
from pathlib import Path
import numpy as np
from .real_sim_data import CAMERAS, PROMPTS, write, sha, decode_selected


def freeze_pairs(batch_paths, output, parent_splits, *, minimum_sources=300):
    """Freeze complete audited pairs, retaining original train-only provenance."""
    pairs=[];seen=set();files={}
    for batch_path in batch_paths:
        path=Path(batch_path).resolve();batch=json.loads(path.read_text())
        rows=batch.get('segments',[])
        if batch.get('ready') is not True or len(rows)!=2 or [r['prompt'] for r in rows]!=list(PROMPTS[:2]):
            raise ValueError('complete_two_action_batch_required')
        room=Path(rows[0]['source_room']).resolve()
        if str(room) in seen:raise ValueError('duplicate_source_room')
        seen.add(str(room));parent=rows[0]['parent_scene_id'];split=rows[0]['split']
        if parent_splits.get(parent)!=split:raise ValueError('parent_split_mismatch')
        audit=room/'parallel_export_audit.json';audit_row=json.loads(audit.read_text())
        if audit_row.get('passed') is not True:raise ValueError('independent_room_audit_required')
        for row in rows:
            if (Path(row['source_room']).resolve()!=room or row['parent_scene_id']!=parent or row['split']!=split
                    or not row.get('complete_pick_place_pair') or row.get('model_executed') is not False
                    or row.get('source_domain')!='simulation/program_generated'):
                raise ValueError('pair_source_identity_mismatch')
            receipt=Path(row['actual_engine_exit_receipt']);d=json.loads(receipt.read_text())
            if d.get('actual_child_wait') is not True or d.get('returncode')!=0:raise ValueError('actual_engine_exit_required')
            checks={Path(row['trajectory']):row['trajectory_sha256'],room/'native_trace.npz':row['source_trace_sha256'],
                    room/'result.json':row['source_result_sha256']}
            checks.update({Path(v['path']):v['sha256'] for v in row['videos']})
            if set(v['camera'] for v in row['videos'])!={'head_left','head_right','left_wrist','right_wrist'}:
                raise ValueError('four_recorded_cameras_required')
            if audit_row['trace_sha256']!=row['source_trace_sha256']:raise ValueError('audit_trace_changed')
            for file,h in checks.items():
                if sha(file)!=h:raise ValueError('source_artifact_changed:'+str(file))
                files[str(file.resolve())]=h
            files[str(receipt.resolve())]=sha(receipt)
        files[str(path)]=sha(path);files[str(audit)]=sha(audit)
        station=room/'initial_base_station.json';files[str(station)]=sha(station)
        pairs.append(dict(source_room=str(room),parent_scene_id=parent,split=split,segments=rows))
    if len(pairs)<minimum_sources:raise ValueError('waiting_for_complete_sources:'+str(len(pairs)))
    result=dict(schema='parallel_pickplace_frozen_training/1',ready=True,engine='isaacsim',physics_backend='physx',
                complete_source_pairs=len(pairs),action_segments=2*len(pairs),pairs=pairs,files=files,
                reward_enabled=False,method='BC',full_three_tray_task=False)
    output=Path(output)
    if output.exists():
        if json.loads(output.read_text())!=result:raise ValueError('frozen_manifest_changed')
    else:write(output,result)
    return result


def verify_frozen(path):
    result=json.loads(Path(path).read_text())
    if result.get('schema')!='parallel_pickplace_frozen_training/1' or result.get('ready') is not True:
        raise ValueError('frozen_parallel_manifest_required')
    for file,h in result['files'].items():
        if sha(file)!=h:raise ValueError('frozen_input_changed:'+file)
    return result


def cache_estimate(frames):
    return dict(frames=int(frames),rgb_bytes=int(frames)*len(CAMERAS)*224*224*3,
                numeric_bytes=int(frames)*(19*4*2+8+4),rgb_dtype='uint8',numeric_dtype='float32',
                real_cache_reused_not_copied=True,checkpoint_bytes_not_included=True)


def materialize_parallel_cache(manifest_path, output, *, split='train', decode=None):
    manifest=verify_frozen(manifest_path);decode=decode or decode_selected
    sources=[p for p in manifest['pairs'] if p['split']==split]
    rows=[s for p in sources for s in p['segments']]
    n=sum(r['frames'] for r in rows)
    if not n:raise ValueError('no_sources_in_requested_original_split')
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    arrays={k:np.lib.format.open_memmap(output/(k+'.npy'),mode='w+',dtype=np.float32,shape=(n,19)) for k in ('state','action')}
    images={c:np.lib.format.open_memmap(output/(c+'.npy'),mode='w+',dtype=np.uint8,shape=(n,224,224,3)) for c in CAMERAS}
    ends=np.empty(n,np.int64);task=np.empty(n,np.int32);episodes=[];offset=0
    for row in rows:
        count=row['frames'];room=Path(row['source_room'])
        with np.load(row['trajectory']) as z:
            state=np.asarray(z['state'][:-1],np.float32);action=np.asarray(z['action'],np.float32)
            if state.shape!=action.shape or state.shape!=(count,19):raise ValueError('segment_state_action_alignment')
            if not np.isfinite(state).all() or not np.isfinite(action).all():raise ValueError('nonfinite_segment')
            # Both domains express the stationary chassis relative to episode
            # origin. Keep true drift; do not replace feedback with the target.
            origin=np.asarray(json.loads((room/'initial_base_station.json').read_text())['fixed_command'],np.float32)
            if not np.allclose(action[:,16:],origin,atol=1e-7,rtol=0):raise ValueError('source_base_not_fixed')
            with np.load(room/'native_trace.npz') as full:
                feedback_origin=np.asarray(full['state'][0,16:19],np.float32).copy()
            state=state.copy();action=action.copy();state[:,16:]-=feedback_origin;action[:,16:]=0.
            arrays['state'][offset:offset+count]=state;arrays['action'][offset:offset+count]=action
        videos={v['camera']:v for v in row['videos']}
        for camera,target in images.items():
            actual=decode(videos[camera]['path'],np.arange(count),target[offset:offset+count])
            if actual!=count:raise ValueError('video_segment_frame_count_changed')
        task_index=PROMPTS.index(row['prompt']);task[offset:offset+count]=task_index;ends[offset:offset+count]=offset+count
        episodes.append(dict(episode_id=row['source_room'],parent_scene_id=row['parent_scene_id'],split=split,
            domain='simulation',engine='isaacsim',task_index=task_index,offset=offset,frames=count,
            duration_seconds=count/20,source_trajectory_sha256=row['trajectory_sha256'],reward_weight_applied=False,
            base_mapping=dict(state_origin_measured_mobile19=feedback_origin.tolist(),source_fixed_command=origin.tolist(),
                observation='source_measured_base_minus_episode_first_feedback',action='static_zero_hold',
                original_trace_unchanged=True,arm_and_gripper_values_unchanged=True)))
        offset+=count
    for a in [*arrays.values(),*images.values()]:a.flush()
    np.save(output/'end.npy',ends);np.save(output/'task.npy',task)
    write(output/'manifest.json',dict(schema='parallel_pickplace_bc_cache/1',ready=True,fps=20,frames=n,
        episodes=episodes,source_domains=['simulation'],engine='isaacsim',physics_backend='physx',split=split,
        complete_source_pairs=len(sources),action_segments=len(rows),source_manifest=str(Path(manifest_path).resolve()),
        source_manifest_sha256=sha(manifest_path),base_target='fixed_episode_relative_origin_preserve_measured_drift',
        state_dtype='float32',rgb_dtype='uint8',model_cameras=list(CAMERAS),recorded_camera_count=4,
        arm_units='rad',gripper_units='m',chunk_boundary='action_segment_end',method='BC',reward_enabled=False))
    write(output/'integrity.json',{p.name:sha(p) for p in output.iterdir() if p.suffix in ('.npy','.json')})
    return output


def duration_sampling_weights(tasks,episodes,*,fps=20):
    """Train-only bounded relative sampling weights; not an RL reward.

    Median duration is computed separately per action within this one domain.
    Every source frame remains available; no time resampling or trimming.
    """
    tasks=np.asarray(tasks);weights=np.ones(len(tasks),float);covered=np.zeros(len(tasks),bool)
    durations={k:[] for k in (0,1)}
    for episode in episodes:
        if episode.get('split')!='train':raise ValueError('duration_weights_train_only')
        task=int(episode['task_index']);frames=int(episode['frames']);offset=int(episode['offset'])
        if task not in durations or frames<=0 or offset<0 or offset+frames>len(tasks):raise ValueError('invalid_duration_episode')
        if covered[offset:offset+frames].any() or not np.all(tasks[offset:offset+frames]==task):raise ValueError('duration_episode_alignment')
        covered[offset:offset+frames]=True;durations[task].append(frames/fps)
    if not covered.all() or any(not v for v in durations.values()):raise ValueError('duration_episode_coverage')
    medians={k:float(np.median(v)) for k,v in durations.items()};rows=[]
    for episode in episodes:
        task=int(episode['task_index']);frames=int(episode['frames']);offset=int(episode['offset'])
        w=float(np.clip(medians[task]/(frames/fps),.5,2.));weights[offset:offset+frames]=w/frames
        rows.append(dict(offset=offset,frames=frames,task_index=task,duration_seconds=frames/fps,
                        source_weight=w,unnormalized_frame_weight=w/frames))
    for task in (0,1):
        total=float(weights[tasks==task].sum())
        for row in rows:
            if row['task_index']==task:
                row['source_probability_within_domain_action']=row['source_weight']/total
                row['frame_probability_within_domain_action']=row['unnormalized_frame_weight']/total
    return weights,dict(method='duration_weighted_sampling_BC',not_RL=True,train_only=True,
        normalization_scope='within_this_domain_and_action',median_seconds=medians,clip=[.5,2.],
        frame_weight_min=float(weights.min()),frame_weight_max=float(weights.max()),frame_weight_mean=float(weights.mean()),
        episodes=rows,sampling='weighted_episode_then_uniform_frame',frames_trimmed=0,playback_speed_changed=False)


def balanced_mixed_schedule(real_tasks,sim_tasks,*,steps=10000,seed=42,real_weights=None,sim_weights=None,real_fraction=.5):
    if not isinstance(steps,int) or steps<1 or not np.isfinite(real_fraction) or not 0<=real_fraction<=1:
        raise ValueError('invalid_mixture_schedule')
    rng=np.random.default_rng(seed);domains=np.empty((steps,8),np.int8)
    indices=np.empty_like(domains,dtype=np.int64)
    pools={};counts=[0,0]
    for d,tasks,weights in ((0,np.asarray(real_tasks),real_weights),(1,np.asarray(sim_tasks),sim_weights)):
        if (real_fraction if d==0 else 1-real_fraction)==0:continue
        if set(map(int,tasks))!={0,1}:raise ValueError('two_actions_required_in_each_used_domain')
        for label in (0,1):
            pool=np.flatnonzero(tasks==label);probability=None
            if weights is not None:
                selected=np.asarray(weights)[pool]
                if not np.isfinite(selected).all() or np.any(selected<=0):raise ValueError('invalid_sampling_weights')
                probability=selected/selected.sum()
            pools[d,label]=(pool,probability)
    for step,row in enumerate(domains):
        # Cumulative rounding keeps any requested integer percent within one draw.
        # Action parity carries between batches, including odd per-domain counts.
        real_count=int(round((step+1)*8*real_fraction))-int(round(step*8*real_fraction))
        row[:real_count]=0;row[real_count:]=1
        rng.shuffle(row)
        for domain in (0,1):
            positions=np.flatnonzero(row==domain)
            labels=(np.arange(len(positions))+counts[domain])%2;counts[domain]+=len(positions)
            rng.shuffle(labels)
            for position,label in zip(positions,labels):
                pool,probability=pools[domain,int(label)]
                indices[step,position]=rng.choice(pool,p=probability)
    return domains,indices
