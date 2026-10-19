"""Bounded outer process guardian, never a physics timeout or recipe editor."""
import json
import os
from pathlib import Path
import subprocess
import time
from .campaign import atomic_json,digest
from .workflow import process_identity,checked_process,terminal_training_status

BACKOFF_SECONDS=(10,30,90)


def terminal_pipeline_failure(options):
    workflow=json.loads(Path(options['workflow_options']).read_text())
    train=Path(workflow.get('training_options',''))
    if not train.is_file():return None
    settings=json.loads(train.read_text());path=Path(settings['run_dir'])/'pipeline_status.json'
    if not path.is_file():return None
    value=json.loads(path.read_text())
    if terminal_training_status(value):
        return dict(status=str(path),status_sha256=digest(path),error=value.get('error'),stage=value['stage'])
    return None


def registered_data_watcher_needs_supervision(options):
    """A terminal main run cannot abandon an independently registered watcher."""
    workflow=json.loads(Path(options['workflow_options']).read_text());watcher=workflow.get('data_version2_watcher')
    if not watcher:return False
    if digest(watcher['options'])!=watcher['options_sha256']:raise ValueError('registered_data_watcher_options_changed')
    status_path=Path(workflow['workflow_dir'])/'workflow_status.json'
    if not status_path.is_file():return False
    state=json.loads(status_path.read_text())
    if state.get('options_sha256')!=digest(options['workflow_options']):raise ValueError('data_watcher_parent_options_identity_changed')
    job=state.get('children',{}).get('source_v2_dataset_watcher')
    if not job or not job.get('start_ticks') or not job.get('argv'):return False
    if checked_process(job):return True
    faults=state.get('process_faults',{}).get('source_v2_dataset_watcher',[])
    if len(faults)>=3 or 'source_v2_dataset_watcher' in state.get('blocked_process_faults',{}):return False
    watch_status=Path(watcher['watch_dir'])/'status.json'
    if not watch_status.is_file():return False
    value=json.loads(watch_status.read_text())
    if value.get('stage') in ('data_only_v2_verified_complete','data_only_watch_contract_or_fault_budget_blocked'):return False
    return job.get('exited') is True or job.get('command_output') is not None


def validate_guardian(options):
    if options.get('schema')!='airport_three_table_workflow_guardian/1':raise ValueError('reviewed_guardian_options_required')
    for key in ('guardian_dir','workflow_options','supervisor_cwd'):
        if not isinstance(options.get(key),str) or not options[key]:raise ValueError('guardian_paths_required')
    if digest(options['workflow_options'])!=options.get('workflow_options_sha256'):raise ValueError('immutable_workflow_options_changed')
    argv=options.get('supervisor_argv')
    if not isinstance(argv,list) or '--recover' not in argv or '--options' not in argv or Path(argv[argv.index('--options')+1]).resolve()!=Path(options['workflow_options']).resolve():raise ValueError('explicit_same_workflow_recovery_command_required')
    if len(argv)<2 or Path(argv[1]).name!='supervise_three_table_workflow.py':raise ValueError('guardian_may_only_restart_reviewed_workflow_supervisor')
    identity=options.get('adopt_supervisor')
    if identity and (not identity.get('start_ticks') or not identity.get('argv') or not identity.get('cwd') or type(identity.get('pid')) is not int):raise ValueError('full_existing_supervisor_identity_required')
    return options


def completed_artifact(options):
    from ..vla.data_three_table_single_tray import PROFILE
    workflow=json.loads(Path(options['workflow_options']).read_text())
    train_options=Path(workflow.get('training_options',''))
    if not train_options.is_file():return False
    settings=json.loads(train_options.read_text());run=Path(settings['run_dir']);path=run/'pipeline_status.json'
    milestone_run=Path(settings.get('external_training_run',run))
    if 'external_training_run' in settings:
        resources=settings.get('external_input_sha256')
        if not isinstance(resources,dict) or not resources or not settings.get('training_release'):return False
        if any(not Path(p).is_file() or digest(p)!=sha for p,sha in resources.items()):return False
    if not path.is_file():return False
    training=json.loads(path.read_text())
    if not (training.get('stage')=='three_table_bc_training_and_new_scope_evaluations_complete' and training.get('training_complete') is True and training.get('actual_completed_updates')==100000):return False
    for updates in (10,100,1000,10000,100000):
        milestone=milestone_run/f'milestone_{updates:06d}.json';receipt_path=run/'evaluations'/f'step_{updates:06d}'/'completion_receipt.json'
        if not milestone.is_file() or not receipt_path.is_file():return False
        m=json.loads(milestone.read_text());r=json.loads(receipt_path.read_text())
        if m.get('schema')!='airport_pi05_training_milestone/1' or m.get('prompt_mode')!=PROFILE or m.get('checkpoint_verified') is not True or m.get('actual_completed_updates')!=updates or m.get('checkpoint_step')!=updates-1:return False
        checkpoint=Path(m.get('checkpoint',''));norm=Path(m.get('normalization',''))
        if not (checkpoint/'params').is_dir() or not (checkpoint/'train_state').is_dir() or not norm.is_file() or digest(norm)!=m.get('norm_sha256'):return False
        if r.get('schema')!='airport_three_table_single_tray_evaluation_handoff/1' or r.get('task_profile')!=PROFILE or r.get('actual_completed_updates')!=updates or r.get('training_status_sha256')!=digest(milestone) or r.get('status')!='evaluation_completed_gpu_released' or r.get('training_resume_allowed') is not True or r.get('active_owned_gpu_rows')!=[]:return False
        processes=r.get('actual_owned_processes',[])
        if not processes or any(p.get('returncode') is None or p.get('active') is not False for p in processes):return False
        summary=Path(r.get('evaluation_summary',''))
        if not summary.is_file() or digest(summary)!=r.get('evaluation_summary_sha256'):return False
        s=json.loads(summary.read_text())
        if s.get('protocol_id')!=r.get('new_three_table_single_tray_protocol_id') or s.get('covered')!=s.get('selected') or not s.get('selected') or len(s.get('cases',[]))!=s['selected']:return False
        for case in s['cases']:
            for field in ('trace','result'):
                if not Path(case.get(field,'')).is_file() or digest(case[field])!=case.get(field+'_sha256'):return False
            videos=case.get('videos',[])
            if {v.get('camera') for v in videos}!={'head_left','head_right','left_wrist','right_wrist'} or len(videos)!=4:return False
            if any(not Path(v.get('path','')).is_file() or digest(v['path'])!=v.get('sha256') for v in videos):return False
    return True


