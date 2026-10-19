"""Durable single-milestone evaluation; trainer owns the outer resume chain.

Exclusive service on 8766, fixed held-out full-DAG cases, then service shutdown
before sequential native replay. Only an actual completion receipt permits resume.
"""
from pathlib import Path
import argparse,importlib.util,json,math,os,socket,subprocess,sys,time,traceback
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from r1pro_teleop.vla.evaluation_protocol import verify_protocol,evaluation_summary,summary_text,file_sha

GPU_UUID='GPU-97ac5ae8-1b03-fdf8-fca5-d1192c8fe27d'


def read(path):return json.loads(Path(path).read_text())
def exclusive(path,value):
    with Path(path).open('x') as stream:json.dump(value,stream,indent=2)


def evaluation_command(args,protocol,*,scene_ids=None,output_name='episode_run'):
    return [args.sim_python,'-u',str(Path(args.controller_root)/'scripts/evaluate_pi05_airport.py'),
        '--collection',protocol['source_collection'],'--output',str(Path(args.output)/output_name),
        '--scene-ids',*(protocol['scene_ids'] if scene_ids is None else scene_ids),'--port',str(args.port),'--training-status',args.training_status,
        '--actuator-saturation','--reference-rate-limit','--rate-fraction','.5','--model-render-max-dim','224',
        '--init-arm-tolerance','.15','--init-gripper-tolerance','.01','--initializer-base-hold',
        '--max-skill-steps','6000','--record-substep-controls']


def resource_rows():
    result=subprocess.run(['nvidia-smi','--query-gpu=uuid,memory.free','--format=csv,noheader,nounits'],
        capture_output=True,text=True,check=True)
    return {line.split(',')[0].strip():int(line.split(',')[1].strip()) for line in result.stdout.splitlines()}


def frozen_dependency_inventory(root):
    names=('scripts/serve_pi05_airport.py','scripts/evaluate_pi05_airport.py',
           'scripts/render_action8_evaluation.py','scripts/render_vla_rollout_videos.py',
           'r1pro_teleop/airport_fsm/exporter.py',
           'runs/vla_deploy_20261001/bc32_post_runtime_checks.py',
           'runs/vla_deploy_20261001/render_failed_raw1_heads.py')
    result=[]
    for name in names:
        path=Path(root)/name
        if not path.is_file():raise ValueError('Frozen evaluation dependency missing:'+name)
        result.append(dict(path=name,sha256=file_sha(path)))
    return result


def _eligible_tail_failure(attempt):
    import h5py,numpy as np
    path=Path(attempt);failure=path/'failure.json'
    if not failure.is_file() or 'Diagnostic terminal state did not replay exactly' not in read(failure).get('error',''):
        return False
    with h5py.File(path/'trace.h5','r') as trace:
        if trace.attrs.get('schema')!='airport_fsm_raw/1':return False
        complete=trace['transition_completed'][:].astype(bool)
        if not len(complete) or complete[-1] or not complete[:-1].all():return False
        metadata=json.loads(trace.attrs['metadata_json']);terminal=json.loads(trace.attrs['terminal_snapshot_json'])
        dt=float(metadata['physics_timestep_s']);fps=float(metadata['fps'])
        count=(float(terminal['time'])-float(trace['sim_time'][-1]))/dt
        return np.isfinite(count) and dt>0 and abs(count-round(count))<=1e-6 and 1<=round(count)<=round(1/(fps*dt))


def eligible_tail_failure(attempt):
    try:
        return bool(_eligible_tail_failure(attempt))
    except (KeyError,ValueError,TypeError,OSError,ZeroDivisionError,OverflowError):
        return False


def preserve_strict_partial(attempt):
    attempt=Path(attempt);destination=attempt/'native_strict_partial'
    destination.mkdir(exist_ok=False)
    for name in ('head_left.mp4','head_right.mp4','left_wrist.mp4','right_wrist.mp4','failure.json'):
        source=attempt/name
        if source.is_file():source.rename(destination/name)
    return destination


