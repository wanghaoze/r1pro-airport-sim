from types import SimpleNamespace
import numpy as np
from test_airport_fsm_unit import spec_fixture,poses
from r1pro_teleop.airport_fsm.geometry import Geometry,Scheduler,slot_geometry_ready
from r1pro_teleop.airport_fsm.contracts import Criteria,Config
from r1pro_teleop.airport_fsm.machine import Machine


def test_accepted_gap_cannot_obstruct_next_reserved_slot():
    g=Geometry(spec_fixture());p=poses(g)
    p[0,:3]+=g.R@np.array([.0135,0,0])
    p[1,:3]+=g.R@np.array([.3,.2,0])
    assert g.at_slot(p,0,0,position_tol=.03)
    assert not slot_geometry_ready(g,p,[0,1,2],0,0,Criteria())
    s=Scheduler(g,Criteria(),consistent_placement=True);s.mapping=[0,1,2]
    assert s.choose(p).tray==0


def test_valid_placement_is_not_selected_again():
    g=Geometry(spec_fixture());p=poses(g)
    s=Scheduler(g,Criteria(),consistent_placement=True);s.mapping=[0,1,2]
    assert s.choose(p) is None


def test_separation_target_reserves_execution_clearance_and_tracking_margin():
    m=Machine.__new__(Machine);m.g=Geometry(spec_fixture())
    m.c=SimpleNamespace(single_contact_separation=True,keep_pick_contact=False)
    m._separation_path_valid=lambda *a:True
    p=poses(m.g)
    candidates=m._separation_candidates(p,0,m.g.goal_yaw[0])
    assert candidates
    assert all(not m.g.blockers(p,0,q,m.g.goal_yaw[0],.075) for q in candidates)


def test_new_behaviour_does_not_silently_change_old_configs():
    assert not Config().consistent_placement
    assert not Config().single_contact_separation
