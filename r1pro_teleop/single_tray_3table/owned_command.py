"""Durable exit receipts for one explicitly registered CPU child command."""
import json
import os
from pathlib import Path
import subprocess
import time
from r1pro_teleop.single_tray_3table.campaign import atomic_json, digest
from r1pro_teleop.single_tray_3table.workflow import process_identity, checked_process


def run_command_receipt(options_path):
    path=Path(options_path).resolve();options=json.loads(path.read_text());sha=digest(path)
    if options.get('schema')!='airport_three_table_owned_command/1':raise ValueError('explicit_owned_command_required')
    argv=options.get('argv');cwd=Path(options['cwd']).resolve();output=Path(options['output']).resolve()
    if not isinstance(argv,list) or not argv or any(not isinstance(s,str) for s in argv) or not cwd.is_dir():raise ValueError('explicit_argv_cwd_required')
    output.mkdir(parents=True,exist_ok=True)
    import fcntl
    lock=(output/'command.lock').open('a+');fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
    receipt=output/'process.json';exitfile=output/'exit.json'
    if receipt.exists() or exitfile.exists():raise ValueError('owned_command_output_fresh_required')
    env=dict(os.environ,CUDA_VISIBLE_DEVICES='',OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1')
    env.update(options.get('environment',{}))
    with (output/'stdout.log').open('xb') as log:
        proc=subprocess.Popen(argv,cwd=cwd,env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT)
        identity=process_identity(proc.pid)
        row=dict(schema='airport_three_table_owned_command_process/1',options=str(path),options_sha256=sha,wrapper_identity=process_identity(os.getpid()),child_identity=identity,argv=argv,cwd=str(cwd),pid=proc.pid,started_unix=time.time(),actual_exit_observed=False)
        if identity:row['start_ticks']=identity['start_ticks']
        atomic_json(receipt,row)
        code=proc.wait()
    row.update(actual_exit_observed=True,returncode=code,exited_unix=time.time())
    atomic_json(exitfile,row)
    return code


def command_state(output,options_path,*,probe=process_identity):
    """Artifact receipt beats /proc presence; a zombie is not running."""
    root=Path(output);path=Path(options_path);sha=digest(path)
    options=json.loads(path.read_text());receipt=root/'process.json';exitfile=root/'exit.json'
    if exitfile.exists():
        row=json.loads(exitfile.read_text())
        if row.get('options_sha256')!=sha or row.get('argv')!=options['argv'] or Path(row.get('cwd','')).resolve()!=Path(options['cwd']).resolve() or row.get('actual_exit_observed') is not True or type(row.get('returncode')) is not int:
            raise ValueError('actual_command_exit_identity_changed')
        return dict(stage='closed',returncode=row['returncode'],receipt=str(exitfile),receipt_sha256=digest(exitfile))
    if not receipt.exists():return dict(stage='unstarted_or_startup_gap')
    row=json.loads(receipt.read_text())
    if row.get('options_sha256')!=sha:raise ValueError('owned_command_options_changed')
    wrapper=row.get('wrapper_identity');child=row.get('child_identity')
    if wrapper and checked_process(wrapper,probe):return dict(stage='running_wrapper',identity=wrapper)
    if child and checked_process(child,probe):return dict(stage='running_orphan_child_without_wrapper',identity=child)
    return dict(stage='incomplete_exit_not_observed',receipt=str(receipt),receipt_sha256=digest(receipt))