def verify_native_manifest(attempt,row,checkpoint_id,replay_tolerance):
    attempt=Path(attempt);manifest=read(attempt/'manifest.json')
    if (manifest.get('status')!='complete' or manifest.get('purpose')!='inspection_not_training_export' or
        manifest.get('checkpoint_id')!=checkpoint_id or manifest.get('frames')!=row['frames'] or
        manifest.get('task_completed')!=(row.get('task_completed') is True) or
        manifest.get('trace_sha256')!=file_sha(attempt/'trace.h5') or
        manifest.get('source_result_sha256')!=file_sha(attempt/'result.json')):
        raise ValueError('Actual native manifest/result/trace identity differs')
    for key in ('replay_max_qpos_error','replay_max_qvel_error','replay_max_time_error',
                'terminal_qpos_error','terminal_qvel_error','terminal_time_error'):
        value=manifest[key];limit=1e-8 if 'time' in key else replay_tolerance*(10 if 'qvel' in key else 1)
        if not math.isfinite(value) or not 0<=value<=limit:raise ValueError('Native continuous replay error:'+key)
    refs=manifest['references'];cameras={'head_left','head_right','left_wrist','right_wrist'}
    if len(refs)!=4 or {r['camera'] for r in refs}!=cameras:raise ValueError('Expected four native inspection streams')
    for ref in refs:
        path=Path(ref['path']).resolve()
        if path.parent!=attempt.resolve() or ref.get('native') is not True or ref['frames']!=row['frames'] or file_sha(path)!=ref['sha256']:
            raise ValueError('Native video path/hash/frame mismatch')
    return manifest


