import json
from pathlib import Path
from types import SimpleNamespace
import subprocess
import pytest
from scripts import evaluate_action8_checkpoint_dual as dual


def fixture():
    protocol=dict(protocol_id='original50',main_denominator=50,scene_ids=[f's{i:02}' for i in range(50)],
        teacher_success_subset_scene_ids=[f's{i:02}' for i in range(22)])
    identity=dict(checkpoint_id='sha256:trained',prompt_mode='task_complete_action8_v1')
    plan=dual.static_plan(protocol,'GPU-explicit-second','frozen','corehash')
    receipts=[];reports=[]
    for worker in plan['workers']:
        receipts.append(dict(worker_index=worker['index'],registration_id=plan['registration_id'],
            checkpoint_id=identity['checkpoint_id'],assigned_scene_ids=worker['scene_ids'],
            service_pid_reaped=True,renderers_all_reaped=True,
            videos=[dict(scene_id=s,status='complete') for s in worker['scene_ids']]))
        reports.append(dict(checkpoint_metadata=identity,results=[dict(scene_id=s,frames=1,
            inverse_dynamics_calls=0,motion_backend='pi05',controller_source='vla_generated',
            task_completed=s in ('s00','s01'),strict_success=s=='s00') for s in worker['scene_ids']]))
    return protocol,plan,identity,receipts,reports


def test_static25_registration_and_true_global50_subset22():
    p,plan,identity,receipts,reports=fixture()
    assert [len(w['scene_ids']) for w in plan['workers']]==[25,25]
    assert set(plan['workers'][0]['scene_ids']).isdisjoint(plan['workers'][1]['scene_ids'])
    assert [w['port'] for w in plan['workers']]==[8766,8768]
    assert [w['egl_device'] for w in plan['workers']]==[1,0]
    summary,_,resume=dual.aggregate(p,plan,identity,receipts,reports)
    assert resume and summary['main_test']['denominator']==50
    assert summary['main_test']['approximate_success_rate']==2/50
    assert summary['teacher_success_subset']['denominator']==22
    assert summary['teacher_success_subset']['approximate_success_rate']==2/22
    changed=dual.static_plan(p,'GPU-explicit-second','newfrozen','newcore')
    assert changed['registration_id']!=plan['registration_id']


@pytest.mark.parametrize('mutation',['unreaped','identity','outside','duplicate','registration'])
def test_worker_receipt_errors_cannot_allow_resume(mutation):
    p,plan,i,receipts,reports=fixture()
    if mutation=='unreaped':receipts[1]['service_pid_reaped']=False
    if mutation=='identity':reports[1]['checkpoint_metadata']=dict(checkpoint_id='different')
    if mutation=='registration':receipts[1]['registration_id']='different'
    if mutation=='outside':reports[1]['results'][0]['scene_id']='s00'
    if mutation=='duplicate':reports[1]['results'].append(reports[1]['results'][0])
    with pytest.raises(ValueError):dual.aggregate(p,plan,i,receipts,reports)


def test_missing_case_and_infra_success_flag_keep_global_denominator_and_block_resume():
    p,plan,i,receipts,reports=fixture()
    reports[0]['results'][0].pop('inverse_dynamics_calls')
    reports[1]['results'].pop()
    summary,_,resume=dual.aggregate(p,plan,i,receipts,reports)
    assert not resume
    assert summary['main_test']['denominator']==50 and summary['main_test']['not_run']==1
    assert summary['main_test']['approximate_completed']==1
    assert summary['main_test']['raw_completed_flags']==2
    assert summary['main_test']['infrastructure_failures']==1


def test_missing_video_cannot_allow_resume():
    p,plan,i,receipts,reports=fixture();receipts[1]['videos'].pop()
    summary,_,resume=dual.aggregate(p,plan,i,receipts,reports)
    assert summary['status']=='evaluation_complete' and not resume


def test_explicit_second_gpu_and_environment_cpu_pin_removed(monkeypatch):
    p,_,_,_,_=fixture()
    with pytest.raises(ValueError):dual.static_plan(p,dual.serial.GPU_UUID,'r','sha')
    monkeypatch.setenv('JAX_PLATFORMS','cpu');monkeypatch.setenv('JAX_PLATFORM_NAME','cpu')
    worker=dual.static_plan(p,'GPU-second','r','sha')['workers'][1]
    env=dual.gpu_environment('r','client',worker)
    assert env['CUDA_VISIBLE_DEVICES']=='GPU-second' and env['MUJOCO_EGL_DEVICE_ID']=='0'
    assert 'JAX_PLATFORMS' not in env and 'JAX_PLATFORM_NAME' not in env


