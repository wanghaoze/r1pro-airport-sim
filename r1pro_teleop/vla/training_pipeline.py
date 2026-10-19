"""Durable process orchestration for complete-data BC and immutable evaluations."""
from pathlib import Path
import hashlib,json,os,signal,subprocess,time

EXPECTED_SPLITS={'train':149,'val':22,'test':22}
MILESTONES=(10,100,1000,10000,100000)
GPU_UUIDS=('GPU-97ac5ae8-1b03-fdf8-fca5-d1192c8fe27d','GPU-c8e2826c-b460-18ba-dab5-ccd8c1da8b6c')

def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        while chunk:=stream.read(8*1024*1024):h.update(chunk)
    return h.hexdigest()

def read(path):return json.loads(Path(path).read_text())

def write_atomic(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_suffix(path.suffix+'.tmp');temporary.write_text(json.dumps(value,indent=2));temporary.replace(path)

def source_gate(source_root):
    """A native replay alone never proves a train-ready dataset."""
    source_root=Path(source_root);proofs=[]
    for split,count in EXPECTED_SPLITS.items():
        folder=source_root/('action8_export_'+split+'_parallel_v2');status_path=folder/'status.json'
        if not status_path.exists():return None
        status=read(status_path)
        if status.get('stage')=='failed':raise ValueError('source_export_failed:'+split)
        if status.get('stage')!='complete' or status.get('dataset_ready') is not True:return None
        if status.get('expected_scenes')!=count or status.get('completed_scenes')!=count:raise ValueError('completed_source_scene_count_changed')
        manifest_path=folder/'dataset/airport_training_manifest.json'
        if not manifest_path.exists():raise ValueError('publisher_complete_without_dataset_manifest')
        manifest=read(manifest_path);ids=set(manifest.get('complete_expected_scene_ids',[]));actual={e['scene_id'] for e in manifest['episodes']}
        if (manifest.get('dataset_ready') is not True or manifest.get('split')!=split or manifest.get('repo_id')!='airport/task_complete_action8_'+split+'_v2' or manifest.get('prompt_mode')!='task_complete_action8_v1' or ids!=actual or len(ids)!=count or any(e['split']!=split for e in manifest['episodes']) or not manifest.get('all_parquet_values_verified',{}).get('verified')):raise ValueError('final_split_semantics_or_official_audit_changed')
        if digest(manifest['source_manifest'])!=manifest['source_manifest_sha256']:raise ValueError('published_source_manifest_changed')
        proofs.append(dict(split=split,scene_ids=sorted(ids),training_manifest=str(manifest_path),training_manifest_sha256=digest(manifest_path),source_manifest_sha256=manifest['source_manifest_sha256']))
    sets=[set(proof['scene_ids']) for proof in proofs]
    if any(sets[i]&sets[j] for i in range(3) for j in range(i)):raise ValueError('scene_split_leakage')
    receipt=source_root/'native_parallel_exit_receipt.json'
    if not receipt.exists():return None
    native=read(receipt)
    if native.get('schema')!='airport_native_producer_exit/1' or native.get('returncode')!=0 or native.get('source_native_verified') is not True or native.get('selected')!=193 or native.get('completed_scene_count')!=193 or native.get('reference_count')!=772 or native.get('active_owned_renderers')!=[]:raise ValueError('native_producer_not_closed_and_verified')
    if digest(native['status_path'])!=native['status_sha256'] or digest(source_root/'native_references_current.json')!=native['references_sha256']:raise ValueError('native_exit_publisher_files_changed')
    native_status=read(native['status_path'])
    if native_status.get('status')!='complete' or native_status.get('selected')!=193 or native_status.get('completed_scene_count')!=193:raise ValueError('native_source_status_not_complete')
    if len(read(source_root/'native_references_current.json'))!=772:raise ValueError('native_reference_list_not_complete')
    return dict(splits=proofs,native_exit_receipt=str(receipt),native_exit_receipt_sha256=digest(receipt))


def evaluation_script(options):
    mode=options.get('evaluation_mode','serial')
    if mode=='serial':return 'evaluate_action8_checkpoint.py'
    if mode=='dual_static_two_gpu':
        if options.get('gpu1_uuid')!=GPU_UUIDS[1]:raise ValueError('dual_evaluation_gpu_identity_changed')
        return 'evaluate_action8_checkpoint_dual.py'
    raise ValueError('unsupported_evaluation_mode')


def runtime_gate(options):
    release=Path(options['runtime_release']);report=Path(options['runtime_core_report'])
    if not (release/'scripts'/evaluation_script(options)).is_file() or not report.is_file():return None
    core=read(report)
    if core.get('returncode')!=0:raise ValueError('runtime_core_not_verified')
    if options.get('runtime_core_report_sha256') and digest(report)!=options['runtime_core_report_sha256']:raise ValueError('runtime_core_report_changed')
    return dict(runtime_release=str(release),core_report=str(report),core_report_sha256=digest(report))

def verify_owned(child,argv,cwd):
    """Natural-exit races are reaped; a live mismatched owner is never signaled."""
    if child.poll() is not None:return False
    proc=Path('/proc')/str(child.pid)
    try:
        actual=(proc/'cmdline').read_bytes().rstrip(b'\0').split(b'\0')
        actual=[value.decode() for value in actual]
        actual_cwd=(proc/'cwd').resolve(strict=True)
    except (FileNotFoundError,ProcessLookupError):
        try:child.wait(timeout=.2);return False
        except subprocess.TimeoutExpired:raise ValueError('live_process_identity_could_not_be_verified')
    if actual!=argv or actual_cwd!=Path(cwd).resolve():
        if child.poll() is not None:return False
        # /proc/cmdline can become empty slightly before waitpid observes exit.
        # Only the actual Popen child exit can resolve this; never infer exit
        # from an empty argv, and never signal a live/reused mismatched PID.
        try:child.wait(timeout=.2);return False
        except subprocess.TimeoutExpired:pass
        raise ValueError('live_owned_process_identity_changed:'+repr(dict(actual_argv=actual,expected_argv=argv,actual_cwd=str(actual_cwd),expected_cwd=str(Path(cwd).resolve()))))
    return True

def wait_owned_startup(child,argv,cwd,*,timeout_seconds=5,poll_seconds=.02):
    """Bounded first-exec handshake, never permission to signal a mismatch.

    Once a matching identity is seen, later checks remain strict. An already
    exited child is reaped by run_owned and its return code still must be zero.
    """
    started=time.monotonic();retries=0;last_error=None
    while True:
        try:
            verified=verify_owned(child,argv,cwd)
            return dict(verified=verified,retry_count=retries,elapsed_seconds=time.monotonic()-started,last_transient_error=last_error)
        except ValueError as error:
            if child.poll() is not None:
                return dict(verified=False,retry_count=retries,elapsed_seconds=time.monotonic()-started,last_transient_error=repr(error))
            last_error=repr(error);retries+=1
            if time.monotonic()-started>=timeout_seconds:
                raise ValueError('owned_startup_identity_not_verified:'+last_error) from error
            time.sleep(poll_seconds)


def classify_progress(previous,current,seconds_since):
    if current.get('actual_completed_updates') is not None and current['actual_completed_updates']>(previous.get('actual_completed_updates') or 0):return 'training_updates',0.
    if current.get('completed_frames',0)>previous.get('completed_frames',0) or current.get('log_bytes',0)>previous.get('log_bytes',0):return 'artifact_progress',0.
    if current.get('cpu_ticks',0)>previous.get('cpu_ticks',0):return 'cpu_active_planning_or_compute',0.
    return 'no_observed_progress',seconds_since

def run_owned(argv,cwd,env,log_path,*,deadline_hours=240,on_started=None,on_progress=None):
    log_path=Path(log_path)
    with log_path.open('x') as log:
        child=subprocess.Popen(argv,cwd=cwd,env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
    started=time.monotonic();gpu_receipts=[];last_progress={};last_observed_progress=started
    startup_receipt=dict(pid=child.pid,argv=argv,cwd=str(cwd),status='spawned_awaiting_identity')
    startup_path=log_path.with_suffix('.startup.json');write_atomic(startup_path,startup_receipt)
    identity_verified=False
    try:
        startup_receipt.update(wait_owned_startup(child,argv,cwd))
        identity_verified=startup_receipt['verified']
        startup_receipt['status']='identity_verified' if identity_verified else 'already_exited_before_first_check'
        write_atomic(startup_path,startup_receipt)
        if on_started is not None and identity_verified:on_started(dict(startup_receipt))
        while child.poll() is None:
            verify_owned(child,argv,cwd)
            if time.monotonic()-started>deadline_hours*3600:
                if verify_owned(child,argv,cwd):os.killpg(child.pid,signal.SIGTERM)
                child.wait(timeout=30);raise TimeoutError('owned_process_resource_deadline')
            rows=subprocess.check_output(['nvidia-smi','--query-compute-apps=pid,gpu_uuid,used_memory','--format=csv,noheader'],text=True)
            own=[line for line in rows.splitlines() if line.split(',')[0].strip()==str(child.pid)]
            if own and own not in gpu_receipts:gpu_receipts.append(own)
            if on_progress is not None:
                counters={}
                try:
                    fields=(Path('/proc')/str(child.pid)/'stat').read_text().rsplit(')',1)[1].split();counters=dict(cpu_ticks=int(fields[11])+int(fields[12]),start_ticks=int(fields[19]))
                except (OSError,ValueError,IndexError):pass
                model_status=log_path.parent/'training_status.json';actual_updates=None;training_state=None
                if model_status.exists():
                    try:
                        saved=read(model_status)
                        if saved.get('pid')==child.pid:actual_updates=saved.get('actual_completed_updates');training_state=saved.get('status')
                    except (OSError,ValueError):pass
                frame_progress={}
                if '--output' in argv:
                    progress_path=Path(argv[argv.index('--output')+1])/'progress.json'
                    if progress_path.exists():
                        try:
                            rendering=read(progress_path)
                            if rendering.get('pid')==child.pid:frame_progress={'completed_frames':rendering.get('completed_frames',0),'artifact_stage':rendering.get('stage')}
                        except (OSError,ValueError):pass
                current=dict(pid=child.pid,argv=argv,cwd=str(Path(cwd).resolve()),elapsed_seconds=time.monotonic()-started,log_bytes=log_path.stat().st_size,actual_own_gpu_rows=own,actual_completed_updates=actual_updates,actual_training_status=training_state,**counters,**frame_progress)
                kind,elapsed=classify_progress(last_progress,current,time.monotonic()-last_observed_progress)
                if kind!='no_observed_progress':last_observed_progress=time.monotonic()
                current.update(progress_kind=kind,seconds_since_observed_progress=elapsed,diagnostic_only_not_a_timeout_or_deadlock_claim=True);last_progress=current;on_progress(current)
            time.sleep(1)
        code=child.wait()
    except BaseException as error:
        startup_receipt.update(error=repr(error),child_returncode=child.poll());write_atomic(startup_path,startup_receipt)
        # Startup failure never authorizes signaling an unverified process.
        if identity_verified and child.poll() is None and verify_owned(child,argv,cwd):
            os.killpg(child.pid,signal.SIGTERM);child.wait(timeout=30)
        raise
    receipt=dict(pid=child.pid,argv=argv,cwd=str(cwd),returncode=code,trainer_exited=True,actual_own_gpu_rows=gpu_receipts,elapsed_seconds=time.monotonic()-started,log=str(log_path))
    write_atomic(log_path.with_suffix('.exit.json'),receipt)
    if code:
        tail=log_path.read_text(errors='replace')[-16384:]
        exceptions=[line.strip() for line in tail.splitlines() if line.strip().startswith(('ValueError:','AssertionError:'))]
        if exceptions:raise ValueError('owned_child_contract_failed:'+exceptions[-1])
        raise RuntimeError('owned_child_failed:'+str(code))
    return receipt

def gpu_available():
    rows=subprocess.check_output(['nvidia-smi','--query-gpu=uuid,memory.free','--format=csv,noheader,nounits'],text=True)
    free={row.split(',')[0].strip():int(row.split(',')[1]) for row in rows.splitlines()}
    processes=subprocess.check_output(['nvidia-smi','--query-compute-apps=pid,gpu_uuid','--format=csv,noheader'],text=True)
    return all(free.get(uuid,0)>72000 for uuid in GPU_UUIDS) and not any(row.split(',')[1].strip() in GPU_UUIDS for row in processes.splitlines())


def unused_path(path):
    path=Path(path)
    if not path.exists():return path
    for number in range(1,1000):
        candidate=path.with_name(path.stem+f'_recovery_{number:03d}'+path.suffix)
        if not candidate.exists():return candidate
    raise ValueError('too_many_recovery_attempts')

def latest_saved_update(run,spec):
    folder=Path(run)/'checkpoints'/spec['name']/'training'
    candidates=[]
    for path in folder.glob('*'):
        if path.name.isdigit() and (path/'params').is_dir() and (path/'train_state').is_dir() and (path/'assets'/spec['dataset_repo_id']/'norm_stats.json').is_file():candidates.append(int(path.name)+1)
    return max(candidates,default=0)

def completed_evaluation(receipt,updates,status_path):
    if not Path(receipt).exists():return False
    value=read(receipt)
    return value.get('status')=='evaluation_completed_gpu_released' and value.get('training_resume_allowed') is True and value.get('actual_completed_updates')==updates

def pipeline(options):
    spec_path=Path(options['spec']).resolve();spec=read(spec_path);run=Path(spec['run_dir']);run.mkdir(parents=True,exist_ok=True)
    path=run/'pipeline_status.json';status=dict(schema='airport_action8_training_pipeline/1',flow='bc_then_optional_scene_split_simulation_expert_dagger',current_method='bc_lora',dagger_executed=False,status='waiting_complete_sources',spec=str(spec_path),spec_sha256=digest(spec_path),pid=os.getpid(),planned_total_steps=100000)
    import fcntl
    lock=(run/'pipeline.lock').open('a+')
    try:fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:raise ValueError('another_owned_training_pipeline_is_active')
    if path.exists():
        previous=read(path)
        if not options.get('recover') or previous.get('spec_sha256')!=digest(spec_path):raise ValueError('existing_pipeline_requires_unchanged_explicit_recovery')
        write_atomic(unused_path(run/'pipeline_failure_history.json'),previous)
    if spec.get('num_train_steps')!=100000 or spec.get('prompt_mode')!='task_complete_action8_v1' or spec.get('fsdp_devices')!=1 or spec.get('lora') is not True:raise ValueError('reviewed_training_budget_or_model_changed')
    acceleration_path=run/'acceleration_spec.json'
    if not acceleration_path.exists():write_atomic(acceleration_path,options['acceleration_spec'])
    if read(acceleration_path)!=options['acceleration_spec']:raise ValueError('existing_acceleration_strategy_changed')
    code=Path(options['training_release']).resolve();runtime=Path(options['runtime_release']).resolve()
    def stage(name,**values):status.update(status=name,**values);write_atomic(path,status)
    vla=options['vla_python'];sim=options['sim_python'];parent=options['parent_status'];source=options['source_root']
    env=dict(os.environ,OPENPI_DATA_HOME=str(Path(options['project'])/'resources/openpi_cache'),HF_HOME=str(Path(options['project'])/'resources/hf_cache'),OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1',TOKENIZERS_PARALLELISM='false',WANDB_MODE='disabled')
    gpu_env=dict(env,CUDA_VISIBLE_DEVICES=','.join(GPU_UUIDS),XLA_PYTHON_CLIENT_MEM_FRACTION='.55',NCCL_P2P_DISABLE='1',NCCL_SHM_DISABLE='1',NCCL_IB_DISABLE='1',NCCL_NET='Socket',NCCL_CUMEM_HOST_ENABLE='0',NCCL_DEBUG='WARN',XLA_FLAGS='--xla_gpu_use_memcpy_local_p2p=false --xla_gpu_enable_nccl_user_buffers=false --xla_gpu_enable_command_buffer= --xla_gpu_enable_triton_gemm=false')
    gpu_env.pop('JAX_PLATFORMS',None)
    eval_env=dict(env,CUDA_VISIBLE_DEVICES='');eval_env.pop('JAX_PLATFORMS',None)
    cpu_env=dict(env,CUDA_VISIBLE_DEVICES='',JAX_PLATFORMS='cpu')
    try:
        script=evaluation_script(options)
        rng_receipt=options.get('evaluation_rng_receipt')
        if options.get('evaluation_mode')=='dual_static_two_gpu':
            if not rng_receipt or digest(rng_receipt)!=options.get('evaluation_rng_receipt_sha256'):raise ValueError('dual_evaluation_rng_registration_changed')
        stage('waiting_complete_sources',evaluation_mode=options.get('evaluation_mode','serial'),evaluation_registration_id=options.get('evaluation_registration_id'),options_sha256=options.get('options_sha256'))
        proof=None
        while proof is None:
            proof=source_gate(source)
            if proof is None:time.sleep(30)
        runtime_proof=None
        while runtime_proof is None:
            runtime_proof=runtime_gate(options)
            if runtime_proof is None:stage('waiting_verified_runtime_release');time.sleep(30)
        stage('preparing_cpu_train_cache',source_proof=proof,runtime_proof=runtime_proof)
        command=[vla,str(code/'scripts/train_pi05_accelerated.py'),'--spec',str(spec_path),'--parent-status',parent,'--prepare-cache']
        if not (run/'data_cache/cache_manifest.json').exists():run_owned(command,code,cpu_env,unused_path(run/'prepare_cache.log'))
        for updates in MILESTONES:
            immutable=run/f'milestone_{updates:06d}.json';completion=run/'handoffs'/f'eval_{updates:06d}.json'
            if immutable.exists() and completed_evaluation(completion,updates,immutable):continue
            if not immutable.exists():
                while not gpu_available():stage('waiting_exclusive_model_gpus',next_completed_updates=updates);time.sleep(30)
                stage('training_to_milestone',next_completed_updates=updates)
                command=[vla,str(code/'scripts/train_pi05_accelerated.py'),'--spec',str(spec_path),'--parent-status',parent,'--stop-after',str(updates)]
                if latest_saved_update(run,spec)>0:command.append('--resume')
                exit=run_owned(command,code,gpu_env,unused_path(run/f'train_to_{updates:06d}.log'))
            else:
                exits=[read(file) for file in run.glob(f'train_to_{updates:06d}*.exit.json')]
                successful=[value for value in exits if value.get('returncode')==0 and value.get('trainer_exited') is True]
                if not successful:raise ValueError('saved_milestone_without_verified_trainer_zero_exit')
                exit=successful[-1]
            checkpoint=read(immutable)
            if checkpoint.get('actual_completed_updates')!=updates or checkpoint.get('status')!='milestone_checkpoint' or checkpoint.get('checkpoint_step')!=updates-1:raise ValueError('actual_milestone_not_saved')
            gpu_seen={row.split(',')[1].strip() for receipt in exit['actual_own_gpu_rows'] for row in receipt}
            if gpu_seen!=set(GPU_UUIDS):raise ValueError('training_not_proven_on_both_physical_gpus')
            handoff=unused_path(run/'handoffs'/f'train_{updates:06d}.json')
            write_atomic(handoff,dict(status='checkpoint_saved_trainer_exited',actual_completed_updates=updates,training_status_sha256=digest(immutable),trainer_pid=exit['pid'],trainer_returncode=0))
            stage('evaluating_immutable_milestone',actual_completed_updates=updates,training_status=str(immutable))
            output=unused_path(run/'evaluations'/f'step_{updates:06d}');completion=unused_path(run/'handoffs'/f'eval_{updates:06d}.json')
            argv=[vla,str(runtime/'scripts'/script),'--protocol',options['protocol'],'--training-status',str(immutable),'--trainer-handoff',str(handoff),'--output',str(output),'--controller-root',str(runtime),'--core-report',options['runtime_core_report'],'--completion-receipt',str(completion),'--sim-python',sim,'--vla-python',vla,'--openpi-client-path',options['openpi_client_path'],'--completed-updates',str(updates)]
            if script=='evaluate_action8_checkpoint_dual.py':argv.extend(['--gpu1-uuid',options['gpu1_uuid']])
            run_owned(argv,runtime,eval_env,unused_path(run/f'eval_{updates:06d}.log'),deadline_hours=72)
            evaluated=read(completion)
            if evaluated.get('status')!='evaluation_completed_gpu_released' or evaluated.get('training_resume_allowed') is not True:raise ValueError('evaluation_did_not_release_gpus_or_complete_required_artifacts')
        stage('training_and_all_milestone_evaluations_complete',actual_completed_updates=100000)
    except BaseException as error:
        stage('failed_preserving_checkpoints',error=repr(error));raise
