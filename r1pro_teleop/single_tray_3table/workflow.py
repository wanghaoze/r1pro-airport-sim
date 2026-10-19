"""Durable reviewed demo -> fresh source campaign -> existing training gate.

This scheduler edits no controller/config/source and never retries an unlisted
recipe. A failed or absent demo remains explicitly blocked awaiting review.
"""
import html
import json
import os
from pathlib import Path
import subprocess
import time
from fractions import Fraction

from .campaign import atomic_json, digest
from ..vla.data_three_table_single_tray import PROFILE, RULE_REVISION

SCHEMA='airport_three_table_workflow_options/1'


WATCHER_TERMINAL_STAGES=('data_only_v2_verified_complete','data_only_watch_contract_or_fault_budget_blocked')


def terminal_training_status(value):
    return (value.get('stage') in ('failed_preserving_sources_and_checkpoints',
            'preflight_contract_failed_preserving_sources_and_checkpoints','blocked_frozen_batch_media_case')
            or value.get('stage')=='waiting_missing_qualified_media_split' and value.get('source_campaign_closed') is True)


def dataset_watcher_argv(options):
    watcher=options['data_version2_watcher']
    if digest(watcher['options'])!=watcher['options_sha256']:raise ValueError('registered_data_version2_watcher_options_changed')
    return [options['vla_python'],str(Path(options['release'])/'scripts/watch_three_table_data_version2.py'),
            '--options',watcher['options'],'--training-run',watcher['training_run'],'--watch-dir',watcher['watch_dir']]


def reusable_campaign_proof(options):
    receipt=options.get('reusable_campaign')
    if not receipt:return None
    required=('campaign_dir','status_sha256','prior_workflow_options','prior_workflow_options_sha256',
              'process_exit_receipt','process_exit_receipt_sha256')
    if any(not isinstance(receipt.get(k),str) or not receipt[k] for k in required):
        raise ValueError('hash_bound_prior_campaign_receipt_required')
    campaign=Path(receipt['campaign_dir']).resolve()
    if campaign!=Path(options['campaign_dir']).resolve():raise ValueError('reused_campaign_pointer_changed')
    for path,sha in ((campaign/'status.json',receipt['status_sha256']),
                     (receipt['prior_workflow_options'],receipt['prior_workflow_options_sha256']),
                     (receipt['process_exit_receipt'],receipt['process_exit_receipt_sha256'])):
        if digest(path)!=sha:raise ValueError('reused_campaign_evidence_changed')
    prior=json.loads(Path(receipt['prior_workflow_options']).read_text())
    exit_receipt=json.loads(Path(receipt['process_exit_receipt']).read_text())
    status=json.loads((campaign/'status.json').read_text())
    if Path(prior['campaign_dir']).resolve()!=campaign or exit_receipt.get('returncode')!=0 or exit_receipt.get('exited') is not True:
        raise ValueError('prior_campaign_actual_exit_zero_required')
    if status.get('completed')!=status.get('selected') or not status.get('results') or any(r.get('returncode')!=0 for r in status['results']):
        raise ValueError('prior_campaign_closed_all_actual_children_required')
    return receipt


def validate_adopted_continuation(options):
    adoption=options.get('adopt_children',{}).get('source_campaign_v2')
    if not adoption:return None
    if set(options.get('adopt_children',{}))-{'source_campaign_v2','source_v2_dataset_watcher'}:raise ValueError('only_registered_source_continuation_adoption_allowed')
    required=('pid','start_ticks','argv','cwd','log','prior_workflow_options','prior_workflow_options_sha256','source_plan','source_plan_sha256','selection_sha256')
    if any(k not in adoption for k in required) or type(adoption['pid']) is not int or not adoption['start_ticks']:raise ValueError('full_source_coordinator_adoption_identity_required')
    priorpath=Path(adoption['prior_workflow_options'])
    if digest(priorpath)!=adoption['prior_workflow_options_sha256'] or digest(adoption['source_plan'])!=adoption['source_plan_sha256']:
        raise ValueError('adopted_source_prior_identity_changed')
    prior=json.loads(priorpath.read_text());continuation=options['continuation'];old=prior['continuation']
    if Path(continuation['campaign_dir']).resolve()!=Path(old['campaign_dir']).resolve() or Path(adoption['source_plan']).resolve()!=Path(old['campaign_dir']).resolve()/'plan.json' or digest(continuation['selection'])!=adoption['selection_sha256'] or digest(old['selection'])!=adoption['selection_sha256']:
        raise ValueError('exact_prior_continuation_plan_selection_required')
    expected=campaign_argv(dict(prior,**old))
    if adoption['argv']!=expected or Path(adoption['cwd']).resolve()!=Path(prior['release']).resolve():raise ValueError('reviewed_prior_source_command_changed')
    checked_process(adoption)
    return adoption


