from types import SimpleNamespace
import hashlib
import numpy as np
import pytest
from r1pro_teleop.vla.executor import ActionBounds,ServoProjection,VLAOperationExecutor,ReferenceRateLimiter
from r1pro_teleop.vla.policy import Pi05Policy,PolicyContract,PolicyError


def fixture(tmp_path,raw,enabled=True):
    lower=-np.ones(19);upper=np.ones(19);lower[[7,15]]=0.;upper[[7,15]]=.1
    bounds=ActionBounds(lower,upper)
    sim=SimpleNamespace(target=np.zeros(16),base_target=np.zeros(3),state=lambda:np.zeros(16),
        base_joint_state=lambda:np.zeros(3),image=lambda _:np.zeros((2,2,3),np.uint8))
    runtime=SimpleNamespace(cfg=SimpleNamespace(fps=20),sim=sim,steps=0)
    actual=[];decisions=[];events=[]
    def tick():
        actual.append(np.concatenate((sim.target,sim.base_target)).copy());runtime.steps+=1
    runtime.tick=tick
    policy=Pi05Policy(SimpleNamespace(infer=lambda _:{'actions':raw}),
                     PolicyContract('test',action_horizon=len(raw),action_width=19))
    executor=VLAOperationExecutor(runtime,policy,bounds,execute_steps=1,max_operation_steps=1,
        projection=ServoProjection(tmp_path/'projection') if enabled else None,
        on_decision=decisions.append,on_chunk=events.append)
    return executor,runtime,actual,decisions,events


def test_small_negative_gripper_projects_but_keeps_raw_dagger_prediction(tmp_path):
    raw=np.zeros((2,19),np.float32);raw[:,7]=-.0001
    executor,runtime,actual,decisions,events=fixture(tmp_path,raw)
    executor.execute_operation(SimpleNamespace(tray=0,slot=0),'Grasp.',lambda r,op:r.steps==1)
    assert actual[0][7]==0 and decisions[0]['actions'][0,7]<0
    assert decisions[0]['servo_actions'][0,7]==0
    stats=executor.projection_stats
    assert stats['projected_chunks']==1 and stats['projected_action_rows']==2
    assert stats['executed_projected_rows']==1 and stats['raw_policy_unmodified'] is False
    artifact=tmp_path/'projection/chunk_000000.npz'
    with np.load(artifact) as arrays:
        np.testing.assert_array_equal(arrays['raw_actions'],raw)
        assert arrays['servo_actions'][0,7]==0 and arrays['projection_mask'][0,7]
    event=events[-1]
    assert event['projection_sha256']==hashlib.sha256(artifact.read_bytes()).hexdigest()
    assert not any(isinstance(v,np.ndarray) for v in event.values())


@pytest.mark.parametrize('column,value',[(0,1.01),(7,-.001),(15,.101),(16,1.01),(17,-1.01),(18,1.04)])
def test_small_declared_axis_error_projects_into_original_bounds(tmp_path,column,value):
    raw=np.zeros((2,19),np.float32);raw[:,column]=value
    executor,runtime,actual,_,_=fixture(tmp_path,raw)
    executor.execute_operation(SimpleNamespace(tray=0,slot=0),'Move.',lambda r,op:r.steps==1)
    executor.bounds.validate(np.asarray(actual))
    assert executor.projection_stats['projected_channels']==2


@pytest.mark.parametrize('column,value',[(0,1.04),(7,-.003),(15,.104),(16,1.03),(17,-1.03),(18,1.06)])
def test_large_errors_reject_complete_chunk_before_tick_and_preserve_raw_failure(tmp_path,column,value):
    raw=np.zeros((2,19),np.float32);raw[-1,column]=value
    executor,runtime,actual,decisions,_=fixture(tmp_path,raw)
    with pytest.raises(PolicyError,match='projection_envelope'):
        executor.execute_operation(SimpleNamespace(tray=0,slot=0),'Move.',lambda *_:False)
    assert not actual and not decisions and runtime.steps==0
    path=tmp_path/'projection/rejected_chunk_000000.npz'
    with np.load(path) as evidence:
        np.testing.assert_array_equal(evidence['raw_actions'],raw)
        assert 'projection_envelope' in str(evidence['rejection_code'])
        assert 'servo_actions' not in evidence
    assert executor.projection_stats['rejected_chunk_sha256']==hashlib.sha256(path.read_bytes()).hexdigest()


