"""Reviewed live-publication transition; immutable source/video/per-case evidence retained."""
from pathlib import Path
import json,os,signal,time,subprocess,hashlib,math
BASE=Path('/home/michelle/haoze/r1pro-airport-sim');ROOT=BASE/'runs/vla_20261005/task_complete_actions_v1'
OLD=ROOT/'native_full_v1';NEW=ROOT/'native_full_parallel_v2';TOOL=BASE/'runs/vla_20261005/task_native_tool_v3'
PY='/home/michelle/miniconda3/envs/r1pro-vla/bin/python';CONT=BASE/'releases/robust_v64_20260930'
INVENTORY=BASE/'runs/vla_20261005/task_complete_skill6_v1/source_audit_v1/selected_complete_tasks_terminal_media_v2.jsonl'
def read(p):return json.loads(Path(p).read_text())
def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for block in iter(lambda:f.read(1048576),b''):h.update(block)
    return h.hexdigest()
def save(p,v):
    p=Path(p);temp=p.with_name(p.name+'.transition.tmp')
    with temp.open('x') as f:json.dump(v,f,indent=2,allow_nan=False)
    temp.replace(p)
def argv(pid):
    try:return [s.decode() for s in (Path('/proc')/str(pid)/'cmdline').read_bytes().split(b'\0') if s]
    except FileNotFoundError:return []
def physical_pids():
    import xml.etree.ElementTree as ET
    xml=ET.fromstring(subprocess.check_output(['nvidia-smi','-q','-x'],text=True))
    return {int(p.findtext('pid')) for p in xml.findall('./gpu/processes/process_info')}
def verified_manifest(path,row):
    m=read(path)
    assert m['status']=='complete' and m['trace_sha256']==row['trace_sha256'] and m['scene_xml_sha256']==row['scene_xml_sha256']
    assert m['frames']==row['frames'] and m['fps']==20 and m['source_hashes_before_after_verified'] is True
    assert m['initial_restore_count']==1 and m['per_frame_state_reset'] is False and m['IK_calls']==0
    assert m['camera_texture_quality_passed'] is True and len(m['references'])==4
    assert {x['camera'] for x in m['references']}=={'head_left','head_right','left_wrist','right_wrist'}
    tol=read(Path(m['trace']).parents[3]/'collection.json')['config']['replay_tolerance']
    assert type(tol) in (int,float) and math.isfinite(tol) and tol>0
    limits={'qpos':tol,'qvel':10*tol,'time':1e-8}
    for key in ('prefix_errors','terminal_errors'):
        assert set(m[key])=={'qpos','qvel','time'}
        assert all(type(v) in (int,float) and math.isfinite(v) and 0<=v<=limits[k] for k,v in m[key].items())
    for ref in m['references']:assert sha(ref['path'])==ref['sha256']
    return m