def validate_adopted_data_watcher(options):
    adoption=options.get('adopt_children',{}).get('source_v2_dataset_watcher')
    if not adoption:return None
    required=('pid','start_ticks','argv','cwd','log','prior_workflow_options','prior_workflow_options_sha256',
              'command_options','command_options_sha256','command_output','actual_command_argv')
    if any(k not in adoption for k in required) or type(adoption['pid']) is not int or not adoption['start_ticks']:
        raise ValueError('full_data_watcher_wrapper_adoption_required')
    priorpath=Path(adoption['prior_workflow_options'])
    if digest(priorpath)!=adoption['prior_workflow_options_sha256'] or digest(adoption['command_options'])!=adoption['command_options_sha256']:
        raise ValueError('adopted_data_watcher_binding_changed')
    prior=json.loads(priorpath.read_text());root=Path(prior['workflow_dir']).resolve()
    if options.get('data_version2_watcher')!=prior.get('data_version2_watcher') or not options.get('data_version2_watcher'):
        raise ValueError('immutable_prior_data_watcher_configuration_required')
    command=json.loads(Path(adoption['command_options']).read_text());expected=dataset_watcher_argv(prior)
    wrapper=[prior['vla_python'],str(Path(prior['release'])/'scripts/run_three_table_owned_command.py'),
             '--options',adoption['command_options']]
    if adoption['argv']!=wrapper or adoption['actual_command_argv']!=expected or command.get('schema')!='airport_three_table_owned_command/1' or command.get('argv')!=expected or Path(command['output']).resolve()!=Path(adoption['command_output']).resolve() or Path(command['cwd']).resolve()!=Path(prior['release']).resolve() or Path(adoption['cwd']).resolve()!=Path(prior['release']).resolve():
        raise ValueError('registered_prior_data_watcher_command_required')
    if any(not Path(adoption[k]).resolve().is_relative_to(root) for k in ('command_options','command_output')):
        raise ValueError('prior_data_watcher_receipt_scope_required')
    if not checked_process(adoption):
        evidence=adoption.get('closed_data2_evidence',{})
        for key in ('exit','watcher_status','pipeline_status'):
            if not isinstance(evidence.get(key),str) or digest(evidence[key])!=evidence.get(key+'_sha256'):
                raise ValueError('closed_data2_actual_artifact_binding_required')
        data=json.loads(Path(prior['data_version2_watcher']['options']).read_text())
        expected_paths=dict(exit=Path(adoption['command_output'])/'exit.json',
                            watcher_status=Path(prior['data_version2_watcher']['watch_dir'])/'status.json',
                            pipeline_status=Path(data['run_dir'])/'pipeline_status.json')
        if any(Path(evidence[k]).resolve()!=p.resolve() for k,p in expected_paths.items()):raise ValueError('closed_data2_original_artifact_scope_required')
        exited=json.loads(Path(evidence['exit']).read_text());watch=json.loads(Path(evidence['watcher_status']).read_text());pipeline=json.loads(Path(evidence['pipeline_status']).read_text())
        identity=exited.get('wrapper_identity',{})
        if exited.get('actual_exit_observed') is not True or type(exited.get('returncode')) is not int or exited['returncode']!=evidence.get('actual_returncode') or exited.get('options_sha256')!=adoption['command_options_sha256'] or any(identity.get(k)!=adoption[k] for k in ('pid','start_ticks','argv','cwd')):
            raise ValueError('closed_data2_actual_exit_identity_required')
        if watch.get('stage') not in WATCHER_TERMINAL_STAGES or pipeline.get('stage')!='data_only_exports_verified_no_training' or pipeline.get('dataset_ready') is not True or pipeline.get('training_started') is not False or set(pipeline.get('verified_splits',[]))!={'train','val','test'}:
            raise ValueError('closed_data2_independent_verified_exports_required')
    return adoption


