"""The diagnostic routing budget and profile never alter formal evaluation."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from r1pro_teleop.airport_fsm.contracts import Config

path=Path('runs/task_complete_deploy_20261005/run_action8_dual_route_smoke.py')
spec=importlib.util.spec_from_file_location('dual_route_smoke_fixture',path)
smoke=importlib.util.module_from_spec(spec);spec.loader.exec_module(smoke)


def test_short_route_configuration_is_explicit_raw2_and_no_teacher():
    original=Config()
    configured=smoke.config_for_route(original,dict(checkpoint_id='sha256:actual-diagnostic'),dict(action_horizon=20),8769)
    configured.validate()
    assert original.motion_backend=='teacher'
    assert configured.motion_backend=='pi05' and configured.vla_port==8769
    assert configured.vla_checkpoint_id=='sha256:actual-diagnostic'
    assert configured.vla_prompt_mode=='task_complete_action8_v1'
    assert configured.vla_max_skill_steps==10 and configured.substep_control_enabled
    assert configured.vla_model_render_max_dim==224
    assert configured.vla_initializer_base_hold_enabled and not configured.vla_grasp_base_hold_enabled
    assert configured.vla_reference_rate_fraction==.5
    assert configured.vla_servo_projection_mode=='actuator_saturation'


def test_children_use_explicit_frozen_runtime_and_same_immutable_status():
    args=SimpleNamespace(controller_root='/frozen/v5',core_report='/core/actual.json',protocol='/protocol/fixed50.json',
        training_status='/diagnostic/milestone_000004.json',output='/new/dual_route_smoke_v1')
    worker=smoke.argv(args,'--worker',1);physical=smoke.argv(args,'--physical',1)
    assert worker[0]==smoke.VLA and physical[0]==smoke.SIM
    for command in (worker,physical):
        assert command[command.index('--controller-root')+1]=='/frozen/v5'
        assert command[command.index('--training-status')+1]=='/diagnostic/milestone_000004.json'
        assert command[-2:]==['--worker-index','1']
