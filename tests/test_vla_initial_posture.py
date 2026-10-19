from types import SimpleNamespace
from dataclasses import replace
import importlib.util
from pathlib import Path
import numpy as np
import pytest
from r1pro_teleop.airport_fsm.contracts import Config,State
from r1pro_teleop.airport_fsm.geometry import Operation
from r1pro_teleop.vla.machine import VLAMachine,initial_posture_metrics,initial_posture_ready,stable_evaluation


def runtime(config=None):
 state=np.zeros(16);r=SimpleNamespace(cfg=config or Config(),tucked=np.zeros(16),sim=SimpleNamespace(state=lambda:state.copy()),steps=0)
 return r,state


def test_default_initial_phase_thresholds_stay_strict():
 r,state=runtime();state[4]=.06001;assert not initial_posture_ready(r)
 state[4]=.06;state[7]=.005;assert initial_posture_ready(r)
 state[7]=.00501;assert not initial_posture_ready(r)


def test_explicit_approximate_initial_readiness_keeps_strict_measured_audit():
 cfg=replace(Config(),vla_initialize_arm_tolerance_rad=.15,vla_initialize_gripper_tolerance_m=.01)
 r,state=runtime(cfg);state[4]=.079;state[5]=.077;state[12]=.118;state[7]=.00633
 detail=initial_posture_metrics(r)
 assert detail['configured_passed'] and not detail['strict_passed']
 assert detail['max_arm_error_rad']==.118 and detail['max_gripper_error_m']==.00633
 assert detail['strict_arm_tolerance_rad']==.06 and detail['strict_gripper_tolerance_m']==.005
 assert detail['arm_tolerance_rad']==.15 and detail['gripper_tolerance_m']==.01
 assert cfg.criteria==Config().criteria  # final-task acceptance parameters unchanged
 check=stable_evaluation(initial_posture_ready,3)
 assert not check(r,None);r.steps=1;assert not check(r,None);r.steps=2;assert check(r,None)
 state[12]=.15001;r.steps=3;assert not check(r,None)


@pytest.mark.parametrize('key',['vla_initialize_arm_tolerance_rad','vla_initialize_gripper_tolerance_m'])
@pytest.mark.parametrize('value',[0,-.1,float('nan'),float('inf'),True,'0.15'])
def test_invalid_initial_threshold_configuration_rejected(key,value):
 with pytest.raises(ValueError,match='finite and positive'):replace(Config(),**{key:value}).validate()


def test_nonfinite_measured_state_never_qualifies():
 r,state=runtime(replace(Config(),vla_initialize_arm_tolerance_rad=.15));state[4]=np.nan
 detail=initial_posture_metrics(r)
 assert not detail['configured_passed'] and not detail['strict_passed'] and not detail['finite']
 assert detail['measured_absolute_errors'][4] is None


def test_production_completion_event_and_result_preserve_strict_difference(monkeypatch,tmp_path):
 from r1pro_teleop.airport_fsm.machine import Machine
 r,state=runtime(replace(Config(),motion_backend='pi05',vla_checkpoint_id='test',vla_initialize_arm_tolerance_rad=.15,vla_initialize_gripper_tolerance_m=.01))
 state[4]=.1;m=VLAMachine.__new__(VLAMachine);m.r=r;m.c=r.cfg;m.directory=tmp_path;m.operations=0
 m.g=SimpleNamespace(ids=['tray0'],spec={'slots':[]});events=[]
 m.log=SimpleNamespace(event=lambda kind,**detail:events.append((kind,detail)));m.transition=lambda *a,**kw:None
 def execute(op,prompt,predicate):
  for step in range(3):r.steps=step;ready=predicate(r,op)
  assert ready
 m.executor=SimpleNamespace(execute_operation=execute)
 m._node(Operation(0,-1,np.zeros(3),0),'initialize_posture',State.SEARCH_TARGET,initial_posture_ready,3)
 complete=events[-1][1]['initial_posture'];assert complete['configured_passed'] and not complete['strict_passed']
 monkeypatch.setattr(Machine,'finish',lambda self,*a,**kw:dict(task_completed=False))
 result=m.finish(False)
 assert result['task_completed'] is False and result['vla_initial_posture_completed']==complete
 assert not result['vla_initial_posture_at_finish']['strict_passed']


def test_isolated_diagnostic_uses_identical_initial_predicate():
 path=Path(__file__).resolve().parents[1]/'scripts/diagnose_pi05_skills.py'
 spec=importlib.util.spec_from_file_location('diag_init',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
 r,state=runtime();predicate,frames=module.skill_predicate(SimpleNamespace(r=r),'initialize_posture')
 assert predicate is initial_posture_ready and frames==3
