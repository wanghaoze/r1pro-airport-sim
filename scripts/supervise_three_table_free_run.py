"""Independent diagnostic-only model -> timed run -> native media pipeline.

Never edits, restarts or adopts a formal trainer/evaluator. Only its own model
service may be stopped after recording. Simulation/render stages have no wall
time deadline and task failures never authorize replacement or padded frames.
"""
from pathlib import Path
import argparse,hashlib,json,os,signal,socket,subprocess,sys,time,traceback
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from r1pro_teleop.single_tray_3table.campaign import atomic_json

SCHEMA='airport_three_table_free_run_pipeline/1'
sha=lambda path:hashlib.sha256(Path(path).read_bytes()).hexdigest()
read=lambda path:json.loads(Path(path).read_text())

def identity(pid):
    folder=Path('/proc')/str(pid)
    try:
        if folder.stat().st_uid!=os.getuid():return None
        text=(folder/'stat').read_text();tail=text[text.rfind(')')+2:].split()
        if tail[0]=='Z':return None
        return dict(pid=pid,start_ticks=tail[19],ppid=int(tail[1]),sid=int(tail[3]),
            argv=[v.decode() for v in (folder/'cmdline').read_bytes().split(b'\0') if v],
            cwd=str((folder/'cwd').resolve(strict=True)))
    except (OSError,ValueError):return None

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--options',required=True,type=Path)
    args=parser.parse_args();options=read(args.options);root=Path(options['run_dir'])
    if options.get('schema')!=SCHEMA or options.get('run_kind')!='free_run_diagnostic':
        raise ValueError('explicit_independent_free_run_options_required')
    root.mkdir(parents=True,exist_ok=True)
    import fcntl
    lock=(root/'pipeline.lock').open('a+');fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
    if (root/'pipeline_status.json').exists():raise ValueError('fresh_diagnostic_pipeline_required_no_duplicate')
    release=Path(options['release']);option_sha=sha(args.options)
    state=dict(schema=SCHEMA,run_kind='free_run_diagnostic',diagnostic_only=True,
        counts_toward_task_success_rate=False,training_eligible=False,training_ready=False,
        task_success_claimed=False,pid=os.getpid(),options_sha256=option_sha,
        teacher_calls=0,inverse_solver_calls=0,formal_process_signals=0,children=[])
    def pulse(stage,**values):
        state.update(stage=stage,heartbeat_unix=time.time(),**values)
        atomic_json(root/'pipeline_status.json',state)
    def checked(job):
        actual=identity(job['pid'])
        if actual and any(actual[k]!=job[k] for k in ('start_ticks','argv','cwd')):
            raise ValueError('diagnostic_child_identity_changed_no_signal')
        return actual
    def spawn(stage,argv,env):
        log=root/(stage+'.log');stream=log.open('xb')
        proc=subprocess.Popen(argv,cwd=release,env=env,stdin=subprocess.DEVNULL,
            stdout=stream,stderr=subprocess.STDOUT,start_new_session=True)
        from r1pro_teleop.vla.training_pipeline import wait_owned_startup
        startup=wait_owned_startup(proc,argv,release)
        job=identity(proc.pid)
        if job is None:
            code=proc.wait();stream.close()
            raise RuntimeError('diagnostic_child_startup_exited:'+stage+':'+str(code))
        job.update(stage=stage,log=str(log),startup=startup,started_unix=time.time(),returncode=None)
        state['children'].append(job);atomic_json(root/(stage+'_process.json'),job)
        return proc,stream,job
    def wait(stage,proc,stream,job,*,case=None):
        while True:
            try:code=proc.wait(timeout=5);break
            except subprocess.TimeoutExpired:
                checked(job);progress=None
                if case:
                    for name in ('progress.json','free_run_progress.json','status.json'):
                        path=Path(case)/name
                        if path.is_file():
                            try:progress=read(path)
                            except (OSError,ValueError):pass
                            break
                pulse(stage,active_child=dict(job),actual_progress=progress,
                    log_bytes=Path(job['log']).stat().st_size,
                    no_wall_time_deadline=True)
        stream.close();job.update(returncode=code,actual_exit_observed=True,exited_unix=time.time())
        atomic_json(root/(stage+'_exit.json'),job);pulse(stage+'_exited',last_exit=job)
        return code
    def env_for(python,gpu,egl):
        env=dict(os.environ,CUDA_VISIBLE_DEVICES=gpu,MUJOCO_GL='egl',MUJOCO_EGL_DEVICE_ID=str(egl),
            OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1',PYTHONUNBUFFERED='1')
        env.pop('JAX_PLATFORMS',None)
        env['PYTHONPATH']=os.pathsep.join([options['openpi_client_path'],options['openpi_src'],str(release)])
        return env
    model_env=env_for(options['vla_python'],options['model_gpu_uuid'],options['model_egl_device'])
    sim_env=env_for(options['sim_python'],options['sim_gpu_uuid'],options['sim_egl_device'])
    # This parent performs the metadata handshake too; child-only PYTHONPATH
    # never changes the already running parent's import search path.
    sys.path.insert(0,options['openpi_client_path'])
    sys.path.insert(0,options['openpi_src'])
    model=None;model_stream=None;model_job=None
    try:
        pulse('verifying_frozen_inputs')
        for path,digest in options['input_sha256'].items():
            if sha(path)!=digest:raise ValueError('free_run_frozen_input_changed:'+path)
        freeze=read(release/'RUNTIME_SOURCE_FREEZE.json')
        for path,digest in freeze['files'].items():
            if sha(release/path)!=digest:raise ValueError('free_run_release_changed:'+path)
        identity_command=[options['vla_python'],str(release/'scripts/serve_pi05_airport.py'),
            '--training-status',options['training_status'],'--identity-only']
        checkpoint=json.loads(subprocess.check_output(identity_command,cwd=release,
            env=dict(model_env,CUDA_VISIBLE_DEVICES='',JAX_PLATFORMS='cpu'),text=True))
        if checkpoint['checkpoint_id']!=options['checkpoint_id']:raise ValueError('free_run_checkpoint_identity_changed')
        atomic_json(root/'checkpoint_identity.json',checkpoint)
        from r1pro_teleop.vla.three_table_recovery import training_resources
        resources=training_resources(min_free_mib=30000,project_root=options['project_root'])
        adopted=options.get('adopt_model_service')
        if adopted:
            if checked(adopted) is None:raise ValueError('registered_healthy_diagnostic_model_not_alive')
            expected_model_argv=[options['vla_python'],str(Path(adopted['cwd'])/'scripts/serve_pi05_airport.py'),
                '--training-status',options['training_status'],'--host','127.0.0.1','--port',str(options['port'])]
            if adopted['argv']!=expected_model_argv or sha(adopted['argv'][1])!=options['adopt_model_script_sha256']:
                raise ValueError('only_exact_prior_diagnostic_model_can_be_adopted')
            blockers=[row for row in resources['active_owned_compute'] if row['pid']!=adopted['pid']]
        else:blockers=resources['active_owned_compute']
        if (not adopted and resources['actual_free_mib'].get(options['model_gpu_uuid'],0)<30000) or blockers:
            raise ValueError('free_run_gpu_resources_unavailable_existing_jobs_untouched')
        atomic_json(root/'resource_preflight.json',resources)
        if adopted:
            model_job=dict(adopted,reused_healthy_diagnostic_model=True)
            state['children'].append(model_job);atomic_json(root/'adopted_model_service.json',model_job)
        else:
            with socket.socket() as sock:sock.bind(('127.0.0.1',options['port']))
            argv=[options['vla_python'],str(release/'scripts/serve_pi05_airport.py'),
                '--training-status',options['training_status'],'--host','127.0.0.1','--port',str(options['port'])]
            model,model_stream,model_job=spawn('model_service',argv,model_env)
        pulse('loading_verified_model',model_identity=model_job)
        from r1pro_teleop.single_tray_3table.learned import ThreeTablePolicy
        from r1pro_teleop.vla.policy import PolicyContract
        from r1pro_teleop.vla.data_three_table_single_tray import PROFILE
        deadline=time.monotonic()+600
        while True:
            if model is not None and model.poll() is not None:raise RuntimeError('free_run_model_service_exited:'+str(model.returncode))
            if checked(model_job) is None:raise RuntimeError('free_run_model_service_not_alive')
            try:
                policy=ThreeTablePolicy.from_websocket('127.0.0.1',options['port'],
                    PolicyContract(options['checkpoint_id'],action_width=19,action_horizon=20,prompt_mode=PROFILE))
                break
            except Exception as error:
                if time.monotonic()>deadline:raise
                pulse('loading_verified_model',model_identity=model_job,last_model_handshake_error=repr(error));time.sleep(2)
        atomic_json(root/'loaded_model_metadata.json',policy.server_metadata)
        for stage_name,seconds in [('smoke',options.get('smoke_stage_seconds',.5)),('full',200.)]:
            if stage_name=='smoke' and not seconds:continue
            case=root/(stage_name+'_case_00')
            argv=[options['sim_python'],str(release/'scripts/run_three_table_pi05_free_run.py'),
                '--scene',options['scene'],'--config',options['config'],'--output',str(case),
                '--checkpoint-id',options['checkpoint_id'],'--host','127.0.0.1','--port',str(options['port']),
                '--action-horizon','20','--execute-steps','5','--stage-seconds',str(seconds),
                '--gpu-uuid',options['sim_gpu_uuid'],'--egl-device',str(options['sim_egl_device'])]
            proc,stream,job=spawn(stage_name+'_record',argv,sim_env)
            code=wait(stage_name+'_record',proc,stream,job,case=case)
            result=read(case/'result.json')
            if result.get('run_kind')!='free_run_diagnostic' or result.get('training_eligible') is not False:
                raise ValueError('free_run_diagnostic_output_scope_required')
            if code not in (0,2):raise RuntimeError('free_run_record_process_failed:'+str(code))
            pulse(stage_name+'_recorded',recording_result=result)
            if result.get('frames',0)>0:
                native=root/(stage_name+'_native_00')
                argv=[options['sim_python'],str(release/'scripts/render_three_table_free_run.py'),
                    '--case',str(case),'--output',str(native)]
                proc,stream,job=spawn(stage_name+'_native',argv,sim_env)
                if wait(stage_name+'_native',proc,stream,job,case=native)!=0:raise RuntimeError('free_run_native_process_failed')
                media=read(native/'video_closure.json')
                if (media.get('run_kind')!='free_run_diagnostic' or media.get('training_eligible') is not False or
                        media.get('task_completed') is not False or media.get('video_closure_verified') is not True or
                        media.get('recorded_frames')!=result['frames'] or len(media.get('videos',[]))!=4):
                    raise ValueError('actual_diagnostic_four_native_closure_required')
                if code==0 and media.get('requested_duration_recording_complete') is not True:
                    raise ValueError('complete_requested_diagnostic_duration_and_native_required')
                atomic_json(root/(stage_name+'_record_and_native.json'),dict(result=result,native=str(native),
                    actual_record_exit=code,actual_native_exit=0,media=media,task_success_claimed=False,training_eligible=False))
            if stage_name=='smoke' and code!=0:
                pulse('smoke_real_error_preserving_prefix',recording_result=result);return 2
        pulse('diagnostic_recording_and_media_closed',recording_result=result,native_output=str(native),
            diagnostic_duration_completed=result.get('diagnostic_duration_completed',False))
        return 0 if code==0 else 2
    except Exception as error:
        (root/'exception.txt').write_text(traceback.format_exc())
        pulse('diagnostic_pipeline_error_preserving_evidence',last_error=repr(error));return 1
    finally:
        if model is not None:
            if model.poll() is None:
                if checked(model_job):model.terminate()
                try:model.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    pulse('owned_model_cleanup_failed_no_unverified_signal',model_identity=model_job)
            model_job.update(returncode=model.poll(),actual_exit_observed=model.poll() is not None)
            atomic_json(root/'model_service_exit.json',model_job)
            if model_stream:model_stream.close()
        elif model_job is not None and model_job.get('reused_healthy_diagnostic_model'):
            if checked(model_job):os.kill(model_job['pid'],signal.SIGTERM)
            deadline=time.monotonic()+30
            while checked(model_job) and time.monotonic()<deadline:time.sleep(.1)
            atomic_json(root/'model_service_exit.json',dict(model_job,returncode=None,
                actual_exit_observed=False,exit_code_unavailable_adopted_nonchild=True,
                verified_process_no_longer_alive=checked(model_job) is None,formal_process_signals=0))

if __name__=='__main__':raise SystemExit(main())