def process_identity(pid):
    path=Path('/proc')/str(pid)
    try:
        stat=(path/'stat').read_text();state=stat[stat.rfind(')')+2:].split()[0]
        if state=='Z':return None
        argv=[x.decode() for x in (path/'cmdline').read_bytes().split(b'\0') if x]
        return dict(pid=pid,argv=argv,cwd=str((path/'cwd').resolve()),start_ticks=stat[stat.rfind(')')+2:].split()[19])
    except (FileNotFoundError,ProcessLookupError):return None


def checked_process(job,probe=process_identity):
    if not job.get('pid'):return None
    actual=probe(job['pid'])
    if actual is None:return None
    if actual['argv']!=job['argv'] or Path(actual['cwd']).resolve()!=Path(job['cwd']).resolve() or (job.get('start_ticks') and job['start_ticks']!=actual['start_ticks']):
        raise ValueError('owned_process_identity_changed_no_signal_or_duplicate')
    return actual


def demo_gate(candidate,probe=process_identity):
    """Never repeat a healthy process, or accept an old-task/partial result."""
    if checked_process(candidate,probe):return dict(status='running',task_completed=False)
    result_path=Path(candidate['result'])
    if not result_path.is_file():return dict(status='missing_result',task_completed=False)
    scene=json.loads(Path(candidate['scene']).read_text());result=json.loads(result_path.read_text())
    if scene.get('task_profile')!=PROFILE or scene.get('task_rule_revision')!=RULE_REVISION:
        raise ValueError('new_three_table_demo_scope_required')
    if candidate.get('scene_sha256') and digest(candidate['scene'])!=candidate['scene_sha256']:
        raise ValueError('reviewed_demo_scene_changed')
    continuation=result.get('loaded_continuation',{})
    complete=(result.get('schema')=='airport_three_table_full_motion_candidate/1' and
              all(result.get(k) is True for k in ('task_completed','empty_pick_completed','empty_place_completed')) and
              continuation.get('push_loaded_completed') is True and continuation.get('actual_handover_verified') is True)
    return dict(status='complete' if complete else 'failed',task_completed=complete,
                result=str(result_path.resolve()),result_sha256=digest(result_path),
                error=result.get('error_code'),frames=result.get('recorded_frames'))


