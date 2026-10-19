"""Read-only real/sim transfer stage, percent, actual MSE and measured ETA."""
import argparse,json,time,datetime
from pathlib import Path

def read(path):
    try:return json.loads(Path(path).read_text())
    except FileNotFoundError:return {}

def report(run):
    r=Path(run);p=read(r/'pipeline_status.json');t=read(r/'pi05/training_status.json');prep=read(r/'preparation_status.json');stage=p.get('stage','not_started')
    lines=[f"{datetime.datetime.now().astimezone().isoformat(timespec='seconds')}  {stage}  PID={p.get('active_pid')}"]
    if prep:
        lines.append(f"Data {prep.get('stage')}: {prep.get('split','')} {prep.get('completed_episodes',0)}/{prep.get('total_episodes','--')} episodes; real split {prep.get('real_counts','see frozen selection')}")
    if t:
        n=t.get('updates',0);eta=t.get('eta_seconds') if stage=='train' and t.get('stage')=='training' else None
        lines.append(f"Mixed pi0.5: {n}/10000 ({n/100:.2f}%) ETA={int(eta)//60 if eta is not None else '--'} minutes")
    else:lines.append('Mixed pi0.5: not started; preparing/MSE is not gradient training.')
    for m in ['pi05','affordvla','mixed_pi05']:
        prog=read(r/f'mse_{m}_progress.json');data=read(r/f'mse_{m}.json')
        if prog:lines.append(f"MSE {m}: {prog['evaluated_episodes']}/{prog['total_episodes']} episodes")
        for action,g in data.get('groups',{}).items():lines.append(f"  {m} {action}: arm MSE={g['arm_mse_rad2']:.6g} rad^2; gripper MSE={g['gripper_mse_mm2']:.6g} mm^2")
    sim=read(r/'sim_evaluations/progress.json')
    if sim:lines.append(f"Simulation cases {sim['completed']}/{sim['target']}, successes={sim['successes']}; independent actions, not whole tasks")
    if p.get('error'):lines.append('ERROR: '+p['error'])
    lines.append('Ctrl+C exits monitor only. ETA covers current training stage; videos/trajectories remain server.')
    return '\n'.join(lines)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--run',required=True);p.add_argument('--watch',type=int,default=0);a=p.parse_args()
    try:
        while True:
            print(report(a.run),flush=True)
            if not a.watch:break
            time.sleep(max(1,a.watch))
    except KeyboardInterrupt:pass
