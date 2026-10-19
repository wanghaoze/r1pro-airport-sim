"""Qualify per-room native pairs using one real engine exit receipt.

Never synthesizes per-room process exits or aligns independent starts by trimming.
The overview is a shared-clock diagnostic; only audited complete pairs export.
"""
import argparse
import html
import json
from pathlib import Path
import subprocess
import sys
import time

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from audit_isaacsim_fast_pickplace import audit
from isaacsim_stage_runner import atomic
from r1pro_teleop.vla.isaac_dataset import sha, video_probe

CAMERAS = ('head_left', 'head_right', 'left_wrist', 'right_wrist')
PROMPTS = ('Pick up the tray', 'Place the tray')
STEMS = ('pick_up_the_tray', 'place_the_tray')


def validate_alignment(result, z, initial, station):
    n = len(z['raw_action'])
    spans = result['actions']
    if [s['prompt'] for s in spans] != list(PROMPTS):
        raise ValueError('exact_pick_place_pair_required')
    if len(z['time']) != n+1 or not np.allclose(np.diff(z['time']), .05, atol=2e-5, rtol=0):
        raise ValueError('native_shared_clock_time_invalid')
    if len(z['state']) != n+1 or z['submitted_control'].shape[:2] != (n, 25):
        raise ValueError('native_control_alignment_invalid')
    for span in spans:
        if not (0 <= span['start'] < span['end'] <= n):
            raise ValueError('invalid_action_interval')
    at = spans[1]['start']
    if spans[0]['end'] != at or initial['frame'] != at or initial['reset_between_pick_and_place'] is not False:
        raise ValueError('place_not_actual_pick_continuation')
    if not np.array_equal(np.asarray(initial['state']), z['state'][at]):
        raise ValueError('place_initial_feedback_mismatch')
    if station.get('initialization_only_before_first_step') is not True:
        raise ValueError('fixed_base_initialization_receipt_required')
    command = np.asarray(station['fixed_command'])
    if command.shape != (3,) or not np.allclose(z['raw_action'][:, 16:19], command, atol=1e-12, rtol=0):
        raise ValueError('base_command_changed_including_preparation')
    drift = np.linalg.norm(z['state'][:, 16:18]-command[:2], axis=1)
    if not np.isfinite(drift).all() or drift.max() > .05:
        raise ValueError('base_actual_drift_over_existing_5cm')
    settings = result['case']
    if settings['initial_base_world'] != station['requested_world'] or settings['fixed_base_world'] != station['requested_world']:
        raise ValueError('fixed_station_identity_mismatch')
    return float(drift.max())


def validate_shared_clock(times):
    if not times:
        raise ValueError('no_room_times')
    reference = np.asarray(times[0])
    if len(reference) < 2 or not np.allclose(np.diff(reference), .05, atol=2e-5, rtol=0):
        raise ValueError('overview_reference_clock_invalid')
    if any(np.asarray(t).shape != reference.shape or not np.allclose(t, reference, atol=1e-8, rtol=0) for t in times[1:]):
        raise ValueError('overview_requires_identical_global_frame_clock')
    return len(reference)-1


def immutable(path, value):
    if path.exists():
        if json.loads(path.read_text()) != value:
            raise ValueError('immutable_manifest_changed:'+str(path))
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic(path, value)


def clip(source, output, lo, frames):
    if not output.exists():
        subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-n', '-threads', '1',
                        '-ss', f'{lo/20:.6f}', '-i', str(source), '-frames:v', str(frames),
                        '-an', '-vf', 'setpts=PTS-STARTPTS', '-c:v', 'libx264', '-preset', 'fast',
                        '-crf', '23', '-threads', '1', str(output)], check=True)
    p = video_probe(output)
    if p['frames'] != frames or p['fps'] != 20:
        raise ValueError('export_video_not_aligned:'+str(output))
    return dict(path=str(output), sha256=sha(output), **p)


