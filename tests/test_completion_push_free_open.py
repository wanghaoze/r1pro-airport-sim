from types import SimpleNamespace
import numpy as np
import pytest
from r1pro_teleop.airport_fsm.primitives import completion_free_open_points
from r1pro_teleop.airport_fsm.contracts import Fault

def fixture(profile='completion_first',enabled=True):
 events=[];r=SimpleNamespace(cfg=SimpleNamespace(acceptance_profile=profile,completion_push_free_open_enabled=enabled,gripper_open_m=.1),primitive_deadline_step=100,trace=SimpleNamespace(event=lambda name,**kw:events.append((name,kw))))
 points=np.arange(64,dtype=float).reshape(4,16)/1000;points[:,7]=.038;points[:,15]=0
 return r,points,events

@pytest.mark.parametrize('side',['left','right'])
def test_candidate_changes_only_free_jaw_and_preserves_source(side):
 r,p,events=fixture();col=15 if side=='left' else 7;p[:,col]=.038;before=p.copy()
 q=completion_free_open_points(r,p,side,free_retreat=True,withdraw_free=False)
 np.testing.assert_array_equal(p,before)
 np.testing.assert_array_equal(q[:,[i for i in range(16)if i!=col]],p[:,[i for i in range(16)if i!=col]])
 assert q[0,col]==p[0,col] and q[-1,col]==.1 and np.all(np.diff(q[:,col])>=0)
 assert events[0][1]['primitive_deadline_step']==100
 assert 'unvalidated' in events[0][1]['qualification']

@pytest.mark.parametrize('profile,enabled,free,withdraw',[
 ('strict',True,True,False),('completion_first',False,True,False),
 ('completion_first',True,False,False),('completion_first',True,True,True)])
def test_outside_scope_unchanged(profile,enabled,free,withdraw):
 r,p,events=fixture(profile,enabled)
 assert completion_free_open_points(r,p,'right',free_retreat=free,withdraw_free=withdraw) is p
 assert not events

def test_existing_over_limit_is_not_silently_closed():
 r,p,events=fixture();p[0,7]=.11
 with pytest.raises(Fault,match='completion_free_open_path_invalid'):
  completion_free_open_points(r,p,'right',free_retreat=True,withdraw_free=False)
 assert not events

def test_push_passes_candidate_to_whole_path_planner_before_execution():
 import inspect
 from r1pro_teleop.airport_fsm.primitives import push
 source=inspect.getsource(push)
 # Integration ordering: candidate is not applied to executing ctrl or after validation.
 assert source.index('completion_free_open_points(')<source.index('planned=plan(r,points')<source.index('_execute_push_reference(')

def test_candidate_full_planner_honors_collision_and_original_budget():
 from test_fixed_primitives import fake_planner
 from r1pro_teleop.airport_fsm.primitives import plan
 r,p,events=fixture();p[:]=0;p[:,7]=.038
 q=completion_free_open_points(r,p,'right',free_retreat=True,withdraw_free=False)
 planner=fake_planner()
 with pytest.raises(Fault,match='primitive_path_infeasible'):plan(planner,q,available=.05)
 planner._path_rejection=lambda *args:{'reason':'collision','pair':['free_finger','neighbour']}
 with pytest.raises(Fault,match='primitive_path_infeasible'):plan(planner,q,available=2.9)
 planner._path_rejection=lambda *args:None
 path,frames=plan(planner,q,available=2.9)
 assert frames/20<=2.9
 np.testing.assert_allclose(path.evaluate(0,frames/20)[0],q[0],atol=1e-12)
 np.testing.assert_allclose(path.evaluate(1,frames/20)[0],q[-1],atol=1e-12)
