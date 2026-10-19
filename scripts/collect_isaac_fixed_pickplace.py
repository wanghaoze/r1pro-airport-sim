"""Separate fixed-base Pick/Place data from physically continuous native pairs.

This is a new two-action scope; it never changes a frozen BC manifest or claims
full three-tray success. Actual VLA origins must be added by a real policy run.
"""
import argparse
import fcntl
import json
from pathlib import Path
import subprocess
import sys
import time
import traceback
import numpy as np
from isaacsim_stage_runner import atomic, checked, identity
from audit_isaacsim_fast_pickplace import audit


def verify_base_trace(raw_action,state,start,end,initial_station=None):
    if initial_station is not None:start,end=0,len(raw_action)
    targets=raw_action[start:end,16:19]
    if initial_station is not None and not np.array_equal(targets[0],initial_station['fixed_command']):
        raise ValueError('initial_station_command_identity_mismatch')
    if not np.allclose(targets,targets[0],atol=1e-12,rtol=0.):raise ValueError('base_command_moved_during_actions')
    drift=np.linalg.norm(state[start:end+1,16:18]-targets[0,:2],axis=1)
    if float(drift.max())>.05:raise ValueError('actual_base_exceeded_existing_5cm_allowance')
    return drift


def partial_terminal_summary(accepted_count,candidate_count,returncode):
    complete=returncode==0 and accepted_count==candidate_count
    return dict(stage='complete' if complete else 'partial_complete',
                complete_source_pairs=accepted_count,action_segments=2*accepted_count,
                actual_producer_returncode=returncode,
                failed_or_unaccepted_candidates=candidate_count-accepted_count,
                all_candidates_passed=complete)


