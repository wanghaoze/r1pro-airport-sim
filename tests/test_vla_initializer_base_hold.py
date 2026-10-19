from types import SimpleNamespace
from dataclasses import replace
import json,hashlib
import numpy as np
import pytest
from r1pro_teleop.airport_fsm.contracts import Config,State
from r1pro_teleop.airport_fsm.geometry import Operation
from r1pro_teleop.vla.policy import Pi05Policy,PolicyContract,PolicyError
from r1pro_teleop.vla.executor import ActionBounds,VLAOperationExecutor,ReferenceRateLimiter,InitializerBaseHold
from r1pro_teleop.vla.machine import VLAMachine,initial_posture_ready


def fixture(tmp_path,*,guard=False):
 measured=np.concatenate((np.arange(16,dtype=float)/100,[.1,.2,.3]));raw=np.full((4,19),.6,np.float32);events=[];decisions=[];commands=[]
 class Client:
  def infer(self,observation):return dict(actions=raw.copy())
 sim=SimpleNamespace(target=np.zeros(16),base_target=np.zeros(3),state=lambda:measured[:16].copy(),base_joint_state=lambda:measured[16:].copy(),image=lambda name:np.zeros((4,4,3),np.uint8))
 runtime=SimpleNamespace(cfg=SimpleNamespace(fps=20),sim=sim,steps=0)
 def banned(*a,**k):raise AssertionError('No IK/teacher/physics reset permitted')
 for key in ('solve_pair','teacher','joints','cartesian','reset','inverse_dynamics'):setattr(runtime,key,banned)
 def tick():
  cmd=np.concatenate((sim.target,sim.base_target));commands.append(cmd.copy());measured[:]=cmd;runtime.steps+=1
  if guard:raise RuntimeError('actual camera guard')
 runtime.tick=tick
 policy=Pi05Policy(Client(),PolicyContract('unit-test',action_horizon=4,action_width=19))
 rate=ReferenceRateLimiter(np.ones(19)*.5,np.ones(19),tmp_path/'rate',physical_bounds=ActionBounds(-np.ones(19),np.ones(19)))
 executor=VLAOperationExecutor(runtime,policy,ActionBounds(-np.ones(19),np.ones(19)),execute_steps=2,max_operation_steps=5,rate_limiter=rate,on_decision=decisions.append,on_chunk=events.append)
 return runtime,executor,raw,events,decisions,commands


def test_initializer_hold_uses_measured_once_retains_model_and_dagger_raw_then_releases(tmp_path):
 r,e,raw,events,decisions,commands=fixture(tmp_path);initial=np.concatenate((r.sim.state(),r.sim.base_joint_state()))
 hold=InitializerBaseHold(tmp_path/'hold');op=SimpleNamespace(tray=0,slot=-1)
 assert e.execute_operation(op,'Initial posture.',lambda r,op:r.steps>=3,reference_constraint=hold)
 assert hold.stats['capture_count']==1 and hold.stats['chunks']==2 and hold.stats['submitted_rows']==hold.stats['executed_rows']==3
 assert hold.stats['raw_policy_unmodified'] and hold.stats['raw_model_actions_retained'] and hold.stats['servo_reference_modified']
 for command in commands:np.testing.assert_allclose(command[16:],initial[16:],atol=2e-8)
 assert not np.array_equal(commands[-1][:16],initial[:16])  # arms actually follow policy through rate servo
 for decision in decisions:
  np.testing.assert_array_equal(decision['actions'],raw);np.testing.assert_array_equal(decision['servo_actions'],raw)
  np.testing.assert_allclose(decision['constrained_actions'][:,16:],np.tile(initial[16:],(4,1)),atol=2e-8)
 with np.load(tmp_path/'hold/chunk_000000.npz') as data:
  np.testing.assert_array_equal(data['raw_actions'],raw)
  np.testing.assert_array_equal(data['prehold_servo_actions'],raw)
  np.testing.assert_array_equal(data['constraint_delta'][:,:16],np.zeros((4,16)))
 detail=next(row for row in events if row.get('event')=='vla_initializer_base_hold')
 assert hashlib.sha256(__import__('pathlib').Path(detail['constraint_artifact']).read_bytes()).hexdigest()==detail['constraint_sha256']
 count=hold.stats['submitted_rows'];previous=commands[-1][16:].copy()
 assert e.execute_operation(SimpleNamespace(tray=0,slot=0),'Navigate.',lambda r,op:r.steps>=4)
 assert hold.stats['submitted_rows']==count and np.any(commands[-1][16:]!=previous)
 assert decisions[-1]['reference_constraint'] is None


