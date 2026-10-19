"""Own policy service + native Isaac process, with actual child exit receipts."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback
import numpy as np
from studio_mse import ROOT,CODE,load_registered_policy,write,sha


def serve(run):
    request=json.loads((run/'request.json').read_text())['payload']
    if request.get('transport')=='ros2':
        from studio_ros2_service import serve as ros_serve
        return ros_serve(run)
    os.environ['CUDA_VISIBLE_DEVICES']='1'
    entry=json.loads((run/'checkpoints.json').read_text())[0];directory=run/'policy';directory.mkdir(exist_ok=True)
    policy=load_registered_policy(entry)
    write(directory/'ready.json',dict(checkpoint_id=entry['id'],horizon=20,pid=os.getpid(),receipt_sha256=entry['receiptSha256']))
    done=set()
    while not (directory/'stop').exists():
        for path in sorted(directory.glob('*.request.npz')):
            if path.name in done:continue
            stem=path.name.removesuffix('.request.npz')
            try:
                with np.load(path,allow_pickle=False) as values:
                    sample={key:values[key].copy() for key in values.files};sample['prompt']=str(sample['prompt'])
                if set(sample)!={'state','prompt','image/head_left','image/left_wrist','image/right_wrist'}:raise ValueError('invalid_policy_input_fields')
                actions=np.asarray(policy.infer(sample)['actions'])
                if actions.shape!=(20,19) or not np.isfinite(actions).all():raise ValueError('invalid_native_model_chunk')
                target=directory/(stem+'.reply.npz');tmp=target.with_suffix('.tmp')
                with tmp.open('wb') as stream:np.savez(stream,actions=actions)
                tmp.replace(target)
            except Exception as exc:write(directory/(stem+'.error.json'),dict(error=repr(exc)))
            done.add(path.name)
        write(directory/'heartbeat.json',dict(heartbeat_unix=time.time(),inference_requests=len(done),pid=os.getpid()))
        time.sleep(.02)


def audit_room(room):
    result=json.loads((room/'result.json').read_text());contract=json.loads((room/'policy_contract.json').read_text()) if (room/'policy_contract.json').exists() else {}
    if not result.get('passed'):return dict(passed=False,failure_category=result.get('failure_category') or 'infrastructure_failure',reason=result.get('error'))
    trace=np.load(room/'native_trace.npz');frames=result['frames'];spans=result['actions']
    if len(trace['state'])!=frames+1 or len(trace['action'])!=frames or len(spans)!=2:raise ValueError('native_policy_trace_shape')
    if trace['submitted_control'].shape[1]!=25:raise ValueError('native_policy_actual_substeps')
    if not np.all(trace['front_region_ok']) or np.max(trace['penetration'])>.02:raise ValueError('native_policy_physics_gate')
    fingers=trace['finger_contact_force'][:,-1,0];tables=trace['table_force'][:,-1,0]
    end=spans[0]['end'];pose=trace['tray_pose'][:,0]
    pick=bool(np.all(fingers[end-1]>.5) and np.prod(trace['long_edge_sign'][end,0])==-1 and tables[end-1]<=.01 and pose[end,2]-pose[0,2]>=.02)
    begin=spans[1]['start'];finish=spans[1]['end'];height=contract['task_table']['center_world'][2]+contract['task_table']['dimensions_m'][2]
    releases=np.flatnonzero(np.any(fingers[begin:finish]<=.5,axis=1));release_gap=float(pose[begin+int(releases[0])+1,2]-height) if len(releases) else None
    last=slice(finish-10,finish);speed=np.linalg.norm(np.diff(pose[finish-10:finish+1,:3],axis=0),axis=1)*20
    place=bool(finish-begin>=10 and release_gap is not None and release_gap<=.02 and np.all(tables[last]>.01) and np.all(fingers[last]<=.5) and np.all(speed<.01) and trace['boundary_ok'][finish,0] and trace['axis_error_rad'][finish,0]<=np.deg2rad(15))
    media=result.get('native_encoders',{});closed=len(media)==4 and all(v.get('returncode')==0 and v.get('frames')==frames for v in media.values())
    if not closed:return dict(passed=False,failure_category='infrastructure_failure',reason='native_video_not_closed')
    return dict(passed=pick and place,failure_category=None if pick and place else 'model_failure',pickPassed=pick,placePassed=place,releaseGapM=release_gap,frames=frames,traceSha256=sha(room/'native_trace.npz'),nativeMediaClosed=closed)


def evaluate(run,native_python):
    request=json.loads((run/'request.json').read_text())['payload'];entry=json.loads((run/'checkpoints.json').read_text())[0]
    directory=run/'policy';directory.mkdir(exist_ok=True)
    cfg=json.loads((ROOT/'runs/isaacsim_parallel_pickplace300_20261017_v1/batch_001/config.json').read_text())
    selected=[]
    for index in request['roomIds']:
        case=cfg['cases'][index];case.update(original_room_id=index,policy=dict(runtime_profile=request.get('runtimeProfile','baseline'),robot_action_limits=json.loads((CODE/'gpu/robot_action_limits.json').read_text()) if (CODE/'gpu/robot_action_limits.json').exists() else None,action_safety_mode=request.get('actionSafetyMode','strict'),directory=str(directory),checkpoint_id=entry['id'],frames_per_action=request['framesPerAction'],action_horizon=entry.get('modelConfig',{}).get('horizon',20),inference_timeout_seconds=request.get('inferenceTimeoutSeconds',300),max_simulation_frames=int(request['maxSimulationSeconds']*20) if request.get('liveEvaluation') else None,wall_deadline=time.time()+request.get('maxWallSeconds',7200) if request.get('liveEvaluation') else None))
        selected.append(case)
    cfg.update(cases=selected,rooms=len(selected),execution_mode='policy',output=str(run/'native'),pin_render_products_to_gpus=False, realtime_pacing=request.get('realtimePacing',False),live_evaluation=request.get('liveEvaluation',False),runtime_profile=request.get('runtimeProfile','baseline'))
    write(run/'native_config.json',cfg)
    service_log=(run/'policy.log').open('ab');native_log=None;service=None;native=None
    started=time.time()
    try:
        if not request.get('externalService'):
            service=subprocess.Popen([sys.executable,__file__,'--run',str(run),'--serve'],cwd=ROOT,stdin=subprocess.DEVNULL,stdout=service_log,stderr=subprocess.STDOUT)
        deadline=time.monotonic()+min(1200,request.get('maxWallSeconds',7200))
        while not (directory/'ready.json').exists():
            if service is not None and service.poll() is not None:raise RuntimeError('policy_service_initialization_failed')
            if time.monotonic()>deadline:raise TimeoutError('policy_initialization_timeout')
            write(run/'progress.json',dict(stage='initializing',completed=0,total=len(selected),heartbeat_unix=time.time()));time.sleep(3)
        native_log=(run/'native.log').open('ab')
        native=subprocess.Popen([native_python,str(CODE/'scripts/run_isaac_parallel_pickplace.py'),'--config',str(run/'native_config.json')],cwd=ROOT,
            stdin=subprocess.DEVNULL,stdout=native_log,stderr=subprocess.STDOUT,env={**os.environ,'CUDA_VISIBLE_DEVICES':os.environ.get('STUDIO_SIM_GPU','0,1'),'OMNI_KIT_ACCEPT_EULA':'YES','PYTHONUNBUFFERED':'1'})
        write(run/'native.launch.json',dict(pid=native.pid,startedAt=time.time(),configSha256=sha(run/'native_config.json')))
        while native.poll() is None:
            if service is not None and service.poll() is not None:raise RuntimeError('policy_service_disappeared')
            if time.time()-started>request.get('maxWallSeconds',7200):
                (run/'stop_requested').touch()
                if time.time()-started>request.get('maxWallSeconds',7200)+15:raise TimeoutError('native_evaluation_wall_budget_exceeded')
            progress=[]
            for p in (run/'native/rooms').glob('*/policy_progress.json'):
                try:progress.append(json.loads(p.read_text()))
                except ValueError:pass
            done=len(list((run/'native/rooms').glob('*/worker_result.json')))
            native_state=json.loads((run/'native/status.json').read_text()) if (run/'native/status.json').exists() else {}
            phase='native_policy' if native_state.get('frames',0)>0 or progress else 'initializing_native'
            write(run/'progress.json',dict(stage=phase,completed=done,total=len(selected),roomProgress=progress,heartbeat_unix=time.time(),eta_seconds=None,eta_scope='requires_native_speed_measurement'))
            time.sleep(.5 if request.get('liveEvaluation') else 3)
        rc=native.wait();write(run/'native.exit.json',dict(returncode=rc,actual_child_wait=True,pid=native.pid,endedAt=time.time()))
        if rc:raise RuntimeError('native_engine_failed:'+str(rc))
        rows=[]
        for index,case in enumerate(selected):
            room=run/'native/rooms'/f'room_{index:03d}'
            try:row=audit_room(room)
            except Exception as exc:row=dict(passed=False,failure_category='infrastructure_failure',reason=repr(exc))
            row.update(roomId=case['original_room_id'],parentSplit=case['parent_split']);write(room/'policy_audit.json',row);rows.append(row)
        report=dict(modelFamily=entry.get('family','pi05'),transport=request.get('transport','file'),policyHorizon=entry.get('modelConfig',{}).get('horizon',20),temporalComparison=entry.get('modelConfig',{}).get('temporalComparison','20 Hz training / 20 Hz evaluation'),gripperMapping=entry.get('modelConfig',{}).get('gripperUnit','m'),scope='training_scene_native_closed_loop_diagnostic',checkpointId=entry['id'],totalRooms=len(rows),passedPairs=sum(r['passed'] for r in rows),
            modelFailures=sum(r['failure_category']=='model_failure' for r in rows),infrastructureFailures=sum(r['failure_category']=='infrastructure_failure' for r in rows),rooms=rows,
            teacherFallback=False,trainingEligible=False,heldOutGeneralization=False,framesPerAction=request['framesPerAction'],fps=20,
            maxSimulationSeconds=request.get('maxSimulationSeconds'),inferenceTimeoutSeconds=request.get('inferenceTimeoutSeconds'),maxWallSeconds=request.get('maxWallSeconds'),elapsedWallSeconds=time.time()-started,wallTimingIncludes=['model_initialization','native_initialization','inference','physics','render','encoding'],baseActuatorMask='fixed_episode_base')
        evaluated=report['passedPairs']+report['modelFailures']
        report.update(evaluatedRooms=evaluated,successRate=report['passedPairs']/evaluated if evaluated else None,successRateDenominator='passedPairs + modelFailures; infrastructure failures excluded',evaluationCoverage=evaluated/len(rows) if rows else 0)
        report['runtimeProfile']=request.get('runtimeProfile','baseline')
        report['nativeTiming']=json.loads((run/'native/status.json').read_text())
        if request.get('actionSafetyMode') in ('clip_diagnostic','robot_limits'):
            report.update(actionSafetyMode=request['actionSafetyMode'],pureModelSuccessEligible=False,diagnosticPassedPairs=report['passedPairs'],passedPairs=0,successRate=None,successRateDenominator='Excluded: explicit action clipping diagnostic')
        else:report.update(actionSafetyMode='strict',pureModelSuccessEligible=True)
        write(run/'report.json',report)
        (run/'native_videos.txt').write_text('\n'.join(str(p) for p in sorted((run/'native').rglob('*.mp4')))+'\n')
        write(run/'progress.json',dict(stage='completed',completed=len(rows),total=len(rows),heartbeat_unix=time.time()))
    finally:
        if not request.get('externalService'):(directory/'stop').touch()
        for label,process in [('native',native),('policy',service)]:
            if process is None:continue
            if process.poll() is None:
                try:process.wait(timeout=15 if label=='policy' else .1)
                except subprocess.TimeoutExpired:process.terminate()
            try:rc=process.wait(timeout=15)
            except subprocess.TimeoutExpired:process.kill();rc=process.wait()
            write(run/(label+'.exit.json'),dict(returncode=rc,actual_child_wait=True,pid=process.pid,endedAt=time.time()))
        service_log.close()
        if native_log:native_log.close()


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);p.add_argument('--serve',action='store_true');p.add_argument('--native-python');args=p.parse_args()
    if args.serve:serve(args.run)
    else:evaluate(args.run,args.native_python)
