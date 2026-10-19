"""Continue the failed comparison in a new run, preserving the old evidence."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import subprocess
import time
import traceback


def write(path,data):
    p=Path(path);t=p.with_suffix('.tmp');t.write_text(json.dumps(data,indent=2));t.replace(p)


def identity(pid):
    p=Path('/proc')/str(pid)
    return dict(pid=pid,start_ticks=p.joinpath('stat').read_text().rsplit(')',1)[1].split()[19],
        argv=p.joinpath('cmdline').read_bytes().decode().strip('\0').split('\0'),cwd=str(p.joinpath('cwd').resolve()))


def supervise(run,release):
    run=Path(run).resolve();release=Path(release).resolve()
    lock=(run/'comparison.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    state=dict(stage='preflight',training_started=False,pid=os.getpid(),identity=identity(os.getpid()),heartbeat_unix=time.time(),method='BC',dagger_executed=False)
    env=dict(os.environ,AIRPORT_COMPARISON_RUN=str(run),CUDA_VISIBLE_DEVICES='GPU-c8e2826c-b460-18ba-dab5-ccd8c1da8b6c',MUJOCO_GL='egl',MUJOCO_EGL_DEVICE_ID='0',OMP_NUM_THREADS='2',OPENBLAS_NUM_THREADS='2',MKL_NUM_THREADS='2',XLA_PYTHON_CLIENT_MEM_FRACTION='.85',WANDB_MODE='disabled',TOKENIZERS_PARALLELISM='false')
    def persist(stage,**kw):state.update(stage=stage,heartbeat_unix=time.time(),**kw);write(run/'pipeline_status.json',state)
    def execute(stage,argv):
        with (run/'logs'/f'{stage}.log').open('x') as stream:
            child=subprocess.Popen(argv,cwd=release,env=env,stdin=subprocess.DEVNULL,stdout=stream,stderr=subprocess.STDOUT,start_new_session=True)
        birth=identity(child.pid);write(run/'logs'/f'{stage}.process.json',birth)
        persist(stage,active_pid=child.pid,active_identity=birth)
        while child.poll() is None:
            trained=run/'affordvla/training_status.json'
            current=json.loads(trained.read_text()) if trained.exists() else {}
            persist(stage,training_started=current.get('training_started',False),actual_afford_updates=current.get('total_completed_updates',0));time.sleep(5)
        code=child.wait();write(run/'logs'/f'{stage}.exit.json',dict(returncode=code,actual_child_wait=True,identity=birth,completed_unix=time.time()))
        if code:raise RuntimeError(f'{stage}: actual exit {code}; see logs/{stage}.log')
        persist(stage,active_pid=None)
    try:
        persist('preflight')
        setup=json.loads((run/'environment_status.json').read_text())
        if setup['stage']!='installed_pending_actual_cuda_test':raise ValueError('new_conda_environment_not_installed')
        py=setup['python'];script=str(release/'scripts/compare_pickup120.py')
        execute('cuda_smoke',[py,'-c',"import torch,json; x=torch.randn(128,128,device='cuda',requires_grad=True); (x@x).square().mean().backward(); torch.cuda.synchronize(); assert torch.isfinite(x.grad).all(); print(json.dumps(dict(torch=torch.__version__,cuda=torch.version.cuda,capability=torch.cuda.get_device_capability(),arch=torch.cuda.get_arch_list(),finite_gradient=True)))"])
        execute('affordvla_training',[py,script,'affordvla'])
        status=json.loads((run/'affordvla/training_status.json').read_text())
        if status.get('stage')!='trained' or not Path(status.get('checkpoint','')).is_file():raise ValueError('missing_actual_afford_checkpoint')
        execute('pi05_evaluation',['/home/michelle/miniconda3/envs/r1pro-vla/bin/python',script,'evaluate','--model','pi05'])
        execute('affordvla_evaluation',[py,script,'evaluate','--model','affordvla'])
        results={m:json.loads((run/'evaluations'/m/'summary.json').read_text()) for m in ['pi05','affordvla']}
        write(run/'comparison.json',results)
        if any(not x['valid_model_comparison'] for x in results.values()):raise ValueError('evaluation_infrastructure_failure_not_model_comparison')
        persist('complete',training_started=True,active_pid=None)
    except BaseException as error:
        persist('failed_preserving_checkpoints_and_evidence',error=repr(error),traceback=traceback.format_exc(),active_pid=None);raise


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--run',required=True);p.add_argument('--release',required=True);a=p.parse_args();supervise(a.run,a.release)
