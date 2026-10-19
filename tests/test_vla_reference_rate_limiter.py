from types import SimpleNamespace
import hashlib
import numpy as np
import pytest
from r1pro_teleop.vla.executor import ActionBounds,ReferenceRateLimiter,VLAOperationExecutor
from r1pro_teleop.vla.policy import Pi05Policy,PolicyContract,PolicyError


def limiter(tmp_path):
    bounds=ActionBounds(-np.ones(19),np.ones(19))
    return ReferenceRateLimiter(np.full(19,.4),np.full(19,.8),tmp_path/'rate'),bounds


def test_initial_measured_inside_physical_outside_margin_recovers_continuously(tmp_path):
    physical=ActionBounds(-np.ones(19),np.ones(19))
    targets=ActionBounds(np.full(19,-.985),np.full(19,.985))
    lim=ReferenceRateLimiter(np.full(19,.4),np.full(19,.8),tmp_path,physical_bounds=physical)
    measured=np.full(19,-.995,dtype=np.float32);initial=measured.astype(float).copy()
    commands=[initial]
    for step in range(60):
        cmd=command(lim,targets,-.9,step,measured)
        commands.append(cmd.copy())
    commands=np.asarray(commands);velocity=np.diff(commands,axis=0)/lim.dt
    acceleration=np.diff(np.concatenate((np.zeros((1,19)),velocity)),axis=0)/lim.dt
    assert np.max(np.abs(velocity))<=.4+1e-8
    assert np.max(np.abs(acceleration))<=.8+1e-8
    assert commands[1,0]<targets.lower[0]  # No hidden instantaneous clamp.
    assert np.min(commands)>=physical.lower[0]
    assert lim.stats['margin_recovery_complete']
    assert lim.stats['margin_recovery_steps']>1
    np.testing.assert_array_equal(measured,initial.astype(np.float32))
    np.testing.assert_allclose(lim.stats['first_command_measured_velocity'],velocity[0])
    np.testing.assert_allclose(lim.stats['first_command_measured_acceleration'],acceleration[0])
    with np.load(tmp_path/'step_000000.npz') as artifact:
        assert np.min(artifact['command_margin_deficit'])>0
        np.testing.assert_array_equal(artifact['measured_state'],initial)


def test_initial_actual_physical_violation_is_rejected_and_target_margin_remains_hard(tmp_path):
    physical=ActionBounds(-np.ones(19),np.ones(19))
    target=ActionBounds(np.full(19,-.985),np.full(19,.985))
    lim=ReferenceRateLimiter(np.full(19,.4),np.full(19,.8),tmp_path,physical_bounds=physical)
    with pytest.raises(PolicyError,match='outside_joint_limits'):
        command(lim,target,0.,0,np.full(19,-1.001))
    with pytest.raises(PolicyError,match='outside_joint_limits'):
        command(lim,target,.99,0,np.zeros(19))
    assert lim.stats['submitted_rows']==0


def command(lim,bounds,target,step,measured=None):
    target=np.full(19,target,dtype=np.float32)
    return lim.submit(target,target,np.zeros(19) if measured is None else measured,bounds,
                      step=step,checkpoint_id='test')[0]


def test_accumulated_reference_speed_acceleration_and_static_goal_no_overshoot(tmp_path):
    lim,bounds=limiter(tmp_path)
    commands=[np.zeros(19)]
    for step in range(100):commands.append(command(lim,bounds,.7,step))
    commands=np.asarray(commands)
    velocity=np.diff(commands,axis=0)/lim.dt
    acceleration=np.diff(np.concatenate((np.zeros((1,19)),velocity)),axis=0)/lim.dt
    assert np.max(np.abs(velocity))<=.4+1e-8
    assert np.max(np.abs(acceleration))<=.8+1e-8
    assert np.max(commands)<=np.float32(.7)
    np.testing.assert_allclose(commands[-1],.7,atol=1e-6)


def test_direction_reversal_brakes_to_zero_before_opposite_velocity(tmp_path):
    lim,bounds=limiter(tmp_path)
    for step in range(30):command(lim,bounds,.7,step)
    velocities=[]
    for step in range(30,80):
        command(lim,bounds,-.7,step);velocities.append(lim.velocity[0])
    first_negative=next(i for i,v in enumerate(velocities) if v<0)
    assert first_negative>0 and velocities[first_negative-1]==0
    assert np.max(np.abs(np.diff(velocities)/lim.dt))<=.8+1e-8
    assert lim.stats['max_target_overshoot_by_channel'][0]>0


