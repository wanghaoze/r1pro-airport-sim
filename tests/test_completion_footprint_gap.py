"""Actual v29 terminal pose regressions, geometry only (not new episode success)."""
import numpy as np
import pytest
from dataclasses import replace
from test_airport_fsm_unit import spec_fixture,valid_rows
from test_completion_acceptance import config
from r1pro_teleop.airport_fsm.geometry import Geometry,rectangle,footprint_boundary_distance,slot_geometry_ready,Scheduler
from r1pro_teleop.airport_fsm.acceptance_profile import completion_criteria,profile_placement_ok

CASES = {5: {'poses': [[0.8433106283055427, -0.515783261736528, 0.7999976045100429, 0.9997931297336767, -4.526531201111428e-07, -2.0932325903036525e-07, 0.020339560887357472], [0.8409340690479938, -0.06702258157786065, 0.7999952170405821, 0.9998939123443201, -1.497494309979303e-07, 8.314466070573587e-08, 0.014565852420597315], [0.847232156793458, 0.3797565397274745, 0.7999952170405821, 0.0020153222236976853, -8.561621711699094e-08, -1.4835022322951778e-07, 0.9999979692360905]], 'mapping': [2, 1, 0]}, 7: {'poses': [[0.8497455495389548, 0.3816770382251835, 0.7999952170405823, -0.0012306322809555207, 8.54997826789184e-08, 1.4841736050066498e-07, -0.9999992427717932], [0.8437267395192052, -0.5153844037227593, 0.7999960312942677, -0.0198300992922267, -2.676570366952757e-06, 9.783611296050755e-06, 0.9998033641967697], [0.840297164894113, -0.06770104805365766, 0.7999952170405825, 0.01685377769950474, 8.280178441432148e-08, 1.4993928910774486e-07, -0.9998579650016436]], 'mapping': [0, 2, 1]}, 310: {'poses': [[0.8432082201030732, -0.06974377371909625, 0.7999952170405821, 0.011909602302730731, 8.35421751061441e-08, 1.495280274242811e-07, -0.9999290781715282], [0.8387243976255534, -0.5083856685275507, 0.7999974109240211, 0.9998410633223376, -2.452456725461636e-06, -1.2139756309895925e-07, 0.017828294602385487], [0.8512215226239017, 0.3744903372299939, 0.799995217040582, 0.0010525353742022814, 8.516069934547226e-08, 1.4861218286405816e-07, -0.9999994460844743]], 'mapping': [2, 0, 1]}}

@pytest.mark.parametrize('case',[5,7,310])
def test_v29_actual_disjoint_terminal_poses_are_completion_eligible(case):
    value=CASES[case];g=Geometry(spec_fixture());p=np.asarray(value['poses']);cfg=config();criteria=completion_criteria(cfg)
    mapping=value['mapping'];tray=mapping[2]
    assert not slot_geometry_ready(g,p,mapping,tray,2,criteria)
    assert slot_geometry_ready(g,p,mapping,tray,2,criteria,require_full_footprint=False,use_actual_gap=True)
    scheduler=Scheduler(g,criteria,consistent_placement=True,require_full_footprint=False,use_actual_gap=True)
    scheduler.mapping=mapping
    assert scheduler.choose(p) is None
    rows=valid_rows();rows['tray_pose'][:]=p
    valid,report=profile_placement_ok(rows,g,cfg)
    assert valid and not report['strict_accepted']
    assert report['placement']['gap_measure']=='disjoint_rotated_footprint_euclidean_boundary'
    assert all(0<=gap<=.05 for gap in report['placement']['final_gaps_m'])
    # Real intersection, unsupported COM, or no physical support never become completion.
    rows['tray_pose'][:,mapping[2]]=rows['tray_pose'][:,mapping[1]]
    assert not profile_placement_ok(rows,g,cfg)[0]
    rows['tray_pose'][:]=p;rows['table_contact'][-1,tray]=0
    assert not profile_placement_ok(rows,g,cfg)[0]


def test_euclidean_distance_not_single_axis_and_intersection_is_rejected():
    a=rectangle([0,0],0,[1,1]);b=rectangle([1.04,1.04],0,[1,1])
    assert footprint_boundary_distance(a,b)==pytest.approx(np.sqrt(2)*.04)
    assert footprint_boundary_distance(a,rectangle([.99,0],0,[1,1])) is None
    assert footprint_boundary_distance(a,rectangle([1,0],0,[1,1]))==0


def test_gap_ceiling_is_not_removed_and_strict_defaults_remain():
    from test_airport_fsm_unit import poses
    g=Geometry(spec_fixture());p=poses(g);p[2,1]-=.04
    c=completion_criteria(config())
    assert not slot_geometry_ready(g,p,[0,1,2],2,2,c,require_full_footprint=False,use_actual_gap=True)
    rows=valid_rows();rows['tray_pose'][:]=p
    assert not profile_placement_ok(rows,g,config())[0]
