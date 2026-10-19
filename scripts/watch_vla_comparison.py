"""Read-only comparison progress; no model imports and no fabricated ETA."""
import argparse
import datetime
import json
import os
from pathlib import Path
import time


def read(path):
    try:
        return json.loads(Path(path).read_text())
    except FileNotFoundError:
        return {}


def progress(done, total, seconds_per_update=None, active=False):
    if not 0 <= done <= total or total <= 0:
        raise ValueError('invalid actual progress counters')
    eta = (total-done)*seconds_per_update if active and seconds_per_update and seconds_per_update > 0 else None
    return dict(done=done, total=total, percent=100*done/total, eta_seconds=eta)


def snapshot(run):
    run=Path(run);pipeline=read(run/'pipeline_status.json')
    pi=read(run/'pi05/training_status.json');aff=read(run/'affordvla/training_status.json')
    phase=aff.get('training_stage',1);count=aff.get('stage_updates',0)
    active=pipeline.get('stage')=='affordvla_training' and aff.get('stage')=='training'
    pid=pipeline.get('active_pid')
    alive=bool(pid and Path('/proc',str(pid)).is_dir()) if os.name=='posix' else None
    active=active and alive is not False
    total_aff=(1000 if phase==2 else 0)+count
    return dict(time=datetime.datetime.now().astimezone().isoformat(timespec='seconds'),
        pipeline_stage=pipeline.get('stage','not_started'),active_pid=pid,process_alive=alive,
        last_error=pipeline.get('error'),
        pi05=progress(pi.get('updates',0),10000),
        afford_mask_warmup=progress(1000 if phase==2 else count,1000,aff.get('seconds_per_update_ema'),active and phase==1),
        afford_action_bc=progress(count if phase==2 else 0,10000,aff.get('seconds_per_update_ema'),active and phase==2),
        combined_training=progress(pi.get('updates',0)+total_aff,21000),
        checkpoint=aff.get('checkpoint'),loss=aff.get('loss'),
        training_status_age_seconds=None if not aff.get('heartbeat_unix') else time.time()-aff['heartbeat_unix'],
        evaluations={m:read(run/'evaluations'/m/'progress.json') for m in ('pi05','affordvla')},
        eta_scope='active training stage only; excludes setup, other stages, checkpoint writes and evaluation')


def duration(seconds):
    if seconds is None:return '--'
    seconds=int(seconds);return f'{seconds//3600:02d}:{seconds//60%60:02d}:{seconds%60:02d}'


def render(s):
    lines=[f"{s['time']}  {s['pipeline_stage']}  PID={s['active_pid']} alive={s['process_alive']}"]
    for label,key in [('pi0.5 BC','pi05'),('Afford mask warmup','afford_mask_warmup'),('Afford action BC','afford_action_bc'),('All training updates','combined_training')]:
        p=s[key];n=int(p['percent']/5);bar='#'*n+'-'*(20-n)
        lines.append(f"{label:22} [{bar}] {p['done']:5}/{p['total']:<5} {p['percent']:6.2f}%  ETA {duration(p['eta_seconds'])}")
    for model,p in s['evaluations'].items():
        lines.append(f"{model} evaluation: {p.get('evaluated',0)}/{p.get('target',50)} completed, successes={p.get('successes','--')}")
    if s['last_error']:lines.append('ERROR: '+str(s['last_error']))
    lines.append('ETA covers the active training stage only; -- = unavailable. Ctrl+C exits this monitor only.')
    return '\n'.join(lines)


def main():
    p=argparse.ArgumentParser();p.add_argument('--run',required=True);p.add_argument('--watch',type=float,default=0);p.add_argument('--json',action='store_true');a=p.parse_args()
    try:
        while True:
            s=snapshot(a.run)
            if a.watch and not a.json:print('\033[2J\033[H',end='')
            print(json.dumps(s,indent=2) if a.json else render(s),flush=True)
            if not a.watch:break
            time.sleep(max(1,a.watch))
    except KeyboardInterrupt:pass


if __name__=='__main__':main()
