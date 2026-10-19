"""Independent candidate tests; does not import or execute the probe CLI."""
import ast
from pathlib import Path
from types import SimpleNamespace
import sys
import numpy as np
import pytest
from r1pro_teleop.airport_fsm.contracts import Fault


def candidate_class(base):
    source=Path(__file__).resolve().parents[1]/'runs/single_tray_loaded_push_physics_probe.py'
    node=next(n for n in ast.parse(source.read_text()).body if isinstance(n,ast.ClassDef) and n.name=='Diagnostic')
    namespace=dict(SingleTrayController=base,np=np,sys=sys,Fault=Fault)
    exec(compile(ast.Module(body=[node],type_ignores=[]),str(source),'exec'),namespace)
    return namespace['Diagnostic']


def test_hand_reference_cap_uses_actual_tcp_even_after_body_stops_and_retraction():
    c=candidate_class(object)();c.p=SimpleNamespace(robot_left=(0,1,0),loaded_goal_position=(.85,.295,.8),push_step_m=.012,push_reference_lead_m=.04)
    c.push_anchor=('right',np.array([.85,-.24,.8]),np.array([.65,-.44,.875]),np.eye(3))
    actual=np.array([.65,-.405,.87]);c.sim=SimpleNamespace(tcp=lambda side:(actual,np.eye(3)))
    c.observation=lambda:dict(tray_position=np.array([.85,-.24,.8]))
    desired,_,_,increment=c._diagnostic_hand_goal('right')
    assert increment==pytest.approx(.012)  # tray did not move but hand reference can still supply effort
    assert desired[1]==pytest.approx(-.428)
    c.diagnostic_tcp_force_goals={'right':np.array([.65,-.36,.875])}
    desired,_,_,increment=c._diagnostic_hand_goal('right')
    assert increment==pytest.approx(-.005)  # measured retreat cannot silently exceed the cap
    assert (desired-actual)[1]==pytest.approx(.04)
    np.testing.assert_array_equal(desired[[0,2]],[.65,.875])


def test_neutralization_changes_only_left_axis_and_requires_three_actual_ticks(monkeypatch):
    class Base:
        def _push_reference_move(self,position,side):self.submitted=(position.copy(),side)
        def _handover(self):self.real_handover_called=True
    c=candidate_class(Base)();monkeypatch.setattr(sys,'argv',['probe']+['unused']*7+['tcp_lead_handover'])
    c.p=SimpleNamespace(robot_left=(0,1,0),fps=20,contact_n=.5)
    origin=np.array([.85,-.24,.8]);anchor=np.array([.65,-.44,.875]);actual=np.array([.66,-.36,.87])
    c.push_anchor=('right',origin,anchor,np.eye(3));reference=np.array([.65,-.34,.875])
    c.diagnostic_tcp_force_goals={'right':reference.copy()}
    c.sim=SimpleNamespace(tcp=lambda side:(actual.copy(),np.eye(3)))
    obs=dict(tray_position=np.array([.85,-.16,.8]),gripper_contact_force={'right':2.})
    c.observation=lambda:obs;c._on_table=lambda state:True;c.events=[]
    c.event=lambda name,**data:c.events.append((name,data));c.ticks=0
    def tick():c.ticks+=1;return obs
    c.tick=tick;c._handover()
    neutral=c.diagnostic_tcp_force_goals['right']
    np.testing.assert_array_equal(neutral[[0,2]],reference[[0,2]])
    assert neutral[1]==actual[1] and c.ticks==3 and c.real_handover_called
    np.testing.assert_array_equal(c.submitted[0],origin+neutral-anchor)