def test_jittered_target_inside_stopping_distance_is_recorded_not_rejected(tmp_path):
    lim,bounds=limiter(tmp_path)
    for step in range(20):command(lim,bounds,.8,step)
    new_target=lim.position[0]+.0001
    before=lim.position.copy()
    cmd=command(lim,bounds,new_target,20)
    assert cmd[0]>new_target
    assert lim.stats['max_target_overshoot_by_channel'][0]>0
    assert cmd[0]-new_target<=lim.stats['max_stopping_distance_by_channel'][0]+1e-6
    bounds.validate(cmd[None,:])


def test_physical_bounds_are_kept_by_early_discrete_braking(tmp_path):
    lim,bounds=limiter(tmp_path)
    cmds=[command(lim,bounds,1.,step) for step in range(120)]
    bounds.validate(np.asarray(cmds))
    assert np.max(cmds)<=1 and lim.velocity[0]==0


def test_initial_reference_uses_measured_state_not_stale_sim_target(tmp_path):
    lim,bounds=limiter(tmp_path)
    measured=np.full(19,.2)
    cmd=command(lim,bounds,.9,0,measured=measured)
    assert np.max(np.abs(cmd-measured))<=.8*lim.dt**2+1e-8
    assert lim.stats['initial_measured_state']==measured.tolist()


def runtime_fixture(tmp_path,fail_tick=False):
    state=np.zeros(16,dtype=np.float32);base=np.zeros(3,dtype=np.float32)
    sim=SimpleNamespace(target=np.full(16,.9),base_target=np.full(3,.9),
        state=lambda:state.copy(),base_joint_state=lambda:base.copy(),image=lambda _:np.zeros((2,2,3),np.uint8))
    runtime=SimpleNamespace(cfg=SimpleNamespace(fps=20),sim=sim,steps=0)
    trace=[]
    def tick():
        trace.append(np.concatenate((sim.target,sim.base_target)).copy())
        if fail_tick:raise RuntimeError('actual physics guard')
        state[:]=sim.target;base[:]=sim.base_target;runtime.steps+=1
    runtime.tick=tick
    raw=np.full((2,19),.7,np.float32)
    policy=Pi05Policy(SimpleNamespace(infer=lambda obs:{'actions':raw.copy()}),
                     PolicyContract('test',action_horizon=2,action_width=19))
    lim,bounds=limiter(tmp_path);decisions=[]
    executor=VLAOperationExecutor(runtime,policy,bounds,execute_steps=1,max_operation_steps=2,
                                   rate_limiter=lim,on_decision=decisions.append)
    return runtime,executor,lim,decisions,trace


def test_zero_expert_opening_executes_with_measured_positive_finger_minimum(tmp_path):
    # Existing teacher uses opening=0; MuJoCo saturates each finger ctrl at
    # .002. Measured separation therefore stays .004 without altering the
    # valid command contract or relabelling the raw expert action.
    state=np.zeros(16,np.float32);state[[7,15]]=.004
    sim=SimpleNamespace(target=state.copy(),base_target=np.zeros(3),state=lambda:state.copy(),
        base_joint_state=lambda:np.zeros(3),image=lambda _:np.zeros((2,2,3),np.uint8))
    runtime=SimpleNamespace(cfg=SimpleNamespace(fps=20),sim=sim,steps=0);trace=[];finger_ctrl=[]
    def tick():
        trace.append(np.concatenate((sim.target,sim.base_target)).copy())
        finger_ctrl.append(np.clip(sim.target[[7,15]]/2,.002,.05))
        state[:]=sim.target;state[[7,15]]=2*finger_ctrl[-1];runtime.steps+=1
    runtime.tick=tick
    lower=-np.ones(19);upper=np.ones(19);lower[[7,15]]=0.;upper[[7,15]]=.1
    bounds=ActionBounds(lower,upper)
    lim=ReferenceRateLimiter(np.full(19,.4),np.full(19,.8),tmp_path/'rate',physical_bounds=bounds)
    expert_action=np.zeros((2,19),np.float32);decisions=[]
    policy=Pi05Policy(SimpleNamespace(infer=lambda _:dict(actions=expert_action.copy())),
                     PolicyContract('test',action_horizon=2,action_width=19))
    executor=VLAOperationExecutor(runtime,policy,bounds,execute_steps=1,max_operation_steps=10,
                                  rate_limiter=lim,on_decision=decisions.append)
    assert executor.execute_operation(SimpleNamespace(tray=0,slot=0),'Close.',lambda r,_:r.steps==10)
    np.testing.assert_allclose(trace[-1][[7,15]],0.,atol=1e-12)
    np.testing.assert_allclose(state[[7,15]],.004)
    assert all(np.all(d['actions']==expert_action) for d in decisions)
    assert all(np.all(ctrl==np.float32(.002)) for ctrl in finger_ctrl)
    assert 'gripper_declared_opening_command' in lim.contract()['reference_bounds_semantics']
    with np.load(tmp_path/'rate/step_000009.npz') as artifact:
        assert artifact['raw_action'][7]==0.
        assert abs(artifact['rate_limited_action'][7])<1e-12