def export_pair(run,case,cfg):
    sys.path.insert(0,cfg['code'])
    from r1pro_teleop.vla.isaac_dataset import sha,video_probe
    report=audit(case)
    if not report['passed']:raise ValueError('native_pair_audit_failed:'+str(report['errors']))
    result=json.loads((case/'result.json').read_text());settings=result['case']
    diverse=cfg.get('allow_supported_preadjustment',False)
    expected_scope='diverse_fixed_pickplace_physical_candidate' if diverse else 'fixed_base_pickplace'
    if settings.get('collection_scope')!=expected_scope or settings.get('fixed_base_world')!=cfg['fixed_base_world']:
        raise ValueError('fixed_base_collection_identity_mismatch')
    station=cfg['fixed_base_world']
    if cfg.get('allow_episode_front_station_search',False):
        if not diverse or station is not None or settings.get('search_front_stations') is not True:
            raise ValueError('episode_front_station_search_identity_mismatch')
        selected=json.loads((case/'episode_station.json').read_text())
        if selected.get('target_fixed_during_actions') is not True or selected.get('selection_before_action') is not True:
            raise ValueError('episode_station_not_frozen_before_actions')
        station=selected['base_world']
        if np.asarray(station).shape!=(3,) or not np.isfinite(station).all():raise ValueError('invalid_episode_station')
    if set(report['videos'])!={'head_left','head_right','left_wrist','right_wrist','presentation'}:raise ValueError('five_native_cameras_required')
    initial=json.loads((case/'place_initial_state.json').read_text());split=cfg['parent_split'];parent=cfg['parent_scene_id'];segments=[]
    clip_manifests=[json.loads(p.read_text()) for p in sorted(case.glob('clips*/manifest.json'))]
    closed_clips=next((m for m in clip_manifests if m.get('ready') and m.get('source_trace_sha256')==report['trace_sha256']),None)
    if closed_clips is None:raise ValueError('closed_native_action_clips_missing')
    with np.load(case/'native_trace.npz') as z:
        spans=result['actions'];start=spans[0]['start'];end=spans[-1]['end']
        initial_station=None
        if cfg.get('fixed_base_from_initialization',False):
            if settings.get('initial_base_world')!=station:raise ValueError('initial_station_not_identical_to_fixed_station')
            station_record=case/'initial_base_station.json'
            if not station_record.exists():raise ValueError('initial_station_receipt_missing')
            initial_station=json.loads(station_record.read_text())
            if (initial_station.get('requested_world')!=station or
                    initial_station.get('initialization_only_before_first_step') is not True):
                raise ValueError('initial_station_receipt_identity_mismatch')
        actual_drift=verify_base_trace(z['raw_action'],z['state'],start,end,initial_station)
        at=spans[1]['start']
        if spans[0]['end']!=at or initial['frame']!=at or initial['reset_between_pick_and_place'] is not False:raise ValueError('place_not_physical_pick_continuation')
        if not np.array_equal(np.asarray(initial['state']),z['state'][at]):raise ValueError('place_initial_feedback_not_aligned')
        for span,stem in zip(spans,('pick_up_the_tray','place_the_tray')):
            target=run/'dataset'/stem/split/case.name;target.mkdir(parents=True,exist_ok=True)
            manifest=target/'segment.json'
            if manifest.exists():
                row=json.loads(manifest.read_text())
                if row['source_trace_sha256']!=report['trace_sha256']:raise ValueError('immutable_segment_source_changed')
                segments.append(row);continue
            lo,hi=span['start'],span['end'];videos=[]
            for cam in report['videos']:
                source=Path(next(c['path'] for c in closed_clips['clips'] if c['prompt']==span['prompt'] and c['camera']==cam));out=target/(cam+'.mp4')
                if not source.exists():raise ValueError('native_action_clip_missing:'+str(source))
                # Immutable source action clips are linked, never copied locally.
                if not out.exists():out.symlink_to(source)
                probe=video_probe(out)
                if probe['frames']!=hi-lo or probe['fps']!=20:raise ValueError('action_video_alignment_failed')
                videos.append(dict(camera=cam,path=str(out),sha256=sha(out),training_camera=cam!='presentation',**probe))
            arrays={}
            for key in ('time','state','raw_action','action','submitted_control','tray_pose','finger_contact_force','table_force','rigid_pose'):
                arrays[key]=z[key][lo:hi+1] if len(z[key])==len(z['state']) else z[key][lo:hi]
            arrays['time']=arrays['time']-arrays['time'][0]
            trace=target/'trajectory.npz';np.savez_compressed(trace,**arrays)
            row=dict(schema='fixed_base_pickplace_segment/1',ready=True,prompt=span['prompt'],split=split,parent_scene_id=parent,
                source_case=str(case),source_trace_sha256=report['trace_sha256'],source_frame_interval=[lo,hi],frames=hi-lo,fps=20,
                sampling_seed=settings['seed'],includes_supported_preadjustment=span.get('includes_supported_preadjustment',False),
                core_motion_frames=span.get('core_motion_frames',hi-lo),
                source_domain='simulation/program_generated',controller='expert',model_executed=False,
                complete_pick_place_pair=True,full_three_tray_task=False,eligible_for_training_scope='fixed_base_pickplace_only',
                fixed_base_world=station,episode_front_station_search=cfg.get('allow_episode_front_station_search',False),maximum_actual_base_xy_drift_m=float(actual_drift.max()),
                base_audit_includes_all_preparation=cfg.get('fixed_base_from_initialization',False),
                actual_initial_state=z['state'][lo].tolist(),actual_initial_tray_pose=z['tray_pose'][lo,0].tolist(),
                place_initial_source=initial if stem=='place_the_tray' else None,trajectory=str(trace),trajectory_sha256=sha(trace),videos=videos)
            atomic(manifest,row);segments.append(row)
    frozen=run/'dataset/batches'/case.name/'manifest.json';frozen.parent.mkdir(parents=True,exist_ok=True)
    batch=dict(ready=True,scope='fixed_base_pickplace_only',source_pairs=1,action_segments=2,counts={split:2},segments=segments)
    if frozen.exists() and json.loads(frozen.read_text())!=batch:raise ValueError('frozen_pair_manifest_changed')
    if not frozen.exists():atomic(frozen,batch)
    return dict(case=case.name,manifest=str(frozen),segments=segments)


