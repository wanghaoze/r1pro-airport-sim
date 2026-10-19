from types import SimpleNamespace as NS
from copy import deepcopy
import numpy as np
import pytest
from test_release_scheduler import scene7
from r1pro_teleop.airport_fsm import general_buffer as mod
from r1pro_teleop.airport_fsm.geometry import Operation
from r1pro_teleop.airport_fsm.contracts import Fault


def setup(monkeypatch,*,original_direct=False,qualifies=True):
 pose=np.array([[0.,0.,.8,1,0,0,0],[1.,0.,.8,1,0,0,0],[2.,0.,.8,1,0,0,0]])
 op=Operation(0,-1,np.array([.8,0.,.801]),0.,True);requested=Operation(1,0,np.array([0.,0.,.8]),0.)
 g=NS(sizes=np.full((3,3),.3),belt_length=2.4,belt_width=.6,goal_yaw=np.zeros(3),
      footprint_supported=lambda *a:True,blockers=lambda *a:[],top_available=lambda *a:True,
      to_world=lambda p:np.array(p))
 c=NS(acceptance_profile='completion_first',temporary_buffer_serviceability_enabled=True,completion_direct_buffer_enabled=True,
      criteria=NS(contact_n=.5),placement_max_probes=18)
 obs={'tray_pose':pose.copy(),'gripper_contact_force':np.ones((3,2))};obs['tray_pose'][0,2]=1.0
 events=[];calls=[]
 m=NS(c=c,g=g,operations=1,scheduler=NS(mapping=[1,0,2]),verified_final_trays={2},
      r=NS(holding=0,retained_contact=None,observation=lambda:obs),
      log=NS(event=lambda name,**kw:events.append((name,kw))),_inward_yaw=lambda p:0.)
 ctx=mod.BufferContext(deepcopy(op),requested,pose,(1,0,2),frozenset({2}),1,'test_source')
 def release(g,p,candidate,c):
  return candidate.destination.copy() if original_direct or not mod.same_operation(candidate,op) else candidate.destination+np.array([.105,0,0])
 monkeypatch.setattr(mod,'release_location',release)
 monkeypatch.setattr(mod,'_executable_geometry',lambda *a:True)
 monkeypatch.setattr(mod,'carried_placement_candidates',lambda *a,**kw:[np.zeros(3)])
 def screen(*args,**kw):
  calls.append((args,kw));return NS(examined=18,rejected=[],qualified=[{'base':[.2,.3,0]}] if qualifies else [])
 monkeypatch.setattr(mod,'screen_placement',screen)
 return m,op,ctx,events,calls,obs


def test_staging_is_declared_new_operation_not_false_old_goal_success(monkeypatch):
 m,op,ctx,events,calls,obs=setup(monkeypatch)
 before=obs['tray_pose'].copy();selected,proposal=mod.select_direct_buffer(m,op,ctx)
 np.testing.assert_allclose(selected.destination,[.905,0,.801]);np.testing.assert_array_equal(proposal['staged'],selected.destination)
 np.testing.assert_array_equal(obs['tray_pose'],before);assert op.destination[0]==.8
 assert calls[0][1]['max_candidates']==18 and len(calls)==1
 log=next(d for n,d in events if n=='general_buffer_serviceability')
 assert log['original_push_infeasibility_claimed'] is False
 assert events[-1][0]=='operation_destination_revised'
 assert mod.select_direct_buffer(m,selected,ctx)==(selected,None)


def test_original_direct_candidate_keeps_priority(monkeypatch):
 m,op,ctx,events,calls,_=setup(monkeypatch,original_direct=True)
 selected,proposal=mod.select_direct_buffer(m,op,ctx)
 assert mod.same_operation(selected,op) and len(calls)==1
 assert not any(n=='operation_destination_revised' for n,d in events)


def test_three_by_eighteen_max_and_original_fallback(monkeypatch):
 m,op,ctx,events,calls,_=setup(monkeypatch,qualifies=False)
 assert mod.select_direct_buffer(m,op,ctx)==(op,None)
 assert len(calls)==3 and ctx.screened
 assert events[-1][1]['examined']==54