def test_guard_checks_owned_uuid_and_index_without_mutating_frozen_guard(tmp_path):
    path=tmp_path/'runs/vla_deploy_20261001/bc32_post_runtime_checks.py';path.parent.mkdir(parents=True)
    content='def own_gpu_rows(pid): return [{"index":1,"uuid":"GPU-second"}]\n'
    path.write_text(content)
    guard=dual.owned_guard(tmp_path,dict(index=1,gpu_uuid='GPU-second'))
    assert guard.checked_gpu_rows(123)[0]['index']==1
    guard.own_gpu_rows=lambda pid:[dict(index=0,uuid='GPU-second')]
    with pytest.raises(RuntimeError,match='different physical GPU'):guard.checked_gpu_rows(123)
    guard.own_gpu_rows=lambda pid:[dict(index=1,uuid='GPU-other')]
    with pytest.raises(RuntimeError):guard.checked_gpu_rows(123)
    assert path.read_text()==content


def test_worker_service_reaped_before_25_native_replays(tmp_path,monkeypatch):
    root=tmp_path/'frozen';root.mkdir();out=tmp_path/'step';out.mkdir()
    p,_,identity,_,_=fixture();p['source_collection']='source'
    core=tmp_path/'core';core.write_text('{}')
    plan=dual.static_plan(p,'GPU-second',root,dual.file_sha(core))
    dual.serial.exclusive(out/'dual_registration.json',plan)
    args=SimpleNamespace(controller_root=str(root),core_report=str(core),output=str(out),worker_index=1,
        gpu1_uuid='GPU-second',openpi_client_path='client',resource_hours=1,minimum_free_mib=1,
        vla_python='vla',sim_python='sim',training_status='immutable')
    monkeypatch.setattr(dual,'verified_setup',lambda a:(root,p,identity,{},[]))
    monkeypatch.setattr(dual.serial,'resource_rows',lambda:{'GPU-second':30000})
    class Socket:
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def connect_ex(self,*a):return 1
    monkeypatch.setattr(dual.socket,'socket',Socket)
    service=[];rendered=[];physical=[]
    class Guard:
        def verify_owned_identity(self,*a):pass
        def wait_owned_startup(self,*a):return dict(identity_verified=True)
        def checked_gpu_rows(self,*a):return [dict(index=1,uuid='GPU-second')]
        def terminate_owned(self,process,*a):process.returncode=0
        def monitor_owned(self,process,*a,**kw):process.wait()
    monkeypatch.setattr(dual,'owned_guard',lambda *a:Guard())
    def dump(path,value):path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value))
    class Process:
        def __init__(self,cmd,**kwargs):
            self.pid=123;self.returncode=None
            assert kwargs['env']['CUDA_VISIBLE_DEVICES']=='GPU-second'
            if 'serve_pi05_airport.py' in cmd[2]:service.append(self)
            elif 'evaluate_pi05_airport.py' in cmd[2]:
                ids=cmd[cmd.index('--scene-ids')+1:cmd.index('--port')];physical.extend(ids)
                assert ids==p['scene_ids'][1::2] and cmd[cmd.index('--port')+1]=='8768'
                base=Path(cmd[cmd.index('--output')+1]);rows=[]
                for sid in ids:
                    row=dict(scene_id=sid,frames=1,inverse_dynamics_calls=0,motion_backend='pi05',controller_source='vla_generated',task_completed=False)
                    attempt=base/'attempts'/sid/'a000';dump(attempt/'result.json',row);(attempt/'trace.h5').write_bytes(b'mock_not_physics');rows.append(row)
                dump(base/'rollout_report.json',dict(results=rows,checkpoint_metadata=identity,config=dict(replay_tolerance=1e-6)))
            else:
                assert service[0].returncode==0  # model allocation released before rendering
                rendered.append(cmd[cmd.index('--attempt')+1])
        def poll(self):return self.returncode
        def wait(self,**kw):self.returncode=0;return 0
    monkeypatch.setattr(dual.subprocess,'Popen',Process)
    monkeypatch.setattr(dual.subprocess,'run',lambda *a,**kw:subprocess.CompletedProcess(a,0,json.dumps(identity)+'\n'))
    monkeypatch.setattr(dual.serial,'verify_native_manifest',lambda *a:None)
    receipt=dual.worker_run(args)
    assert len(rendered)==len(physical)==25
    assert receipt['service_pid_reaped'] and receipt['renderers_all_reaped']
    assert receipt['training_resume_allowed'] is False
    assert 'main_test' not in receipt and 'approximate_success_rate' not in receipt


def test_failed_coordinator_preserves_partial_50_denominator(tmp_path):
    p,plan,identity,_,reports=fixture()
    path=tmp_path/'worker_0/episode_run/rollout_report.json';path.parent.mkdir(parents=True)
    path.write_text(json.dumps(reports[0]))
    summary=dual.partial_summary(p,plan,identity,tmp_path)
    assert summary['main_test']['denominator']==50
    assert summary['main_test']['attempted']==25 and summary['main_test']['not_run']==25
    assert summary['orchestration_failed'] and not summary['training_resume_allowed']
    reports[0]['checkpoint_metadata']=dict(checkpoint_id='wrong')
    path.write_text(json.dumps(reports[0]))
    summary=dual.partial_summary(p,plan,identity,tmp_path)
    assert summary['main_test']['attempted']==0 and summary['main_test']['not_run']==50
    assert len(summary['partial_reports_excluded'])==1
