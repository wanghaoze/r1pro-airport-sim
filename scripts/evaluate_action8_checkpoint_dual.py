"""Optional static dual-GPU full-test evaluation. Serial supervisor is unchanged.

Each independent worker restores the same immutable checkpoint and owns one
service/GPU and 25 fixed cases. Only the coordinator emits the full-50 summary
and a training-resume receipt. This script never owns the training lifecycle.
"""
from pathlib import Path
import argparse, importlib.util, json, os, socket, subprocess, sys, time, traceback
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import evaluate_action8_checkpoint as serial
from r1pro_teleop.vla.evaluation_protocol import verify_protocol, evaluation_summary, summary_text, file_sha


def write(path, value):
    path = Path(path); temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(value, indent=2)); temp.replace(path)


def static_plan(protocol, gpu1_uuid, root, core_sha):
    if protocol['main_denominator'] != 50 or len(protocol['scene_ids']) != 50 or len(set(protocol['scene_ids'])) != 50:
        raise ValueError('Static dual evaluation requires the original distinct test50')
    if not isinstance(gpu1_uuid, str) or not gpu1_uuid.startswith('GPU-') or gpu1_uuid == serial.GPU_UUID:
        raise ValueError('Explicit distinct physical GPU1 UUID required')
    plan = dict(schema='airport_action8_static_dual_registration/1', protocol_id=protocol['protocol_id'],
        controller_root=str(Path(root).resolve()), core_report_sha256=core_sha,
        configuration=dict(init_arm_tolerance=.15, init_gripper_tolerance=.01, initializer_base_hold=True,
            grasp_base_hold=False, actuator_saturation=True, rate_fraction=.5, model_render_max_dim=224,
            max_skill_steps=6000, record_substep_controls=True, denoising_steps=10),
        workers=[dict(index=i, gpu_uuid=uuid, egl_device=egl, port=port, scene_ids=protocol['scene_ids'][i::2])
                 for i, uuid, egl, port in ((0, serial.GPU_UUID, 1, 8766), (1, gpu1_uuid, 0, 8768))],
        main_denominator=50, source='simulation', dispatch='static_25_per_gpu_not_dynamic_batching')
    import hashlib
    plan['registration_id']='sha256:'+hashlib.sha256(json.dumps(plan,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    return plan


def owned_guard(root, worker):
    path=Path(root)/'runs/vla_deploy_20261001/bc32_post_runtime_checks.py'
    spec=importlib.util.spec_from_file_location('static_owned_gpu_'+str(worker['index']),path)
    guard=importlib.util.module_from_spec(spec); spec.loader.exec_module(guard)
    def checked(pid):
        rows=guard.own_gpu_rows(pid)
        if any(row['index'] != worker['index'] or row['uuid'] != worker['gpu_uuid'] for row in rows):
            raise RuntimeError('Owned process allocated on a different physical GPU')
        return rows
    # This isolated imported module retains the exact frozen identity, natural
    # exit, deadline and narrow signaling guards; only the registered GPU differs.
    guard.checked_gpu_rows=checked
    return guard


def gpu_environment(root, client_path, worker):
    env=dict(os.environ, MUJOCO_GL='egl', MUJOCO_EGL_DEVICE_ID=str(worker['egl_device']),
        CUDA_VISIBLE_DEVICES=worker['gpu_uuid'], XLA_PYTHON_CLIENT_MEM_FRACTION='.20',
        OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1',
        PYTHONPATH=str(root)+':'+client_path)
    env.pop('JAX_PLATFORMS',None); env.pop('JAX_PLATFORM_NAME',None)
    return env


def verified_setup(args):
    root=Path(args.controller_root).resolve(); protocol=verify_protocol(serial.read(args.protocol))
    core=serial.read(args.core_report)
    if core.get('returncode') != 0 or Path(core.get('release','')).resolve()!=root:
        raise ValueError('Exact frozen passing core report required')
    dependencies=serial.frozen_dependency_inventory(root)
    script=root/'scripts/evaluate_action8_checkpoint_dual.py'
    if not script.is_file():raise ValueError('Dual supervisor must be included in the frozen runtime')
    dependencies.append(dict(path=str(script.relative_to(root)),sha256=file_sha(script)))
    sys.path.insert(0,str(root))
    from scripts.serve_pi05_airport import verify_training_checkpoint
    _, _, identity=verify_training_checkpoint(args.training_status)
    if identity.get('prompt_mode')!='task_complete_action8_v1' or identity.get('training_steps')!=args.completed_updates:
        raise ValueError('Checkpoint actual update/prompt mode differs')
    if args.completed_updates not in protocol['milestones']:raise ValueError('Not a registered milestone')
    handoff=serial.read(args.trainer_handoff)
    if (handoff.get('status')!='checkpoint_saved_trainer_exited' or
        handoff.get('actual_completed_updates')!=args.completed_updates or
        handoff.get('training_status_sha256')!=file_sha(args.training_status) or
        type(handoff.get('trainer_pid')) is not int or Path('/proc',str(handoff['trainer_pid'])).exists()):
        raise ValueError('Immutable exited-trainer handoff required')
    return root, protocol, identity, handoff, dependencies


def worker_run(args):
    root,protocol,identity,_,_=verified_setup(args)
    plan=serial.read(Path(args.output)/'dual_registration.json')
    if plan!=static_plan(protocol,args.gpu1_uuid,root,file_sha(args.core_report)):
        raise ValueError('Worker static registration changed')
    worker=plan['workers'][args.worker_index]; out=Path(args.output)/('worker_'+str(args.worker_index))
    out.mkdir(exist_ok=False); guard=owned_guard(root,worker)
    env=gpu_environment(root,args.openpi_client_path,worker)
    deadline=time.monotonic()+args.resource_hours*3600
    if serial.resource_rows().get(worker['gpu_uuid'],0)<args.minimum_free_mib:
        raise RuntimeError('Insufficient free registered GPU')
    with socket.socket() as conn:
        if conn.connect_ex(('127.0.0.1',worker['port']))==0:raise RuntimeError('Registered service port occupied')
    service=None;command=None
    def stage(name,**details):write(out/'worker_status.json',dict(stage=name,worker=worker,updated_unix=time.time(),**details))
    try:
        command=[args.vla_python,'-u',str(root/'scripts/serve_pi05_airport.py'),'--training-status',args.training_status,
                 '--host','127.0.0.1','--port',str(worker['port']),'--denoising-steps','10']
        with (out/'service.log').open('xb') as log:
            service=subprocess.Popen(command,cwd=root,env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        serial.exclusive(out/'service_process.json',dict(pid=service.pid,command=command))
        guard.wait_owned_startup(service,command,root,out/'service_startup.json')
        stage('restoring_checkpoint')
        restore_deadline=min(deadline,time.monotonic()+1500); metadata=None
        while time.monotonic()<restore_deadline:
            if service.poll() is not None:raise RuntimeError('Owned service exited before restore')
            guard.verify_owned_identity(service.pid,command,root); rows=guard.checked_gpu_rows(service.pid)
            if rows and not (out/'service_gpu_verified.json').exists():
                serial.exclusive(out/'service_gpu_verified.json',dict(pid=service.pid,actual_gpu_rows=rows))
            code='import json;from r1pro_teleop.vla.rollout import verified_server_metadata;print(json.dumps(verified_server_metadata("127.0.0.1",'+str(worker['port'])+',expected_checkpoint_id='+repr(identity['checkpoint_id'])+')))'
            try:
                probe=subprocess.run([args.vla_python,'-c',code],cwd=root,env=env,capture_output=True,text=True,check=True,timeout=20)
                metadata=json.loads(probe.stdout.splitlines()[-1])
                if rows:break
            except subprocess.SubprocessError:time.sleep(3)
        else:raise TimeoutError('Model restore budget exhausted')
        if metadata.get('prompt_mode')!='task_complete_action8_v1':raise ValueError('Live mode differs')
        serial.exclusive(out/'service_metadata.json',metadata)
        from types import SimpleNamespace
        case_args=SimpleNamespace(**vars(args));case_args.output=str(out);case_args.port=worker['port']
        def physical(ids,name):
            cmd=serial.evaluation_command(case_args,protocol,scene_ids=ids,output_name=name)
            stage('physical_evaluation',scene_ids=ids,command=cmd)
            with (out/(name+'.log')).open('xb') as log:
                process=subprocess.Popen(cmd,cwd=root,env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
                guard.monitor_owned(process,cmd,root,out/(name+'_gpu_verified.json'),deadline=deadline)
            report=serial.read(out/name/'rollout_report.json')
            if any(row['scene_id'] not in ids for row in report['results']):raise ValueError('Physical worker returned outside assigned cases')
            return report
        report=physical(worker['scene_ids'],'episode_run')
        routes={row['scene_id']:'episode_run' for row in report['results']}
        retry_ids=[sid for sid in evaluation_summary(protocol,report)['main_test']['required_infrastructure_rerun_scene_ids'] if sid in worker['scene_ids']]
        if retry_ids and time.monotonic()<deadline:
            retry=physical(retry_ids,'episode_run_infrastructure_retry_1')
            merged={row['scene_id']:row for row in report['results']}
            for row in retry['results']:merged[row['scene_id']]=row;routes[row['scene_id']]='episode_run_infrastructure_retry_1'
            report={**report,'results':[merged[sid] for sid in worker['scene_ids'] if sid in merged]}
        serial.exclusive(out/'combined_rollout_report.json',report)
        serial.exclusive(out/'final_case_artifact_routes.json',routes)
        guard.terminate_owned(service,command,root);service.wait(timeout=30)
        serial.exclusive(out/'service_exit.json',dict(pid=service.pid,returncode=service.returncode,reaped=True))
        stage('native4_after_owned_service_exit');videos=[]
        for row in report['results']:
            attempt=out/routes[row['scene_id']]/'attempts'/row['scene_id']/'a000'
            if not (attempt/'trace.h5').is_file() or row.get('frames',0)<=0:
                videos.append(dict(scene_id=row['scene_id'],status='no_physical_trace'));continue
            cmd=[args.sim_python,str(root/'scripts/render_action8_evaluation.py'),'--attempt',str(attempt),
                 '--source-collection',protocol['source_collection'],'--controller-root',str(root)]
            def render(argv, log_name, receipt):
                with (attempt/log_name).open('xb') as log:
                    process=subprocess.Popen(argv,cwd=root,env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
                    guard.monitor_owned(process,argv,root,attempt/receipt,deadline=deadline)
                serial.verify_native_manifest(attempt,row,identity['checkpoint_id'],report['config']['replay_tolerance'])
            try:
                render(cmd,'native_render.log','native_gpu_verified.json')
                videos.append(dict(scene_id=row['scene_id'],status='complete',manifest=str(attempt/'manifest.json')))
            except Exception as exc:
                if not serial.eligible_tail_failure(attempt):
                    videos.append(dict(scene_id=row['scene_id'],status='failed',error=repr(exc)));continue
                partial=serial.preserve_strict_partial(attempt)
                try:
                    render(cmd+['--recover-failed-tail'],'native_tail_recovery.log','native_tail_gpu_verified.json')
                    videos.append(dict(scene_id=row['scene_id'],status='complete_guarded_failed_tail',manifest=str(attempt/'manifest.json'),strict_partial=str(partial)))
                except Exception as recovery:videos.append(dict(scene_id=row['scene_id'],status='failed_recovery',error=repr(recovery)))
        serial.exclusive(out/'native_video_index.json',dict(cases=videos))
        # Per-worker results deliberately have no main_test success rate.
        receipt=dict(schema='airport_action8_static_worker_receipt/1',worker_index=args.worker_index,
            registration_id=plan['registration_id'],checkpoint_id=identity['checkpoint_id'],
            assigned_scene_ids=worker['scene_ids'],report=str(out/'combined_rollout_report.json'),
            videos=videos,service_pid_reaped=True,renderers_all_reaped=True,training_resume_allowed=False)
        serial.exclusive(out/'worker_receipt.json',receipt);stage('worker_closed')
        return receipt
    except BaseException as exc:stage('failed',error=repr(exc),traceback=traceback.format_exc());raise
    finally:
        if service is not None and service.poll() is None:
            guard.terminate_owned(service,command,root);service.wait(timeout=30)


def aggregate(protocol, plan, identity, receipts, reports):
    if len(receipts)!=2 or len(reports)!=2:raise ValueError('Both static workers required')
    rows=[];videos=[]
    for worker,receipt,report in zip(plan['workers'],receipts,reports):
        if (receipt.get('worker_index')!=worker['index'] or receipt.get('registration_id')!=plan['registration_id'] or
            receipt.get('checkpoint_id')!=identity['checkpoint_id'] or receipt.get('assigned_scene_ids')!=worker['scene_ids'] or
            receipt.get('service_pid_reaped') is not True or receipt.get('renderers_all_reaped') is not True):
            raise ValueError('Worker ownership/checkpoint/registration receipt differs')
        if report.get('checkpoint_metadata',{}).get('checkpoint_id')!=identity['checkpoint_id']:
            raise ValueError('Worker report checkpoint differs')
        worker_rows=report.get('results',[])
        if len({r['scene_id'] for r in worker_rows})!=len(worker_rows) or not {r['scene_id'] for r in worker_rows}<=set(worker['scene_ids']):
            raise ValueError('Worker returned duplicate or outside assigned scenes')
        rows.extend(worker_rows);videos.extend(receipt['videos'])
    summary=evaluation_summary(protocol,dict(results=rows,checkpoint_metadata=identity))
    video_ids=[v['scene_id'] for v in videos]
    evidence=(len(video_ids)==50 and len(set(video_ids))==50 and set(video_ids)==set(protocol['scene_ids']) and all(v['status'].startswith('complete') for v in videos))
    return summary,videos,summary['status']=='evaluation_complete' and evidence


def partial_summary(protocol, plan, identity, out):
    """Closed or partial physical reports retain the original denominator on failure."""
    rows=[];excluded=[]
    for worker in plan['workers']:
        directory=Path(out)/('worker_'+str(worker['index']))
        path=directory/'combined_rollout_report.json'
        if not path.is_file():path=directory/'episode_run/rollout_report.json'
        if not path.is_file():continue
        try:
            report=serial.read(path)
            if report.get('checkpoint_metadata',{}).get('checkpoint_id')!=identity['checkpoint_id']:
                raise ValueError('Unverified partial report checkpoint')
            current=report.get('results',[]);ids=[r['scene_id'] for r in current]
            if len(ids)!=len(set(ids)) or not set(ids)<=set(worker['scene_ids']):
                raise ValueError('Invalid partial report scene partition')
            rows.extend(current)
        except Exception as exc:excluded.append(dict(path=str(path),reason=repr(exc)))
    summary=evaluation_summary(protocol,dict(results=rows,checkpoint_metadata=identity))
    summary['orchestration_failed']=True
    summary['partial_reports_excluded']=excluded
    summary['training_resume_allowed']=False
    return summary


def run(args):
    root,protocol,identity,handoff,deps=verified_setup(args);out=Path(args.output).resolve()
    plan=static_plan(protocol,args.gpu1_uuid,root,file_sha(args.core_report))
    out.mkdir(parents=True,exist_ok=False)
    serial.exclusive(out/'protocol.json',protocol);serial.exclusive(out/'dual_registration.json',plan)
    serial.exclusive(out/'checkpoint_identity.json',identity);serial.exclusive(out/'frozen_dependency_inventory.json',deps)
    serial.exclusive(out/'trainer_handoff.json',handoff)
    status_sha=file_sha(args.training_status);(out/'training_status_source.json').write_bytes(Path(args.training_status).read_bytes())
    if file_sha(out/'training_status_source.json')!=status_sha:raise ValueError('Immutable checkpoint receipt changed')
    processes=[]
    try:
        free=serial.resource_rows()
        for worker in plan['workers']:
            if free.get(worker['gpu_uuid'],0)<args.minimum_free_mib:
                raise RuntimeError('Insufficient free registered physical GPU before dispatch')
            with socket.socket() as connection:
                if connection.connect_ex(('127.0.0.1',worker['port']))==0:
                    raise RuntimeError('Registered port occupied before dispatch; refuse unknown service')
        for index in (0,1):
            command=[sys.executable,str(root/'scripts/evaluate_action8_checkpoint_dual.py')]
            for name in ('protocol','training_status','trainer_handoff','output','controller_root','core_report','completion_receipt','sim_python','vla_python','openpi_client_path','completed_updates','gpu1_uuid','minimum_free_mib','resource_hours'):
                command.extend(['--'+name.replace('_','-'),str(getattr(args,name))])
            command.extend(['--worker-index',str(index)])
            with (out/('worker_'+str(index)+'.log')).open('xb') as log:
                process=subprocess.Popen(command,cwd=root,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            processes.append((process,command));serial.exclusive(out/('worker_'+str(index)+'_process.json'),dict(pid=process.pid,command=command))
        write(out/'evaluation_status.json',dict(stage='static_dual_workers_running',registration_id=plan['registration_id']))
        # Workers own their deadlines and cleanup. The CPU coordinator never
        # signals a worker with live services; it waits for their own cleanup.
        codes=[process.wait() for process,_ in processes]
        if codes!=[0,0]:raise RuntimeError('Worker failed; preserve both artifacts, refuse training resume')
        receipts=[serial.read(out/('worker_'+str(i))/'worker_receipt.json') for i in (0,1)]
        reports=[serial.read(receipt['report']) for receipt in receipts]
        summary,videos,valid=aggregate(protocol,plan,identity,receipts,reports)
        serial.exclusive(out/'evaluation_summary.json',summary);(out/'evaluation_summary.txt').write_text(summary_text(summary))
        serial.exclusive(out/'native_video_index.json',dict(schema='airport_action8_milestone_native4/1',cases=videos))
        if file_sha(args.training_status)!=status_sha:raise ValueError('Immutable checkpoint receipt changed')
        receipt=dict(schema='airport_action8_evaluation_handoff/1',status='evaluation_completed_gpu_released' if valid else 'evaluation_requires_recovery',
            actual_completed_updates=args.completed_updates,checkpoint_id=identity['checkpoint_id'],protocol_id=protocol['protocol_id'],
            registration_id=plan['registration_id'],service_pid_reaped=True,renderers_all_reaped=True,training_resume_allowed=valid,
            success_report=str(out/'evaluation_summary.json'),evaluation_status=str(out/'evaluation_status.json'))
        serial.exclusive(args.completion_receipt,receipt)
        write(out/'evaluation_status.json',dict(stage='complete' if valid else 'requires_recovery',physical_summary=summary,registration_id=plan['registration_id']))
        index_path=out.parent/'evaluation_index.json'
        index=serial.read(index_path) if index_path.exists() else dict(schema='airport_action8_evaluation_index/1',milestones={})
        index['milestones'][str(args.completed_updates)]=dict(output=str(out),checkpoint_id=identity['checkpoint_id'],receipt=str(args.completion_receipt),
            approximate_success_rate=summary['main_test']['approximate_success_rate'],strict_success_rate=summary['main_test']['strict_success_rate'],status=receipt['status'],registration_id=plan['registration_id'])
        write(index_path,index);return receipt
    except BaseException as exc:
        summary=partial_summary(protocol,plan,identity,out)
        write(out/'evaluation_summary.json',summary)
        (out/'evaluation_summary.txt').write_text(summary_text(summary)+'Orchestration failed; training resume forbidden.\n')
        write(out/'evaluation_status.json',dict(stage='failed',error=repr(exc),traceback=traceback.format_exc(),training_resume_allowed=False))
        raise


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('protocol','training-status','trainer-handoff','output','controller-root','core-report','completion-receipt','sim-python','vla-python','openpi-client-path','gpu1-uuid'):
        parser.add_argument('--'+name,required=True)
    parser.add_argument('--completed-updates',type=int,required=True);parser.add_argument('--worker-index',type=int,choices=(0,1))
    parser.add_argument('--minimum-free-mib',type=int,default=12000);parser.add_argument('--resource-hours',type=float,default=48)
    args=parser.parse_args(argv)
    if not 0<args.resource_hours<=96:parser.error('resource-hours must be in (0,96]')
    print(json.dumps(worker_run(args) if args.worker_index is not None else run(args),indent=2))


if __name__=='__main__':main()
