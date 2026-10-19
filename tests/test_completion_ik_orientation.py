from dataclasses import replace
from types import SimpleNamespace
import copy
import numpy as np
import pytest
from scipy.spatial.transform import Rotation
from test_completion_held_ik import runtime
from r1pro_teleop.airport_fsm import runtime as module
from r1pro_teleop.airport_fsm.contracts import Fault

def setup(monkeypatch,angle=.07,bound=.12):
 r=runtime(bound=.022);r.cfg=replace(r.cfg,completion_held_ik_orientation_tolerance_rad=bound)
 monkeypatch.setattr(module,'least_squares',lambda fn,initial,**kw:SimpleNamespace(x=np.zeros(len(initial))))
 goals={s:(np.zeros(3),Rotation.from_euler('x',angle).as_matrix()) for s in ['left','right']}
 return r,goals

def test_rotation_only_accepted_with_accurate_policy(monkeypatch):
 r,g=setup(monkeypatch);r.solve_pair(g)
 codes=[e['code'] for n,e in r.events if n=='planning_policy_deviation']
 assert codes==['held_ik_orientation_outside_strict_contract']
 d=next(e for n,e in r.events if n=='held_ik_query_diagnostic')
 assert d['planning_only'] and not d['execution_confirmed']
 assert not r.strict_runtime_passed

@pytest.mark.parametrize('angle,bound',[(.12001,.12),(.07,.05)])
def test_orientation_ceiling(monkeypatch,angle,bound):
 r,g=setup(monkeypatch,angle,bound)
 with pytest.raises(Fault,match='ik_unreachable'):r.solve_pair(g)
 assert not r.events

@pytest.mark.parametrize('rigid',[{'position_m':.016,'rotation_rad':0},{'position_m':0,'rotation_rad':.101}])
def test_orientation_does_not_relax_rigidity(monkeypatch,rigid):
 r,g=setup(monkeypatch);r._rigid_grasp_error=lambda d:rigid
 with pytest.raises(Fault,match='coupled_ik_unreachable'):r.solve_pair(g)
 assert not r.events

def test_strict_empty_retained_orientation_unchanged(monkeypatch):
 r,g=setup(monkeypatch)
 for mode in ['strict','empty','retained']:
  r.cfg=replace(r.cfg,acceptance_profile='strict' if mode=='strict' else 'completion_first')
  r.holding=None if mode=='empty' else 0;r.retained_contact=(0,'left') if mode=='retained' else None
  assert r._completion_held_ik_orientation_bound(.05)==.05

def test_orientation_later_strict_seed_wins(monkeypatch):
 r,g=setup(monkeypatch);calls=[]
 def fit(fn,initial,**kw):
  q=np.zeros(7);q[3]=0 if not calls else .04;calls.append(1);return SimpleNamespace(x=q)
 monkeypatch.setattr(module,'least_squares',fit)
 r.solve_pair({'left':g['left']})
 assert len(calls)==2 and not r.events

def test_orientation_private_clone_warning_isolation(monkeypatch):
 from r1pro_teleop.airport_fsm.placement_reachability import _SilentTrace
 live,g=setup(monkeypatch);live.soft_guard_violation_by_code={}
 probe=copy.copy(live);probe.trace=_SilentTrace();probe.shadow=probe.mj.MjData(probe.m)
 probe.solve_pair(g)
 assert live.strict_runtime_passed and live.soft_guard_violation_by_code=={} and not live.events
 assert not probe.strict_runtime_passed
