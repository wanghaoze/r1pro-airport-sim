"""Read-only progress monitor for the isolated real-only experiment."""
import argparse
import datetime
import json
from pathlib import Path
import time


def read(p):
    return json.loads(p.read_text()) if p.exists() else {}


def report(run):
    p=read(run/'pipeline_status.json');t=read(run/'pi05/training_status.json');e=read(run/'evaluation_status.json')
    print(datetime.datetime.now().astimezone().isoformat(timespec='seconds'),p.get('stage','not_started'),
          'supervisor=',p.get('pid'),'child=',p.get('active_pid'),'heartbeat=',p.get('heartbeat_unix'),flush=True)
    n=t.get('updates',0);target=t.get('target_updates',10000);eta=t.get('eta_seconds') if t.get('stage')=='training' else None
    print(f"Real-only pi0.5: {t.get('stage','waiting_for_data')} {n}/{target} {n/target:.2%} ETA={round(eta/60,1) if eta is not None else '--'} min (training only)",flush=True)
    if e:print('Evaluation:',json.dumps(e),flush=True)
    if p.get('error'):print('ERROR:',p['error'],flush=True)
    for split in ('val','test'):
        r=read(run/'evaluation'/f'{split}_summary.json')
        if r:print(split,json.dumps(r['groups']),flush=True)
    print('No simulation training samples. Offline error is not real-robot success. Ctrl+C exits monitor only.',flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);p.add_argument('--watch',type=int,default=0);a=p.parse_args()
    try:
        while True:
            report(a.run)
            if not a.watch:break
            time.sleep(max(1,a.watch))
    except KeyboardInterrupt:pass