def test_cross_chunk_and_node_state_persists_raw_dagger_and_actual_trace_are_distinct(tmp_path):
    runtime,executor,lim,decisions,trace=runtime_fixture(tmp_path)
    op=SimpleNamespace(tray=0,slot=0)
    executor.execute_operation(op,'Navigate.',lambda r,op:r.steps==2)
    previous=lim.position.copy()
    executor.execute_operation(op,'Grasp.',lambda r,op:r.steps==4)
    assert lim.stats['submitted_rows']==4 and lim.stats['executed_rows']==4
    assert len(decisions)==4 and all(np.all(d['actions']==np.float32(.7)) for d in decisions)
    assert all(np.all(d['servo_actions']==np.float32(.7)) for d in decisions)
    assert all(d['servo_actions_stage'].endswith('not_executed_chunk') for d in decisions)
    assert lim.position[0]>previous[0]
    velocity=np.diff(np.concatenate((np.zeros((1,19)),np.asarray(trace))),axis=0)/lim.dt
    assert np.max(np.abs(velocity))<=.4+1e-8
    artifact=tmp_path/'rate/step_000003.npz'
    with np.load(artifact) as saved:
        np.testing.assert_array_equal(saved['rate_limited_action'],trace[-1])
        assert np.all(saved['raw_action']==np.float32(.7))


def test_failed_physical_tick_keeps_submitted_reference_evidence_not_completed_counter(tmp_path):
    runtime,executor,lim,decisions,trace=runtime_fixture(tmp_path,fail_tick=True)
    with pytest.raises(RuntimeError,match='actual physics guard'):
        executor.execute_operation(SimpleNamespace(tray=0,slot=0),'Navigate.',lambda *_:False)
    assert lim.stats['submitted_rows']==1 and lim.stats['executed_rows']==0
    assert len(trace)==1 and (tmp_path/'rate/step_000000.npz').is_file()


def test_invalid_rate_caps_and_nonfinite_reference_are_rejected(tmp_path):
    with pytest.raises(PolicyError,match='invalid_reference_rate_caps'):
        ReferenceRateLimiter(np.full(19,np.nan),np.ones(19),tmp_path)
    lim,bounds=limiter(tmp_path)
    with pytest.raises(PolicyError,match='invalid_rate_reference'):
        lim.submit(np.full(19,np.nan),np.zeros(19),np.zeros(19),bounds,step=0,checkpoint_id='test')
    assert lim.stats['submitted_rows']==0


def test_genuinely_infeasible_physical_braking_is_hard_failure_before_submission(tmp_path):
    lim,bounds=limiter(tmp_path)
    # An invalid incoming reference state cannot fit its stopping distance
    # before the physical upper bound. Do not mask that with an abrupt stop.
    lim.position=np.full(19,.999);lim.velocity=np.full(19,.396)
    with pytest.raises(PolicyError,match='physical_braking_infeasible'):
        command(lim,bounds,1.,0)
    assert lim.stats['submitted_rows']==0 and not (tmp_path/'rate').exists()


def test_observer_contract_is_a_copy_of_reported_caps(tmp_path):
    lim,bounds=limiter(tmp_path)
    contract=lim.contract();contract['velocity_caps'][0]=999
    assert lim.contract()['velocity_caps'][0]==.4
