"""Detached single-job controller. Child exit codes come from actual wait()."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback
from studio_backend import ROOT,CURRENT,JOBS,read,write,identity,sha,validate_request,assert_training_allowed

CODE=Path(__file__).resolve().parents[1] if Path(__file__).parent.name=='gpu' else Path(__file__).parent
VLA='/home/michelle/miniconda3/envs/r1pro-vla/bin/python'
NATIVE='/home/michelle/miniconda3/envs/env_isaaclab6/bin/python'


def status(run,stage,message,**kw):
    prior=read(run/'status.json');prior.update(status=stage,message=message,heartbeat_unix=time.time(),artifactDirectory=str(run),**kw);write(run/'status.json',prior)


def stage(run,name,argv):
    job=read(run/'request.json')
    assert_training_allowed(job.get('kind'))
    log=(run/(name+'.log')).open('ab');started=time.time()
    from execution_settings import selection
    job=read(run/'request.json');ids=selection(job['payload'],job['kind'])
    devices=ids if job['kind']=='training.create' else [job['payload'].get('inferenceGpu',min(ids))]
    write(run/(name+'.devices.json'),dict(physicalGpuIds=devices,cudaVisibleDevices=','.join(map(str,devices))))
    p=subprocess.Popen(argv,cwd=ROOT,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,env={**os.environ,'AIRPORT_PROJECT':str(ROOT),'CUDA_VISIBLE_DEVICES':','.join(map(str,devices))})
    write(run/(name+'.launch.json'),dict(identity(p.pid) or {},argv=argv,startedAt=started))
    try:
        while p.poll() is None:
            progress=read(run/'progress.json')
            if name=='train':progress=read(run/'training/training_status.json')
            status(run,'running',name,progress=progress,currentStage=name);time.sleep(.5 if name=='vla' else 5)
        rc=p.wait()
    finally:log.close()
    write(run/(name+'.exit.json'),dict(returncode=rc,actual_child_wait=True,pid=p.pid,startedAt=started,endedAt=time.time()))
    if rc:raise RuntimeError(f'{name}_failed_exit_{rc}')


def train(run,job):
    assert_training_allowed(job.get('kind'))
    p=job['payload'];training=run/'training';training.mkdir(exist_ok=False)
    selection=read(run/'dataset_selection.json');base=read(CURRENT/'inputs.json')
    config=dict(base,training_steps=p['steps'],real_fraction=p['realPercent']/100,minimum_sources=1,selected_dataset_ids=p['datasets'])
    config.update(sim_cache=None,frozen_manifest=None)
    write(training/'selection.json',selection)
    write(training/'inputs.pending.json',config)
    stage(run,'prepare_sources',[VLA,str(CODE/'scripts/studio_prepare_training.py'),'--run',str(training)])
    stage(run,'prepare_training',[VLA,str(CODE/'scripts/train_pi05_parallel_real_mix.py'),'--run',str(training),'--mode','prepare'])
    stage(run,'cpu_transform',[VLA,str(CODE/'scripts/check_parallel_mix_cpu.py'),'--run',str(training)])
    # One process continues to the exact requested target; intermediate saves do
    # not reinitialize the optimizer or restart JIT.
    stage(run,'train',[VLA,str(CODE/'scripts/train_pi05_parallel_real_mix.py'),'--run',str(training),'--mode','train','--stop',str(p['steps'])])
    receipt=read(training/f'checkpoint_{p["steps"]:06d}.json')
    if not receipt.get('checkpoint_saved') or receipt.get('checkpoint_updates')!=p['steps']:raise ValueError('final_checkpoint_not_closed')
    write(run/'report.json',dict(scope='fixed_base_pickplace_training',actualUpdates=p['steps'],checkpoint=receipt['checkpoint'],modelValidationPassed=None))


def mse(run,job):
    entries=read(run/'checkpoints.json',[]);reports=[]
    for i,entry in enumerate(entries):
        stage(run,f'mse_{i}',[VLA,str(CODE/'scripts/studio_mse.py'),'--run',str(run),'--index',str(i)])
        reports.append(read(run/entry['id']/'report.json'))
    for row in reports[1:]:
        for key in ('contract','validMaskSha256','truthSha256'):
            if row[key]!=reports[0][key]:raise ValueError('paired_MSE_protocol_or_targets_changed')
    write(run/'report.json',dict(protocol=reports[0]['contract'],split=job['payload']['split'],frames=reports[0]['frames'],validTimesteps=reports[0]['validTimesteps'],models=reports))


def vla(run,job):
    os.environ['CUDA_VISIBLE_DEVICES']=str(job['payload'].get('inferenceGpu',0))
    os.environ['STUDIO_SIM_GPU']=str(job['payload'].get('simulationGpu',0))
    stage(run,'vla',[VLA,str(CODE/'scripts/studio_vla_evaluate.py'),'--run',str(run),'--native-python',NATIVE])
    if not read(run/'report.json'):raise ValueError('native_report_missing')


def main():
    import fcntl
    parser=argparse.ArgumentParser();parser.add_argument('--run',type=Path,required=True);args=parser.parse_args();run=args.run.resolve()
    if run.parent!=JOBS.resolve():raise ValueError('unregistered_job_directory')
    with (JOBS/'gpu_job.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        write(run/'runner_identity.json',dict(identity(os.getpid()),startedAt=time.time()))
        job=read(run/'request.json');code=0
        try:
            validate_request(job);status(run,'preparing','复核固定数据来源与检查点身份。')
            {'training.create':train,'evaluation.mse':mse,'evaluation.vla':vla,'evaluation.live':vla}[job['kind']](run,job)
            report=read(run/'report.json')
            # Detailed per-episode results remain on the GPU; only bounded metrics travel.
            for model in report.get('models',[]):model.pop('byEpisode',None)
            status(run,'cancelled' if (run/'stop_requested').exists() else 'completed','作业流程已结束；训练完成不等于闭环验证通过。',report=report,progress=read(run/'progress.json'))
        except BaseException as exc:
            code=1;write(run/'failure.json',dict(error=repr(exc),traceback=traceback.format_exc()));status(run,'cancelled' if (run/'stop_requested').exists() else 'failed',str(exc),error=repr(exc))
        finally:write(run/'exit.json',dict(jobReturnCode=code,endedAt=time.time(),pid=os.getpid()))
        return code


if __name__=='__main__':sys.exit(main())
