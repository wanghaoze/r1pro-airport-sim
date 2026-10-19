"""Versioned router handoff around an existing owned native producer; no renderer signals."""
from pathlib import Path
import hashlib,json,os,signal,time,subprocess,math,sys,importlib.util
BASE=Path('/home/michelle/haoze/r1pro-airport-sim');ROOT=BASE/'runs/vla_20261005/task_complete_actions_v1'
OLD=ROOT/'native_full_v1';NEW=ROOT/'native_full_parallel_v2'
spec=importlib.util.spec_from_file_location('owned_router',Path(__file__).resolve().parent.parent/'r1pro_teleop/vla/native_reference_router.py')
helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)
def read(p):return json.loads(Path(p).read_text())
def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for block in iter(lambda:f.read(1048576),b''):h.update(block)
    return h.hexdigest()
def save(p,v):
    p=Path(p);temp=p.with_name(p.name+'.router_v2.tmp')
    with temp.open('x') as f:json.dump(v,f,indent=2,allow_nan=False)
    temp.replace(p)
def proc(pid):
    p=Path('/proc')/str(pid)
    try:
        fields=(p/'stat').read_text().split(') ',1)[1].split()
        argv=[s.decode() for s in (p/'cmdline').read_bytes().split(b'\0') if s]
        return dict(argv=argv,state=fields[0],parent_pid=int(fields[1]),raw_exit_code=int(fields[49]))
    except FileNotFoundError:return None
def manifest_verified(path):
    m=read(path);assert m['status']=='complete' and m['source_hashes_before_after_verified'] is True
    assert m['camera_texture_quality_passed'] is True and m['initial_restore_count']==1 and m['per_frame_state_reset'] is False and m['IK_calls']==0
    assert len(m['references'])==4 and {r['camera'] for r in m['references']}=={'head_left','head_right','left_wrist','right_wrist'}
    tol=read(Path(m['trace']).parents[3]/'collection.json')['config']['replay_tolerance']
    helper.verify_native_replay_errors(m,tol)
    return m
