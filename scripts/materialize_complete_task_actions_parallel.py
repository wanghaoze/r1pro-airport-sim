"""Bounded isolated CPU case exporters; reuse only independently verified cases."""
from pathlib import Path
import argparse,hashlib,json,os,subprocess,sys,time
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from r1pro_teleop.vla.data_task_lerobot import materialize_complete_task_split,available_native_overrides,assemble_complete_task_split,action_vocabulary,audit_task_parquet
from r1pro_teleop.vla.data import digest

def read(path):return json.loads(Path(path).read_text())
def save(path,value):
    path=Path(path);temp=path.with_name(path.name+'.tmp');temp.write_text(json.dumps(value,indent=2,allow_nan=False));temp.replace(path)

def verified_reuse(case_root,case,label_spec):
    root=Path(case_root);manifest=root/'airport_training_manifest.json';m=read(manifest);task=case['original_inventory']
    if (m.get('split')!=task['split'] or m.get('label_spec_sha256')!=digest(label_spec)
        or m.get('all_parquet_values_verified',{}).get('verified') is not True
        or m.get('actual_training_rgb_derivation',{}).get('verified') is not True
        or m.get('training_video_encoding_verification',{}).get('verified') is not True
        or {e['scene_id'] for e in m['episodes']}!={task['scene_id']}
        or any(e['source_trace_sha256']!=task['trace_sha256'] or e['original_task_result_sha256']!=task['result_sha256'] for e in m['episodes'])):
        raise ValueError('old_case_not_verified_same_source_labels_split')
    plan_path=root.parents[1]/'plans'/f"{task['scene_id']}.jsonl"
    if digest(plan_path)!=m['input_plan_sha256'] or json.loads(plan_path.read_text())!=case:
        raise ValueError('old_case_plan_identity_changed')
    audit=audit_task_parquet(root,m['episodes'],action_vocabulary(m['action_vocabulary']),repo_id=m['repo_id'])
    if audit.get('verified') is not True:raise ValueError('old_case_current_source_numeric_loader_audit_failed')
    # Bind all current derived bytes, including native FFV1 clips, before reuse.
    inventory=[]
    for folder in ('data','meta','videos','native_action_clips'):
        for path in sorted((root/folder).rglob('*')):
            if path.is_file():inventory.append(dict(path=str(path),sha256=digest(path),bytes=path.stat().st_size))
    for episode in m['episodes']:
        for ref in episode['native_action_clips'].values():
            if digest(ref['path'])!=ref['sha256']:raise ValueError('old_case_native_clip_changed')
    return dict(path=str(root),scene_id=task['scene_id'],repo_id=m['repo_id'],counts=m['counts'],episodes=len(m['episodes']),
        training_manifest_sha256=digest(manifest),reuse_verified=True,current_resource_inventory=inventory,
        reused_from_older_complete_case=True,training_started=False)

