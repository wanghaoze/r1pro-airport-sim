"""Read actual probe/demo receipts and emit metadata only; never launch jobs."""
import argparse
import datetime
import json
from pathlib import Path
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from r1pro_teleop.real2sim.isaac_parallel_collection import write_json


def snapshot(project):
    project=Path(project);original=project/'runs/isaacsim_parallel_collection_20261016_v1'
    pointer=project/'runs/ISAAC_PARALLEL_CURRENT.json'
    run=Path(json.loads(pointer.read_text())['run']) if pointer.exists() else original
    def read(p):return json.loads(p.read_text()) if p.exists() else None
    diverse_pointer=read(project/'runs/ISAAC_DIVERSE_CURRENT.json')
    diverse=Path(diverse_pointer['run']) if diverse_pointer else project/'runs/isaacsim_diverse_pickplace_20261016_v1'
    def live(j):
        if not j:return False
        p=Path('/proc')/str(j['pid'])
        try:
            s=(p/'stat').read_text().rsplit(')',1)[1].split()
            return (s[0]!='Z' and s[19]==str(j['start_ticks']) and
                    (p/'cmdline').read_text().split('\0')[:-1]==j['argv'] and
                    str((p/'cwd').resolve())==j['cwd'])
        except OSError:return False
    state=read(run/'pipeline_status.json') or {};g=read(run/'guardian_status.json') or {}
    bc_pointer=read(project/'runs/ISAAC_BC_RESUME_CURRENT.json')
    bc_run=Path(bc_pointer['run']) if bc_pointer else project/'runs/isaacsim_three_tray_workflow_20261015_v1/bc_resume_after_stable_20261016_v1'
    active=state.get('active_output');native=read(Path(active)/'status.json') if active else None
    probes=[];paths=[]
    for p in sorted(run.glob('*/media_exit.json')):
        exit_receipt=read(run/(p.parent.name+'.exit.json'))
        closed=bool(exit_receipt and exit_receipt.get('actual_child_wait') and exit_receipt.get('returncode')==0)
        rows=read(p) or {}
        videos=[r['path'] for r in rows.values() if r.get('returncode')==0 and Path(r.get('path','')).is_file()]
        if closed:paths.extend(videos)
        probes.append(dict(output=str(p.parent),actual_exit=exit_receipt,closed=closed,
                           video_files=len(videos),training_eligible=False))
    demos=[]
    for p in sorted((project/'runs').glob('isaacsim_diverse_pickplace_20261016_v*/case_*/result.json')):
        value=read(p);receipt=read(p.parent.parent/(p.parent.name+'.exit.json'))
        demos.append(dict(output=str(p.parent),result=value,actual_exit=receipt))
        if receipt and receipt.get('actual_child_wait'):
            paths.extend(v['path'] for v in value.get('native_encoders',{}).values()
                         if v.get('returncode')==0 and Path(v['path']).is_file())
    checkpoints=[]
    for p in sorted((bc_run/'training').glob('checkpoint_*.json')):
        value=read(p) or {};target=Path(value.get('checkpoint','/__missing_checkpoint__'))
        if value.get('checkpoint_saved') and all((target/name).exists() for name in ('params','train_state','assets')):
            checkpoints.append(dict(receipt=str(p),checkpoint=str(target),updates=value['actual_completed_updates']))
    durable_updates=max((v['updates'] for v in checkpoints),default=0)
    data=dict(snapshot_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),run=str(run),
        state=state,guardian=g,supervisor_alive=live(g.get('producer')),native=native,
        native_alive=live(read(run/(Path(active).name+'.launch.json'))) if active else False,
        integration_probes=probes,diverse_demos=demos,actual_qualified_new_sources=0,
        model_test_passed=False,new_dataset_training_started=False,
        original_BC_restore=read(original/'bc_restore_v3/pipeline_status.json') or read(original/'bc_restore_v2/pipeline_status.json') or read(original/'bc_restore/pipeline_status.json'),
        original_BC_pipeline=read(bc_run/'pipeline_status.json'),original_BC_run=str(bc_run),
        original_BC_durable_updates=durable_updates,original_BC_checkpoints=checkpoints,
        gpu_participation=read(run/'gpu_participation.json'))
    write_json(run/'monitor_latest.json',data)
    lines=[f"Snapshot: {data['snapshot_utc']}",f"Stage: {state.get('stage')}",
           f"Active rooms: {state.get('active_rooms')}; native alive: {data['native_alive']}",
           f"Actual frame: {(native or {}).get('frames')}; phase: {(native or {}).get('stage')}",
           'Scope: engine integration and diverse preparation candidates; NOT qualified training data.',
           'Qualified new sources: 0; new dataset training: not started.',
           f"Server run: {run}",f"Diverse candidates: {diverse}",
           f"Original BC restore: {(data['original_BC_restore'] or {}).get('stage','deferred; see BC_resource_deferral.json')}",
           f"Original BC current: {(data['original_BC_pipeline'] or {}).get('stage')}; updates: {(data['original_BC_pipeline'] or {}).get('actual_completed_updates')}; run: {bc_run}",
           f"Original BC verified saved updates: {durable_updates} (preserved during next milestone initialization)",
           f"GPU participation evidence: {data['gpu_participation']}",
           'Known pending: adaptive batch controller, full contact audit, camera isolation/image audit, supported preadjustment physical success.']
    (project/'ISAAC_PARALLEL_COLLECTION_STATUS.txt').write_text('\n'.join(lines)+'\n',encoding='utf8')
    (project/'ISAAC_PARALLEL_VIDEO_PATHS.txt').write_text('\n'.join(paths)+'\n',encoding='utf8')
    return lines


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--project',type=Path,default=Path(__file__).resolve().parents[1])
    p.add_argument('--watch',action='store_true');p.add_argument('--interval',type=float,default=10.)
    a=p.parse_args()
    if not 1<=a.interval<=60:raise ValueError('monitor_interval_outside_1_60_seconds')
    while True:
        print('\n'.join(snapshot(a.project)),flush=True)
        if not a.watch:break
        time.sleep(a.interval)
