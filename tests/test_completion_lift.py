from types import SimpleNamespace
from dataclasses import replace
import numpy as np
import pytest
from scipy.spatial.transform import Rotation
from r1pro_teleop.airport_fsm.contracts import Config
from r1pro_teleop.airport_fsm.primitives import lift_postcondition


def runtime(profile='completion_first',minimum=.10):
 events=[];r=SimpleNamespace(cfg=Config(acceptance_profile=profile,completion_lift_min_m=minimum),
                            record_strict_deviation=lambda code,detail:events.append((code,detail)))
 return r,events


def evidence(height=.12):
 return dict(min_z=np.array([height]),support_contact=np.array([0]),gripper_contact_force=np.array([[13.,14.]]),tray_pose=np.array([[0.,0.,height,1.,0.,0.,0.]]))


@pytest.mark.parametrize('value',[True,False,.079,.151,float('inf'),float('nan'),'0.10'])
def test_invalid_lower_height_policy(value):
 with pytest.raises(ValueError,match='completion_lift_min_m'):replace(Config(),completion_lift_min_m=value).validate()


def test_schema_default_and_bounded_values():
 assert Config().completion_lift_min_m==.15
 for value in (.08,.10,.15):replace(Config(),completion_lift_min_m=value).validate()
 assert Config().primitive_lift_m==.18


def test_strict_and_default_completion_preserve_old_behavior():
 for profile,minimum in [('strict',.08),('completion_first',.15)]:
  r,events=runtime(profile,minimum);check=lift_postcondition(r,0,0.)
  assert not check(evidence(.149)) and check(evidence(.15)) and check(evidence(.20))
  assert not check(evidence(.201)) and events==[]


def test_explicit_lower_range_marks_original_strict_failure():
 r,events=runtime();check=lift_postcondition(r,0,0.)
 assert not check(evidence(.0999)) and events==[]
 assert check(evidence(.10)) and check(evidence(.141))
 assert all(code=='primitive_lift_outside_strict_contract' for code,d in events)
 assert events[-1][1]['measured_height_m']==.141
 assert events[-1][1]['strict_height_range_m']==[.15,.20]
 assert events[-1][1]['effective_height_range_m']==[.10,.20]
 n=len(events);assert check(evidence(.18)) and len(events)==n
 assert not check(evidence(.20001))


@pytest.mark.parametrize('failure',['support','left_force','right_force','tilt','nonfinite_height'])
def test_completion_never_swallows_contact_tilt_or_upper_range(failure):
 r,events=runtime();e=evidence()
 if failure=='support':e['support_contact'][0]=1
 if failure=='left_force':e['gripper_contact_force'][0,0]=.5
 if failure=='right_force':e['gripper_contact_force'][0,1]=0
 if failure=='tilt':
  q=Rotation.from_euler('x',5.01,degrees=True).as_quat();e['tray_pose'][0,3:]=q[[3,0,1,2]]
 if failure=='nonfinite_height':e['min_z'][0]=np.nan
 assert not lift_postcondition(r,0,0.)(e) and not events


def test_approximate_lift_accepts_bounded_intermediate_support_and_tilt_with_evidence():
 r,events=runtime()
 r.cfg=replace(r.cfg,approximate_completion_enabled=True)
 e=evidence(.141)
 e['support_contact'][0]=4
 q=Rotation.from_euler('x',16.,degrees=True).as_quat()
 e['tray_pose'][0,3:]=q[[3,0,1,2]]
 assert lift_postcondition(r,0,0.)(e)
 assert len(events)==1 and events[0][0]=='primitive_lift_outside_strict_contract'
 detail=events[0][1]
 assert detail['support_contact']==4 and detail['effective_height_range_m']==[.10,.35]
 assert detail['effective_tilt_limit_deg']==25.


@pytest.mark.parametrize('failure',['below_min','above_max','left_force','right_force','tilt','nan'])
def test_approximate_lift_retains_finite_height_force_and_tilt_bounds(failure):
 r,events=runtime();r.cfg=replace(r.cfg,approximate_completion_enabled=True)
 e=evidence(.14)
 if failure=='below_min':e['min_z'][0]=.0999
 if failure=='above_max':e['min_z'][0]=.3501
 if failure=='left_force':e['gripper_contact_force'][0,0]=.5
 if failure=='right_force':e['gripper_contact_force'][0,1]=0.
 if failure=='tilt':
  q=Rotation.from_euler('x',25.01,degrees=True).as_quat()
  e['tray_pose'][0,3:]=q[[3,0,1,2]]
 if failure=='nan':e['min_z'][0]=np.nan
 assert not lift_postcondition(r,0,0.)(e) and not events


def test_nominal_timing_opt_in_validation():
 assert Config().completion_preserve_nominal_timing_enabled is False
 with pytest.raises(ValueError,match='requires completion_first'):
  replace(Config(),completion_preserve_nominal_timing_enabled=True).validate()
 with pytest.raises(ValueError,match='must be boolean'):
  replace(Config(),completion_preserve_nominal_timing_enabled=1).validate()