def validate_options(options):
    if options.get('schema')!=SCHEMA:raise ValueError('explicit_reviewed_three_table_workflow_options_required')
    if set(options.get('adopt_children',{}))-{'source_campaign_v2','source_v2_dataset_watcher'}:raise ValueError('only_registered_source_children_may_be_adopted')
    required=('workflow_dir','release','sim_python','vla_python','selection','inventory','parent_manifest',
              'split_registry','campaign_dir','config','push_reference_scene','training_options')
    if any(not isinstance(options.get(k),str) or not options[k] for k in required):raise ValueError('workflow_paths_required')
    root=Path(options['workflow_dir']).resolve()
    if not Path(options['campaign_dir']).resolve().is_relative_to(root) and not reusable_campaign_proof(options):raise ValueError('new_campaign_must_be_inside_workflow')
    candidates=options.get('demo_candidates')
    if not isinstance(candidates,list) or not 1<=len(candidates)<=3:raise ValueError('bounded_one_to_three_reviewed_demo_candidates_required')
    for row in candidates:
        if any(not isinstance(row.get(k),str) for k in ('scene','result','cwd')):raise ValueError('explicit_demo_identity_required')
        if row.get('pid') is not None and (type(row['pid']) is not int or row['pid']<=0):raise ValueError('actual_demo_pid_required')
        if row.get('pid') or row.get('launch_if_absent'):
            if not isinstance(row.get('argv'),list) or not row['argv']:raise ValueError('reviewed_demo_argv_required')
        if row.get('launch_if_absent') and not row.get('new_output'):raise ValueError('new_output_for_reviewed_retry_required')
    train=json.loads(Path(options['training_options']).read_text())
    if Path(train['campaign']).resolve()!=Path(options['campaign_dir']).resolve():raise ValueError('training_campaign_pointer_changed')
    if Path(train['release']).resolve()!=Path(options['release']).resolve():raise ValueError('training_release_pointer_changed')
    if options.get('reusable_campaign') and not train.get('certified_source_catalog'):raise ValueError('independent_certified_source_catalog_required')
    continuation=options.get('continuation')
    if continuation:
        adopted=validate_adopted_continuation(options)
        if (not Path(continuation['campaign_dir']).resolve().is_relative_to(root) and not adopted) or Path(continuation['campaign_dir']).resolve()==Path(options['campaign_dir']).resolve():
            raise ValueError('fresh_independent_continuation_campaign_required')
        if digest(continuation['selection'])!=continuation['selection_sha256']:raise ValueError('continuation_selection_changed')
        from .campaign import build_plan
        build_plan(json.loads(Path(continuation['selection']).read_text()),options['inventory'],options['parent_manifest'],options['split_registry'])
        if continuation.get('dataset_only_options'):
            settings=Path(continuation['dataset_only_options'])
            if digest(settings)!=continuation.get('dataset_only_options_sha256'):raise ValueError('version2_data_only_options_changed')
            data=json.loads(settings.read_text())
            if data.get('data_only') is not True or data.get('data_version')!='v2' or Path(data['campaign']).resolve()!=Path(continuation['campaign_dir']).resolve():raise ValueError('independent_version2_data_only_contract_required')
    for key in ('release_freeze','training_options','selection'):
        if key in options and options.get(key+'_sha256') and digest(options[key])!=options[key+'_sha256']:
            raise ValueError('reviewed_workflow_input_changed:'+key)
    watcher=options.get('data_version2_watcher')
    if watcher:
        if options.get('continuation',{}).get('dataset_only_options'):raise ValueError('only_one_version2_data_launcher_allowed')
        if any(not isinstance(watcher.get(k),str) or not watcher[k] for k in ('options','options_sha256','training_run','watch_dir')):raise ValueError('registered_data_watcher_identity_required')
        adopted=validate_adopted_data_watcher(options)
        if (not Path(watcher['watch_dir']).resolve().is_relative_to(root) or Path(watcher['training_run']).resolve()!=Path(train['run_dir']).resolve()) and not adopted:raise ValueError('watcher_registered_run_scope_required')
        dataset_watcher_argv(options)
        data=json.loads(Path(watcher['options']).read_text())
        if data.get('data_only') is not True or data.get('data_version')!='v2':raise ValueError('independent_data_only_watcher_required')
    return options


def campaign_argv(options):
    release=Path(options['release'])
    argv=[options['sim_python'],str(release/'scripts/collect_three_table_campaign.py'),
          '--selection',options['selection'],'--inventory',options['inventory'],
          '--parent-manifest',options['parent_manifest'],'--split-registry',options['split_registry'],
          '--output',options['campaign_dir'],'--release',str(release),'--sim-python',options['sim_python'],
          '--config',options['config'],'--push-reference-scene',options['push_reference_scene'],
          '--workers',str(options.get('source_workers',3)),'--execute']
    if options.get('scene_options'):argv.extend(['--scene-options',options['scene_options']])
    return argv


