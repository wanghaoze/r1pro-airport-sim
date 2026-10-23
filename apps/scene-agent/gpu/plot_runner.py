"""CPU plot subprocess with durable actual child wait and independent failure state."""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import time
from studio_backend import JOBS, ROOT, identity, write

if __name__ == '__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--job-id',required=True); args=parser.parse_args()
    run=(JOBS/args.job_id).resolve()
    if run.parent != JOBS.resolve() or not (run/'report.json').exists(): raise ValueError('plot_job_not_registered')
    out=ROOT/'runs/web_mse_figures_20261019_v1'/run.name; out.mkdir(parents=True,exist_ok=True)
    write(out/'identity.json',identity(os.getpid()))
    code=1
    try:
        with (out/'render.log').open('ab') as log:
            p=subprocess.Popen(['/home/michelle/miniconda3/envs/r1pro-vla/bin/python',str(Path(__file__).resolve().parents[1]/'scripts/studio_mse_plots.py'),'--run',str(run),'--output',str(out)],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,stdin=subprocess.DEVNULL,env={**os.environ,'CUDA_VISIBLE_DEVICES':''})
            write(out/'child_identity.json',identity(p.pid))
            code=p.wait()
        write(out/'exit.json',dict(returncode=code,actual_child_wait=True,endedAt=time.time()))
    except Exception as exc:
        write(out/'exit.json',dict(returncode=1,actual_child_wait=False,error=repr(exc),endedAt=time.time()))
    sys.exit(code)