def test_guard_failure_retains_submitted_actual_state_but_not_successful_tick_count(tmp_path):
 r,e,raw,events,decisions,commands=fixture(tmp_path,guard=True);hold=InitializerBaseHold(tmp_path/'hold')
 with pytest.raises(RuntimeError,match='camera guard'):e.execute_operation(SimpleNamespace(tray=0,slot=-1),'Initialize.',lambda *_:False,reference_constraint=hold)
 assert hold.stats['submitted_rows']==1 and hold.stats['executed_rows']==0 and e.rate_limit_stats['executed_rows']==0
 with np.load(tmp_path/'hold/tick_000000.npz') as data:
  assert not bool(data['executed']) and 'camera guard' in str(data['error'])
  np.testing.assert_array_equal(data['actual_submitted_reference'],commands[0])


@pytest.mark.parametrize('bad',[np.full(19,np.nan),np.zeros(18),np.concatenate((np.zeros(16),[2,0,0]))])
def test_capture_rejects_invalid_measurement_without_silent_clip(tmp_path,bad):
 hold=InitializerBaseHold(tmp_path/'hold')
 with pytest.raises(PolicyError):hold.begin(bad,ActionBounds(-np.ones(19),np.ones(19)),0)
 assert hold.stats['capture_count']==0


def test_base_hold_is_only_attached_to_initializer_node(tmp_path):
 cfg=replace(Config(),vla_initializer_base_hold_enabled=True,vla_reference_rate_limit_enabled=True)
 cfg.validate();m=VLAMachine.__new__(VLAMachine);m.c=cfg;m.operations=0;m.directory=tmp_path
 m.r=SimpleNamespace(cfg=cfg,sim=SimpleNamespace(state=lambda:np.zeros(16)),tucked=np.zeros(16))
 m.g=SimpleNamespace(ids=['tray0'],spec={'slots':[dict(slot_id='slot0')]});calls=[]
 m.log=SimpleNamespace(event=lambda *a,**kw:None);m.transition=lambda *a,**kw:None
 m.executor=SimpleNamespace(execute_operation=lambda *a,**kw:calls.append(kw))
 m._node(Operation(0,-1,np.zeros(3),0),'initialize_posture',State.SEARCH_TARGET,initial_posture_ready,3)
 m._node(Operation(0,0,np.zeros(3),0),'navigate_to_tray',State.ALIGN_BASE,lambda *_:True)
 assert isinstance(calls[0]['reference_constraint'],InitializerBaseHold) and calls[1]=={}
 with pytest.raises(ValueError,match='requires reference rate'):replace(Config(),vla_initializer_base_hold_enabled=True).validate()
 assert not Config().vla_initializer_base_hold_enabled

def test_hold_does_not_hide_invalid_late_model_chunk(tmp_path):
 r,e,raw,events,decisions,commands=fixture(tmp_path);raw[-1,16]=2
 hold=InitializerBaseHold(tmp_path/'hold')
 with pytest.raises(PolicyError,match='outside_joint_limits'):
  e.execute_operation(SimpleNamespace(tray=0,slot=-1),'Initialize.',lambda *_:False,reference_constraint=hold)
 assert r.steps==0 and not commands and not decisions and hold.stats['chunks']==0
