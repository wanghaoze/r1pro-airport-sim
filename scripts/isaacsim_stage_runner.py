"""Independent actual wait receipt for one native-workflow child."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import time


def atomic(path,data):
    p=Path(path);t=p.with_suffix('.tmp');t.write_text(json.dumps(data,indent=2));t.replace(p)


def identity(pid):
    p=Path(f'/proc/{pid}')
    if not p.exists():return None
    try:
        # Linux may expose an empty cmdline very briefly during exec. Do not
        # publish that transient as the child's permanent command identity.
        for attempt in range(20):
            stat=p.joinpath('stat').read_text().rsplit(')',1)[1].split()
            if stat[0]=='Z':return None
            argv=p.joinpath('cmdline').read_text().split('\0')[:-1]
            if argv:break
            time.sleep(.01)
        return dict(pid=pid,start_ticks=stat[19],argv=argv,cwd=str(p.joinpath('cwd').resolve()))
    except FileNotFoundError:return None


def checked(job):
    current=identity(job['pid'])
    if current is None:return False
    if any(current[k]!=job[k] for k in ('start_ticks','argv','cwd')):
        raise RuntimeError('process_identity_changed_no_duplicate_or_signal')
    return True


def main():
    p=argparse.ArgumentParser();p.add_argument('--job',type=Path,required=True);a=p.parse_args()
    job=json.loads(a.job.read_text());base=a.job.with_suffix('')
    atomic(str(base)+'.runner.json',identity(os.getpid()))
    with Path(job['log']).open('x') as stream:
        child=subprocess.Popen(job['argv'],cwd=job['cwd'],stdin=subprocess.DEVNULL,
            stdout=stream,stderr=subprocess.STDOUT,env={**os.environ,**job.get('environment',{})})
        atomic(job['launch'],identity(child.pid))
        rc=child.wait()
    atomic(job['receipt'],dict(returncode=rc,actual_child_wait=True,unix=time.time(),child=identity(child.pid)))


if __name__=='__main__':main()