def run_transition(*,base,run_root,inventory,controller,tool,python,authorized=False):
    if not authorized:raise ValueError('explicit_transition_authorization_required')
    global BASE,ROOT,OLD,NEW,CONT,TOOL,INVENTORY,PY
    BASE=Path(base);ROOT=Path(run_root);OLD=ROOT/'native_full_v1';NEW=ROOT/'native_full_parallel_v2'
    CONT=Path(controller);TOOL=Path(tool);INVENTORY=Path(inventory);PY=python
    receipt_path=ROOT/'native_parallel_transition_receipt.json';receipt=read(receipt_path)
    rows=[json.loads(l) for l in INVENTORY.read_text().splitlines()];by_scene={r['scene_id']:r for r in rows}
    children=receipt['children'];deadline=time.time()+3600
    while any(argv(c['pid']) for c in children):
        if time.time()>deadline:raise RuntimeError('natural_renderer_completion_deadline; no child killed')
        time.sleep(10)
    gpu=physical_pids();assert not any(c['pid'] in gpu for c in children)
    for c in children:
        sid=c['command'][c['command'].index('--one')+1]
        verified_manifest(OLD/sid/'a000/manifest.json',by_scene[sid])
    old_pid=receipt['old_pid'];assert argv(old_pid)==receipt['old_argv']
    # SIGTERM is pending before CONT; stopped producer never resumes dispatch work.
    os.kill(old_pid,signal.SIGTERM);os.kill(old_pid,signal.SIGCONT)
    deadline=time.time()+30
    while argv(old_pid) and time.time()<deadline:time.sleep(.1)
    assert not argv(old_pid)
    reuse_paths=[ROOT/'native_benchmark_v1/airport_0011_20270927/a000/manifest.json']
    reuse_paths.extend(sorted(OLD.glob('airport_*/a000/manifest.json')))
    for path in reuse_paths:verified_manifest(path,by_scene[read(path)['scene_id']])
    save(ROOT/'native_parallel_reuse_manifests.json',[dict(path=str(p),sha256=sha(p),scene_id=read(p)['scene_id']) for p in reuse_paths])
    assert not NEW.exists()
    caps=ROOT/'native_parallel_worker_caps.json';save(caps,{'0':3,'1':3})
    allowed_path=ROOT/'native_parallel_coordinated_compute.json'
    if not allowed_path.exists():save(allowed_path,{'pids':[4168289],'source':'runtime agent explicit service PID, GPU0 UUID97ac, .20 allocation'})
    while True:
        current={int(x.strip()) for x in subprocess.check_output(['nvidia-smi','--query-compute-apps=pid','--format=csv,noheader'],text=True).splitlines() if x.strip()}
        allowed=set(read(allowed_path)['pids'])
        if current<=allowed:break
        receipt.update(stage='waiting_coordinated_GPU_compute',uncoordinated_compute_pids=sorted(current-allowed));save(receipt_path,receipt);time.sleep(10)
    cmd=[PY,'-u',str(TOOL/'scripts/render_task_complete_sources.py'),'--inventory',str(INVENTORY),'--controller',str(CONT),
        '--output',str(NEW),'--dispatch','--workers-per-gpu','4','--worker-cap-file',str(caps)]
    for pid in sorted(current):cmd+=['--allowed-compute-pid',str(pid)]
    for path in reuse_paths:cmd+=['--reuse-manifest',str(path)]
    log=(ROOT/'native_full_parallel_v2.log').open('x')
    env=dict(os.environ,OMP_NUM_THREADS='1',MKL_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1')
    producer=subprocess.Popen(cmd,cwd=CONT,env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
    receipt.update(stage='new_producer_starting_three_per_GPU',new_pid=producer.pid,new_argv=cmd,new_cwd=str(CONT),
        natural_children_closed=children,old_producer_exited=True,new_output=str(NEW),canonical_references=str(ROOT/'native_references_current.json'),
        initial_worker_caps={'0':3,'1':3},reused_new_manifests=len(reuse_paths),cli_sha256=sha(TOOL/'scripts/render_task_complete_sources.py'),
        module_sha256=sha(TOOL/'r1pro_teleop/vla/data_task_native.py'))
    save(receipt_path,receipt)
    old_status=read(OLD/'status.json');save(ROOT/'native_v1_status_before_forwarding.json',old_status)
    old_status.update(status='superseded_forwarding',forwarded_to=str(NEW/'status.json'),live_references_forwarded_to=str(ROOT/'native_references_current.json'))
    save(OLD/'status.json',old_status)
    last_sha=None;cache={};promoted=False
    while True:
        refs_path=NEW/'video_references.json';status_path=NEW/'status.json'
        if refs_path.exists():
            refs_bytes=refs_path.read_bytes();actual_sha=hashlib.sha256(refs_bytes).hexdigest()
            if actual_sha!=last_sha:
                refs=json.loads(refs_bytes);keys=set()
                for ref in refs:
                    key=(ref['trace_sha256'],ref['camera']);assert key not in keys;keys.add(key)
                    for path_key,sha_key in (('path','sha256'),('source_manifest','source_manifest_sha256')):
                        path=Path(ref[path_key]);stat=path.stat();signature=(stat.st_size,stat.st_mtime_ns,ref[sha_key])
                        if cache.get(str(path))!=signature:assert sha(path)==ref[sha_key];cache[str(path)]=signature
                save(ROOT/'native_references_current.json',refs);save(OLD/'video_references.json',refs)
                save(ROOT/'native_references_current_provenance.json',dict(schema='airport_native_live_reference_router/1',
                    canonical=str(ROOT/'native_references_current.json'),producer_status_path=str(status_path),
                    bridge=str(OLD/'video_references.json'),references_sha256=actual_sha,reference_count=len(refs),
                    previous_snapshot=receipt['old_reference_snapshot'],previous_sha256=receipt['old_reference_sha256'],
                    old_closed_per_case_resources_changed=False))
                last_sha=actual_sha
        if status_path.exists() and not promoted:
            state=read(status_path);finished=state.get('results',[])
            if any(x['returncode'] for x in finished):raise RuntimeError('new_native_case_failed; evidence retained')
            grouped={gpu:[x for x in finished if x['physical_gpu']==gpu][:3] for gpu in (0,1)}
            chosen=grouped[0]+grouped[1] if all(len(v)==3 for v in grouped.values()) else []
            first=[verified_manifest(NEW/x['scene_id']/'a000/manifest.json',by_scene[x['scene_id']]) for x in chosen]
            if len(first)==6 and {m['gpu_receipt'][0]['physical_index'] for m in first}=={0,1}:
                total_frames=sum(m['frames'] for m in first);wall=sum(m['wall_seconds'] for m in first)
                save(ROOT/'native_three_per_GPU_actual_audit.json',dict(verified=True,cases=[m['scene_id'] for m in first],frames=total_frames,
                    aggregate_worker_fps=total_frames/wall,all_four_native_views_verified=True,all_six_physical_errors_verified=True,
                    actual_GPU_UUIDs=sorted({r['uuid'] for m in first for r in m['gpu_receipt']}),no_proportional_speedup_claim=True))
                save(caps,{'0':4,'1':4});promoted=True
                receipt.update(stage='four_per_GPU_after_actual_three_per_GPU_audit',promoted_unix_time=time.time());save(receipt_path,receipt)
        code=producer.poll()
        if code is not None:
            assert code==0
            final=read(status_path);refs=read(refs_path)
            assert final['status']=='complete' and final['selected']==193 and final['completed_scene_count']==193 and len(refs)==772
            assert all(x['returncode']==0 for x in final['results'])
            active=[]
            for path in NEW.glob('*_process.json'):
                r=read(path)
                if argv(r['pid']):active.append(r['pid'])
            assert not active
            save(ROOT/'native_parallel_exit_receipt.json',dict(schema='airport_native_producer_exit/1',returncode=code,
                source_native_verified=True,selected=193,completed_scene_count=193,reference_count=772,active_owned_renderers=[],
                producer_pid=producer.pid,producer_argv=cmd,status_path=str(status_path),status_sha256=sha(status_path),
                references_sha256=sha(ROOT/'native_references_current.json'),training_ready=False))
            receipt.update(stage='complete_source_producer_exited',returncode=code);save(receipt_path,receipt);break
        time.sleep(10)
    log.close()
    

def main():
    import argparse
    p=argparse.ArgumentParser()
    for name in ('base','run-root','inventory','controller','tool','python'):p.add_argument('--'+name,required=True)
    p.add_argument('--authorize-transition',action='store_true')
    a=p.parse_args();run_transition(base=a.base,run_root=a.run_root,inventory=a.inventory,controller=a.controller,tool=a.tool,python=a.python,authorized=a.authorize_transition)

if __name__=='__main__':main()