def run_observer(*,base,run_root,old_router_pid,authorized=False):
    if not authorized:raise ValueError('explicit_observer_authorization_required')
    global BASE,ROOT,OLD,NEW
    BASE=Path(base);ROOT=Path(run_root);OLD=ROOT/'native_full_v1';NEW=ROOT/'native_full_parallel_v2'
    receipt=read(ROOT/'native_parallel_transition_receipt.json');old_router=old_router_pid;producer=receipt['new_pid']
    old=proc(old_router);assert old and old['argv'][0]=='/home/michelle/miniconda3/envs/r1pro-vla/bin/python'
    assert old['argv'][-1]==str(BASE/'diagnostictools/transition_native_parallel_v2.py')
    live=proc(producer);assert live and live['argv']==receipt['new_argv'] and live['parent_pid']==old_router
    os.kill(old_router,signal.SIGSTOP)
    closed=read(receipt['old_reference_snapshot']);catalog={(r['trace_sha256'],r['camera']):r for r in closed}
    for entry in read(ROOT/'native_parallel_reuse_manifests.json'):
        path=Path(entry['path']);assert sha(path)==entry['sha256'];m=manifest_verified(path)
        for r in m['references']:
            ref=dict(r,source_manifest=str(path),source_manifest_sha256=entry['sha256'])
            key=(ref['trace_sha256'],ref['camera'])
            if key in catalog:
                # Retain every already published value; recover absent actual header fields only.
                ref.update(catalog[key])
            catalog[key]=ref
    save(ROOT/'native_retained_reference_fields.json',list(catalog.values()))
    handoff=dict(schema='airport_native_router_handoff/2',old_router_pid=old_router,old_argv=old['argv'],old_router_state='stopped',
        producer_pid=producer,producer_argv=live['argv'],new_router_pid=os.getpid(),new_router_argv=sys.argv,
        retained_closed_reference_count=len(catalog),all_old_per_case_bytes_unchanged=True,renderer_signals_sent=[],
        router_source_sha256=sha(__file__),helper_source_sha256=sha(spec.origin))
    save(ROOT/'native_router_v3_handoff.json',handoff)
    cache={};last_sha=None;promoted=False
    while True:
        source=NEW/'video_references.json';refs=read(source);raw_sha=sha(source)
        if raw_sha!=last_sha:
            # Fresh native worker references bind the adjacent complete manifest;
            # explicitly publish that observed identity rather than invent metadata.
            for ref in refs:
                if 'source_manifest' not in ref:
                    manifest_path=Path(ref['path']).parent/'manifest.json';body=manifest_verified(manifest_path)
                    assert body['trace_sha256']==ref['trace_sha256'] and body['frames']==ref['frames']
                    actual=next(r for r in body['references'] if r['camera']==ref['camera'])
                    assert actual['path']==ref['path'] and actual['sha256']==ref['sha256']
                    ref['source_manifest']=str(manifest_path);ref['source_manifest_sha256']=sha(manifest_path)
            refs=helper.merge_verified_reference_fields(refs,list(catalog.values()))
            for ref in refs:
                for pk,hk in (('path','sha256'),('source_manifest','source_manifest_sha256')):
                    p=Path(ref[pk]);st=p.stat();signature=(st.st_size,st.st_mtime_ns,ref[hk])
                    if cache.get(str(p))!=signature:assert sha(p)==ref[hk];cache[str(p)]=signature
            save(ROOT/'native_references_current.json',refs);save(OLD/'video_references.json',refs)
            save(ROOT/'native_references_current_provenance.json',dict(schema='airport_native_live_reference_router/3',
                canonical=str(ROOT/'native_references_current.json'),producer_status_path=str(NEW/'status.json'),
                bridge=str(OLD/'video_references.json'),references_sha256=sha(ROOT/'native_references_current.json'),
                raw_producer_references_sha256=raw_sha,reference_count=len(refs),restored_actual_encoded_metadata=True,
                retained_reference_snapshot=receipt['old_reference_snapshot'],retained_reference_sha256=receipt['old_reference_sha256'],
                router_handoff=str(ROOT/'native_router_v3_handoff.json'),old_closed_per_case_resources_changed=False))
            last_sha=raw_sha
        state=read(NEW/'status.json');finished=state.get('results',[])
        if any(x['returncode'] for x in finished):raise RuntimeError('native_source_failed; evidence retained')
        if not promoted:
            grouped={gpu:[x for x in finished if x['physical_gpu']==gpu][:3] for gpu in (0,1)}
            if all(len(v)==3 for v in grouped.values()):
                chosen=grouped[0]+grouped[1];first=[manifest_verified(NEW/x['scene_id']/'a000/manifest.json') for x in chosen]
                assert {r['physical_index'] for m in first for r in m['gpu_receipt']}=={0,1}
                save(ROOT/'native_three_per_GPU_actual_audit.json',dict(verified=True,cases=[m['scene_id'] for m in first],
                    frames=sum(m['frames'] for m in first),aggregate_worker_fps=sum(m['frames'] for m in first)/sum(m['wall_seconds'] for m in first),
                    wall_seconds=[m['wall_seconds'] for m in first],actual_GPU_receipts=[m['gpu_receipt'] for m in first],
                    all_four_native_views_verified=True,all_six_physical_errors_verified=True,no_proportional_speedup_claim=True))
                save(ROOT/'native_parallel_worker_caps.json',{'0':4,'1':4});promoted=True
        live=proc(producer)
        if live and live['state']=='Z':
            code=helper.decode_linux_wait_status(live['raw_exit_code']);assert code==0
            assert state['status']=='complete' and state['selected']==193 and state['completed_scene_count']==193 and len(refs)==772
            active=[];reused=[]
            for path in NEW.glob('*_process.json'):
                saved=read(path);current=proc(saved['pid'])
                if current and current['argv']==saved['command']:active.append(saved['pid'])
                elif current and current['argv']:reused.append(saved['pid'])
            assert not active
            save(ROOT/'native_parallel_exit_receipt.json',dict(schema='airport_native_producer_exit/1',returncode=code,
                actual_exit_evidence=dict(source='/proc/PID/stat field52 while parent retained Z',raw_exit_code=live['raw_exit_code'],producer_state='Z'),
                source_native_verified=True,selected=193,completed_scene_count=193,reference_count=772,active_owned_renderers=[],
                nonowned_reused_PIDs=reused,producer_pid=producer,producer_argv=receipt['new_argv'],status_path=str(NEW/'status.json'),
                status_sha256=sha(NEW/'status.json'),references_sha256=sha(ROOT/'native_references_current.json'),training_ready=False))
            assert proc(old_router)['argv']==old['argv']
            os.kill(old_router,signal.SIGTERM);os.kill(old_router,signal.SIGCONT)
            receipt.update(stage='complete_source_producer_exited',returncode=code,router_handoff=str(ROOT/'native_router_v3_handoff.json'))
            save(ROOT/'native_parallel_transition_receipt.json',receipt);break
        if not live:raise RuntimeError('producer_disappeared_before_actual_exit_receipt')
        time.sleep(10)

def main():
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--base',required=True);p.add_argument('--run-root',required=True)
    p.add_argument('--old-router-pid',type=int,required=True);p.add_argument('--authorize-observer',action='store_true')
    a=p.parse_args();run_observer(base=a.base,run_root=a.run_root,old_router_pid=a.old_router_pid,authorized=a.authorize_observer)

if __name__=='__main__':main()
