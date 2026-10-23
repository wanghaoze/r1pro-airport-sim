"""No GPU or subprocess execution: repair mode must fail closed for training."""
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

GPU=Path(__file__).resolve().parents[1]/'apps/scene-agent/gpu'
sys.path.insert(0,str(GPU))
import studio_backend as b
import studio_job_runner as runner


@pytest.mark.parametrize('policy',[None,'broken','[]','null',json.dumps({'schema':'studio_maintenance_policy/1','trainingAllowed':'true'}),json.dumps({'schema':'wrong','trainingAllowed':True})])
def test_missing_or_invalid_policy_cannot_start_training(tmp_path,monkeypatch,policy):
    path=tmp_path/'policy.json'
    if policy is not None:path.write_text(policy)
    monkeypatch.setattr(b,'EXECUTION_POLICY',path)
    with pytest.raises(ValueError,match='training_disabled'):
        b.assert_training_allowed('training.create')
    for kind in ['evaluation.mse','evaluation.vla','evaluation.live','evaluation.auto']:
        b.assert_training_allowed(kind)


def test_shipped_policy_blocks_enqueue_even_with_payload_override(tmp_path,monkeypatch):
    monkeypatch.setattr(b,'JOBS',tmp_path/'jobs')
    with pytest.raises(ValueError,match='training_disabled'):
        b.enqueue(dict(id='blocked_training',kind='training.create',payload={'trainingAllowed':True}))
    assert not b.JOBS.exists()


def test_direct_runner_and_stage_cannot_bypass_repair_gate(tmp_path,monkeypatch):
    run=tmp_path/'run';run.mkdir()
    job=dict(id='blocked_training',kind='training.create',payload={})
    b.write(run/'request.json',job)
    monkeypatch.setattr(runner.subprocess,'Popen',lambda *a,**k:pytest.fail('training process started'))
    with pytest.raises(ValueError,match='training_disabled'):runner.train(run,job)
    with pytest.raises(ValueError,match='training_disabled'):runner.stage(run,'train',['never-execute'])
    assert not (run/'training').exists() and not (run/'train.log').exists()


def test_scheduler_blocks_preexisting_training_and_keeps_evaluation_eligible(tmp_path,monkeypatch):
    jobs=tmp_path/'jobs';monkeypatch.setattr(b,'JOBS',jobs)
    monkeypatch.setitem(sys.modules,'fcntl',SimpleNamespace(LOCK_EX=1,LOCK_NB=2,flock=lambda *a:None))
    monkeypatch.setitem(sys.modules,'auto_evaluation',SimpleNamespace(reconcile=lambda _:None))
    checked=[]
    monkeypatch.setitem(sys.modules,'execution_settings',SimpleNamespace(availability=lambda payload,kind:checked.append(kind)))
    for name,kind in [('old_training','training.create'),('existing_model_mse','evaluation.mse')]:
        b.write(jobs/name/'request.json',dict(id=name,kind=kind,payload={}))
        b.write(jobs/name/'status.json',dict(status='waiting_gpu'))
    spawned=[]
    monkeypatch.setattr(b.subprocess,'Popen',lambda argv,**kw:spawned.append(argv) or SimpleNamespace(pid=123))
    monkeypatch.setattr(b,'identity',lambda _:None)
    b.queue_tick()
    assert b.read(jobs/'old_training/status.json')['status']=='blocked'
    assert checked==['evaluation.mse']
    assert len(spawned)==1 and spawned[0][-1]==str(jobs/'existing_model_mse')
    b.queue_tick()
    assert len(spawned)==1  # Blocked training is not automatically retried.