def export_room(run, room, receipt, parent_splits):
    result = json.loads((room/'result.json').read_text())
    settings = result['case'];parent = settings['parent_scene_id'];split = settings['parent_split']
    if parent_splits.get(parent) != split or split not in ('train', 'val', 'test'):
        raise ValueError('parent_split_identity_mismatch')
    if set(result['native_encoders']) != set(CAMERAS):
        raise ValueError('four_native_cameras_required')
    report = audit(room, receipt_path=receipt)
    atomic(room/'parallel_export_audit.json', report)
    if not report['passed']:
        raise ValueError('actual_pair_audit_failed:'+str(report['errors']))
    initial = json.loads((room/'place_initial_state.json').read_text())
    station = json.loads((room/'initial_base_station.json').read_text())
    segments = []
    with np.load(room/'native_trace.npz') as z:
        drift = validate_alignment(result, z, initial, station)
        for span, stem in zip(result['actions'], STEMS):
            lo, hi = span['start'], span['end'];out = run/'dataset'/stem/split/room.name
            out.mkdir(parents=True, exist_ok=True)
            existing = out/'segment.json'
            if existing.exists():
                row=json.loads(existing.read_text())
                if row['source_trace_sha256'] != report['trace_sha256'] or row['source_result_sha256'] != report['source_result_sha256']:
                    raise ValueError('immutable_room_source_changed')
                for media in row['videos']:
                    if sha(media['path']) != media['sha256']:
                        raise ValueError('immutable_video_changed')
                if sha(row['trajectory']) != row['trajectory_sha256']:
                    raise ValueError('immutable_trajectory_changed')
                segments.append(row);continue
            videos = [dict(camera=cam, training_camera=True,
                           **clip(report['videos'][cam]['path'], out/(cam+'.mp4'), lo, hi-lo)) for cam in CAMERAS]
            arrays = {key: z[key][lo:hi+1] if len(z[key]) == len(z['state']) else z[key][lo:hi]
                      for key in ('time', 'state', 'raw_action', 'action', 'submitted_control', 'tray_pose',
                                  'finger_contact_force', 'table_force')}
            arrays['time'] = arrays['time']-arrays['time'][0]
            trace = out/'trajectory.npz';np.savez_compressed(trace, **arrays)
            row = dict(schema='parallel_fixed_pickplace_segment/1', ready=True, prompt=span['prompt'],
                       split=split, parent_scene_id=parent, sampling_seed=settings['seed'], source_room=str(room),
                       source_frame_interval=[lo,hi], frames=hi-lo, fps=20, source_trace_sha256=report['trace_sha256'],
                       source_result_sha256=report['source_result_sha256'], actual_engine_exit_receipt=str(receipt),
                       source_domain='simulation/program_generated', controller='expert', model_executed=False,
                       complete_pick_place_pair=True, full_three_tray_task=False,
                       eligible_for_training_scope='fixed_base_pickplace_only',
                       fixed_base_world=station['requested_world'], maximum_actual_base_xy_drift_m=drift,
                       includes_supported_preadjustment=span.get('includes_supported_preadjustment',False),
                       place_initial_source=initial if stem==STEMS[1] else None,
                       trajectory=str(trace), trajectory_sha256=sha(trace), videos=videos)
            immutable(existing, row);segments.append(row)
    manifest=run/'dataset/batches'/room.name/'manifest.json'
    immutable(manifest, dict(ready=True, scope='fixed_base_pickplace_only', complete_source_pairs=1,
                            action_segments=2, segments=segments))
    return dict(room=room.name, split=split, manifest=str(manifest), segments=segments)


def overview(run, rooms):
    """Verify the producer's shared-world recording, never align room clips."""
    record=json.loads((run/'global_overview.json').read_text())
    if (record.get('returncode')!=0 or record.get('shared_world_render') is not True or
            record.get('global_start_frame')!=0):
        raise ValueError('actual_global_overview_encoder_closure_required')
    path=Path(record['path'])
    probe=video_probe(path)
    if probe['frames']!=record['frames'] or probe['fps']!=20 or record.get('fps')!=20:
        raise ValueError('global_overview_frame_alignment_failed')
    return dict(**record,sha256=sha(path),probe=probe,time_shift_or_speed_change=False)


