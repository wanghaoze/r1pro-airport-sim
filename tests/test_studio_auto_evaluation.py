"""Post-training gating and restart-safe evaluation tests; no GPU required."""
from pathlib import Path
import sys
import pytest

ROOT=Path(__file__).resolve().parents[1]
GPU=ROOT/'apps/scene-agent/gpu'
if not GPU.exists():GPU=ROOT/'gpu'
sys.path.insert(0,str(GPU))
import studio_backend as b
import auto_evaluation as auto


@pytest.fixture
def setup(tmp_path,monkeypatch):
    current=tmp_path/'runs/current';current.mkdir(parents=True)
    jobs=tmp_path/'jobs';jobs.mkdir()
    registry=tmp_path/'registry.json';b.write(registry,{'real_pickplace_v2':{}})
    monkeypatch.setattr(b,'CURRENT',current);monkeypatch.setattr(b,'JOBS',jobs);monkeypatch.setattr(b,'REGISTRY',registry)
    entries=[]
    def checkpoint(root,updates,identifier):
        cp=root/f'checkpoint/{updates-1}'
        for name in ['_CHECKPOINT_METADATA','params/manifest.ocdbt','assets/data/norm_stats.json']:
            path=cp/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('{}')
        (cp/'train_state').mkdir()
        entries.append(dict(id=identifier,updates=updates,run=str(root),checkpoint=str(cp),label=f'{identifier} {updates}',spec={'dataset_repo_id':'data'},receiptSha256='receipt'))
    checkpoint(current,100,'cp_old');checkpoint(current,10000,'cp_final')
    checkpoint(tmp_path/'real_only_pi05_20261012_v1',10000,'cp_real')
    monkeypatch.setattr(b,'checkpoints',lambda:entries)
    b.write(current/'inputs.json',{'training_steps':10000})
    b.write(current/'training_status.json',{'actual_completed_updates':10000})
    return current,jobs,entries


def register():
    return b.enqueue(dict(id='auto_current_123',kind='evaluation.auto',payload=auto.payload()))


def test_no_early_evaluation_without_successful_exit(setup):
    current,jobs,_=setup;register();auto.reconcile(b)
    assert len(list(jobs.glob('*/request.json')))==1
    assert b.read(jobs/'auto_current_123/status.json')['status']=='waiting_training'
    b.write(current/'train_10000_attempt_0.exit.json',dict(actual_child_wait=True,returncode=1))
    auto.reconcile(b);assert len(list(jobs.glob('*/request.json')))==1
    b.write(current/'train_10000_attempt_1.exit.json',dict(actual_child_wait=True,returncode=0))
    auto.reconcile(b);assert len(list(jobs.glob('*/request.json')))==3


def test_latest_final_checkpoint_and_restart_idempotency(setup):
    current,jobs,entries=setup
    b.write(current/'train_10000_attempt_0.exit.json',dict(actual_child_wait=True,returncode=0))
    register();auto.reconcile(b)
    binding=b.read(jobs/'auto_current_123/selection.json')
    assert binding['checkpointId']=='cp_final'
    auto.reconcile(b);assert len(list(jobs.glob('*/request.json')))==3
    assert binding==b.read(jobs/'auto_current_123/selection.json')
    requests=[b.read(p) for p in jobs.glob('*/request.json')]
    vla=next(r for r in requests if r['kind']=='evaluation.vla')['payload']
    mse=next(r for r in requests if r['kind']=='evaluation.mse')['payload']
    assert vla['roomIds']==list(range(32)) and vla['teacherFallback'] is False
    assert mse['checkpointIds']==['cp_final','cp_real'] and mse['split']=='test'


def test_final_step_with_only_partial_checkpoint_still_waits(setup):
    current,jobs,entries=setup
    entries[:]=[c for c in entries if c['id']!='cp_final']
    b.write(current/'train_10000_attempt_0.exit.json',dict(actual_child_wait=True,returncode=0))
    register();auto.reconcile(b)
    assert b.read(jobs/'auto_current_123/status.json')['status']=='waiting_training'


def test_preserve_zero_success_and_independent_mse_failure(setup):
    current,jobs,_=setup
    b.write(current/'train_10000_attempt_0.exit.json',dict(actual_child_wait=True,returncode=0))
    register();auto.reconcile(b);binding=b.read(jobs/'auto_current_123/selection.json')
    report=dict(passedPairs=0,modelFailures=31,infrastructureFailures=1,totalRooms=32,successRate=0.)
    b.write(jobs/binding['vlaJobId']/'status.json',dict(status='completed',report=report))
    b.write(jobs/binding['mseJobId']/'status.json',dict(status='failed',message='inference failed'))
    auto.reconcile(b);state=b.read(jobs/'auto_current_123/status.json')
    assert state['status']=='failed' and state['report']['vla']['report']==report
    auto.reconcile(b);assert len(list(jobs.glob('*/request.json')))==3


def test_new_training_opt_in_and_opt_out(setup):
    _,jobs,_=setup
    for identifier,enabled in [('train_enabled',True),('train_disabled',False)]:
        b.enqueue(dict(id=identifier,kind='training.create',payload=dict(datasets=['real_pickplace_v2'],realPercent=100,steps=500,rewardEnabled=False,autoEvaluate=enabled)))
    auto.reconcile(b);auto.reconcile(b)
    policies=auto.summaries(b)
    assert len(policies)==1 and policies[0]['payload']['trainingRun']=='train_enabled'
    assert policies[0]['status']=='waiting_training'


def test_reject_unregistered_path_and_modified_contract(setup):
    for config in [auto.payload('../../etc'),dict(auto.payload(),teacherFallback=True)]:
        with pytest.raises(ValueError):b.enqueue(dict(id='auto_bad_123',kind='evaluation.auto',payload=config))


def test_custom_training_requires_its_own_wait_receipt(setup):
    _,jobs,entries=setup
    run=jobs/'train_custom'/ 'training';run.mkdir(parents=True)
    b.write(run/'inputs.json',{'training_steps':500});b.write(run/'training_status.json',{'actual_completed_updates':500})
    cp=dict(entries[1],run=str(run),updates=500,id='cp_custom');entries.append(cp)
    assert auto.final_checkpoint(b,run,entries) is None
    b.write(run.parent/'train.exit.json',dict(actual_child_wait=True,returncode=0))
    assert auto.final_checkpoint(b,run,entries)['id']=='cp_custom'
