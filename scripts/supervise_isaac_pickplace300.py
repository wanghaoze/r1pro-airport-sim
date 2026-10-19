"""Bounded, detached 32-room production. Does not train or alter physical gates."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import traceback


def read(p):
    return json.loads(Path(p).read_text())


def write(p,d):
    p=Path(p);t=p.with_suffix(p.suffix+'.tmp');t.write_text(json.dumps(d,indent=2));t.replace(p)


def select_pairs(catalogs,target,root):
    pairs=[];seen=set()
    for c in catalogs:
        if c.get('overview_error') or not c.get('overview'):raise ValueError('overview_missing')
        for p in c['frozen_batches']:
            ss=p['segments']
            if len(ss)!=2 or [s['prompt'] for s in ss]!=['Pick up the tray','Place the tray']:raise ValueError('not_complete_pair')
            if any(not s['ready'] or not s['complete_pick_place_pair'] or s['split']!='train' for s in ss):raise ValueError('not_qualified_train_pair')
            source=ss[0]['source_room']
            if not Path(source).is_relative_to(root):raise ValueError('historical_source_excluded')
            if ss[1]['source_room']!=source:raise ValueError('cross_source_pair')
            if source in seen:raise ValueError('duplicate_source')
            seen.add(source);pairs.append(p)
    return pairs[:target],len(pairs)


def main(cfg):
    import fcntl
    sys.path.insert(0,str(Path(cfg['code'])/'scripts'))
    from isaacsim_stage_runner import identity,checked
    root=Path(cfg['run']);root.mkdir(parents=True,exist_ok=True)
    lock=(root/'production.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    global_lock=(Path(cfg['project'])/'runs/parallel_engine_production.lock').open('a')
    fcntl.flock(global_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    for proc in Path('/proc').glob('[0-9]*'):
        try:
            argv=proc.joinpath('cmdline').read_text().split('\0')
            if any(x.endswith('/run_isaac_parallel_pickplace.py') for x in argv):
                if not any(str(root) in x for x in argv):raise RuntimeError('another_native_engine_active:'+proc.name)
        except (FileNotFoundError,PermissionError):pass
    write(root/'supervisor.identity.json',identity(os.getpid()))
    def status(stage,**kw):
        write(root/'production_status.json',dict(stage=stage,pid=os.getpid(),heartbeat_unix=time.time(),target_source_pairs=cfg['target'],training_started=False,**kw))
    def job(run,name,argv):
        receipt=run/(name+'.exit.json');jp=run/(name+'.job.json');runner=jp.with_suffix('.runner.json')
        if receipt.exists():return read(receipt)
        if runner.exists():
            if not checked(read(runner)):raise RuntimeError('lost_waiter_without_exit:'+str(runner))
        elif jp.exists():raise RuntimeError('ambiguous_job_without_waiter:'+str(jp))
        else:
            write(jp,dict(argv=argv,cwd=cfg['project'],log=str(run/(name+'.log')),launch=str(run/(name+'.launch.json')),receipt=str(receipt),environment={'PYTHONUNBUFFERED':'1'}))
            child=subprocess.Popen([cfg['control_python'],str(Path(cfg['code'])/'scripts/isaacsim_stage_runner.py'),'--job',str(jp)],cwd=cfg['project'],start_new_session=True,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            time.sleep(.5)
        while not receipt.exists():
            status(name,batch=str(run),qualified_pairs=current_count,disk_free_bytes=shutil.disk_usage(root).free)
            if runner.exists() and not checked(read(runner)) and not receipt.exists():raise RuntimeError('lost_waiter:'+str(runner))
            time.sleep(10)
        result=read(receipt)
        if result.get('actual_child_wait') is not True:raise RuntimeError('invalid_actual_wait')
        return result
    catalogs=[];current_count=0
    for n in range(cfg['max_batches']):
        if current_count>=cfg['target']:break
        run=root/f'batch_{n:03d}';run.mkdir(exist_ok=True)
        catalog=run/'native/dataset_catalog.json'
        if catalog.exists() and (run/'export.exit.json').exists() and read(run/'export.exit.json').get('returncode')==0:
            if read(run/'native.exit.json').get('returncode')!=0:raise RuntimeError('invalid_native_exit')
            catalogs.append(read(catalog));_,current_count=select_pairs(catalogs,cfg['target'],root);continue
        if (run/'failed.json').exists():continue
        if shutil.disk_usage(root).free<cfg['minimum_free_bytes']:raise RuntimeError('insufficient_disk_preserve_existing_data')
        candidates=run/'candidates'
        cpu=job(run,'precheck',[cfg['native_python'],str(Path(cfg['controller_code'])/'prepare_isaac_parallel_candidates.py'),'--output',str(candidates),'--seed',str(cfg['seed']+n*1000)])
        if cpu['returncode']!=0:
            write(run/'failed.json',dict(reason='cpu_precheck_failed',actual_exit=cpu));continue
        data=read(candidates/'config.json')
        if len(data['cases'])!=32:
            write(run/'failed.json',dict(reason='fewer_than_32_registered_candidates',accepted=len(data['cases'])));continue
        pipeline=run/'supervisor_config.json'
        if not pipeline.exists():write(pipeline,dict(run=str(run),project=cfg['project'],code=cfg['code'],native_python=cfg['native_python'],control_python=cfg['control_python'],stages=[dict(run=str(run),rooms=32,native_config=dict(scene_root=data['scene_root'],lab_assets=data['lab_assets'],rooms=32,cases=data['cases'],pin_render_products_to_gpus=True),parent_splits={data['parent_scene_id']:data['parent_split']})]))
        # Existing independent runners retain actual wait receipts if this controller exits.
        # A recovered batch supervisor is only started once its former children have closed.
        completed=False
        for attempt in range(3):
            name=f'pipeline_{attempt}'
            result=job(run,name,[cfg['control_python'],str(Path(cfg['code'])/'scripts/supervise_isaac_parallel_pickplace.py'),'--config',str(pipeline)])
            if result['returncode']==0:completed=True;break
            children=[run/'native.job.runner.json',run/'export.job.runner.json']
            while any(p.exists() and checked(read(p)) for p in children):
                status('waiting_existing_child_after_supervisor_failure',batch=str(run),attempt=attempt,qualified_pairs=current_count);time.sleep(10)
            # A physically unsuccessful engine or exporter is evidence, not an automatic replay.
            if any(p.exists() and read(p).get('returncode')!=0 for p in [run/'native.exit.json',run/'export.exit.json']):break
            time.sleep(10*(attempt+1))
        if not completed:
            write(run/'failed.json',dict(reason='pipeline_failed_bounded_recovery',actual_exit=result));continue
        catalogs.append(read(catalog));chosen,current_count=select_pairs(catalogs,cfg['target'],root)
        write(root/'progress_manifest.json',dict(ready=False,source_pairs=current_count,action_segments=current_count*2,pairs=chosen,training_started=False))
        status('batch_closed',batch=str(run),qualified_pairs=current_count)
    chosen,total=select_pairs(catalogs,cfg['target'],root)
    if len(chosen)<cfg['target']:raise RuntimeError('finite_candidate_budget_exhausted:'+str(len(chosen)))
    frozen=root/'dataset_v1';frozen.mkdir(exist_ok=True)
    manifest=dict(schema='parallel_pickplace_production/1',ready=True,source_pairs=len(chosen),action_segments=2*len(chosen),pairs=chosen,source_pairs_by_split={'train':len(chosen),'val':0,'test':0},source_domain='simulation/program_generated',scope='fixed_base_pickplace_only',historical_pairs_included=0,total_new_qualified_pairs=total,unused_extra_pairs=total-len(chosen),training_started=False)
    dest=frozen/'manifest.json'
    if dest.exists() and read(dest)!=manifest:raise RuntimeError('immutable_manifest_conflict')
    if not dest.exists():write(dest,manifest)
    write(root/'data_ready.json',dict(ready=True,manifest=str(dest),sha256=hashlib.sha256(dest.read_bytes()).hexdigest(),source_pairs=len(chosen),action_segments=2*len(chosen)))
    status('complete',qualified_pairs=len(chosen),total_new_qualified_pairs=total,manifest=str(dest))


def entry():
    p=argparse.ArgumentParser();p.add_argument('--config',type=Path,required=True);p.add_argument('--guard',action='store_true');a=p.parse_args();cfg=read(a.config)
    root=Path(cfg['run']);root.mkdir(exist_ok=True)
    if not a.guard:
        try:main(cfg)
        except BaseException as exc:
            write(root/'production_failure.json',dict(error=repr(exc),traceback=traceback.format_exc(),unix=time.time()));raise
        return
    import fcntl
    sys.path.insert(0,str(Path(cfg['code'])/'scripts'))
    from isaacsim_stage_runner import identity
    lock=(root/'guard.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    write(root/'guard.identity.json',identity(os.getpid()))
    for attempt in range(3):
        with (root/f'supervisor_attempt_{attempt}.log').open('a') as log:
            child=subprocess.Popen([sys.executable,__file__,'--config',str(a.config)],cwd=cfg['project'],stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT)
            write(root/'guard_status.json',dict(stage='supervising',attempt=attempt,child=identity(child.pid),unix=time.time()))
            rc=child.wait()
        write(root/f'supervisor_attempt_{attempt}.exit.json',dict(returncode=rc,actual_child_wait=True,unix=time.time()))
        if rc==0:break
        time.sleep(30*(attempt+1))
    write(root/'guard_status.json',dict(stage='complete' if rc==0 else 'blocked',actual_exit_code=rc,attempt=attempt,unix=time.time()))


if __name__=='__main__':entry()
