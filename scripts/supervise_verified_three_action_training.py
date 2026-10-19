"""Independent guardian for a frozen, completed three-action BC dataset."""
import argparse,json,os,subprocess,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from r1pro_teleop.single_tray_3table.campaign import atomic_json,digest
from r1pro_teleop.single_tray_3table.workflow import process_identity,checked_process
from r1pro_teleop.single_tray_3table.guardian import guardian_step


def validate(path):
    o=json.loads(Path(path).read_text())
    if o.get('data_only') is not False or not o.get('completed_dataset_run') or o.get('external_training_run'):
        raise ValueError('completed_dataset_fresh_optimizer_bc_required')
    if Path(o['spec']).resolve().parent!=Path(o['run_dir']).resolve():
        raise ValueError('fresh_training_spec_in_new_run_required')
    return o


def guardian(path):
    import fcntl
    path=Path(path).resolve();o=validate(path);root=Path(o['run_dir']);root.mkdir(parents=True,exist_ok=True)
    handle=(root/'training_guardian.lock').open('a+');fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
    workflow=root/'training_guardian_scope.json'
    scope=dict(schema='airport_completed_dataset_training_scope/1',workflow_dir=str(root),training_options=str(path))
    if workflow.exists() and json.loads(workflow.read_text())!=scope:raise ValueError('immutable_guardian_scope_changed')
    if not workflow.exists():atomic_json(workflow,scope)
    argv=[o['vla_python'],str(Path(__file__).resolve()),'--options',str(path),'--recover']
    opts=dict(workflow_options=str(workflow),supervisor_argv=argv,supervisor_cwd=o['release'])
    state_path=root/'training_guardian_status.json'
    state=json.loads(state_path.read_text()) if state_path.exists() else dict(options_sha256=digest(path),process_faults=[],completed=False)
    if state['options_sha256']!=digest(path):raise ValueError('immutable_training_options_changed')
    state['identity']=process_identity(os.getpid());handles={}
    def launch(command,cwd,attempt):
        with (root/f'training_supervisor_{attempt:02d}.log').open('ab') as log:
            child=subprocess.Popen(command,cwd=cwd,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True,
                env=dict(os.environ,CUDA_VISIBLE_DEVICES='',OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1'))
        handles[child.pid]=child;actual=process_identity(child.pid)
        if actual is None:child.wait();raise RuntimeError('supervisor_exited_before_identity_capture')
        job=dict(pid=child.pid,start_ticks=actual['start_ticks'],argv=command,cwd=str(Path(cwd).resolve()))
        atomic_json(root/f'training_supervisor_{attempt:02d}_launch.json',job);return job
    if not state.get('supervisor'):state['supervisor']=launch(argv,opts['supervisor_cwd'],0)
    while True:
        for pid,child in handles.items():
            if child.poll() is not None:atomic_json(root/f'training_supervisor_{pid}_exit.json',dict(pid=pid,returncode=child.wait(),actual_child_wait=True))
        # Preserve healthy children after an outer supervisor failure. Never
        # launch a second trainer while a recorded stage child is still alive.
        live=[]
        for p in root.glob('*.startup.json'):
            saved=json.loads(p.read_text());actual=process_identity(saved.get('pid'))
            if actual and actual.get('argv')==saved.get('argv') and actual.get('cwd')==saved.get('cwd'):
                births=state.setdefault('stage_child_identities',{})
                prior=births.setdefault(str(p),actual)
                if checked_process(prior):live.append(prior)
        try:
            if not checked_process(state.get('supervisor',{})) and live:
                state.update(stage='waiting_for_healthy_stage_children_without_duplicate',active_stage_children=live,heartbeat_unix=time.time())
            else:guardian_step(opts,state,launch=launch)
        except (ValueError,KeyError) as error:
            state.update(stage='blocked_identity_or_artifact_error',last_error=repr(error),heartbeat_unix=time.time())
        atomic_json(state_path,state)
        if state.get('completed') or state['stage'].startswith('blocked_'):return state
        time.sleep(5)


def main():
    p=argparse.ArgumentParser();p.add_argument('--options',required=True);p.add_argument('--guardian',action='store_true');p.add_argument('--recover',action='store_true');a=p.parse_args()
    if a.guardian:return guardian(a.options)
    from r1pro_teleop.vla.three_table_single_tray_pipeline import supervise
    o=validate(a.options);return supervise(o,recover=a.recover and (Path(o['run_dir'])/'pipeline_status.json').exists())

if __name__=='__main__':main()