def publish_demo_native(output,proof):
    """Actual diagnostic media closure; never a training-source qualification."""
    output=Path(output);manifest_path=output/'manifest.json'
    m=json.loads(manifest_path.read_text())
    if m.get('task_profile')!=PROFILE or m.get('terminal_checked') is not True or len(m.get('errors',{}))!=6 or any(v>1e-7 for v in m['errors'].values()) or m.get('initial_restore_count')!=1 or m.get('pose_resets_during_replay')!=0:
        raise ValueError('continuous_demo_native_replay_not_verified')
    files=m['source_files'];source_hashes=m['source_sha256']
    if any(digest(path)!=source_hashes[key] for key,path in files.items()):raise ValueError('native_demo_source_changed')
    if digest(proof['result'])!=proof['result_sha256']:raise ValueError('verified_demo_result_changed')
    shapes={'head_left':(1920,1536),'head_right':(1920,1536),'left_wrist':(1280,720),'right_wrist':(1280,720)}
    videos=[]
    for camera,(width,height) in shapes.items():
        path=output/(camera+'.mp4')
        stream=json.loads(subprocess.check_output(['ffprobe','-v','error','-count_frames','-select_streams','v:0',
            '-show_entries','stream=width,height,r_frame_rate,nb_read_frames','-of','json',str(path)],text=True))['streams'][0]
        if (stream['width'],stream['height'])!=(width,height) or Fraction(stream['r_frame_rate'])!=20 or int(stream['nb_read_frames'])!=m['frames']:
            raise ValueError('actual_full_native_four_camera_contract_required')
        videos.append(dict(camera=camera,path=str(path.resolve()),sha256=digest(path),header=stream))
    receipt=dict(schema='airport_three_table_workflow_demo_native_closure/1',verified=True,
                 demo_task_completed=proof['task_completed'],demo_result=proof['result'],demo_result_sha256=proof['result_sha256'],
                 source_manifest_sha256=digest(manifest_path),frames=m['frames'],six_errors=m['errors'],
                 videos=videos,diagnostic_media_only=True,training_eligible=False)
    atomic_json(output/'video_closure.json',receipt)
    (output/'VIDEO_PATHS.txt').write_text(''.join(row['path']+'\n' for row in videos))
    cards=''.join('<p>'+html.escape(row['camera'])+'</p><video controls preload="metadata" width="480" src="'+row['camera']+'.mp4"></video>' for row in videos)
    (output/'viewer.html').write_text('<!doctype html><meta charset="utf-8"><title>Three-table complete demo</title><h1>Actual demo replay</h1><p>Diagnostic media, not a training dataset.</p>'+cards)
    receipt['viewer']=str((output/'viewer.html').resolve());return receipt


def reusable_native_proof(options,proof):
    reuse=options.get('reusable_demo_native')
    if not reuse:return None
    output=Path(reuse['output']);path=output/'video_closure.json'
    if digest(path)!=reuse['closure_sha256']:raise ValueError('prior_native_closure_changed')
    receipt=json.loads(path.read_text())
    if receipt.get('verified') is not True or receipt.get('demo_result_sha256')!=proof['result_sha256'] or len(receipt.get('videos',[]))!=4:
        raise ValueError('prior_native_actual_same_demo_required')
    if digest(output/'manifest.json')!=receipt['source_manifest_sha256']:raise ValueError('prior_native_manifest_changed')
    if any(digest(row['path'])!=row['sha256'] for row in receipt['videos']):raise ValueError('prior_native_video_changed')
    return receipt


