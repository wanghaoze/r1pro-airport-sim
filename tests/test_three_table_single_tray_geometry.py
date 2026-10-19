from copy import deepcopy
import numpy as np
import pytest
from test_airport_fsm_unit import spec_fixture
from r1pro_teleop.airport_fsm.geometry import Geometry
from r1pro_teleop.airport_fsm.runtime import Runtime
from r1pro_teleop.airport_fsm.contracts import Config,Fault
from r1pro_teleop.single_tray_3table.control import teacher_config,ThreeTableRuntime
from r1pro_teleop.airport_fsm.contracts import State
from r1pro_teleop.airport_fsm.machine import Machine
from r1pro_teleop.single_tray_3table.control import ThreeTableMachine
from r1pro_teleop.single_tray_3table.control import horizontal_axis_alignment_error


def test_one_real_tray_scope_is_explicit_and_does_not_change_legacy_default():
    spec=spec_fixture();assert len(Geometry(spec).ids)==3
    spec['trays']=spec['trays'][:1]
    with pytest.raises(Fault,match='scene_object_count'):Geometry(spec)
    geometry=Geometry(spec,expected_trays=1)
    assert geometry.ids==['tray_0'] and len(geometry.tables)==3 and len(geometry.goals)==3
    pose=np.array([np.r_[geometry.goals[0]+[0,0,.001],1.,0.,0.,0.]])
    assert geometry.top_available(pose,0)
    assert geometry.blockers(pose,0,pose[0,:3],0.)==[]
    for invalid in (True,0,2):
        with pytest.raises(Fault,match='unsupported_tray_scope'):Geometry(spec,expected_trays=invalid)


def test_runtime_rejects_foreign_geometry_before_model_or_scene_can_be_opened():
    spec=spec_fixture();spec['trays']=spec['trays'][:1];geometry=Geometry(spec,expected_trays=1)
    with pytest.raises(Fault,match='geometry_spec_identity'):
        Runtime(deepcopy(spec),'must_not_be_opened.xml',Config(),geometry=geometry)


def test_reused_teacher_config_keeps_original_primitives_and_extended_numeric_time_window():
    cfg=teacher_config()
    assert cfg.fixed_primitives and cfg.approximate_completion_enabled and cfg.primitive_seconds==20
    assert cfg.substep_control_enabled and not cfg.keep_place_contact and not cfg.alternate_rim_enabled
    from pathlib import Path
    original=Config.load(Path(__file__).resolve().parents[1]/'configs/airport_approximate_completion_retry3.json')
    assert cfg.completion_collision_penetration_m==original.completion_collision_penetration_m
    assert cfg.completion_held_ik_orientation_tolerance_rad==original.completion_held_ik_orientation_tolerance_rad
    assert cfg.placement_screen_enabled==original.placement_screen_enabled
    assert cfg.placement_arrival_rescreen_enabled==original.placement_arrival_rescreen_enabled
    from r1pro_teleop.airport_fsm.primitives import _original_place_orientation
    r=ThreeTableRuntime.__new__(ThreeTableRuntime);r.cfg=cfg;r.holding=0;r.retained_contact=None
    with _original_place_orientation(r):
        assert r.cfg.completion_held_ik_orientation_tolerance_rad==.05
        assert r._completion_held_ik_orientation_bound(.02)==.05


def test_new_scope_navigation_does_not_override_searched_pose_with_manifest_station(monkeypatch):
    r=ThreeTableRuntime.__new__(ThreeTableRuntime);r.holding=0;r.fsm_state=State.TRANSPORT_TRAY;r.trace=None
    r.manifest={'target_robot_pose':{'position_world':[.47,.05,0.],'yaw_world':0.}}
    executed=[];monkeypatch.setattr(Runtime,'navigate',lambda self,goal:executed.append(goal.copy()))
    r.navigate([.21,.05,0.]);np.testing.assert_array_equal(executed[-1],[.21,.05,0.])
    r.fsm_state=State.ALIGN_BASE;r.navigate([-.59,.1,np.pi])
    np.testing.assert_array_equal(executed[-1],[-.59,.1,np.pi])


def test_private_approximation_requires_declared_approximate_configuration_before_scene_loading():
    with pytest.raises(ValueError,match='Declared approximate'):
        ThreeTableRuntime({},Config(),approximate_planning=True)


def test_source_search_keeps_original_pose_and_heading_candidates_except_table_sides(monkeypatch):
    from types import SimpleNamespace
    m=ThreeTableMachine.__new__(ThreeTableMachine)
    m.g=SimpleNamespace(tables={'front_left':{'table_id':'front_left',
        'center_world':[0,0,.8],'dimensions_m':[1.2,.6,.8],'yaw_world':np.pi/2}},
        support_table=lambda p:'front_left',sizes=np.array([[.56,.43,.105]]))
    m.c=SimpleNamespace(rim_inset_m=.01)
    m._poses=lambda:np.array([[0,0,.8,1,0,0,0]])
    candidates=[(np.array([-.6,0.,.2]),.1,0.),(np.array([-.5,.2,-.15]),.05,.01),
        (np.array([-.1,.8,0.]),0.,0.),(np.array([-.6,.8,0.]),0.,0.)]
    monkeypatch.setattr(Machine,'_candidate_list',lambda self,tray:candidates)
    selected=m._candidate_list(0)
    assert len(selected)==2
    for actual,original in zip(selected,candidates):
        np.testing.assert_array_equal(actual[0],original[0])
        assert actual[2]==original[2] and actual.rim_pair.axis=='width'


def test_forward_alignment_is_horizontal_unoriented_axis_not_roll_pitch():
    assert horizontal_axis_alignment_error([.5,0,.866],[1,0,0])==0.
    assert horizontal_axis_alignment_error([-.5,0,.866],[1,0,.2])==0.
    assert horizontal_axis_alignment_error([1,1,2],[1,0,1])==pytest.approx(np.pi/4)
    with pytest.raises(Fault,match='undefined_horizontal'):horizontal_axis_alignment_error([0,0,1],[1,0,0])