def main():
    p=argparse.ArgumentParser();p.add_argument('--config',type=Path,required=True);a=p.parse_args();cfg=json.loads(a.config.read_text());run=Path(cfg['run'])
    lock=(run/'fixed_collection.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    state=dict(stage='native_pick_then_place',training_started=False,scope='fixed_base_pickplace_only',model_executed=False)
    def status(**kw):state.update(kw,heartbeat_unix=time.time());atomic(run/'collection_status.json',state)
    try:
        scene_root=Path(cfg['scene_root']);meta=scene_root/'source_scene.json'
        if not meta.exists():meta=next((scene_root/'preparation/scenes/train').glob('*/scene.json'))
        source=json.loads(meta.read_text())
        if source['parent_scene_id']!=cfg['parent_scene_id'] or source.get('split','train')!=cfg['parent_split']:raise ValueError('parent_split_identity_mismatch')
        job=run/'native_producer.job.json';receipt=run/'native_producer.exit.json';launch=run/'native_producer.launch.json'
        if not job.exists():
            atomic(job,dict(argv=[sys.executable,str(Path(cfg['code'])/'scripts/supervise_isaacsim_fast_pickplace.py'),'--config',str(a.config)],cwd=cfg['project'],log=str(run/'native_producer.log'),launch=str(launch),receipt=str(receipt)))
            subprocess.Popen([sys.executable,str(Path(cfg['code'])/'scripts/isaacsim_stage_runner.py'),'--job',str(job)],cwd=cfg['project'],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
        accepted={};previous=run/'dataset_catalog.json';failed=json.loads(previous.read_text()).get('export_errors',{}) if previous.exists() else {}
        while True:
            if launch.exists():
                child=json.loads(launch.read_text());runner=run/'native_producer.job.runner.json'
                if not checked(child) and not receipt.exists() and not (runner.exists() and checked(json.loads(runner.read_text()))):raise RuntimeError('producer_disappeared_without_actual_wait')
            rows=json.loads((run/'results.json').read_text()) if (run/'results.json').exists() else []
            for row in rows:
                name=row['directory']
                if not row['passed'] or name in accepted or failed.get(name,0)>=3:continue
                try:accepted[name]=export_pair(run,run/name,cfg)
                except Exception as exc:
                    failed[name]=failed.get(name,0)+1;atomic(run/f'export_{name}_attempt_{failed[name]}.json',dict(error=repr(exc),unix=time.time()))
            catalog=dict(scope='fixed_base_pickplace_only',training_started=False,complete_source_pairs=len(accepted),
                action_segments=2*len(accepted),pick_segments=len(accepted),place_segments=len(accepted),
                counts={cfg['parent_split']:2*len(accepted)},frozen_batches=list(accepted.values()),export_errors=failed,
                provenance_note='Expert Pick endpoints physically continue into Place; no live VLA pickups claimed.')
            atomic(run/'dataset_catalog.json',catalog);status(complete_source_pairs=len(accepted),action_segments=2*len(accepted),export_errors=failed)
            if receipt.exists():
                native_exit=json.loads(receipt.read_text())
                if cfg.get('allow_partial_native_batch',False):
                    status(**partial_terminal_summary(len(accepted),len(cfg['cases']),native_exit['returncode']))
                    return
                if native_exit['returncode']!=0:raise RuntimeError('native_producer_failed_preserved')
                if len(accepted)!=len(cfg['cases']):raise RuntimeError('native_or_export_failures_not_a_complete_dataset')
                status(stage='complete',complete_source_pairs=len(accepted),action_segments=2*len(accepted));return
            time.sleep(10)
    except BaseException as exc:
        status(stage='failed',last_error=repr(exc));atomic(run/'collection_failure.json',dict(error=repr(exc),traceback=traceback.format_exc()));raise


if __name__=='__main__':main()
