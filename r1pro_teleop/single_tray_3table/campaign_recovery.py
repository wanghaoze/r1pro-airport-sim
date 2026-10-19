"""Bounded coordinator recovery; physical failures remain immutable outcomes."""
import json,os,time,subprocess,threading
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,wait,FIRST_COMPLETED
from r1pro_teleop.single_tray_3table.campaign import atomic_json,digest,case_commands,verified_case
from r1pro_teleop.single_tray_3table.workflow import process_identity
from .owned_command import command_state


def execute_recoverable(plan,output,*,release,sim_python,config,reference,workers=1,recover=False,poll_seconds=5):
    out=Path(output).resolve();release=Path(release).resolve()
    if type(workers) is not int or not 1<=workers<=64:raise ValueError('worker_resource_cap_required')
    if out.exists() and not recover:raise ValueError('existing_campaign_requires_explicit_recover')
    out.mkdir(parents=True,exist_ok=True)
    import fcntl
    lock=(out/'campaign.lock').open('a+');fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
    planpath=out/'plan.json';statuspath=out/'status.json'
    bindings=dict(release=str(release),sim_python=str(sim_python),config=str(config),config_sha256=digest(config),reference=str(reference),reference_sha256=digest(reference))
    if planpath.exists():
        if json.loads(planpath.read_text())!=plan:raise ValueError('campaign_plan_changed_no_recovery')
        state=json.loads(statuspath.read_text())
        if state.get('execution_bindings')!=bindings or state['source_plan_sha256']!=digest(planpath):raise ValueError('campaign_execution_bindings_changed')
    else:
        atomic_json(planpath,plan)
        state=dict(schema='airport_three_table_source_campaign_status/1',task_profile=plan['task_profile'],task_rule_revision=plan['task_rule_revision'],source_plan_sha256=digest(planpath),execution_bindings=bindings,selected=plan['selected'],results=[],completed=0,dataset_ready=False,training_started=False,route_coverage=plan['route_coverage'],child_cpu_threads=1,child_process_receipts_are_actual=True,peak_active_child_processes=0)
    state.update(pid=os.getpid(),workers=workers,stage='collecting_physical_candidates',recovered=recover)
    atomic_json(statuspath,state)
    finished={r['index']:r for r in state['results']}
    for i,row in finished.items():
        if digest(row['result'])!=row['result_sha256']:raise ValueError('closed_source_result_changed')
        if row['task_completed'] and not verified_case(row['result'],plan['variants'][i]):raise ValueError('closed_qualified_source_changed')
    def one(index,variant):
        base=out/f'case_{index:04d}';base.mkdir(exist_ok=True)
        journalpath=base/'recovery_status.json'
        journal=json.loads(journalpath.read_text()) if journalpath.exists() else dict(index=index,process_faults=[],attempt=0)
        if journal.get('stage')=='process_fault_backoff':
            while time.time()<journal['retry_after_unix']:time.sleep(min(poll_seconds,journal['retry_after_unix']-time.time()))
            journal.update(attempt=journal['attempt']+1,stage='resumed_next_registered_attempt');atomic_json(journalpath,journal)
        while True:
            attempt=int(journal['attempt']);directory=base/f'attempt_{attempt:02d}';directory.mkdir(exist_ok=True)
            result=directory/'observed_source/result.json';error=None;code=None;os_fault=False
            for key in ('inventory','parent_manifest','split_registry'):
                if digest(plan[key])!=plan[key+'_sha256']:raise ValueError('registered_inputs_changed')
            if digest(variant['parent_scene_json'])!=variant['parent_scene_json_sha256']:raise ValueError('parent_changed')
            generate,collect=case_commands(plan,variant,directory,release,sim_python,config,reference)
            for stage,argv in (('generate',generate),('collect',collect)):
                child=directory/(stage+'_owned');options=directory/(stage+'_options.json')
                if not options.exists():atomic_json(options,dict(schema='airport_three_table_owned_command/1',argv=argv,cwd=str(release),output=str(child)))
                else:
                    saved=json.loads(options.read_text())
                    if saved['argv']!=argv or saved['cwd']!=str(release):raise ValueError('registered_child_command_changed')
                launch_receipt=directory/(stage+'_wrapper.json')
                existing=command_state(child,options)
                if not launch_receipt.exists() and existing['stage']=='unstarted_or_startup_gap':
                    command=[str(sim_python),str(release/'scripts/run_three_table_owned_command.py'),'--options',str(options)]
                    with (directory/(stage+'_wrapper.log')).open('xb') as log:
                        p=subprocess.Popen(command,cwd=release,env=dict(os.environ,CUDA_VISIBLE_DEVICES='',OMP_NUM_THREADS='1',MKL_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1'),stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
                    identity=process_identity(p.pid)
                    atomic_json(launch_receipt,dict(pid=p.pid,argv=command,cwd=str(release),start_ticks=(identity or {}).get('start_ticks')))
                journal.update(stage=stage,active_output=str(child),heartbeat_unix=time.time());atomic_json(journalpath,journal)
                while True:
                    s=command_state(child,options)
                    if s['stage']=='closed':code=s['returncode'];break
                    if s['stage']=='unstarted_or_startup_gap':
                        from r1pro_teleop.single_tray_3table.workflow import checked_process
                        wrapper=json.loads(launch_receipt.read_text())
                        if not checked_process(wrapper):os_fault=True;error='owned_wrapper_died_before_child_receipt';break
                    elif s['stage']=='incomplete_exit_not_observed':os_fault=True;error='owned_child_exit_not_observed';break
                    journal.update(child_state=s,heartbeat_unix=time.time());atomic_json(journalpath,journal)
                    time.sleep(poll_seconds)
                if os_fault or code!=0:break
            # An actual failed physical result is terminal, irrespective of its
            # child exit code. Never turn task failures into random retries.
            if result.exists():
                try:success=code==0 and verified_case(result,variant)
                except Exception as exc:success=False;error=repr(exc)
                row=dict(index=index,parent_scene_id=variant['parent_scene_id'],variant_seed=variant['variant_seed'],split=variant['split'],result=str(result),result_sha256=digest(result),returncode=code,task_completed=success,source_qualified=success,error=error,attempt=attempt)
                journal.update(stage='closed_actual_result',result=row);atomic_json(journalpath,journal);return row
            if not os_fault:
                error='actual_child_nonzero_without_physical_result';os_fault=True
            faults=journal['process_faults']
            if len(faults)>=3:
                failure=directory/'failure_result.json'
                atomic_json(failure,dict(task_profile=plan['task_profile'],task_completed=False,physics_success=False,training_eligible=False,error=error,process_fault_limit=3))
                return dict(index=index,parent_scene_id=variant['parent_scene_id'],variant_seed=variant['variant_seed'],split=variant['split'],result=str(failure),result_sha256=digest(failure),returncode=code,task_completed=False,source_qualified=False,error=error,attempt=attempt)
            delay=(10,30,90)[len(faults)];faults.append(dict(attempt=attempt,error=error,returncode=code,backoff_seconds=delay,observed_unix=time.time()))
            journal.update(stage='process_fault_backoff',retry_after_unix=time.time()+delay);atomic_json(journalpath,journal)
            while time.time()<journal['retry_after_unix']:time.sleep(min(poll_seconds,journal['retry_after_unix']-time.time()))
            journal.update(attempt=attempt+1);atomic_json(journalpath,journal)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        pending={pool.submit(one,i,v) for i,v in enumerate(plan['variants']) if i not in finished}
        while pending:
            done,pending=wait(pending,timeout=poll_seconds,return_when=FIRST_COMPLETED)
            for future in done:
                row=future.result();finished[row['index']]=row
            state.update(results=[finished[i] for i in sorted(finished)],completed=len(finished),heartbeat_unix=time.time(),active_case_coordinators=len(pending))
            atomic_json(statuspath,state)
    state.update(stage='physical_candidates_complete',completed=len(finished),selected=plan['selected'],successful=sum(r['task_completed'] for r in state['results']),finished_unix=time.time(),source_gpu_processes_started=False)
    atomic_json(statuspath,state);return state
