from types import SimpleNamespace
import numpy as np
from r1pro_teleop.airport_fsm.runtime import Runtime
from r1pro_teleop.airport_fsm.contracts import Config


def static_pair(distance, margin=.001):
    r = object.__new__(Runtime)
    r.cfg = Config(planner_margin_m=margin)
    r.robot_geoms = np.array([0]); r.table_geoms = np.array([1])
    r.m = SimpleNamespace(geom_rbound=np.ones(2), geom_contype=np.ones(2,dtype=int),
                         geom_conaffinity=np.ones(2,dtype=int),
                         geom=lambda i:SimpleNamespace(name=('robot','table')[i]))
    r.d = SimpleNamespace(contact=[],geom_xpos=np.array([[0.,0.,0.],[1.,0.,0.]]))
    r.mj = SimpleNamespace(mj_geomDistance=lambda *args:distance)
    return r


def test_static_body_missing_from_contacts_still_needs_planning_clearance():
    r = static_pair(.0005)
    assert r.collision(planning=True)['geoms'] == ['robot','table']
    assert r.collision() is None
    assert static_pair(.0015).collision(planning=True) is None


def test_static_live_guard_unchanged_and_custom_planning_margin_respected():
    assert static_pair(-.0001).collision() is None
    assert static_pair(-.0003).collision()['distance_m'] == -.0003
    assert static_pair(.002,margin=.003).collision(planning=True) is not None
