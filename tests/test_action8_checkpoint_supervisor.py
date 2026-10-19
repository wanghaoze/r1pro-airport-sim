import json
from pathlib import Path
from types import SimpleNamespace
import subprocess
from scripts import evaluate_action8_checkpoint as job


def dump(path,value):
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value))


def test_service_is_reaped_before_sequential_native4_and_resume_receipt(tmp_path,monkeypatch):
    monkeypatch.setenv('JAX_PLATFORMS','cpu')
    monkeypatch.setenv('JAX_PLATFORM_NAME','cpu')
    root=tmp_path/'frozen';root.mkdir();out=tmp_path/'evaluations/step_000010'
    checkpoint_status=tmp_path/'milestone.json';dump(checkpoint_status,{'actual':'saved'})
    protocol=dict(schema='unit_test_protocol',protocol_id='bound',main_denominator=50,
        scene_ids=[f's{i:02d}' for i in range(50)],teacher_success_subset_scene_ids=['s00','s01'],
        source_collection=str(tmp_path/'source'),milestones=[10,100,1000,10000,100000])
    protocol_path=tmp_path/'protocol.json';dump(protocol_path,protocol)
    core=tmp_path/'core.json';dump(core,dict(returncode=0,release=str(root)))
    handoff=tmp_path/'handoff.json';dump(handoff,dict(status='checkpoint_saved_trainer_exited',
        actual_completed_updates=10,training_status_sha256=job.file_sha(checkpoint_status),trainer_pid=2147483000))
    guard=root/'runs/vla_deploy_20261001/bc32_post_runtime_checks.py';guard.parent.mkdir(parents=True)
    guard.write_text('''def verify_owned_identity(*a): pass
def wait_owned_startup(*a): return {"identity_verified": True}
def checked_gpu_rows(*a): return [{'physical_index':0,'uuid':'test_owned_gpu'}]
def terminate_owned(process,*a):
    process.stopped=True
    process.returncode=0
def monitor_owned(process,command,cwd,evidence_path,**kw):
    process.wait()
''')
    monkeypatch.setattr(job,'frozen_dependency_inventory',lambda _: [{'path':'explicit_test_guard','sha256':'fixture'}])
    from scripts import serve_pi05_airport
    identity=dict(checkpoint_id='sha256:'+'a'*64,prompt_mode='task_complete_action8_v1',training_steps=10)
    monkeypatch.setattr(serve_pi05_airport,'verify_training_checkpoint',lambda _: (None,Path('checkpoint'),identity))
    monkeypatch.setattr(job,'verify_protocol',lambda p:p)
    monkeypatch.setattr(job,'resource_rows',lambda:{job.GPU_UUID:30000})
    class Socket:
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def connect_ex(self,*a):return 1
    monkeypatch.setattr(job.socket,'socket',Socket)
    calls=[];service=[None]
    class Process:
        def __init__(self,command,**kwargs):
            self.pid=100+len(calls);self.returncode=None;self.stopped=False
            calls.append(command)
            if 'serve_pi05_airport.py' in command[2]:
                assert 'JAX_PLATFORMS' not in kwargs['env'] and 'JAX_PLATFORM_NAME' not in kwargs['env']
                assert kwargs['env']['CUDA_VISIBLE_DEVICES']==job.GPU_UUID
                self.role='service';service[0]=self
            elif 'evaluate_pi05_airport.py' in command[2]:
                self.role='evaluation';rows=[]
                for sid in protocol['scene_ids']:
                    attempt=out/'episode_run/attempts'/sid/'a000'
                    row=dict(scene_id=sid,split='test',frames=1,task_completed=False,strict_success=False,
                        inverse_dynamics_calls=0,motion_backend='pi05',controller_source='vla_generated',
                        failure_code='vla_operation_step_budget_exhausted')
                    dump(attempt/'result.json',row);(attempt/'trace.h5').write_bytes(b'unit_test_trace_not_physics')
                    rows.append(row)
                dump(out/'episode_run/rollout_report.json',dict(results=rows,checkpoint_metadata=identity,
                    config=dict(replay_tolerance=1e-6)))
            else:
                self.role='renderer'
                assert service[0].stopped and service[0].returncode==0
                attempt=Path(command[command.index('--attempt')+1]);row=job.read(attempt/'result.json');refs=[]
                for camera in ('head_left','head_right','left_wrist','right_wrist'):
                    path=attempt/(camera+'.mp4');path.write_bytes(b'unit_test_not_encoded_media')
                    refs.append(dict(camera=camera,path=str(path),sha256=job.file_sha(path),frames=1,native=True))
                manifest=dict(status='complete',purpose='inspection_not_training_export',checkpoint_id=identity['checkpoint_id'],
                    frames=1,task_completed=False,trace_sha256=job.file_sha(attempt/'trace.h5'),
                    source_result_sha256=job.file_sha(attempt/'result.json'),references=refs)
                manifest.update({k:0. for k in ('replay_max_qpos_error','replay_max_qvel_error','replay_max_time_error',
                    'terminal_qpos_error','terminal_qvel_error','terminal_time_error')})
                dump(attempt/'manifest.json',manifest)
        def poll(self):return self.returncode
        def wait(self,**kwargs):self.returncode=0;return 0
    monkeypatch.setattr(job.subprocess,'Popen',Process)
    monkeypatch.setattr(job.subprocess,'run',lambda *a,**kw:subprocess.CompletedProcess(a,0,json.dumps(identity)+'\n'))
    args=SimpleNamespace(controller_root=str(root),output=str(out),protocol=str(protocol_path),
        core_report=str(core),training_status=str(checkpoint_status),completed_updates=10,
        trainer_handoff=str(handoff),minimum_free_mib=12000,port=8766,resource_hours=48,
        sim_python='sim',vla_python='vla',openpi_client_path='client',completion_receipt=str(tmp_path/'receipt.json'))
    receipt=job.run(args)
    assert receipt['training_resume_allowed'] and receipt['service_pid_reaped'] and receipt['renderers_all_reaped']
    assert len(calls)==52  # one service, one evaluation, then fifty sequential renderers
    report=job.read(out/'evaluation_summary.json')
    assert report['main_test']['denominator']==50 and report['main_test']['approximate_completed']==0
    assert report['main_test']['resource_truncations']==50
    assert (out.parent/'evaluation_index.json').is_file()
