import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch
import numpy as np
import pytest
from r1pro_teleop.vla.parallel_pickplace_training import balanced_mixed_schedule
from r1pro_teleop.vla.real_sim_data import mse_groups
from r1pro_teleop.real2sim.isaac_policy_pickplace import measured_pick,PlaceObserver,validate_actions

ROOT=Path(__file__).resolve().parents[1]
backend_path=ROOT/'apps/scene-agent/gpu/studio_backend.py'
if not backend_path.exists():backend_path=ROOT/'gpu/studio_backend.py'
spec=importlib.util.spec_from_file_location('studio_backend',backend_path)
backend=importlib.util.module_from_spec(spec);spec.loader.exec_module(backend)


@pytest.mark.parametrize('percent',[0,1,33,50,99,100])
def test_arbitrary_ratio_and_action_balance(percent):
    tasks=np.array([0,0,1,1]);real=tasks if percent else np.array([]);sim=tasks if percent<100 else np.array([])
    domains,indices=balanced_mixed_schedule(real,sim,steps=125,real_fraction=percent/100)
    assert np.sum(domains==0)==10*percent
    for domain in (0,1):
        sampled=tasks[indices[domains==domain]]
        assert abs(np.sum(sampled==0)-np.sum(sampled==1))<=1
    if percent==50:assert np.all(np.sum(domains==0,axis=1)==4)


def test_used_empty_domain_rejected():
    with pytest.raises(ValueError,match='used_domain'):balanced_mixed_schedule([],np.array([0,1]),steps=1,real_fraction=.01)


def test_mse_padding_and_units_are_separate():
    pred=np.zeros((2,20,19));truth=pred.copy();pred[:,:,0]=2;pred[:,:,[7,15]]=.002;pred[:,1:]=999
    valid=np.zeros((2,20),bool);valid[:,0]=True
    metrics=mse_groups(pred,truth,valid)
    assert metrics['arm_mse_rad2']==pytest.approx(4/14)
    assert metrics['gripper_mse_mm2']==pytest.approx(4)


def observation(z=1.,forces=(1.,1.),table=0.):
    return dict(finger_force=np.array([forces]),long_edge_sign=np.array([[-1,1]]),table_force=np.array([table]),tray_pose=np.array([[0.,0.,z,1,0,0,0]]),boundary_ok=np.array([True]),axis_error_rad=np.array([0.]))


def test_measured_pick_cannot_pass_without_actual_contact():
    assert measured_pick(observation(1.03),1.)
    assert not measured_pick(observation(1.03,(0.,0.)),1.)
    assert not measured_pick(observation(1.03,table=2.),1.)


def test_place_early_release_fails_and_stable_support_needs_ten_frames():
    table=dict(center_world=[0,0,0],dimensions_m=[1,1,1])
    gate=PlaceObserver(observation(1.1),table)
    with pytest.raises(ValueError,match='release_above'):gate.update(observation(1.1,(0,0)))
    gate=PlaceObserver(observation(1.001),table)
    assert all(not gate.update(observation(1.001,(0,0),1)) for _ in range(9))
    assert gate.update(observation(1.001,(0,0),1))


def test_nonfinite_or_out_of_range_is_rejected_without_clipping():
    model=SimpleNamespace(joint=lambda _:SimpleNamespace(id=0),jnt_limited=np.array([True]),jnt_range=np.array([[-.1,.1]]))
    chunk=np.zeros((20,19));chunk[0,0]=np.nan
    with pytest.raises(ValueError,match='invalid_policy'):validate_actions(chunk,model)
    chunk[0,0]=.2
    with pytest.raises(ValueError,match='mechanical_joint'):validate_actions(chunk,model)
    assert chunk[0,0]==.2


def test_eta_targets_total_not_checkpoint_and_expires(tmp_path):
    run=tmp_path/'run';run.mkdir();now=10000
    backend.write(run/'training_status.json',dict(stage='training',pid=10,heartbeat_unix=9999,actual_completed_updates=100,target_updates=1000,eta_seconds=200,metrics={'loss':.2}))
    backend.write(run/'pipeline_status.json',dict(stage='train_200'))
    with patch.object(backend.time,'time',return_value=now),patch.object(backend,'identity',return_value=dict(pid=10,state='S',command=str(run))):
        t=backend.telemetry(run,tmp_path/'history.json')
    assert t['secondsPerStep']==2 and t['eta']['lowSeconds']==1440 and t['milestoneEtaSeconds']==200
    with patch.object(backend.time,'time',return_value=11000),patch.object(backend,'identity',return_value=dict(pid=10,state='S',command=str(run))):
        t=backend.telemetry(run,tmp_path/'history.json')
    assert not t['live'] and t['eta'] is None


def test_job_freeze_and_no_unregistered_checkpoint(tmp_path):
    registry=tmp_path/'registry.json';backend.write(registry,{'real_pickplace_v2':{'domain':'real_world'}})
    job=dict(id='test_training_100',kind='training.create',payload=dict(datasets=['real_pickplace_v2'],realPercent=100,steps=500,rewardEnabled=False))
    with patch.object(backend,'JOBS',tmp_path/'jobs'),patch.object(backend,'REGISTRY',registry):
        first=backend.enqueue(job);assert first==backend.enqueue(job)
        job['payload']['steps']=501
        with pytest.raises(ValueError,match='conflict'):backend.enqueue(job)
    with patch.object(backend,'checkpoints',return_value=[]):
        with pytest.raises(ValueError,match='checkpoint_not_closed'):backend.validate_request(dict(id='test_evaluation_1',kind='evaluation.mse',payload={'checkpointIds':['../../etc/passwd']}))


def test_model_worker_does_not_import_teacher_or_use_solver():
    source=(ROOT/'r1pro_teleop/real2sim/isaac_policy_pickplace.py').read_text()
    assert 'DiversePickPlace' not in source and '.solve(' not in source and 'NativeTeacher' not in source
    assert "policy.infer(obs['policy_images'],state,prompt)" in source
