import dataclasses
import h5py
import numpy as np
import pytest
from test_substep_runtime_replay import airport,state,trace_for,close_trace
from test_vla_rollout import source,metadata
from r1pro_teleop.vla.rollout import run_rollouts


def test_actual_airport_held_servo_raw1_raw2_are_bit_exact(airport,tmp_path):
    create,_,_=airport
    legacy=create(False);journal=create(True)
    np.testing.assert_array_equal(state(legacy),state(journal))
    trace_for(legacy,tmp_path/'raw1');trace_for(journal,tmp_path/'raw2')
    initial=legacy.sim.target.copy()
    for frame in range(4):
        target=initial.copy();target[6]+=np.float32(.0001*(frame+1))
        base=np.array([.0001*frame,0.,0.],dtype=np.float32)
        for runtime in (legacy,journal):
            runtime.sim.target=target.copy();runtime.sim.base_target=base.copy()
            runtime.tick()  # No substep_targets: same actual held actuator command.
        np.testing.assert_array_equal(state(legacy),state(journal))
        np.testing.assert_array_equal(legacy.d.ctrl,journal.d.ctrl)
        assert legacy.id_calls==journal.id_calls==0
    old=close_trace(legacy);new=close_trace(journal)
    with h5py.File(old) as raw1,h5py.File(new) as raw2:
        assert raw1.attrs['schema']=='airport_fsm_raw/1' and raw2.attrs['schema']=='airport_fsm_raw/2'
        for key in ('qpos','qvel','action','base_action','ctrl','sim_time','integration_state'):
            np.testing.assert_array_equal(raw1[key][:],raw2[key][:])
        assert np.all(raw2['executed_substeps'][:]==journal.sim.nstep)
        for frame in range(4):
            ctrl=raw2['ctrl_substeps'][frame]
            np.testing.assert_array_equal(ctrl,np.tile(ctrl[0],(journal.sim.nstep,1)))


@pytest.mark.parametrize('original,override,expected',[(False,False,False),(True,False,True),(False,True,True)])
def test_rollout_recording_override_preserves_default_source_semantics(tmp_path,monkeypatch,original,override,expected):
    from r1pro_teleop.vla import rollout
    from r1pro_teleop.airport_fsm.contracts import Config
    root,_=source(tmp_path);monkeypatch.setattr(rollout,'config_for',lambda _:Config(substep_control_enabled=original))
    seen=[]
    def attempt(scene,xml,cfg,*a,**kw):
        seen.append(cfg.substep_control_enabled)
        return dict(scene_id=scene['scene_id'],split='test',task_completed=False,motion_backend='pi05',inverse_dynamics_calls=0)
    report=run_rollouts(root,tmp_path/'new',metadata(),indices=[4],record_substep_controls=override,attempt_runner=attempt)
    assert seen==[expected] and report['record_substep_controls_override'] is override


def test_nonboolean_recording_flag_rejected_before_source_or_model(tmp_path):
    with pytest.raises(ValueError,match='boolean'):run_rollouts('missing',tmp_path/'new',metadata(),indices=[4],record_substep_controls=1)
