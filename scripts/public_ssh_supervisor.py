"""Supervise the project-owned EC2 reverse SSH tunnel with bounded recovery."""
import argparse
import datetime
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--host', default='47.130.167.160')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    run = args.run.resolve()
    run.mkdir(parents=True, exist_ok=True)
    lock = (run / 'supervisor.lock').open('a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    secrets = root / '.secrets' / 'public_ssh'
    command = ['ssh', '-N', '-T', '-o', 'BatchMode=yes', '-o',
               'StrictHostKeyChecking=yes', '-o', f'UserKnownHostsFile={secrets / "known_hosts"}',
               '-o', 'ExitOnForwardFailure=yes', '-o', 'ConnectTimeout=10',
               '-o', 'ServerAliveInterval=15', '-o', 'ServerAliveCountMax=3',
               '-i', str(secrets / 'ec2_tunnel_ed25519'), '-R',
               '127.0.0.1:2222:127.0.0.1:22', f'r1pro-tunnel@{args.host}']
    state = {'pid': os.getpid(), 'cwd': str(root), 'command': command,
             'started_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
             'start_ticks': Path('/proc/self/stat').read_text().split(') ', 1)[1].split()[19],
             'max_recoveries': 3, 'public_login_verified': False, 'attempts': []}
    child = None
    stopping = False

    def stop(signum, frame):
        nonlocal stopping
        stopping = True
        if child is not None and child.poll() is None:
            child.terminate()

    def write(stage):
        state['stage'] = stage
        state['heartbeat_at'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        temporary = run / 'status.json.tmp'
        temporary.write_text(json.dumps(state, indent=2), encoding='utf8')
        temporary.replace(run / 'status.json')

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    with (run / 'ssh.log').open('a', buffering=1) as log:
        for attempt in range(4):
            if stopping:
                break
            record = {'attempt': attempt + 1, 'started_at': datetime.datetime.now(datetime.timezone.utc).isoformat()}
            state['attempts'].append(record)
            try:
                child = subprocess.Popen(command, cwd=root, stdout=log, stderr=log)
                record['pid'] = child.pid
                record['start_ticks'] = Path(f'/proc/{child.pid}/stat').read_text().split(') ', 1)[1].split()[19]
                while child.poll() is None:
                    write('ssh_running_pending_external_verification')
                    time.sleep(5)
                record['exit_code'] = child.returncode
            except OSError as exc:
                record['error'] = str(exc)
            if stopping:
                break
            write('connection_exited')
            if attempt < 3:
                for _ in range((5, 15, 45)[attempt]):
                    if stopping:
                        break
                    time.sleep(1)
        state['actual_exit_code'] = 0 if stopping else 1
        write('stopped' if stopping else 'failed_recovery_budget_exhausted')
    return state['actual_exit_code']


if __name__ == '__main__':
    raise SystemExit(main())
