"""Render immutable complete source tasks; benchmark first, explicit batch dispatch later."""
from pathlib import Path
import argparse,importlib.util,json,os,subprocess,sys,time,threading
from concurrent.futures import ThreadPoolExecutor

module_path=Path(__file__).resolve().parents[1]/'r1pro_teleop/vla/data_task_native.py'
spec=importlib.util.spec_from_file_location('owned_task_native',module_path)
native=importlib.util.module_from_spec(spec);spec.loader.exec_module(native)

def worker_enabled(gpu, lane_index, slots, cap_file):
    if cap_file is None:return True
    caps=native.read(cap_file)
    cap=caps.get(str(gpu))
    if type(cap) is not int or not 1<=cap<=4:raise ValueError('invalid_bounded_native_worker_cap')
    local_index=sum(item==gpu for item in slots[:lane_index])
    return local_index<cap

def main():
    p=argparse.ArgumentParser();p.add_argument('--inventory',required=True);p.add_argument('--controller',required=True)
    p.add_argument('--output',required=True);p.add_argument('--one');p.add_argument('--physical-gpu',type=int,choices=(0,1),default=0)
    p.add_argument('--dispatch',action='store_true');p.add_argument('--workers-per-gpu',type=int,choices=(1,2,3,4),default=1)
    p.add_argument('--worker-cap-file',help='Explicit 1..4 per-GPU concurrency cap; only affects new case scheduling')
    p.add_argument('--allowed-compute-pid',type=int,action='append',default=[],help='Explicitly coordinated existing model process, never terminated by this tool')
    p.add_argument('--allow-low-texture',action='store_true');p.add_argument('--reuse-manifest',action='append',default=[])
    args=p.parse_args()
    inventory=Path(args.inventory).resolve();controller=Path(args.controller).resolve();output=Path(args.output).resolve()
    rows=[json.loads(line) for line in inventory.read_text().splitlines()]
    if len({r['scene_id'] for r in rows})!=len(rows):raise ValueError('duplicate_scene_selection')
    for path in args.reuse_manifest:
        manifest=native.read(path);row=next(r for r in rows if r['scene_id']==manifest['scene_id'])
        if (manifest.get('schema')!='airport_complete_task_native_replay/1' or manifest.get('status')!='complete'
            or manifest.get('trace_sha256')!=row['trace_sha256'] or manifest.get('scene_xml_sha256')!=row['scene_xml_sha256']
            or manifest.get('source_hashes_before_after_verified') is not True or manifest.get('frames')!=row['frames']
            or manifest.get('fps')!=20 or {v['camera'] for v in manifest['references']}!=set(native.CAMERAS)):
            raise ValueError('benchmark_reuse_not_verified_complete_source')
        row['native4_available']=True
        row['native_videos']=[dict(v,manifest=str(Path(path).resolve()),manifest_sha256=native.digest(path)) for v in manifest['references']]
    if args.one:
        if args.dispatch:p.error('one and dispatch are mutually exclusive')
        row=next(r for r in rows if r['scene_id']==args.one)
        if row.get('native4_available'):raise ValueError('already_verified_native4_must_be_reused')
        if (os.environ.get('CUDA_VISIBLE_DEVICES')!=native.GPU_UUIDS[args.physical_gpu]
                or os.environ.get('MUJOCO_EGL_DEVICE_ID')!=str(native.EGL_ENUM[args.physical_gpu])):
            raise ValueError('explicit_single_GPU_UUID_and_verified_EGL_mapping_required')
        print(json.dumps(native.render_source(row,output,controller,physical_gpu=args.physical_gpu,
            allow_low_texture=args.allow_low_texture)),flush=True);return
    if not args.dispatch:p.error('no implicit batch GPU execution; choose --one or --dispatch')
    compute=subprocess.check_output(['nvidia-smi','--query-compute-apps=pid','--format=csv,noheader'],text=True).strip()
    compute_pids={int(value.strip()) for value in compute.splitlines() if value.strip()}
    if not compute_pids.issubset(set(args.allowed_compute_pid)):
        raise ValueError('other_GPU_compute_process_present; review_before_native_batch')
    output.mkdir(parents=True,exist_ok=False)
    plan=dict(schema='airport_complete_task_native_plan/1',inventory=str(inventory),inventory_sha256=native.digest(inventory),
        controller=str(controller),selected=len(rows),reuse_scenes=sum(bool(r.get('native4_available')) for r in rows),
        new_scenes=sum(not r.get('native4_available') for r in rows),workers_per_gpu=args.workers_per_gpu,
        coordinated_compute_pids=sorted(compute_pids),worker_cap_file=args.worker_cap_file)
    native.atomic_json(output/'plan.json',plan)
    reuse=[]
    for row in rows:
        native.verify_source(row)
        if row.get('native4_available'):
            if {v['camera'] for v in row['native_videos']}!=set(native.CAMERAS):raise ValueError('reuse_missing_camera')
            for ref in row['native_videos']:
                if native.digest(ref['path'])!=ref['sha256']:raise ValueError('reuse_video_SHA_changed')
                reuse.append(dict(trace=row['trace'],trace_sha256=row['trace_sha256'],camera=ref['camera'],path=ref['path'],
                    sha256=ref['sha256'],native=True,frames=row['frames'],source_start_frame=0,video_start_frame=0,
                    source_manifest=ref['manifest'],source_manifest_sha256=ref['manifest_sha256']))
    native.atomic_json(output/'reused_references.json',reuse)
    pending=[row for row in rows if not row.get('native4_available')]
    slots=[gpu for gpu in (0,1) for _ in range(args.workers_per_gpu)]
    lock=threading.Lock();finished=[];started=time.time();references=list(reuse)
    native.atomic_json(output/'video_references.json',references)
    native.atomic_json(output/'status.json',dict(status='rendering',selected=len(rows),new_cases=0,
        expected_new_cases=len(pending),reused_scenes=plan['reuse_scenes'],results=[],reference_count=len(references),
        expected_reference_count=len(rows)*4,completed_scene_count=len(references)//4,training_ready=False))
    def lane(gpu,lane_index):
        values=[]
        for row in pending[lane_index::len(slots)]:
            while not worker_enabled(gpu,lane_index,slots,args.worker_cap_file):time.sleep(10)
            free=subprocess.check_output(['nvidia-smi',f'--id={native.GPU_UUIDS[gpu]}',
                '--query-gpu=memory.free','--format=csv,noheader,nounits'],text=True)
            while int(free.strip())<6144:
                time.sleep(10)
                free=subprocess.check_output(['nvidia-smi',f'--id={native.GPU_UUIDS[gpu]}','--query-gpu=memory.free',
                                              '--format=csv,noheader,nounits'],text=True)
            env=dict(os.environ,CUDA_VISIBLE_DEVICES=native.GPU_UUIDS[gpu],MUJOCO_GL='egl',
                MUJOCO_EGL_DEVICE_ID=str(native.EGL_ENUM[gpu]),OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1')
            command=[sys.executable,str(Path(__file__).resolve()),'--inventory',str(inventory),'--controller',str(controller),
                '--output',str(output),'--one',row['scene_id'],'--physical-gpu',str(gpu)]
            if args.allow_low_texture:command.append('--allow-low-texture')
            with (output/(row['scene_id']+'.log')).open('x') as log:
                process=subprocess.Popen(command,env=env,cwd=controller,stdout=log,stderr=subprocess.STDOUT)
                native.atomic_json(output/(row['scene_id']+'_process.json'),dict(pid=process.pid,command=command,
                    cwd=str(controller),physical_gpu=gpu,environment={k:env[k] for k in ('CUDA_VISIBLE_DEVICES','MUJOCO_EGL_DEVICE_ID')}))
                code=process.wait()
            values.append(dict(scene_id=row['scene_id'],returncode=code,physical_gpu=gpu))
            with lock:
                finished.append(values[-1])
                manifest_path=output/row['scene_id']/Path(row['attempt']).name/'manifest.json'
                if code==0:
                    m=native.read(manifest_path)
                    if (m['status']!='complete' or m['trace_sha256']!=row['trace_sha256']
                            or len(m['references'])!=4 or m['source_hashes_before_after_verified'] is not True):
                        raise ValueError('successful_worker_manifest_not_complete')
                    references.extend(m['references'])
                native.atomic_json(output/'video_references.json',references)
                native.atomic_json(output/'status.json',dict(status='rendering',selected=len(rows),new_cases=len(finished),
                    expected_new_cases=len(pending),reused_scenes=plan['reuse_scenes'],results=list(finished),
                    reference_count=len(references),expected_reference_count=len(rows)*4,
                    completed_scene_count=len(references)//4,training_ready=False))
                native.atomic_json(output/'progress.json',dict(stage='rendering',
                    finished_cases=len(finished),expected_new_cases=len(pending),results=list(finished),
                    elapsed_seconds=time.time()-started,training_started=False))
        return values
    with ThreadPoolExecutor(max_workers=len(slots)) as pool:
        lane_results=list(pool.map(lambda pair:lane(pair[1],pair[0]),enumerate(slots)))
    results=[r for lane_rows in lane_results for r in lane_rows]
    native.atomic_json(output/'video_references.json',references)
    native.atomic_json(output/'status.json',dict(status='complete' if all(r['returncode']==0 for r in results) else 'partial',
        selected=len(rows),new_cases=len(results),reused_scenes=plan['reuse_scenes'],results=results,
        reference_count=len(references),expected_reference_count=len(rows)*4,
        completed_scene_count=len(references)//4,expected_new_cases=len(pending),training_ready=False))

if __name__=='__main__':main()