def supervise(options_path,*,recover=False,poll_seconds=10):
    """Bootstrap may exec this in its existing directory/PID/session."""
    options_path=Path(options_path).resolve();options=validate_options(json.loads(options_path.read_text()))
    root=Path(options['workflow_dir']).resolve();root.mkdir(parents=True,exist_ok=True)
    import fcntl
    lock=(root/'workflow.lock').open('a+');fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
    path=root/'workflow_status.json';option_sha=digest(options_path)
    if path.exists():
        state=json.loads(path.read_text())
        if not recover or state.get('options_sha256')!=option_sha:raise ValueError('unchanged_explicit_workflow_recovery_required')
    else:state=dict(schema='airport_three_table_durable_workflow/1',options_sha256=option_sha,
                    task_profile=PROFILE,children={},demo_results=[],training_started=False)
    for key,adoption in options.get('adopt_children',{}).items():
        if key not in state['children']:
            state['children'][key]=dict(adoption,adopted_prior_healthy_coordinator=True,exit_status_not_invented=True)
    state.update(pid=os.getpid(),session_id=os.getsid(0),training_status='waiting_for_data')
    handles={}
    def status(phase,**extra):
        state.update(phase=phase,updated_unix=time.time(),**extra);atomic_json(path,state)
    def start(key,argv,cwd,extra_env=None):
        existing=state['children'].get(key)
        if existing:
            if checked_process(existing):return existing
            # A closed child is not silently retried into its old source output.
            return existing
        log=root/(key+'.log')
        original_argv=list(argv);command_output=None;command_options=None
        if options.get('durable_child_exit_receipts') is True:
            attempt=len(state.get('process_faults',{}).get(key,[]))
            command_output=root/f'{key}_owned_attempt_{attempt:02d}'
            command_options=root/f'{key}_command_attempt_{attempt:02d}.json'
            atomic_json(command_options,dict(schema='airport_three_table_owned_command/1',argv=original_argv,
                        cwd=str(Path(cwd).resolve()),output=str(command_output),environment=extra_env or {}))
            argv=[original_argv[0],str(Path(options['release'])/'scripts/run_three_table_owned_command.py'),
                  '--options',str(command_options)]
        with log.open('xb') as stream:
            env=dict(os.environ,CUDA_VISIBLE_DEVICES='',OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1')
            env.update(extra_env or {})
            proc=subprocess.Popen(argv,cwd=cwd,env=env,stdin=subprocess.DEVNULL,stdout=stream,
                                  stderr=subprocess.STDOUT,start_new_session=True)
        handles[key]=proc;job=dict(pid=proc.pid,argv=argv,cwd=str(Path(cwd).resolve()),log=str(log))
        if command_output:job.update(actual_command_argv=original_argv,command_output=str(command_output),command_options=str(command_options))
        actual=process_identity(proc.pid)
        if actual:job['start_ticks']=actual['start_ticks']
        state['children'][key]=job;atomic_json(root/(key+'_process.json'),job);return job
    def recover_waiter():
        job=state['children']['training_waiter']
        if not job.get('exited'):return False
        training_options=json.loads(Path(options['training_options']).read_text())
        pipeline=Path(training_options['run_dir'])/'pipeline_status.json'
        actual=json.loads(pipeline.read_text()) if pipeline.exists() else {}
        if job.get('returncode')==0:return False
        # A failed physical evaluation or terminal dataset rejection is not an
        # operating-system process fault and cannot become an automatic retry.
        if terminal_training_status(actual) or actual.get('stage') in ('failed','blocked_evaluation','completed','complete'):
            return False
        faults=state.setdefault('process_faults',{}).setdefault('training_waiter',[])
        if len(faults)>=3:
            state['last_error']='training_waiter_process_fault_limit_exhausted';return False
        due=job.setdefault('recovery_after_unix',time.time()+(10,30,90)[len(faults)])
        if time.time()<due:return True
        faults.append(dict(prior_job=dict(job),restart_unix=time.time(),exit_observed='returncode' in job))
        state['children'].pop('training_waiter');handles.pop('training_waiter',None)
        argv=[options['vla_python'],str(release/'scripts/supervise_three_table_single_tray_training.py'),
              '--options',options['training_options'],'--recover']
        # Preserve every original attempt log and exit proof.
        oldlog=root/'training_waiter.log'
        if oldlog.exists():os.replace(oldlog,root/('training_waiter_attempt_'+str(len(faults))+'.log'))
        start('training_waiter',argv,str(release));return True
    def refresh_children():
        for key,job in state['children'].items():
            if key in handles:
                code=handles[key].poll()
                if code is not None:
                    job['returncode']=code;job['exited']=True;atomic_json(root/(key+'_exit.json'),job)
            elif not checked_process(job):
                if job.get('command_output'):
                    from .owned_command import command_state
                    actual=command_state(job['command_output'],job['command_options'])
                    if actual['stage']=='closed':job.update(returncode=actual['returncode'],exited=True,actual_exit_proof=actual)
                    elif actual['stage'] in ('running_wrapper','running_orphan_child_without_wrapper'):continue
                    else:job.update(exited=True,exit_status_unobserved=True)
                else:job.update(exited=True,exit_status_unobserved=True)
    def retry_process(key,argv,cwd,extra_env=None):
        job=state['children'][key]
        if not job.get('exited'):return False
        faults=state.setdefault('process_faults',{}).setdefault(key,[])
        if len(faults)>=3:
            state.setdefault('blocked_process_faults',{})[key]='three_process_attempts_exhausted';return False
        due=job.setdefault('recovery_after_unix',time.time()+(10,30,90)[len(faults)])
        if time.time()<due:return True
        faults.append(dict(prior_job=dict(job),restart_unix=time.time()))
        state['children'].pop(key);handles.pop(key,None)
        oldlog=root/(key+'.log')
        if oldlog.exists():os.replace(oldlog,root/(key+'_attempt_'+str(len(faults))+'.log'))
        start(key,argv,cwd,extra_env);return True
    status('demo',training_status='waiting_for_data')
    while True:
        complete=None;demo_rows=[]
        for index,candidate in enumerate(options['demo_candidates']):
            key='reviewed_demo_'+str(index);job=state['children'].get(key)
            descriptor=dict(candidate,**job) if job else candidate
            proof=demo_gate(descriptor);demo_rows.append(proof)
            if proof['task_completed']:complete=proof;break
            if proof['status']=='running':break
            if proof['status']=='missing_result' and candidate.get('launch_if_absent') and not job:
                if Path(candidate['new_output']).exists():raise ValueError('refuse_existing_demo_output_no_duplicate')
                start(key,candidate['argv'],candidate['cwd']);break
        if complete:status('demo_complete',demo_results=demo_rows,demo_proof=complete);break
        refresh_children();status('demo' if any(r['status']=='running' for r in demo_rows) else 'blocked_demo_requires_reviewed_recipe',
                                  demo_results=demo_rows,training_status='waiting_for_data')
        time.sleep(poll_seconds)
    release=Path(options['release'])
    native=Path(state.get('demo_native_active_output',options.get('demo_native_output',root/'demo_native_v1')))
    reused_native=reusable_native_proof(options,state['demo_proof'])
    if reused_native:state['demo_native_proof']=reused_native
    if not native.resolve().is_relative_to(root):raise ValueError('new_demo_native_output_inside_workflow_required')
    demo_case=Path(options['demo_candidates'][len(state['demo_results'])-1]['scene']).parent.parent
    if not reused_native and 'demo_native' not in state['children'] and native.exists():raise ValueError('refuse_existing_native_output_no_duplicate')
    if not reused_native:start('demo_native',[options['sim_python'],str(release/'scripts/render_three_table_original_trace.py'),
                       '--case',str(demo_case),'--output',str(native)],str(release),
          dict(CUDA_VISIBLE_DEVICES=options.get('demo_render_gpu_uuid','GPU-97ac5ae8-1b03-fdf8-fca5-d1192c8fe27d'),
               MUJOCO_GL='egl',MUJOCO_EGL_DEVICE_ID=str(options.get('demo_render_egl_device',1))))
    start('training_waiter',[options['vla_python'],str(release/'scripts/supervise_three_table_single_tray_training.py'),
                            '--options',options['training_options']],str(release))
    reused_campaign=reusable_campaign_proof(options)
    if reused_campaign:state['reusable_campaign_proof']=reused_campaign
    else:start('source_campaign',campaign_argv(options),str(release))
    if options.get('continuation'):
        continuation=dict(options,**options['continuation'])
        start('source_campaign_v2',campaign_argv(continuation),str(release))
        if continuation.get('dataset_only_options'):
            start('source_v2_dataset_waiter',[options['vla_python'],str(release/'scripts/supervise_three_table_single_tray_training.py'),
                 '--options',continuation['dataset_only_options'],'--data-only'],str(release))
    if options.get('data_version2_watcher'):
        start('source_v2_dataset_watcher',dataset_watcher_argv(options),str(release))
    while True:
        refresh_children();campaign=Path(options['campaign_dir'])/'status.json'
        counts=json.loads(campaign.read_text()) if campaign.exists() else None
        train_options=json.loads(Path(options['training_options']).read_text())
        training_path=Path(train_options['run_dir'])/'pipeline_status.json'
        training=json.loads(training_path.read_text()) if training_path.exists() else None
        native_receipt=state.get('demo_native_proof')
        native_job=state['children'].get('demo_native',{})
        if native_job.get('exited') and native_receipt is None:
            try:
                if native_job.get('returncode')!=0:raise ValueError('owned_demo_renderer_failed_or_exit_unobserved')
                native_receipt=publish_demo_native(native,state['demo_proof']);state['demo_native_proof']=native_receipt
            except Exception as error:
                state['demo_native_error']=repr(error)
                attempt=len(state.get('process_faults',{}).get('demo_native',[]))+1
                fresh=root/f'demo_native_process_attempt_{attempt:02d}'
                retry_process('demo_native',[options['sim_python'],str(release/'scripts/render_three_table_original_trace.py'),
                    '--case',str(demo_case),'--output',str(fresh)],str(release),
                    dict(CUDA_VISIBLE_DEVICES=options.get('demo_render_gpu_uuid','GPU-97ac5ae8-1b03-fdf8-fca5-d1192c8fe27d'),MUJOCO_GL='egl',MUJOCO_EGL_DEVICE_ID=str(options.get('demo_render_egl_device',1))))
                if state['children']['demo_native'] is not native_job:
                    native=fresh;state['demo_native_active_output']=str(fresh)
        for key,setting in (('source_campaign',options),('source_campaign_v2',dict(options,**options.get('continuation',{})))):
            job=state['children'].get(key)
            if job and job.get('exited'):
                producer=Path(setting['campaign_dir'])/'status.json'
                producer_status=json.loads(producer.read_text()) if producer.exists() else {}
                if producer_status.get('stage')!='physical_candidates_complete':
                    if job.get('adopted_prior_healthy_coordinator'):
                        state.setdefault('blocked_process_faults',{})[key]='prior_coordinator_exit_incomplete_requires_reviewed_recovery_protocol';continue
                    argv=campaign_argv(setting)
                    if Path(setting['campaign_dir']).exists():argv.append('--recover')
                    retry_process(key,argv,str(release))
        watcher_status=None
        if options.get('data_version2_watcher'):
            watcher_path=Path(options['data_version2_watcher']['watch_dir'])/'status.json'
            watcher_status=json.loads(watcher_path.read_text()) if watcher_path.exists() else {}
            watcher_job=state['children']['source_v2_dataset_watcher']
            if watcher_job.get('exited') and watcher_status.get('stage') not in WATCHER_TERMINAL_STAGES:
                retry_process('source_v2_dataset_watcher',dataset_watcher_argv(options),str(release))
        status('source_and_training_pipeline',source_status=counts,training_pipeline_status=training,
               demo_native_proof=native_receipt,
               data_version2_watcher_status=watcher_status,
               training_status=(training or {}).get('stage','waiting_for_data'),
               training_started=(training or {}).get('training_started',False))
        if state['children'].get('source_campaign',{}).get('exited') and not counts:
            status('blocked_source_producer_failure',training_status='waiting_for_data')
        if state['children']['training_waiter'].get('exited'):
            if recover_waiter():
                status('training_waiter_process_fault_backoff_or_recovered',training_status=(training or {}).get('stage','waiting_for_data'))
                time.sleep(poll_seconds);continue
            if options.get('data_version2_watcher'):
                watcher_job=state['children']['source_v2_dataset_watcher']
                if not watcher_job.get('exited') or (watcher_status or {}).get('stage') not in WATCHER_TERMINAL_STAGES and 'source_v2_dataset_watcher' not in state.get('blocked_process_faults',{}):
                    status('main_pipeline_exited_supervising_data_version2_watcher',training_status=(training or {}).get('stage','failed_missing_status'),data_version2_watcher_status=watcher_status)
                    time.sleep(poll_seconds);continue
            status('training_pipeline_exited_review_status',training_status=(training or {}).get('stage','failed_missing_status'))
            return state
        time.sleep(poll_seconds)