@pytest.mark.parametrize('change',['strict','off','direct_off','protected','mapping','index','lost_contact','retained'])
def test_gates_do_not_probe(monkeypatch,change):
 m,op,ctx,events,calls,obs=setup(monkeypatch)
 if change=='strict':m.c.acceptance_profile='strict'
 if change=='off':m.c.temporary_buffer_serviceability_enabled=False
 if change=='direct_off':m.c.completion_direct_buffer_enabled=False
 if change=='protected':m.verified_final_trays.add(0)
 if change=='mapping':m.scheduler.mapping=[0,1,2]
 if change=='index':m.operations+=1
 if change=='lost_contact':obs['gripper_contact_force'][0,0]=0
 if change=='retained':m.r.retained_contact=(0,'left')
 if change in ('lost_contact','retained'):
  with pytest.raises(Fault,match='grasp_context'):mod.select_direct_buffer(m,op,ctx)
 else:assert mod.select_direct_buffer(m,op,ctx)==(op,None)
 assert calls==[]


def test_cannot_reblock_requested_target(monkeypatch):
 m,op,ctx,events,calls,_=setup(monkeypatch)
 monkeypatch.setattr(mod,'_executable_geometry',lambda *a:False)
 assert mod.select_direct_buffer(m,op,ctx)==(op,None) and calls==[]


def test_unknown_scheduler_purpose_is_not_guessed(monkeypatch):
 m,op,ctx,events,calls,_=setup(monkeypatch)
 m.scheduler.choose=lambda p:Operation(2,-1,np.array([.5,0,.8]),0.,True)
 assert mod.capture_context(m,op,ctx.source_poses) is None


def test_real_geometry_ordinary_scheduler_source_keeps_requested_blocker_semantics(scene7):
 from r1pro_teleop.airport_fsm.geometry import Scheduler
 from r1pro_teleop.airport_fsm.contracts import Config
 from r1pro_teleop.airport_fsm.acceptance_profile import completion_criteria
 g,pose,_=scene7
 pose[0,:3]=g.goals[0];pose[1,:3]=g.goals[1]
 pose[2,:3]=np.array(g.tables['rear']['center_world']);pose[2,2]=.801
 pose[:,3:]=[1,0,0,0]
 c=Config(acceptance_profile='completion_first',temporary_buffer_serviceability_enabled=True,completion_direct_buffer_enabled=True)
 scheduler=Scheduler(g,completion_criteria(c),consistent_placement=True,require_full_footprint=False,use_actual_gap=True);scheduler.mapping=[0,2,1]
 op=scheduler.choose(pose)
 assert op.temporary and op.tray==1
 m=NS(c=c,g=g,scheduler=scheduler,operations=2,verified_final_trays={0})
 ctx=mod.capture_context(m,op,pose)
 assert ctx is not None and ctx.requested.tray==2 and ctx.requested.slot==1
 assert ctx.scene_id==g.spec['scene_id'] and ctx.operation_index==3
 original=ctx.source_poses.copy();pose[1,0]+=1
 np.testing.assert_array_equal(ctx.source_poses,original)
 m.verified_final_trays.add(1)
 assert mod.capture_context(m,op,original) is None


def test_general_buffer_uses_live_revised_operation_for_place_and_verify(scene7,monkeypatch):
 from test_buffer_serviceability import setup as old_setup
 from dataclasses import replace
 from r1pro_teleop.airport_fsm.machine import Machine
 m,op,oldctx,events,calls,obs,order=old_setup(scene7,monkeypatch)
 m.operations=1;m.c=replace(m.c,acceptance_profile='completion_first',max_operations=1,consistent_placement=False)
 m.scheduler.choose=lambda poses:oldctx.requested
 obs['tray_pose'][:]=oldctx.source_poses;obs['min_z']=np.full(3,.8)
 m.r.holding=None;m.r.tucked=np.zeros(16);m.r.wait=lambda *a,**kw:None;m.r.joints=lambda *a,**kw:None
 m._record_completion_slot_deviations=lambda pose:None
 ctx=NS(screened=False)
 monkeypatch.setattr(mod,'capture_context',lambda *a:ctx)
 revised=deepcopy(op);revised.destination[1]+=.05
 proposal={'operation':deepcopy(revised),'staged':revised.destination.copy(),'base':np.zeros(3)}
 def select(machine,operation,context):
  assert m.r.holding==operation.tray;ctx.screened=True;return revised,proposal
 monkeypatch.setattr(mod,'select_direct_buffer',select)
 m.prepare_pick=lambda *a:(0.,0.)
 m.grasp=lambda tray,*a:setattr(m.r,'holding',tray)
 carried=[];verified=[]
 m.carry_place=lambda operation,**kw:carried.append((operation,kw)) or False
 m.verify_operation=lambda operation:verified.append(operation) or True
 with pytest.raises(Fault,match='operation_budget_exhausted'):m.run()
 assert carried[0][0] is revised and verified[0] is revised
 assert carried[0][1]['placement_proposal'] is proposal