def test_nan_remains_hard_failure_with_projection_enabled(tmp_path):
    raw=np.zeros((2,19),np.float32);raw[-1,7]=np.nan
    executor,runtime,actual,decisions,_=fixture(tmp_path,raw)
    with pytest.raises(PolicyError,match='invalid_action_chunk'):
        executor.execute_operation(SimpleNamespace(tray=0,slot=0),'Move.',lambda *_:False)
    assert not actual and not decisions


def test_default_off_preserves_strict_negative_opening_rejection(tmp_path):
    raw=np.zeros((2,19),np.float32);raw[:,7]=-.0001
    executor,runtime,actual,decisions,_=fixture(tmp_path,raw,enabled=False)
    with pytest.raises(PolicyError,match='outside_joint_limits'):
        executor.execute_operation(SimpleNamespace(tray=0,slot=0),'Move.',lambda *_:False)
    assert not actual and not decisions and not (tmp_path/'projection').exists()


def test_projection_artifacts_are_exclusive_and_envelopes_cannot_expand(tmp_path):
    with pytest.raises(PolicyError,match='invalid_servo_projection_envelope'):
        ServoProjection(tmp_path/'p',gripper_tolerance_m=.01)
    raw=np.zeros((2,19),np.float32)
    executor,runtime,_,_,_=fixture(tmp_path,raw)
    (tmp_path/'projection').mkdir()
    (tmp_path/'projection/chunk_000000.npz').write_bytes(b'old evidence')
    with pytest.raises(FileExistsError):
        executor.execute_operation(SimpleNamespace(tray=0,slot=0),'Move.',lambda *_:False)
    assert runtime.steps==0


def test_explicit_saturation_clips_large_finite_raw_retains_severity_and_rate_caps(tmp_path):
    raw=np.full((2,19),100.,np.float32);raw[:,[7,15]]=-10.
    executor,runtime,actual,decisions,_=fixture(tmp_path,raw)
    executor.projection=ServoProjection(tmp_path/'projection',mode='actuator_saturation')
    lim=ReferenceRateLimiter(np.full(19,.4),np.full(19,.8),tmp_path/'rate')
    executor.rate_limiter=lim;executor.rate_limit_stats=lim.stats
    executor.execute_operation(SimpleNamespace(tray=0,slot=0),'Move.',lambda r,_:r.steps==1)
    np.testing.assert_array_equal(decisions[0]['actions'],raw)
    executor.bounds.validate(decisions[0]['servo_actions'])
    assert np.max(np.abs(actual[0]))<=.8*.05**2
    assert executor.projection_stats['saturated_channel_fraction']==1.
    assert max(executor.projection_stats['max_normalized_severity_by_channel'])>1.
    assert not executor.projection_stats['raw_policy_unmodified']
    with np.load(tmp_path/'projection/chunk_000000.npz') as f:
        assert str(f['mode'])=='actuator_saturation'
        np.testing.assert_array_equal(f['raw_actions'],raw)
        assert f['projection_mask'].all()
        assert np.max(f['normalized_saturation_severity'])>1.


@pytest.mark.parametrize('invalid',[np.nan,np.inf,-np.inf])
def test_saturation_never_accepts_nonfinite(invalid,tmp_path):
    raw=np.zeros((2,19),np.float32);raw[0,0]=invalid
    projection=ServoProjection(tmp_path,mode='actuator_saturation')
    with pytest.raises(PolicyError,match='invalid_mobile19'):
        projection.project(raw,ActionBounds(-np.ones(19),np.ones(19)))


def test_saturation_cannot_bypass_rate_limiter(tmp_path):
    executor,runtime,_,_,_=fixture(tmp_path,np.zeros((2,19),np.float32))
    with pytest.raises(PolicyError,match='requires_rate_limiter'):
        VLAOperationExecutor(runtime,executor.policy,executor.bounds,execute_steps=1,
            projection=ServoProjection(tmp_path,mode='actuator_saturation'))