def guardian_step(options,state,*,probe=process_identity,clock=time.time,launch=None):
    """One testable transition: alive identities are never relaunched/signalled."""
    now=clock();job=state.get('supervisor')
    state.update(heartbeat_unix=now,guardian_pid=os.getpid())
    if job and checked_process(job,probe):
        state.update(stage='watching_verified_supervisor',supervisor_alive=True,last_verified_identity=probe(job['pid']))
        state.pop('retry_after_unix',None);return state
    state['supervisor_alive']=False
    terminal=terminal_pipeline_failure(options)
    if terminal and not registered_data_watcher_needs_supervision(options):
        state.update(stage='blocked_terminal_pipeline_failure_requires_new_reviewed_run',terminal_pipeline_failure=terminal,
                     last_error=terminal['error'])
        return state
    if terminal:
        state.update(terminal_pipeline_failure=terminal,supervision_scope='registered_data_version2_only_main_failure_sticky')
    if completed_artifact(options):state.update(stage='completed_actual_workflow_artifact',completed=True);return state
    if 'retry_after_unix' not in state:
        faults=state.setdefault('process_faults',[])
        if len(faults)>=3:state.update(stage='blocked_process_fault_limit',last_error='three_process_recovery_attempts_exhausted');return state
        delay=BACKOFF_SECONDS[len(faults)];faults.append(dict(observed_unix=now,prior_supervisor=job,backoff_seconds=delay))
        state.update(stage='process_fault_backoff',retry_after_unix=now+delay,last_error='supervisor_process_exited_without_complete_artifact')
        return state
    if now<state['retry_after_unix']:state['stage']='process_fault_backoff';return state
    if launch is None:raise ValueError('explicit_guardian_launcher_required')
    newjob=launch(options['supervisor_argv'],options['supervisor_cwd'],len(state['process_faults']))
    state.update(supervisor=newjob,stage='recovery_supervisor_started',last_launch_unix=now)
    state.pop('retry_after_unix',None);return state


def supervise_guardian(options_path,*,poll_seconds=5):
    options_path=Path(options_path).resolve();options=validate_guardian(json.loads(options_path.read_text()))
    root=Path(options['guardian_dir']).resolve();root.mkdir(parents=True,exist_ok=True)
    import fcntl
    lock=(root/'guardian.lock').open('a+');fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
    state_path=root/'guardian_status.json';sha=digest(options_path)
    if state_path.exists():
        state=json.loads(state_path.read_text())
        if state.get('options_sha256')!=sha:raise ValueError('unchanged_guardian_recovery_options_required')
    else:state=dict(schema='airport_three_table_workflow_guardian_status/1',options_sha256=sha,
                    supervisor=options.get('adopt_supervisor'),process_faults=[],completed=False)
    handles={}
    def launch(argv,cwd,attempt):
        log=root/f'supervisor_recovery_{attempt:02d}.log'
        with log.open('xb') as stream:
            env=dict(os.environ,CUDA_VISIBLE_DEVICES='',OMP_NUM_THREADS='1',MKL_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1')
            p=subprocess.Popen(argv,cwd=cwd,env=env,stdin=subprocess.DEVNULL,stdout=stream,stderr=subprocess.STDOUT,start_new_session=True)
        handles[p.pid]=p;job=dict(pid=p.pid,argv=argv,cwd=str(Path(cwd).resolve()),log=str(log))
        identity=process_identity(p.pid)
        if identity:job['start_ticks']=identity['start_ticks']
        else:job['already_exited_before_identity_capture']=True
        atomic_json(root/f'supervisor_recovery_{attempt:02d}_receipt.json',job);return job
    while True:
        for pid,p in handles.items():
            if p.poll() is not None:
                atomic_json(root/f'owned_supervisor_{pid}_exit.json',dict(pid=pid,returncode=p.returncode,actual_exited=True))
        try:
            guardian_step(options,state,launch=launch)
        except Exception as error:
            state.update(stage='blocked_identity_or_artifact_error',last_error=repr(error),heartbeat_unix=time.time())
        workflow=json.loads(Path(options['workflow_options']).read_text());path=Path(workflow['workflow_dir'])/'workflow_status.json'
        if path.exists():
            value=json.loads(path.read_text());state.update(workflow_stage=value.get('phase'),workflow_heartbeat_unix=value.get('updated_unix'),workflow_status_sha256=digest(path),training_started=value.get('training_started',False))
        atomic_json(state_path,state)
        if state.get('completed'):return state
        time.sleep(poll_seconds)
