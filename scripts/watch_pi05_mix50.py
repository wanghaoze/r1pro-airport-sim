"""Read-only monitor of the frozen 50/50 run; no control or training commands."""
import argparse,json,time
from pathlib import Path


def read(p):
    try:return json.loads(p.read_text())
    except FileNotFoundError:return {}


def report(run):
    p=read(run/'pipeline_status.json');t=read(run/'pi05/training_status.json');d=read(run/'preparation_status.json')
    stage=p.get('stage','not_started')
    if stage=='train':stage=t.get('stage','waiting_for_training_initialization')
    n=t.get('updates',0);eta=t.get('eta_seconds')
    lines=[time.strftime('%Y-%m-%d %H:%M:%S')+'  '+stage,
           f"pi0.5 BC 50% real / 50% sim: {n}/10000 ({n/100:.2f}%) PID={p.get('active_pid')}"]
    if not t.get('training_started',False):lines.append('No gradient updates verified yet; data/initialization is not training.')
    if d:lines.append('Data: '+json.dumps(d.get('counts',{})))
    if n>=100 and t.get('stage')=='training' and eta is not None:lines.append(f'ETA remaining training only: ~{eta/60:.0f} min')
    else:lines.append('ETA: -- (not enough steady-state updates or stage finished)')
    if t.get('metrics'):lines.append('Metrics: '+json.dumps(t['metrics']))
    if p.get('error'):lines.append('ERROR: '+p['error'])
    for action,row in read(run/'mse_mixed_pi05.json').get('groups',{}).items():
        lines.append(f"{action}: arm MSE={row['arm_mse_rad2']:.6g} rad², gripper MSE={row['gripper_mse_mm2']:.6g} mm²")
    lines.append('Ctrl+C exits this monitor only.')
    return '\n'.join(lines)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);p.add_argument('--watch',type=int,default=0);a=p.parse_args()
    try:
        while True:
            print(report(a.run),flush=True)
            if not a.watch:break
            time.sleep(max(1,a.watch))
    except KeyboardInterrupt:pass