def main():
    p=argparse.ArgumentParser();p.add_argument('--plans',required=True);p.add_argument('--label-spec',required=True)
    p.add_argument('--destination',required=True);p.add_argument('--repo-id',required=True);p.add_argument('--split',choices=('train','val','test'),required=True)
    p.add_argument('--native-references',required=True);p.add_argument('--reuse-export');p.add_argument('--workers',type=int,default=1)
    p.add_argument('--camera-workers',type=int,choices=(1,2,4),default=2);p.add_argument('--one-scene');p.add_argument('--override-file')
    args=p.parse_args();destination=Path(args.destination)
    cases=[json.loads(line) for line in Path(args.plans).read_text().splitlines() if line.strip()]
    cases=[c for c in cases if c['original_inventory']['split']==args.split]
    if args.one_scene:
        case=next(c for c in cases if c['original_inventory']['scene_id']==args.one_scene)
        subset=destination.parents[1]/'plans'/f'{args.one_scene}.jsonl';subset.parent.mkdir(parents=True,exist_ok=True)
        subset.write_text(json.dumps(case)+'\n')
        result=materialize_complete_task_split(subset,args.label_spec,destination,args.repo_id,split=args.split,
            native_overrides=read(args.override_file),native_camera_workers=args.camera_workers)
        save(destination/'worker_result.json',dict(result,scene_id=args.one_scene));return
    if not 1<=args.workers<=8:raise ValueError('bounded_CPU_case_workers_required')
    destination.mkdir(parents=True,exist_ok=False);completed={};jobs={};started=time.time();cache={}
    if args.reuse_export:
        old=read(Path(args.reuse_export)/'status.json')
        for item in old.get('cases',[]):
            case=next(c for c in cases if c['original_inventory']['scene_id']==item['scene_id'])
            completed[item['scene_id']]=verified_reuse(item['path'],case,args.label_spec)
    def status(stage,**extra):
        save(destination/'status.json',dict(stage=stage,split=args.split,expected_scenes=len(cases),completed_scenes=len(completed),
            cases=list(completed.values()),active_scenes=list(jobs),elapsed_seconds=time.time()-started,
            dataset_ready=stage=='complete',training_started=False,case_workers=args.workers,camera_workers=args.camera_workers,**extra))
    status('waiting_native_cases')
    while len(completed)<len(cases):
        for sid,job in list(jobs.items()):
            code=job['process'].poll()
            if code is None:continue
            job['log'].close();del jobs[sid]
            if code:
                status('failed',failed_scene=sid,returncode=code);raise RuntimeError('CPU_case_export_failed:'+sid)
            case=next(c for c in cases if c['original_inventory']['scene_id']==sid)
            item=verified_reuse(job['output'],case,args.label_spec);item['reused_from_older_complete_case']=False
            completed[sid]=item
            lines=[]
            for record in completed.values():lines.extend((Path(record['path'])/'COMPLETE_ACTION_VIDEO_INDEX.txt').read_text().splitlines())
            tmp=destination/'COMPLETE_ACTION_VIDEO_INDEX.txt.tmp';tmp.write_text('\n'.join(lines)+'\n');tmp.replace(destination/'COMPLETE_ACTION_VIDEO_INDEX.txt')
            status('case_completed')
        pending=[c for c in cases if c['original_inventory']['scene_id'] not in completed and c['original_inventory']['scene_id'] not in jobs]
        if pending and len(jobs)<args.workers:
            overrides=available_native_overrides(pending,read(args.native_references),verification_cache=cache)
            for case in pending:
                sid=case['original_inventory']['scene_id']
                if sid not in overrides:continue
                override_file=destination/'overrides'/f'{sid}.json';override_file.parent.mkdir(exist_ok=True)
                save(override_file,{sid:overrides[sid]});output=destination/'cases'/sid;output.parent.mkdir(exist_ok=True)
                command=[sys.executable,str(Path(__file__).resolve()),'--plans',args.plans,'--label-spec',args.label_spec,
                    '--destination',str(output),'--repo-id',args.repo_id+'_'+sid,'--split',args.split,'--native-references',args.native_references,
                    '--one-scene',sid,'--override-file',str(override_file),'--camera-workers',str(args.camera_workers)]
                log=(destination/(sid+'.log')).open('x');env=dict(os.environ,CUDA_VISIBLE_DEVICES='',OMP_NUM_THREADS='1',MKL_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1')
                process=subprocess.Popen(command,env=env,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
                jobs[sid]=dict(process=process,log=log,output=output)
                save(destination/(sid+'_process.json'),dict(pid=process.pid,command=command,cwd=str(ROOT),environment=env.get('CUDA_VISIBLE_DEVICES'),GPU_execution=False))
                status('exporting_cases')
                if len(jobs)==args.workers:break
        if len(completed)<len(cases):time.sleep(10)
    status('assembling_complete_split')
    paths=[completed[c['original_inventory']['scene_id']]['path'] for c in cases]
    result=assemble_complete_task_split(paths,destination/'dataset',args.repo_id,split=args.split,
        expected_scene_ids=[c['original_inventory']['scene_id'] for c in cases])
    manifest=destination/'dataset/airport_training_manifest.json';data=read(manifest)
    data.update(full_input_plan=str(Path(args.plans).resolve()),full_input_plan_sha256=digest(args.plans),
        full_input_plan_selected_scene_ids=[c['original_inventory']['scene_id'] for c in cases])
    save(manifest,data);status('complete',split_dataset=result)

if __name__=='__main__':main()
