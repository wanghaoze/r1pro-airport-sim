"""Workstation keyboard command-stop; NOT a hardware emergency stop."""
import argparse, json, os, select, sys, time
from pathlib import Path


def update(path, stopped, reason):
    old=json.loads(path.read_text()) if path.exists() else {'generation':0}
    state=dict(stopped=stopped,generation=old['generation']+1,unix=time.time(),reason=reason)
    tmp=path.with_name(path.name+f'.{os.getpid()}.tmp');tmp.write_text(json.dumps(state,indent=2));os.replace(tmp,path)
    return state


def main():
    p=argparse.ArgumentParser();p.add_argument('--control-file',required=True,type=Path)
    p.add_argument('--stop',action='store_true');a=p.parse_args()
    if a.stop:
        print(update(a.control_file,True,'explicit_operator_stop'),flush=True);return
    import fcntl
    lock=a.control_file.with_suffix('.operator.lock').open('a')
    try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:
        heartbeat=a.control_file.with_name('operator_heartbeat.json')
        try:owner=json.loads(heartbeat.read_text()).get('pid','unknown')
        except (OSError,ValueError):owner='unknown'
        print(f'Control terminal already running (PID {owner}). No control state changed. Use that terminal, or press Q there before reopening.',flush=True)
        return
    print(update(a.control_file,True,'operator_control_started_stopped'),flush=True)
    if not sys.stdin.isatty():raise RuntimeError('Interactive terminal required; left STOP latched')
    import termios,tty
    old=termios.tcgetattr(sys.stdin);tty.setcbreak(sys.stdin.fileno())
    print('E / SPACE = latch STOP. R = rearm (restart robot client). Q = quit and STOP. Hardware stop remains independent.',flush=True)
    try:
        while True:
            heartbeat=a.control_file.with_name('operator_heartbeat.json')
            tmp=heartbeat.with_suffix('.tmp');tmp.write_text(json.dumps(dict(unix=time.time(),pid=os.getpid())));os.replace(tmp,heartbeat)
            if select.select([sys.stdin],[],[],.1)[0]:
                key=sys.stdin.read(1).lower()
                if key in ('e',' ','q'):
                    print(update(a.control_file,True,'keyboard_stop'),flush=True)
                    if key=='q':break
                elif key=='r':print(update(a.control_file,False,'deliberate_keyboard_rearm'),flush=True)
    finally:
        update(a.control_file,True,'operator_control_exit');termios.tcsetattr(sys.stdin,termios.TCSADRAIN,old)


if __name__=='__main__':main()
