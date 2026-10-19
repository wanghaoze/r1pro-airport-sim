"""Preparatory contact is not a qualified grasp; actual illegal grasps reject."""
from types import SimpleNamespace
import numpy as np
import pytest
import r1pro_teleop.single_tray_3table.learned as learned
from r1pro_teleop.vla.policy import PolicyError


def fixture(monkeypatch,codes=(0,0)):
    p=np.zeros((2,1,3));n=np.zeros_like(p);active=np.zeros((2,1),bool)
    force=np.zeros(2)
    for side,code in enumerate(codes):
        if code:
            active[side,0]=True;force[side]=10
            p[side,0]=[.279,0,.075] if code==2 else [0,code*.205,.075]
            n[side,0]=[1,0,0] if code==2 else [0,code,0]
    numeric=dict(gripper_tray_contact_points_local=p,gripper_tray_contact_normals_local=n,
        gripper_tray_contact_active=active,gripper_contact_force=force,table_contact_counts=np.array([0,0,4]))
    obs=dict(gripper_contact_force=np.array([[10.,10.]]),table_contact=np.array([4]),min_z=np.array([.801]))
    r=SimpleNamespace(steps=0,cfg=SimpleNamespace(fps=20,criteria=SimpleNamespace(contact_n=.5,lifted_m=.04)),
        observation=lambda:obs,g=SimpleNamespace(tables={'rear':{}}),d=SimpleNamespace(body=lambda name:SimpleNamespace(xpos=np.zeros(3))))
    c=learned.LearnedThreeTable.__new__(learned.LearnedThreeTable)
    c.action='pick_empty';c.opposed_seen=False;c.initial_bottom=.801;c.grasp_contact_ticks=np.zeros(2,int);c.grasp_sample_step=None
    c.scene={'tray':{'size':[.56,.43,.105]},'source_table':'rear'}
    monkeypatch.setattr(learned,'contact_snapshot',lambda *args:numeric)
    monkeypatch.setattr(learned,'table_front_region_violation',lambda *args:False)
    return c,r,obs


def test_no_actual_contact_preparation_never_demands_opposed_grasp(monkeypatch):
    c,r,_=fixture(monkeypatch)
    for step in range(1,5):
        r.steps=step;assert c.endpoint(r,None) is False
    assert not c.opposed_seen and np.all(c.grasp_contact_ticks==0)


def test_allowed_single_long_rim_preparation_is_not_completed_pick(monkeypatch):
    c,r,_=fixture(monkeypatch,(-1,0))
    for step in range(1,5):r.steps=step;assert not c.endpoint(r,None)
    assert not c.opposed_seen


def test_confirmation_counts_distinct_ticks_and_completion_still_requires_lift(monkeypatch):
    c,r,obs=fixture(monkeypatch,(-1,1));r.steps=1
    for _ in range(5):assert not c.endpoint(r,None)
    assert np.all(c.grasp_contact_ticks==1) and not c.opposed_seen
    for step in (2,3):r.steps=step;assert not c.endpoint(r,None)
    assert c.opposed_seen
    obs['table_contact'][0]=0;obs['min_z'][0]=.851;r.steps=4
    assert c.endpoint(r,None)


@pytest.mark.parametrize('codes,error',[((-1,-1),'opposed_long_rims_required'),((2,0),'short_or_ambiguous_rim_grasp')])
def test_actual_confirmed_same_or_short_grasp_is_not_ignored(monkeypatch,codes,error):
    c,r,_=fixture(monkeypatch,codes)
    for step in (1,2):r.steps=step;assert not c.endpoint(r,None)
    r.steps=3
    with pytest.raises(PolicyError,match=error):c.endpoint(r,None)


def test_airborne_lift_never_waits_for_confirmation_to_reject_missing_dual_grasp(monkeypatch):
    c,r,obs=fixture(monkeypatch,(-1,0));r.steps=1
    obs['table_contact'][0]=0;obs['min_z'][0]=.851
    with pytest.raises(PolicyError,match='lift_requires_actual_opposed'):c.endpoint(r,None)


def test_completed_action_records_verified_endpoint_without_duplicate_event_keyword():
    events=[];trace=SimpleNamespace(count=0,event=lambda event,**row:events.append((event,row)))
    def held_tick():trace.count+=1
    r=SimpleNamespace(trace=trace,tick=held_tick)
    c=learned.LearnedThreeTable.__new__(learned.LearnedThreeTable);c.r=r;c.spans=[]
    c.scene={'place_target':{'position_world':[.85,.05,.801],'yaw_world':0}}
    c.endpoint=lambda runtime,operation:True
    c.executor=SimpleNamespace(execute_operation=lambda *args:None)
    c.run_action('pick_empty','Pick up the tray')
    assert events[-1][0]=='action_complete' and events[-1][1]['verified'] is True
    assert events[-1][1]['measured_endpoint_frame']==0 and events[-1][1]['end_frame']==1