def run(args):
    root=Path(args.controller_root).resolve();out=Path(args.output).resolve()
    if out.exists():raise FileExistsError('Fresh milestone evaluation directory required')
    protocol=verify_protocol(read(args.protocol))
    if protocol['main_denominator']!=50:raise ValueError('Main evaluation must include original test50')
    core=read(args.core_report)
    if core.get('returncode')!=0 or Path(core.get('release','')).resolve()!=root:raise ValueError('Exact frozen core report required')
    sys.path.insert(0,str(root))
    from scripts.serve_pi05_airport import verify_training_checkpoint
    spec,checkpoint,identity=verify_training_checkpoint(args.training_status)
    if identity.get('prompt_mode')!='task_complete_action8_v1' or identity.get('training_steps')!=args.completed_updates:
        raise ValueError('Actual milestone weights/update count/prompt identity differs')
    if args.completed_updates not in protocol['milestones']:raise ValueError('Checkpoint is not a preregistered milestone')
    # The trainer's completion/zero-exit handoff is immutable, not a caller's
    # statement that the same live trainer is paused while retaining GPU memory.
    handoff=read(args.trainer_handoff)
    if (handoff.get('status')!='checkpoint_saved_trainer_exited' or
        handoff.get('actual_completed_updates')!=args.completed_updates or
        handoff.get('training_status_sha256')!=file_sha(args.training_status)):
        raise ValueError('Trainer checkpoint/exit handoff differs')
    trainer_pid=handoff.get('trainer_pid')
    if type(trainer_pid) is not int or Path('/proc',str(trainer_pid)).exists():
        raise ValueError('Trainer must naturally exit and release GPU before evaluation')
    if resource_rows().get(GPU_UUID,0)<args.minimum_free_mib:raise RuntimeError('Insufficient free owned evaluation GPU')
    with socket.socket() as connection:
        if connection.connect_ex(('127.0.0.1',args.port))==0:raise RuntimeError('Evaluation port occupied; refuse unknown service')
    guard_path=root/'runs/vla_deploy_20261001/bc32_post_runtime_checks.py'
    dependencies=frozen_dependency_inventory(root)
    guard_spec=importlib.util.spec_from_file_location('action8_owned_guard',guard_path)
    guard=importlib.util.module_from_spec(guard_spec);guard_spec.loader.exec_module(guard)
    out.mkdir(parents=True,exist_ok=False)
    status_sha=file_sha(args.training_status)
    (out/'training_status_source.json').write_bytes(Path(args.training_status).read_bytes())
    if file_sha(out/'training_status_source.json')!=status_sha:raise ValueError('Milestone source status changed during copy')
    exclusive(out/'protocol.json',protocol);exclusive(out/'checkpoint_identity.json',identity)
    exclusive(out/'frozen_dependency_inventory.json',dependencies)
    exclusive(out/'trainer_handoff.json',handoff)
    environment=dict(os.environ,MUJOCO_GL='egl',MUJOCO_EGL_DEVICE_ID='1',CUDA_VISIBLE_DEVICES=GPU_UUID,
        XLA_PYTHON_CLIENT_MEM_FRACTION='.20',OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1',
        PYTHONPATH=str(root)+':'+args.openpi_client_path)
    # Outer cache/progress supervisors may deliberately use JAX on CPU. This
    # independently verified GPU service must not inherit their backend pin.
    environment.pop('JAX_PLATFORMS',None)
    environment.pop('JAX_PLATFORM_NAME',None)
    service=None;service_command=None;deadline=time.monotonic()+args.resource_hours*3600
    def state(stage,**details):
        path=out/'evaluation_status.json';temp=path.with_suffix('.tmp')
        temp.write_text(json.dumps(dict(stage=stage,actual_completed_updates=args.completed_updates,
            updated_unix=time.time(),controller_root=str(root),protocol_id=protocol['protocol_id'],
            resource_budget_hours=args.resource_hours,skill_control_budget_steps=6000,**details),indent=2));temp.replace(path)
    try:
        service_command=[args.vla_python,'-u',str(root/'scripts/serve_pi05_airport.py'),
            '--training-status',args.training_status,'--host','127.0.0.1','--port',str(args.port),'--denoising-steps','10']
        with (out/'service.log').open('xb') as stream:
            service=subprocess.Popen(service_command,cwd=root,env=environment,stdout=stream,stderr=subprocess.STDOUT,start_new_session=True)
        exclusive(out/'service_process.json',dict(pid=service.pid,command=service_command))
        guard.wait_owned_startup(service,service_command,root,out/'service_startup.json')
        state('restoring_actual_milestone',service_pid=service.pid)
        metadata=None;load_deadline=min(deadline,time.monotonic()+1500)
        while time.monotonic()<load_deadline:
            if service.poll() is not None:raise RuntimeError('Own service exited before model restore')
            guard.verify_owned_identity(service.pid,service_command,root)
            gpu=guard.checked_gpu_rows(service.pid)
            if gpu and not (out/'service_gpu_verified.json').exists():exclusive(out/'service_gpu_verified.json',dict(pid=service.pid,actual_gpu_rows=gpu))
            code=('import json;from r1pro_teleop.vla.rollout import verified_server_metadata;print(json.dumps(verified_server_metadata("127.0.0.1",'+str(args.port)+',expected_checkpoint_id='+repr(identity['checkpoint_id'])+')))')
            try:
                probe=subprocess.run([args.vla_python,'-c',code],cwd=root,env=environment,capture_output=True,text=True,check=True,timeout=20)
                metadata=json.loads(probe.stdout.splitlines()[-1])
                if gpu:break
            except subprocess.SubprocessError:time.sleep(3)
        else:raise TimeoutError('Actual milestone service restore budget exhausted')
        if metadata.get('prompt_mode')!='task_complete_action8_v1':raise RuntimeError('Wrong live prompt mode')
        exclusive(out/'service_metadata.json',metadata)
        command=evaluation_command(args,protocol);state('full_test50_running',command=command)
        with (out/'physical_evaluation.log').open('xb') as stream:
            process=subprocess.Popen(command,cwd=root,env=environment,stdout=stream,stderr=subprocess.STDOUT,start_new_session=True)
            exclusive(out/'physical_process.json',dict(pid=process.pid,command=command))
            try:guard.monitor_owned(process,command,root,out/'physical_gpu_verified.json',deadline=deadline)
            except Exception:
                path=out/'episode_run/rollout_report.json'
                if path.is_file():
                    summary=evaluation_summary(protocol,read(path));exclusive(out/'evaluation_summary.json',summary)
                    (out/'evaluation_summary.txt').write_text(summary_text(summary))
                raise
        report=read(out/'episode_run/rollout_report.json')
        case_runs={row['scene_id']:'episode_run' for row in report['results']}
        first_summary=evaluation_summary(protocol,report)
        retry_ids=first_summary['main_test']['required_infrastructure_rerun_scene_ids']
        if retry_ids and time.monotonic()<deadline:
            exclusive(out/'pre_retry_success_report.json',first_summary)
            retry_name='episode_run_infrastructure_retry_1'
            command=evaluation_command(args,protocol,scene_ids=retry_ids,output_name=retry_name)
            state('infrastructure_retry_running',scene_ids=retry_ids,command=command)
            with (out/'infrastructure_retry.log').open('xb') as stream:
                retry=subprocess.Popen(command,cwd=root,env=environment,stdout=stream,stderr=subprocess.STDOUT,start_new_session=True)
                guard.monitor_owned(retry,command,root,out/'infrastructure_retry_gpu_verified.json',deadline=deadline)
            retry_report=read(out/retry_name/'rollout_report.json')
            original={row['scene_id']:row for row in report['results']}
            for row in retry_report['results']:
                if row['scene_id'] not in retry_ids:raise ValueError('Retry contains non-infrastructure scene')
                original[row['scene_id']]=row;case_runs[row['scene_id']]=retry_name
            report={**report,'results':[original[sid] for sid in protocol['scene_ids'] if sid in original],
                    'infrastructure_retry_reports':[str(out/retry_name/'rollout_report.json')]}
            exclusive(out/'combined_rollout_report.json',report)
        exclusive(out/'final_case_artifact_routes.json',case_runs)
        summary=evaluation_summary(protocol,report);exclusive(out/'evaluation_summary.json',summary)
        (out/'evaluation_summary.txt').write_text(summary_text(summary))
        # No inference service and renderer ever share this evaluation lifecycle.
        guard.terminate_owned(service,service_command,root);service.wait(timeout=30)
        exclusive(out/'service_exit.json',dict(pid=service.pid,returncode=service.returncode,naturally_reaped=True))
        state('native4_sequential_replay',physical_summary=summary)
        videos=[]
        for row in report['results']:
            attempt=out/case_runs[row['scene_id']]/'attempts'/row['scene_id']/'a000'
            if not (attempt/'trace.h5').is_file() or row.get('frames',0)==0:
                videos.append(dict(scene_id=row['scene_id'],status='no_physical_trace_infrastructure_failure'));continue
            command=[args.sim_python,str(root/'scripts/render_action8_evaluation.py'),'--attempt',str(attempt),
                '--source-collection',protocol['source_collection'],'--controller-root',str(root)]
            try:
                with (attempt/'native_render.log').open('xb') as stream:
                    renderer=subprocess.Popen(command,cwd=root,env=environment,stdout=stream,stderr=subprocess.STDOUT,start_new_session=True)
                    guard.monitor_owned(renderer,command,root,attempt/'native_gpu_verified.json',deadline=deadline)
                verify_native_manifest(attempt,row,identity['checkpoint_id'],report['config']['replay_tolerance'])
                videos.append(dict(scene_id=row['scene_id'],status='complete',manifest=str(attempt/'manifest.json')))
            except Exception as exc:
                if not eligible_tail_failure(attempt):
                    videos.append(dict(scene_id=row['scene_id'],status='failed',error=repr(exc)));continue
                partial=preserve_strict_partial(attempt)
                recovery_command=command+['--recover-failed-tail']
                try:
                    with (attempt/'native_tail_recovery.log').open('xb') as stream:
                        renderer=subprocess.Popen(recovery_command,cwd=root,env=environment,stdout=stream,stderr=subprocess.STDOUT,start_new_session=True)
                        guard.monitor_owned(renderer,recovery_command,root,attempt/'native_tail_gpu_verified.json',deadline=deadline)
                    verify_native_manifest(attempt,row,identity['checkpoint_id'],report['config']['replay_tolerance'])
                    videos.append(dict(scene_id=row['scene_id'],status='complete_guarded_failed_tail',manifest=str(attempt/'manifest.json'),strict_partial=str(partial)))
                except Exception as recovery_error:videos.append(dict(scene_id=row['scene_id'],status='failed_guarded_recovery',error=repr(recovery_error),strict_partial=str(partial)))
        exclusive(out/'native_video_index.json',dict(schema='airport_action8_milestone_native4/1',cases=videos))
        valid=summary['status']=='evaluation_complete' and all(v['status'].startswith('complete') for v in videos)
        state('complete' if valid else 'requires_evidence_or_infrastructure_recovery',physical_summary=summary,videos=videos)
        receipt=dict(schema='airport_action8_evaluation_handoff/1',status='evaluation_completed_gpu_released' if valid else 'evaluation_requires_recovery',
            actual_completed_updates=args.completed_updates,checkpoint_id=identity['checkpoint_id'],protocol_id=protocol['protocol_id'],
            service_pid_reaped=True,renderers_all_reaped=True,success_report=str(out/'evaluation_summary.json'),
            evaluation_status=str(out/'evaluation_status.json'),training_resume_allowed=valid)
        if file_sha(args.training_status)!=status_sha:raise ValueError('Immutable milestone status changed during evaluation')
        exclusive(args.completion_receipt,receipt)
        index_path=out.parent/'evaluation_index.json'
        index=read(index_path) if index_path.exists() else dict(schema='airport_action8_evaluation_index/1',milestones={})
        index['milestones'][str(args.completed_updates)]=dict(output=str(out),checkpoint_id=identity['checkpoint_id'],
            approximate_success_rate=summary['main_test']['approximate_success_rate'],
            strict_success_rate=summary['main_test']['strict_success_rate'],receipt=str(args.completion_receipt),status=receipt['status'])
        temporary=index_path.with_suffix('.tmp');temporary.write_text(json.dumps(index,indent=2));temporary.replace(index_path)
        return receipt
    except BaseException as exc:
        state('failed',error=repr(exc),traceback=traceback.format_exc())
        raise
    finally:
        if service is not None and service.poll() is None:
            guard.terminate_owned(service,service_command,root);service.wait(timeout=30)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('protocol','training-status','trainer-handoff','output','controller-root','core-report','completion-receipt','sim-python','vla-python','openpi-client-path'):
        parser.add_argument('--'+name,required=True)
    parser.add_argument('--completed-updates',type=int,required=True);parser.add_argument('--port',type=int,default=8766)
    parser.add_argument('--minimum-free-mib',type=int,default=12000);parser.add_argument('--resource-hours',type=float,default=48)
    args=parser.parse_args(argv)
    if not 0<args.resource_hours<=96:parser.error('resource-hours must be in (0,96]')
    print(json.dumps(run(args),indent=2))


if __name__=='__main__':main()
