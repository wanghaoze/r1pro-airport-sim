from dataclasses import replace
from types import SimpleNamespace
from pathlib import Path
import hashlib
import numpy as np
import pytest
from r1pro_teleop.airport_fsm.contracts import Config,State
from r1pro_teleop.airport_fsm.geometry import Operation
from r1pro_teleop.vla.executor import GraspBaseHold,InitializerBaseHold
from r1pro_teleop.vla.machine import VLAMachine
from test_vla_initializer_base_hold import fixture


def test_grasp_hold_scope_evidence_dagger_raw_and_next_carry_release(tmp_path):
 r,e,raw,events,decisions,commands=fixture(tmp_path);before=r.sim.base_joint_state().copy()
 hold=GraspBaseHold(tmp_path/'grasp');op=SimpleNamespace(tray=2,slot=0)
 assert e.execute_operation(op,'Grasp tray2.',lambda r,op:r.steps>=3,reference_constraint=hold)
 assert hold.stats['kind']=='grasp_only_base_hold' and hold.stats['skill']=='grasp_lift_tray'
 assert hold.stats['capture_count']==1 and hold.stats['submitted_rows']==hold.stats['executed_rows']==3
 assert hold.stats['raw_policy_unmodified'] and hold.stats['servo_reference_modified']
 for cmd in commands:np.testing.assert_allclose(cmd[16:],before,atol=2e-8)
 for decision in decisions:
  np.testing.assert_array_equal(decision['actions'],raw)
  assert decision['reference_constraint']['kind']=='grasp_only_base_hold'
 chunk=next(x for x in events if x.get('event')=='vla_grasp_base_hold')
 assert chunk['constraint_skill']=='grasp_lift_tray' and chunk['checkpoint_id']=='unit-test'
 assert hashlib.sha256(Path(chunk['constraint_artifact']).read_bytes()).hexdigest()==chunk['constraint_sha256']
 assert not any(x.get('event','').startswith('vla_initializer_base_hold') for x in events)
 with np.load(tmp_path/'grasp/tick_000000.npz') as z:
  assert str(z['constraint_kind'])=='grasp_only_base_hold' and str(z['checkpoint_id'])=='unit-test'
  np.testing.assert_array_equal(z['actual_submitted_reference'],commands[0])
 count=hold.stats['executed_rows']
 assert e.execute_operation(op,'Carry.',lambda r,op:r.steps>=4)
 assert hold.stats['executed_rows']==count and decisions[-1]['reference_constraint'] is None
 assert np.any(commands[-1][16:]!=before)


def test_grasp_failed_tick_keeps_actual_submission_and_checkpoint(tmp_path):
 r,e,_,events,_,commands=fixture(tmp_path,guard=True);hold=GraspBaseHold(tmp_path/'grasp')
 with pytest.raises(RuntimeError,match='camera guard'):
  e.execute_operation(SimpleNamespace(tray=2,slot=0),'Grasp.',lambda *_:False,reference_constraint=hold)
 assert hold.stats['submitted_rows']==1 and hold.stats['executed_rows']==0
 with np.load(tmp_path/'grasp/tick_000000.npz') as z:
  assert not bool(z['executed']) and 'camera guard' in str(z['error'])
  assert str(z['skill'])=='grasp_lift_tray' and str(z['checkpoint_id'])=='unit-test'
  np.testing.assert_array_equal(z['actual_submitted_reference'],commands[0])


def test_machine_grasp_flag_does_not_hold_navigation_carry_place_or_initializer(tmp_path):
 cfg=replace(Config(),vla_grasp_base_hold_enabled=True,vla_reference_rate_limit_enabled=True);cfg.validate()
 m=VLAMachine.__new__(VLAMachine);m.c=cfg;m.operations=1;m.directory=tmp_path;m.r=SimpleNamespace()
 m.g=SimpleNamespace(ids=['tray0'],spec={'slots':[dict(slot_id='slot0')]});calls=[]
 m.log=SimpleNamespace(event=lambda *a,**kw:None);m.transition=lambda *a,**kw:None
 m.executor=SimpleNamespace(execute_operation=lambda *a,**kw:calls.append(kw))
 for skill in ('navigate_to_tray','grasp_lift_tray','carry_tray','place_release_tray','grasp_lift_tray'):
  m._node(Operation(0,0,np.zeros(3),0),skill,State.GRASP_TRAY,lambda *_:False)
 assert calls[0]==calls[2]==calls[3]=={}
 a,b=calls[1]['reference_constraint'],calls[4]['reference_constraint']
 assert isinstance(a,GraspBaseHold) and isinstance(b,GraspBaseHold) and a is not b
 assert a.directory!=b.directory and a.target is b.target is None


def test_grasp_default_and_config_validation():
 assert not Config().vla_grasp_base_hold_enabled
 assert Config().vla_initialize_arm_tolerance_rad==.06
 with pytest.raises(ValueError,match='requires reference rate'):replace(Config(),vla_grasp_base_hold_enabled=True).validate()
 for bad in (1,'true',None):
  with pytest.raises(ValueError,match='must be boolean'):replace(Config(),vla_grasp_base_hold_enabled=bad).validate()
 assert InitializerBaseHold('unused').stats['kind']=='initializer_only_base_hold'


def test_grasp_cli_requires_rate_and_passes_explicit_flag(tmp_path,monkeypatch):
 import scripts.evaluate_pi05_airport as cli
 base=['--collection','src','--output',str(tmp_path/'out'),'--indices','4','--grasp-base-hold']
 with pytest.raises(SystemExit) as e:cli.main(base)
 assert e.value.code==2
 calls=[]
 monkeypatch.setattr(cli,'verified_server_metadata',lambda *a,**kw:{})
 monkeypatch.setattr(cli,'run_rollouts',lambda *a,**kw:calls.append(kw) or {'status':'completed'})
 assert cli.main(base+['--reference-rate-limit'])==0
 assert calls[0]['grasp_base_hold'] and calls[0]['reference_rate_limit']
 assert calls[0]['init_arm_tolerance']==.06 and calls[0]['init_gripper_tolerance']==.005


def test_rollout_grasp_constraint_is_explicit_without_task_acceptance_change(tmp_path):
 from test_vla_rollout import source,metadata
 from r1pro_teleop.vla.rollout import run_rollouts
 collection,_=source(tmp_path)
 def runner(spec,xml,cfg,directory,**kw):
  assert cfg.vla_grasp_base_hold_enabled and cfg.vla_reference_rate_limit_enabled
  assert not cfg.vla_initializer_base_hold_enabled
  assert cfg.criteria==Config().criteria and cfg.vla_initialize_arm_tolerance_rad==.06
  directory.mkdir(parents=True)
  return dict(scene_id=spec['scene_id'],split=spec['split'],task_completed=False,inverse_dynamics_calls=0)
 report=run_rollouts(collection,tmp_path/'new',metadata(),indices=[4],grasp_base_hold=True,reference_rate_limit=True,attempt_runner=runner)
 assert report['config']['vla_grasp_base_hold_enabled'] is True and report['completed']==0