@pytest.mark.parametrize('planned,available,expected',[(48,4.9,58),(68,4.9,68),(48,2.6,52),(58,2.9,58)])
def test_nominal_time_preserves_certified_duration_and_available_budget(planned,available,expected):
 from r1pro_teleop.airport_fsm.primitives import retime_push_to_budget
 events=[];audits=[]
 c=Config(acceptance_profile='completion_first',completion_preserve_nominal_timing_enabled=True,primitive_settle_s=.1)
 r=SimpleNamespace(cfg=c,trace=SimpleNamespace(event=lambda name,**kw:events.append((name,kw))),audit_online_reference=lambda *a:audits.append(a))
 path=SimpleNamespace(evaluate=lambda u,t:(np.zeros(16),)*4)
 assert retime_push_to_budget(r,(path,planned),available)==(path,expected)
 assert len(audits)==(21 if expected>planned else 0)
 assert events[0][1]['effective_frames']==expected


def test_nominal_timing_never_shrinks_plan_to_insufficient_available():
 from r1pro_teleop.airport_fsm.primitives import retime_push_to_budget
 from r1pro_teleop.airport_fsm.contracts import Fault
 r=SimpleNamespace(cfg=Config(acceptance_profile='completion_first',completion_preserve_nominal_timing_enabled=True))
 with pytest.raises(Fault,match='primitive_path_infeasible'):retime_push_to_budget(r,(object(),68),2.9)


@pytest.mark.parametrize('profile,flag',[('strict',True),('completion_first',False)])
def test_other_modes_keep_original_full_budget_retime(profile,flag):
 from r1pro_teleop.airport_fsm.primitives import retime_push_to_budget
 r=SimpleNamespace(cfg=Config(acceptance_profile=profile,completion_preserve_nominal_timing_enabled=flag),trace=SimpleNamespace(event=lambda *a,**kw:None),audit_online_reference=lambda *a:None)
 path=SimpleNamespace(evaluate=lambda u,t:(np.zeros(16),)*4)
 assert retime_push_to_budget(r,(path,48),4.9)[1]==98



def lift_planner(monkeypatch,required,*,enabled=True,non_duration=None):
 from r1pro_teleop.airport_fsm import primitives as p,withdraw_merge
 from r1pro_teleop.airport_fsm.contracts import Fault
 calls=[];ik=[];r=SimpleNamespace(cfg=Config(acceptance_profile='completion_first',primitive_settle_s=.1,completion_preserve_nominal_timing_enabled=enabled),physical=0)
 monkeypatch.setattr(withdraw_merge,'planning_snapshot',lambda r:{'physical':r.physical})
 def points(r,target):ik.append(int(target[0]));return np.full((2,16),target[0])
 def planner(r,points,**kwargs):
  i=int(points[0,0]);calls.append((i,kwargs['available']))
  if i==non_duration:raise Fault('primitive_path_infeasible',{'candidates':[{'reason':'collision_or_wrist'}]})
  if required[i]>kwargs['available']:raise Fault('primitive_path_infeasible',{'candidates':[{'reason':'duration','required_s':required[i]}]})
  return ('path',int(required[i]*20))
 monkeypatch.setattr(p,'object_points',points);monkeypatch.setattr(p,'plan',planner)
 return p,r,[(i,np.array([float(i),0,1])) for i in range(len(required))],calls,ik


def test_lift_nominal_scan_retains_later_original_feasible_candidate(monkeypatch):
 p,r,candidates,calls,ik=lift_planner(monkeypatch,[4.,2.25,2.])
 result=p.select_lift_path(r,candidates,4.9)
 assert result[1]==1 and result[-1]=='nominal' and ik==[0,1]
 assert calls==[(0,2.9),(1,2.9)]


def test_lift_extended_retries_cached_duration_only_without_repeating_ik(monkeypatch):
 p,r,candidates,calls,ik=lift_planner(monkeypatch,[4.,3.5,3.2],non_duration=1)
 result=p.select_lift_path(r,candidates,4.9)
 assert result[1]==0 and result[-1]=='extended_cached_duration_only'
 assert ik==[0,1,2] and calls==[(0,2.9),(1,2.9),(2,2.9),(0,4.9)]
 assert len(result[3])==3


def test_default_lift_keeps_extended_first_feasible_order(monkeypatch):
 p,r,candidates,calls,ik=lift_planner(monkeypatch,[4.,2.25],enabled=False)
 assert p.select_lift_path(r,candidates,4.9)[1]==0
 assert calls==[(0,4.9)] and ik==[0]


def test_lift_planning_cannot_change_physical_state(monkeypatch):
 from r1pro_teleop.airport_fsm.contracts import Fault
 p,r,candidates,calls,ik=lift_planner(monkeypatch,[2.])
 def corrupt(*a,**kw):r.physical+=1;return ('path',40)
 monkeypatch.setattr(p,'plan',corrupt)
 with pytest.raises(Fault,match='lift_planning_state_changed'):p.select_lift_path(r,candidates,4.9)