def room_viewer(room):
    result=json.loads((room/'result.json').read_text())
    text='<!doctype html><meta charset="utf-8"><title>Native room</title><h1>'+html.escape(room.name)+'</h1>'
    text+='<p>Raw expert physical recording; qualification is in parallel_export_audit.json. Failed sources are not training data.</p>'
    for camera,row in result.get('native_encoders',{}).items():
        # Producer media belong to this room; never expose unrelated host paths.
        source=Path(row['path']).resolve()
        if not source.is_relative_to(room.resolve()):continue
        relative=source.relative_to(room.resolve()).as_posix()
        text+='<h2>'+html.escape(camera)+'</h2><video controls preload="metadata" style="width:48%" src="'+html.escape(relative,quote=True)+'"></video>'
    text+='<p><a href="result.json">Raw result</a> · <a href="parallel_export_audit.json">Independent audit</a></p>'
    (room/'viewer.html').write_text(text,encoding='utf-8')


def main():
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True)
    p.add_argument('--receipt',type=Path,required=True);p.add_argument('--parent-splits',type=Path,required=True)
    args=p.parse_args();run=args.run.resolve();receipt=args.receipt.resolve()
    import fcntl
    lock=(run/'parallel_export.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    actual=json.loads(receipt.read_text())
    if actual.get('actual_child_wait') is not True or actual.get('returncode')!=0:
        raise ValueError('shared_engine_actual_wait_zero_required')
    parents=json.loads(args.parent_splits.read_text());rooms=sorted(r for r in (run/'rooms').glob('room_*') if r.is_dir())
    accepted=[];failed={};begin=time.time()
    for room in rooms:
        try:accepted.append(export_room(run,room,receipt,parents))
        except Exception as exc:failed[room.name]=repr(exc)
        try:room_viewer(room)
        except Exception as exc:atomic(room/'viewer_failure.json',dict(error=repr(exc)))
        atomic(run/'export_progress.json',dict(stage='exporting',accepted_pairs=len(accepted),rejected=failed,heartbeat_unix=time.time()))
    media=None;media_error=None
    try:media=overview(run,rooms)
    except Exception as exc:media_error=repr(exc)
    counts={s:sum(r['split']==s for r in accepted) for s in ('train','val','test')}
    summary=dict(schema='parallel_pickplace_export/1',stage='complete' if not failed and not media_error else 'partial_complete',
                 complete_source_pairs=len(accepted),action_segments=len(accepted)*2,source_pairs_by_split=counts,
                 frozen_batches=accepted,rejected=failed,overview=media,overview_error=media_error,
                 export_wall_seconds=time.time()-begin,training_started=False,
                 three_split_ready=all(counts.values()),full_three_tray_task=False,model_executed=False)
    producer_timing=run/'benchmark_summary.json'
    if producer_timing.exists():
        # Retain source timing and clock scope instead of inferring throughput
        # from video duration or conflating load, simulation and export times.
        summary['producer_benchmark']=json.loads(producer_timing.read_text())
        summary['producer_benchmark_sha256']=sha(producer_timing)
    atomic(run/'dataset_catalog.json',summary);atomic(run/'benchmark_export_summary.json',summary)
    text='<!doctype html><meta charset="utf-8"><title>Parallel native Pick/Place</title><h1>Shared-clock parallel Pick/Place</h1>'
    text+=f'<p>Qualified pairs: {len(accepted)}/{len(rooms)}; expert data, not VLA evaluation. Split: {html.escape(str(counts))}</p>'
    if media:text+='<video controls style="width:100%" src="global_overview.mp4"></video>'
    for room in rooms:
        text+=f'<p>{html.escape(room.name)}: {html.escape(failed.get(room.name,"qualified"))} <a href="rooms/{room.name}/viewer.html">four cameras</a> · <a href="rooms/{room.name}/result.json">result</a></p>'
    (run/'dataset_viewer.html').write_text(text,encoding='utf-8')
    paths=[m['path'] for a in accepted for s in a['segments'] for m in s['videos']]
    if media:paths.append(media['path'])
    (run/'VIDEO_PATHS.txt').write_text('\n'.join(paths)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in summary.items() if k not in ('frozen_batches','overview')}))


if __name__=='__main__':main()
