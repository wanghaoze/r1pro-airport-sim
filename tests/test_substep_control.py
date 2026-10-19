import numpy as np
import pytest
import mujoco
from r1pro_teleop.airport_fsm.substep_control import (
    PhysicsClock, sample_path_frame, sample_path_targets, require_c2_join, mapped_controls,
    AppliedControlJournal, execute_control_frame, replay_control_frame)
from r1pro_teleop.airport_fsm.trajectory import TimedJointPath, BlendedJointPath, CruiseJointPath


@pytest.mark.parametrize('kind', [TimedJointPath, BlendedJointPath, CruiseJointPath])
def test_samples_original_curve_including_internal_knots_without_refitting(kind):
    path=kind([[0.,0.],[.03,.01],[.12,-.02],[.2,.02]],1.,4.,30.)
    clock=PhysicsClock(.002);frames=37;previous=None
    for i in range(frames):
        frame=sample_path_frame(path,i,frames,clock)
        expected=path.evaluate((i*25+np.arange(1,26))/(frames*25),frames/20)
        for actual,want in zip((frame.position,frame.velocity,frame.acceleration,frame.jerk),expected):
            np.testing.assert_array_equal(actual,want)
        # Scalar and vectorized polynomial evaluation can differ by one float64
        # rounding unit across NumPy/BLAS platforms, without changing the curve.
        np.testing.assert_allclose(frame.position[-1],frame.end[0],rtol=0,atol=1e-14)
        if previous is not None:require_c2_join(previous,frame.start)
        previous=frame.end
    np.testing.assert_allclose(previous[0],[.2,.02])


def test_invalid_clock_and_discontinuous_new_path_are_rejected():
    with pytest.raises(ValueError,match='integer'):PhysicsClock(.003)
    zero=tuple(np.zeros(2) for _ in range(4))
    for order in range(3):
        wrong=list(zero);wrong[order]=np.ones(2)*.001
        with pytest.raises(ValueError,match=f'order {order}'):
            require_c2_join(zero,wrong)


def test_runtime_adapter_preserves_existing_endpoint_action_and_target_precision():
    path=BlendedJointPath([np.zeros(16),np.ones(16)*.2],1.,4.,30.)
    target=sample_path_targets(path,3,20,25,20)
    assert target.shape==(25,16) and target.dtype==np.float32
    np.testing.assert_array_equal(target[-1],path.evaluate(4/20,1.)[0].astype(np.float32))
    expected=path.evaluate((3*25+np.arange(1,26))/(20*25),1.)[0].astype(np.float32)
    np.testing.assert_array_equal(target,expected)


def test_mapping_preserves_untouched_actuators_and_gripper_half_aperture():
    pos=np.array([[.2,.04],[.3,.06]])
    baseline=np.array([7.,8.,9.,10.])
    actual=mapped_controls(pos,baseline,[0,2],[0,1],[1.,.5])
    np.testing.assert_array_equal(actual,[[.2,8.,.02,10.],[.3,8.,.03,10.]])
    assert not actual.flags.writeable
    np.testing.assert_array_equal(baseline,[7.,8.,9.,10.])
    with pytest.raises(ValueError,match='overlapping'):
        mapped_controls(pos,baseline,[0,0],[0,1])


def model_and_data():
    model=mujoco.MjModel.from_xml_string('''<mujoco><option timestep="0.002"/>
    <worldbody><geom type="plane" size="2 2 .1"/>
    <body pos="0 0 .05"><joint type="slide" axis="1 0 0"/>
    <geom type="sphere" size=".05" mass="1"/></body></worldbody>
    <actuator><position joint="0" kp="100" kv="4"/></actuator></mujoco>'''.replace(
        '<joint type=', '<joint name="slide" type=').replace('joint="0"','joint="slide"'))
    data=mujoco.MjData(model);mujoco.mj_forward(model,data)
    return model,data


def integration(model,data):
    kind=mujoco.mjtState.mjSTATE_INTEGRATION
    state=np.empty(mujoco.mj_stateSize(model,kind));mujoco.mj_getState(model,data,state,kind)
    return state


def restore(model,state,warmstart):
    data=mujoco.MjData(model)
    mujoco.mj_setState(model,data,state,mujoco.mjtState.mjSTATE_INTEGRATION)
    mujoco.mj_forward(model,data);data.qacc_warmstart[:]=warmstart
    return data


def test_true_mujoco_trace_controls_replay_each_frame_bitwise_without_resets():
    model,data=model_and_data();initial=integration(model,data);warm=data.qacc_warmstart.copy()
    clock=PhysicsClock(model.opt.timestep);path=BlendedJointPath([[0.],[.02],[.1]],.4,2.,10.)
    frames=20;recorded=[];states=[];guard_calls=[]
    for i in range(frames):
        ref=sample_path_frame(path,i,frames,clock)
        controls=mapped_controls(ref.position,data.ctrl,[0],[0])
        journal=AppliedControlJournal(clock.nstep,model.nu)
        execute_control_frame(mujoco,model,data,controls,journal,
                              guard=lambda:guard_calls.append(float(data.time)))
        recorded.append(journal.fields());states.append(integration(model,data))
    assert len(guard_calls)==frames*clock.nstep
    assert data.time==pytest.approx(frames/20)
    replay=restore(model,initial,warm)
    for row,state in zip(recorded,states):
        replay_control_frame(mujoco,model,replay,row['ctrl_substeps'],int(row['executed_substeps']),
                             expected_nstep=clock.nstep,transition_completed=True)
        np.testing.assert_array_equal(integration(model,replay),state)


def test_guard_failure_keeps_exact_executed_prefix_and_does_not_step_tail():
    model,data=model_and_data();initial=integration(model,data);warm=data.qacc_warmstart.copy()
    controls=np.linspace(0,.05,25)[:,None];journal=AppliedControlJournal(25,model.nu)
    def guard():
        if journal.executed==3:raise RuntimeError('unchanged physical guard rejected')
    with pytest.raises(RuntimeError,match='guard rejected'):
        execute_control_frame(mujoco,model,data,controls,journal,guard=guard)
    assert journal.executed==3 and data.time==pytest.approx(.006)
    np.testing.assert_array_equal(journal.ctrl[:3],controls[:3])
    assert np.all(journal.ctrl[3:]==0.)
    replay=restore(model,initial,warm)
    replay_control_frame(mujoco,model,replay,journal.ctrl,3,expected_nstep=25,transition_completed=False)
    np.testing.assert_array_equal(integration(model,replay),integration(model,data))
    with pytest.raises(ValueError,match='missing physical controls'):
        replay_control_frame(mujoco,model,replay,journal.ctrl,3,expected_nstep=25,transition_completed=True)
    with pytest.raises(ValueError,match='invalid recorded'):
        replay_control_frame(mujoco,model,replay,journal.ctrl.astype(np.float32),3,
                             expected_nstep=25,transition_completed=False)
