from types import SimpleNamespace
import numpy as np
import pytest
from r1pro_teleop.airport_fsm.contracts import Fault
from r1pro_teleop.single_tray_3table import placement_scope as scope


def fixture(monkeypatch):
    events=[]
    r=SimpleNamespace(g=SimpleNamespace(tables={'front_left':dict(center_world=[.85,0,0],dimensions_m=[1.2,.6,.8])},
        R=np.array([[0,-1,0],[1,0,0],[0,0,1]])))
    machine=SimpleNamespace(r=r,c=SimpleNamespace(keep_place_contact=False),
        manifest={'target_table':'front_left'},_place_location=lambda op:op.destination,
        _inward_yaw=lambda p:0.,log=SimpleNamespace(event=lambda name,**kwargs:events.append((name,kwargs))))
    operation=SimpleNamespace(destination=np.array([.85,.05,.801]),yaw=0.)
    monkeypatch.setattr(scope,'candidate_stations',lambda *args:iter([
        np.array([.28,.05,0]),np.array([.4,.05,0]),np.array([.45,.05,0])]))
    return machine,operation,events


def test_future_failure_cannot_fallback_to_empty_only_nominal(monkeypatch):
    machine,op,events=fixture(monkeypatch);screened=[]
    def endpoint(r,m,o,b):
        if b[0]<.39:raise Fault('single_tray_private_ik_unreachable')
        return {'position_error_m':.001}
    monkeypatch.setattr(scope,'future_left_endpoint',endpoint)
    def screen(*a,**k):
        screened.append(k['candidates'][0].copy())
        return SimpleNamespace(qualified=[{}],rejected=[])
    monkeypatch.setattr(scope,'screen_placement',screen)
    selected=scope.select_joint_station(machine,op)
    assert selected['base'][0]==.4 and len(screened)==1
    assert events[0][1]['rejected'][0]['reason']=='single_tray_private_ik_unreachable'
    assert selected['operation'] is op


def test_place_screen_still_must_pass_and_no_live_execution(monkeypatch):
    machine,op,events=fixture(monkeypatch)
    monkeypatch.setattr(scope,'future_left_endpoint',lambda *a:{'position_error_m':0.})
    monkeypatch.setattr(scope,'screen_placement',lambda *a,**k:SimpleNamespace(qualified=[],rejected=[{'reason':'place_collision'}]))
    with pytest.raises(Fault,match='three_table_no_joint_place_push_station'):
        scope.select_joint_station(machine,op)
    assert events==[]


def test_front_filter_rejects_side_station_before_any_solver(monkeypatch):
    machine,op,_=fixture(monkeypatch)
    monkeypatch.setattr(scope,'candidate_stations',lambda *a:iter([np.array([.4,.7,0])]))
    monkeypatch.setattr(scope,'future_left_endpoint',lambda *a:pytest.fail('side solver forbidden'))
    with pytest.raises(Fault) as exc:scope.select_joint_station(machine,op)
    assert exc.value.detail[0]['reason']=='not_table_front'


def test_original_candidates_and_headings_retained(monkeypatch):
    old=[np.array([.28,.05,.12]),np.array([.24,0,0])]
    monkeypatch.setattr(scope,'carried_placement_candidates',lambda *a,**k:iter(old))
    result=list(scope.candidate_stations(None,np.array([.28,.05,0]),np.array([.85,.05]),0))
    np.testing.assert_allclose(result[0],[.32,.05,0]);np.testing.assert_allclose(result[1],[.34,.05,0])
    assert result[-2] is old[0] and result[-1] is old[1]


def test_future_left_does_not_qualify_unreachable_right_approach(monkeypatch):
    machine,op,_=fixture(monkeypatch);r=machine.r
    r.cfg=SimpleNamespace(rim_height_local_m=.075,rim_inset_m=.01)
    r.g.sizes=np.array([[.56,.43,.105]])
    probe=SimpleNamespace(sim=object(),m=object(),d=object(),mj=object(),
        grasp_goals=lambda centre,face,**kw:{kw['sides'][0]:(centre.copy(),np.eye(3))})
    monkeypatch.setattr(scope,'loaded_planning_copy',lambda r:probe)
    monkeypatch.setattr(scope,'_project',lambda *a,**k:None)
    calls=[]
    def solve(checker,side,position,rotation,**kw):
        calls.append((side,position.copy(),checker.private_incremental_command_prediction,checker.holding_sides.copy()))
        if side=='right':raise Fault('single_tray_private_ik_unreachable')
        return [(0,np.zeros(7),.001,.001)]
    monkeypatch.setattr(scope.SingleTrayController,'_ik_candidates',solve)
    scene=dict(target_table='front_left',loaded_push_target={'table_edge_margin_m':0,'goal_edge_tolerance_m':.05})
    with pytest.raises(Fault,match='single_tray_private_ik_unreachable'):
        scope.future_left_endpoint(r,scene,op,np.array([.4,.05,0]))
    assert calls[0][0]=='left' and calls[0][2:] == (True,{'left'})
    assert calls[1][0]=='right' and calls[1][2:] == (False,set())
    assert calls[1][1][2]==pytest.approx(.801+.075+.09)
