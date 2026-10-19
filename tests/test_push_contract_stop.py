import numpy as np
from test_airport_fsm_unit import spec_fixture,poses
from r1pro_teleop.airport_fsm.geometry import Geometry,slot_geometry_ready
from r1pro_teleop.airport_fsm.contracts import Criteria


def fixture():
    g=Geometry(spec_fixture());p=poses(g)
    p[1,:3]+=g.R@np.array([-.0097,.012,0.])
    yaw=g.goal_yaw[1]-.0069;p[1,3:]=[np.cos(yaw/2),0,0,np.sin(yaw/2)]
    return g,p


def test_no_need_to_force_six_mm_when_pose_and_gaps_are_valid():
    g,p=fixture()
    assert np.linalg.norm(p[1,:3]-g.goals[1])>.006
    assert slot_geometry_ready(g,p,[0,1,2],1,1,Criteria())


def test_position_tolerance_does_not_hide_gap_overlap():
    g=Geometry(spec_fixture());p=poses(g)
    p[1,:3]+=g.R@np.array([-.025,0,0])
    assert np.linalg.norm(p[1,:3]-g.goals[1])<.03
    assert not slot_geometry_ready(g,p,[0,1,2],1,1,Criteria())


def test_measured_accepted_neighbour_is_not_replaced_by_ideal_pose():
    g,p=fixture();p[0,:3]+=g.R@np.array([.008,0,0])
    assert not slot_geometry_ready(g,p,[0,1,2],1,1,Criteria())


def test_unplaced_neighbour_reserves_its_future_footprint():
    g,p=fixture();p[0,:3]+=g.R@np.array([-.2,0,0])
    assert slot_geometry_ready(g,p,[0,1,2],1,1,Criteria())
    p[1,:3]+=g.R@np.array([-.02,0,0])
    assert not slot_geometry_ready(g,p,[0,1,2],1,1,Criteria())
