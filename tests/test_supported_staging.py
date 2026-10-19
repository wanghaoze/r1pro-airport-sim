from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest

from r1pro_teleop.airport_fsm.contracts import Config, Fault
from r1pro_teleop.airport_fsm.machine import Machine
from r1pro_teleop.airport_fsm import supported_staging as stage, primitives
from test_placement_arrival_rescreen import setup


def geometric_machine():
    # The full-footprint / push sweep checks are supplied by Geometry in the
    # actual controller; this fixture isolates the ranking and finite bound.
    seen = []
    def push(pose, tray, destination, yaw, **kw):
        seen.append(pose[tray, :3].copy())
        return True
    g = SimpleNamespace(sizes=np.array([[.56,.43],[.56,.43],[.56,.43]]),
        goal_yaw=np.zeros(3), footprint_supported=lambda *a:True,
        blockers=lambda *a, **kw:[], push_possible=push)
    c = Config(acceptance_profile='completion_first', fixed_primitives=True,
               completion_supported_staging_enabled=True)
    scheduler=SimpleNamespace(mapping=[0,1,2], reservation_plan=None, criteria=c.criteria)
    m=SimpleNamespace(g=g,c=c,scheduler=scheduler)
    pose=np.zeros((3,7));pose[0,:3]=[.85,.46,.85]
    operation=SimpleNamespace(tray=0,destination=np.array([.85,.20,.8]),yaw=0.)
    return m,operation,pose,seen


def test_lattice_finds_near_side_supported_stage_and_rejects_unhelpful_geometry():
    m,op,pose,seen=geometric_machine()
    candidates=stage.supported_candidates(m,op,op.destination,pose)
    assert candidates
    assert any(np.allclose(candidate[:2],[.85,.38],atol=.011) for candidate in candidates)
    assert all(np.linalg.norm(candidate[:2]-op.destination[:2])<=.18+1e-9
               for candidate in candidates)
    assert all(np.linalg.norm(pose[0,:2]-candidate[:2])<=.14+1e-9
               for candidate in candidates)
    assert len(seen)<=378
    m.g.footprint_supported=lambda *a:False
    assert stage.supported_candidates(m,op,op.destination,pose)==[]


def test_private_screen_rejects_all_without_mutating_live_runtime(monkeypatch):
    m,op,pose,_=geometric_machine()
    events=[];clones=[]
    m.log=SimpleNamespace(event=lambda name,**kw:events.append((name,kw)))
    r=SimpleNamespace(observation=lambda:{'tray_pose':pose.copy()},
                      sim=SimpleNamespace(base_state=lambda:np.zeros(3)),steps=7)
    m.r=r
    monkeypatch.setattr(stage,'loaded_planning_copy',lambda runtime:clones.append(object()) or clones[-1])
    def reject(probe,*args):
        assert probe is not r
        raise Fault('coupled_ik_unreachable')
    monkeypatch.setattr(stage,'qualify_placement',reject)
    assert stage.screen_supported_staging(m,op,op.destination) is None
    assert len(clones)==stage.MAX_PRIVATE_PROBES
    assert r.steps==7 and np.array_equal(r.observation()['tray_pose'],pose)
    assert events[-1][1]['selected'] is None


def test_private_screen_prefers_later_separate_alignment_over_combined(monkeypatch):
    m, op, pose, _ = geometric_machine()
    events = []
    m.log = SimpleNamespace(event=lambda name, **kw: events.append((name, kw)))
    m.r = SimpleNamespace(observation=lambda: {'tray_pose': pose.copy()},
                          sim=SimpleNamespace(base_state=lambda: np.zeros(3)))
    first = np.array([.85, .35, .8])
    second = np.array([.85, .36, .8])
    monkeypatch.setattr(stage, 'supported_candidates', lambda *a: [first, second])
    monkeypatch.setattr(stage, 'loaded_planning_copy', lambda runtime: object())
    monkeypatch.setattr(stage, 'qualify_placement', lambda probe, staged, *a:
        {'prediction_mode': 'combined_descent' if np.array_equal(staged, first)
         else 'separate_alignment'})
    selected = stage.screen_supported_staging(m, op, op.destination)
    np.testing.assert_array_equal(selected, second)
    assert events[-1][1]['examined'] == 2


def test_machine_fallback_after_original_zero_motion_ik_only(monkeypatch):
    m,op,order,events,bases,screens,failures=setup(monkeypatch,
        failure='coupled_ik_unreachable',enabled=False)
    m.c=replace(m.c,acceptance_profile='completion_first',
                completion_supported_staging_enabled=True)
    m.r.cfg=m.c
    alternate=np.array([.85,.20,.8]);candidates=[]
    def choose(machine, operation, staged):
        candidates.append(staged.copy());return alternate.copy()
    monkeypatch.setattr(stage,'screen_supported_staging',choose)
    previous=primitives.place
    def one_live_alternate(machine, operation, staged):
        if np.array_equal(staged,alternate):
            order.append('alternate_place');return True
        return previous(machine,operation,staged)
    monkeypatch.setattr(primitives,'place',one_live_alternate)
    assert m.carry_place(op)
    assert len(candidates)==1 and len(bases)==1 and not screens
    assert order[-2:]==['remeasure','alternate_place']
    assert any(name=='completion_supported_staging_selected' for name,_ in events)


@pytest.mark.parametrize('code,advance',[
    ('primitive_path_infeasible',0),('coupled_ik_unreachable',1)])
def test_non_ik_or_partial_motion_cannot_enter_staging(monkeypatch,code,advance):
    m,op,order,events,bases,screens,failures=setup(monkeypatch,
        failure=code,advance_steps=advance,enabled=False)
    m.c=replace(m.c,acceptance_profile='completion_first',
                completion_supported_staging_enabled=True)
    m.r.cfg=m.c
    monkeypatch.setattr(stage,'screen_supported_staging',
                        lambda *a:pytest.fail('private staging must not run'))
    with pytest.raises(Fault) as got:m.carry_place(op)
    assert got.value is failures[0]


def test_config_gate_is_default_off_and_completion_only():
    assert not Config().completion_supported_staging_enabled
    with pytest.raises(ValueError,match='requires completion_first'):
        Config(completion_supported_staging_enabled=True).validate()
    Config(acceptance_profile='completion_first',fixed_primitives=True,
           retained_support_integer_clock_enabled=True,keep_place_contact=True,
           completion_supported_staging_enabled=True).validate()
