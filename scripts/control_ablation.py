"""Same-code, same-seed fresh physical ablation; no cross-run state reuse."""
from concurrent.futures import ThreadPoolExecutor, as_completed
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from r1pro_teleop.airport_fsm.contracts import atomic_json


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',default='runs/ablation')
    parser.add_argument('--variants',nargs='+',default=['baseline','substep','payload','alternate'])
    parser.add_argument('--config-prefix',default='configs/airport_ablation_')
    parser.add_argument('--indices',nargs='+',type=int,default=[4,6,7,16,218])
    parser.add_argument('--workers-per-variant',type=int,default=4)
    parser.add_argument('--parallel-variants',type=int,default=4)
    args=parser.parse_args()
    if (min(args.workers_per_variant,args.parallel_variants)<1 or
            len(set(args.variants))!=len(args.variants) or
            any(not name.replace('_','').isalnum() for name in args.variants)):
        raise ValueError('Unique safe variant names and positive worker budgets required')
    destination=ROOT/args.output
    destination.mkdir(parents=True,exist_ok=False)
    variants=tuple(args.variants)
    env=dict(os.environ,OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1')
    def job(name):
        root=destination/name
        with (destination/(name+'.log')).open('x') as log:
            code=subprocess.run([sys.executable,'scripts/control_regression.py',
                '--output',str(root),'--config',f'{args.config_prefix}{name}.json',
                '--workers',str(args.workers_per_variant),'--indices',*map(str,args.indices)],cwd=ROOT,env=env,
                stdout=log,stderr=subprocess.STDOUT).returncode
        report=root/'evaluation_summary.json'
        return name, {'exit_code':code,'summary':json.loads(report.read_text()) if report.exists() else None}
    completed={}
    with ThreadPoolExecutor(max_workers=args.parallel_variants) as pool:
        futures=[pool.submit(job,name) for name in variants]
        for future in as_completed(futures):
            name,record=future.result();completed[name]=record
            atomic_json(destination/'progress.json',{'completed':completed,'total_variants':len(variants)})
    atomic_json(destination/'summary.json',completed)


if __name__=='__main__':main()
