from types import SimpleNamespace
import numpy as np
import pytest
from r1pro_teleop.airport_fsm.contracts import Config, Fault
from r1pro_teleop.airport_fsm.machine import Machine
from r1pro_teleop.airport_fsm import placement_reachability, primitives


@pytest.mark.parametrize('qualified', [False, True])
def test_screen_proposal_requires_navigation_then_measured_replanning(monkeypatch, qualified):
    machine=object.__new__(Machine)
    machine.c=Config(fixed_primitives=True,placement_screen_enabled=True)
    destination=np.array([.85,.38,.8])
    operation=SimpleNamespace(tray=0,destination=destination,yaw=0.)
    machine._place_location=lambda op:destination.copy()
    machine._inward_yaw=lambda position:0.
    machine.transition=lambda *a,**kw:None
    events=[];order=[]
    machine.log=SimpleNamespace(event=lambda name,**kw:events.append((name,kw)))
    observed={'gripper_contact_force':np.full((3,2),10.)}
    proposal=np.array([.85,.95,-np.pi/2])
    bases=[]
    def navigate(base):
        order.append('navigate');bases.append(base.copy());observed['arrived']=True
    machine.r=SimpleNamespace(navigate=navigate,observation=lambda:observed,
        remember_grasp=lambda tray:order.append('remeasure'))
    monkeypatch.setattr(placement_reachability,'carried_placement_candidates',lambda *a,**kw:[proposal])
    def screen(*a,**kw):
        order.append('screen')
        assert kw['max_candidates']==18 and kw['max_qualified']==1
        return SimpleNamespace(examined=1,qualified=[{'base':proposal}] if qualified else [],rejected=[])
    monkeypatch.setattr(placement_reachability,'screen_placement',screen)
    def place(m,op,staged):
        assert m.r.observation()['arrived']
        order.append('live_place')
    monkeypatch.setattr(primitives,'place',place)
    machine.carry_place(operation)
    assert order==['screen','navigate','remeasure','live_place']
    np.testing.assert_allclose(bases[0],proposal if qualified else [.28,.38,0.])
    assert next(fields for event,fields in events if event=='placement_reachability_screen')['fallback_to_nominal'] is not qualified


def test_screen_configuration_rejects_unbounded_or_unsupported_use():
    for value in (0,19,True,1.5):
        with pytest.raises(ValueError):Config(placement_max_probes=value).validate()
    with pytest.raises(ValueError,match='fixed primitives'):
        Config(placement_screen_enabled=True,fixed_primitives=False).validate()
