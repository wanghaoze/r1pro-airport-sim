import copy
from dataclasses import replace
from types import SimpleNamespace
import numpy as np
import pytest
from r1pro_teleop.airport_fsm import primitives as p,placement_reachability as pr,withdraw_merge
from r1pro_teleop.airport_fsm.contracts import Config,Fault


def setup(monkeypatch,strict_index=None,relaxed_index=0):
 events=[];warnings=[];calls=[]
 cfg=Config(acceptance_profile='completion_first',completion_held_ik_orientation_tolerance_rad=.12,completion_lift_strict_orientation_first_enabled=True,completion_preserve_nominal_timing_enabled=True)
 r=SimpleNamespace(cfg=cfg,physical=0,trace=SimpleNamespace(event=lambda n,**d:events.append((n,d))),record_strict_deviation=lambda c,d:warnings.append((c,d)),primitive_deadline_step=100)
 monkeypatch.setattr(withdraw_merge,'planning_snapshot',lambda r:{'physical':r.physical,'deadline':r.primitive_deadline_step})
 monkeypatch.setattr(pr,'loaded_planning_copy',lambda r:copy.copy(r))
 def points(probe,target):
  i=int(target[0]);bound=probe.cfg.completion_held_ik_orientation_tolerance_rad;calls.append((bound,i))
  probe.trace.event('planning_policy_deviation',code='test_'+str(i),detail={'planning_only':True})
  if i!=(strict_index if bound==.05 else relaxed_index):raise Fault('ik_unreachable',{'index':i})
  return np.full((2,16),i,dtype=float)
 monkeypatch.setattr(p,'object_points',points)
 monkeypatch.setattr(p,'plan',lambda r,points,**kw:('curve'+str(int(points[0,0])),40))
 targets=[(i,np.array([i,0,1.]))for i in range(7)]
 return r,targets,calls,events,warnings


def test_later_original_candidate_wins_over_first_relaxed(monkeypatch):
 r,t,calls,events,warnings=setup(monkeypatch,strict_index=4)
 result=p.select_lift_path(r,t,4.9)
 assert result[1]==4 and result[0]==('curve4',40)
 assert calls==[(.05,i)for i in range(5)]
 assert [c for c,d in warnings]==['test_4']
 assert r.cfg.completion_held_ik_orientation_tolerance_rad==.12 and r.primitive_deadline_step==100
 assert events[-1][1]['geometry_queries']==5


def test_all_original_fail_then_second_private_pass(monkeypatch):
 r,t,calls,events,warnings=setup(monkeypatch)
 assert p.select_lift_path(r,t,4.9)[1]==0
 assert calls==[(.05,i)for i in range(7)]+[(.12,0)]
 assert [c for c,d in warnings]==['test_0']
 assert events[-1][1]['maximum_geometry_queries']==14
 assert events[-1][1]['geometry_queries']==8


def test_both_fail_preserves_original_error_no_failed_probe_warnings(monkeypatch):
 r,t,calls,events,warnings=setup(monkeypatch,relaxed_index=None)
 with pytest.raises(Fault,match='primitive_lift_path_unavailable')as e:p.select_lift_path(r,t,4.9)
 assert len(e.value.detail)==7 and len(calls)==14 and not warnings
 assert not any(n=='planning_policy_deviation'for n,d in events)


def test_default_off_uses_same_runtime_and_original_entry(monkeypatch):
 r,t,*_=setup(monkeypatch);r.cfg=replace(r.cfg,completion_lift_strict_orientation_first_enabled=False)
 seen=[]
 monkeypatch.setattr(p,'_select_lift_path',lambda rr,tt,a:seen.append(rr)or 'legacy')
 assert p.select_lift_path(r,t,4.9)=='legacy' and seen==[r]


def test_nonplanning_fault_not_retried(monkeypatch):
 r,t,*_=setup(monkeypatch);calls=[]
 def fail(*a):calls.append(1);raise Fault('illegal_collision')
 monkeypatch.setattr(p,'_select_lift_path',fail)
 with pytest.raises(Fault,match='illegal_collision'):p.select_lift_path(r,t,4.9)
 assert len(calls)==1


def test_geometry_budget_rejects_more_than_original_seven(monkeypatch):
 r,t,*_=setup(monkeypatch)
 with pytest.raises(Fault,match='lift_orientation_candidate_budget_invalid'):p.select_lift_path(r,t+[t[0]],4.9)

def test_original_extended_duration_pass_precedes_relaxed_geometry(monkeypatch):
 r,t,calls,events,warnings=setup(monkeypatch,strict_index=4)
 def plan(rr,points,**kw):
  if kw['available']<4:raise Fault('primitive_path_infeasible',{'candidates':[{'reason':'duration','required_s':4.}]})
  return ('old_extended',80)
 monkeypatch.setattr(p,'plan',plan)
 result=p.select_lift_path(r,t,4.9)
 assert result[0]==('old_extended',80) and result[1]==4
 assert calls==[(.05,i)for i in range(7)]
 assert result[-1]=='extended_cached_duration_only'
 assert [c for c,d in warnings]==['test_4']

from test_physical_preview import machine

def test_real_runtime_copy_keeps_live_state_config_and_failed_warning_private(machine,monkeypatch):
 r=machine.r;r.cfg=replace(r.cfg,acceptance_profile='completion_first',completion_held_ik_orientation_tolerance_rad=.12,completion_lift_strict_orientation_first_enabled=True)
 r.holding=0;r.grasp_rel={s:np.eye(4)for s in ('left','right')};r.primitive_deadline_step=100
 r.soft_guard_violation_by_code={};original_cfg=r.cfg
 before=withdraw_merge.planning_snapshot(r);calls=[]
 def select(probe,targets,available):
  assert probe is not r and probe.d is not r.d and probe.shadow is not r.shadow
  assert probe.cfg is not r.cfg and probe.primitive_deadline_step==100
  calls.append(probe.cfg.completion_held_ik_orientation_tolerance_rad)
  probe._lift_geometry_queries=7
  probe.soft_guard_violation_by_code={'discarded':1};probe.strict_runtime_passed=False
  probe.trace.event('planning_policy_deviation',code='discarded',detail={})
  if len(calls)==1:raise Fault('primitive_lift_path_unavailable',[])
  probe._selected_lift_events=[]
  return ('curve',40),0,np.zeros(3),[],'nominal'
 monkeypatch.setattr(p,'_select_lift_path',select)
 p.select_lift_path(r,[(0,np.zeros(3))],4.9)
 assert calls==[.05,.12] and r.cfg is original_cfg and r.soft_guard_violation_by_code=={}
 assert r.strict_runtime_passed
 assert withdraw_merge.check_unchanged(r,before)
