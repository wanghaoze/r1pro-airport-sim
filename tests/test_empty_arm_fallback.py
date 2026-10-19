from types import SimpleNamespace
import numpy as np
import pytest
from r1pro_teleop.airport_fsm.runtime import Runtime
from r1pro_teleop.airport_fsm.contracts import Config,Fault
from r1pro_teleop.airport_fsm.contracts import minimum_duration


def fake():
 r=object.__new__(Runtime);r.cfg=Config(free_space_joint_shortcut=True);r.trace=None
 r.holding=None;r.retained_contact=None
 r.sim=SimpleNamespace(target=np.zeros(16),state=lambda:np.zeros(16),tcp=lambda s:(np.zeros(3),np.eye(3)))
 r.observation=lambda:{'gripper_contact_force':np.zeros((3,2))}
 def solve(goals,seed,free_endpoint=False):
  if not free_endpoint:raise Fault('ik_unreachable',recoverable=True)
  q=seed.copy();q[0]=1.;return q
 r.solve_pair=solve;r._target_valid=lambda *a,**k:True
 r.tick=lambda:(_ for _ in ()).throw(AssertionError('preview executed'))
 return r


def test_clear_empty_arm_endpoint_can_bypass_unreachable_cartesian_interior():
 r=fake();p=r.cartesian({'left':(np.array([.2,0,0]),np.eye(3))},preview_only=True)
 assert len(p)==2 and p[-1][0]==1.
 assert np.array_equal(r.sim.target,np.zeros(16))


def test_endpoint_is_rejected_when_only_interior_collides():
 r=fake();r._target_valid=lambda q,**k:not .4<q[0]<.6
 with pytest.raises(Fault,match='ik_unreachable'):
  r.cartesian({'left':(np.array([.2,0,0]),np.eye(3))},preview_only=True)


@pytest.mark.parametrize('reason',['holding','retained','contact','wrist'])
def test_contact_and_camera_paths_cannot_use_empty_arm_fallback(reason):
 r=fake()
 if reason=='holding':r.holding=0
 if reason=='retained':r.retained_contact=(0,'left')
 if reason=='contact':r.observation=lambda:{'gripper_contact_force':np.ones((3,2))}
 with pytest.raises(Fault,match='ik_unreachable'):
  r.cartesian({'left':(np.array([.2,0,0]),np.eye(3))},wrist=reason=='wrist',preview_only=True)


def test_solver_endpoint_api_itself_rejects_holding():
 r=fake();r.holding=0
 with pytest.raises(Fault,match='endpoint_ik_requires_empty_arms'):
  Runtime.solve_pair(r,{},free_endpoint=True)


def test_endpoint_execution_reserves_servo_tracking_margin():
 r=fake();r.v=np.ones(16);r.a=np.ones(16)*2;r.j=np.ones(16)*8
 commands=[];r.joints=lambda q,**kw:commands.append((q,kw))
 r.cartesian({'left':(np.array([.02,0,0]),np.eye(3))})
 q,kw=commands[0]
 assert kw['minimum_seconds']>=minimum_duration(q,r.v*.5,r.a*.5,r.j*.5)
