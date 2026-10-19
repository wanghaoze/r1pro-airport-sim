from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest

from r1pro_teleop.airport_fsm import primitives
from r1pro_teleop.airport_fsm.contracts import Config, Fault
from r1pro_teleop.airport_fsm.withdraw_merge import planning_snapshot
from test_physical_preview import machine


def enabled(machine,private_position=.08):
    cfg=replace(machine.c,acceptance_profile='completion_first',
        retained_support_integer_clock_enabled=True,
        completion_held_ik_orientation_tolerance_rad=.12,
        completion_place_ik_fallback_enabled=True,
        completion_place_private_position_tolerance_m=private_position)
    machine.c=machine.r.cfg=cfg
    r=machine.r
    r.holding=0
    r.grasp_rel={'left':np.eye(4),'right':np.eye(4)}
    r.primitive_deadline_step=r.steps+100
    return r


def test_default_off_and_profile_validation():
    assert Config().completion_place_ik_fallback_enabled is False
    with pytest.raises(ValueError,match='must be boolean'):
        replace(Config(),completion_place_ik_fallback_enabled=1).validate()
    with pytest.raises(ValueError,match='requires completion_first'):
        replace(Config(),completion_place_ik_fallback_enabled=True).validate()


def test_transport_alignment_scope_restores_config_even_on_fault(machine):
    r=enabled(machine);configured=r.cfg
    with pytest.raises(Fault,match='coupled_ik_unreachable'):
        with primitives._original_place_orientation(r):
            assert r.cfg.completion_held_ik_orientation_tolerance_rad==.05
            raise Fault('coupled_ik_unreachable')
    assert r.cfg is configured


def test_private_relaxed_place_plan_only_after_full_strict_ik_failure(machine,monkeypatch):
    r=enabled(machine);configured=r.cfg;before=planning_snapshot(r)
    calls=[];selected=(('descent',12),('release',8))
    def prepare(probe_machine,*args):
        p=probe_machine.r
        calls.append((p is r,p.cfg.completion_held_ik_orientation_tolerance_rad,
                      p.steps,float(p.d.time)))
        if p is r:raise Fault('coupled_ik_unreachable',{'strict':True})
        assert p.d is not r.d and p.shadow is not r.shadow and p.sim.target is not r.sim.target
        p.trace.event('planning_policy_deviation',code='held_ik_orientation_outside_strict_contract',
                      detail={'planning_only':True,'execution_confirmed':False})
        return selected
    monkeypatch.setattr(primitives,'_plan_place_descent',prepare)
    result=primitives._plan_place_original_then_relaxed(machine,SimpleNamespace(tray=0),
        np.zeros(3),None,.8,True,None,['left','right'],False,None)
    assert result is selected
    assert calls==[(True,.05,r.steps,float(r.d.time)),(False,.12,r.steps,float(r.d.time))]
    assert r.cfg is configured and planning_snapshot(r).keys()==before.keys()
    for key in before:np.testing.assert_array_equal(planning_snapshot(r)[key],before[key])
    assert r.soft_guard_violation_by_code['held_ik_orientation_outside_strict_contract']==1


@pytest.mark.parametrize('reason',['illegal_collision','primitive_path_infeasible'])
def test_no_relaxed_fallback_for_non_ik_planning_failure(machine,monkeypatch,reason):
    r=enabled(machine);calls=[]
    def prepare(probe_machine,*args):
        calls.append(probe_machine.r)
        raise Fault(reason)
    monkeypatch.setattr(primitives,'_plan_place_descent',prepare)
    with pytest.raises(Fault,match=reason):
        primitives._plan_place_original_then_relaxed(machine,SimpleNamespace(tray=0),
            np.zeros(3),None,.8,True,None,['left','right'],False,None)
    assert calls==[r]


def test_no_relaxed_fallback_after_physical_step(machine,monkeypatch):
    r=enabled(machine);calls=[]
    def prepare(probe_machine,*args):
        calls.append(probe_machine.r)
        r.steps+=1
        raise Fault('coupled_ik_unreachable')
    monkeypatch.setattr(primitives,'_plan_place_descent',prepare)
    with pytest.raises(Fault,match='coupled_ik_unreachable'):
        primitives._plan_place_original_then_relaxed(machine,SimpleNamespace(tray=0),
            np.zeros(3),None,.8,True,None,['left','right'],False,None)
    assert calls==[r]


def test_no_relaxed_fallback_when_planning_changes_live_reference(machine,monkeypatch):
    r=enabled(machine);calls=[]
    def prepare(probe_machine,*args):
        calls.append(probe_machine.r)
        r.sim.target[0]+=.01
        raise Fault('coupled_ik_unreachable')
    monkeypatch.setattr(primitives,'_plan_place_descent',prepare)
    with pytest.raises(Fault,match='withdraw_planning_state_changed'):
        primitives._plan_place_original_then_relaxed(machine,SimpleNamespace(tray=0),
            np.zeros(3),None,.8,True,None,['left','right'],False,None)
    assert calls==[r]


def test_private_solver_prefers_original_orientation_seed_before_wide_seed(monkeypatch):
    from scipy.spatial.transform import Rotation
    from r1pro_teleop.airport_fsm import runtime as runtime_module
    from test_completion_held_ik import runtime
    live=runtime(bound=.08)
    live.cfg=replace(live.cfg,completion_held_ik_orientation_tolerance_rad=.12)
    goals={'left':(np.array([0.,0.,.08]),Rotation.from_euler('x',.08).as_matrix())}
    def solve(prefer):
        live._prefer_original_held_ik_seed=prefer
        calls=[]
        def fit(fn,initial,**kwargs):
            q=np.zeros(7)
            q[2],q[3]=(.01,.04) if not calls else (.03,.02)
            calls.append(1)
            return SimpleNamespace(x=q)
        monkeypatch.setattr(runtime_module,'least_squares',fit)
        return live.solve_pair(goals)
    ordinary=solve(False)
    preferred=solve(True)
    assert len(ordinary)==len(preferred)==16
    assert ordinary[2]==.03 and preferred[2]==.01
    assert ordinary[3]==.02 and preferred[3]==.04


def test_preview_fallback_cannot_modify_source_machine(machine,tmp_path,monkeypatch):
    from r1pro_teleop.airport_fsm import physical_preview
    r=enabled(machine)
    before=planning_snapshot(r)
    original_warnings=dict(r.soft_guard_violation_by_code)
    preview=physical_preview.clone_machine(machine,tmp_path/'preview_orientation')
    try:
        calls=[]
        def prepare(probe_machine,*args):
            calls.append(probe_machine.r)
            if len(calls)==1:raise Fault('coupled_ik_unreachable')
            return ('descent','release')
        monkeypatch.setattr(primitives,'_plan_place_descent',prepare)
        result=primitives._plan_place_original_then_relaxed(preview,SimpleNamespace(tray=0),
            np.zeros(3),None,.8,True,None,['left','right'],False,None)
        assert result==('descent','release') and len(calls)==2
        assert calls[0] is preview.r and calls[1] is not preview.r
        for key,value in before.items():np.testing.assert_array_equal(planning_snapshot(r)[key],value)
        assert r.soft_guard_violation_by_code==original_warnings
        assert machine.r.cfg.completion_place_ik_fallback_enabled
    finally:
        preview.log.close();preview.r.close()


def test_private_position_bound_only_on_place_probe_and_policy_logged(machine,monkeypatch):
    from r1pro_teleop.airport_fsm.contracts import State
    r=enabled(machine,private_position=.10)
    r.fsm_state=State.PLACE_TRAY
    assert r.cfg.validate() is r.cfg
    assert r.cfg.completion_held_ik_position_tolerance_m==.022
    assert not hasattr(r,'_place_private_position_bound_m')
    assert r._completion_held_ik_position_bound(.022)==.022
    seen=[]
    def prepare(probe_machine,*args):
        p=probe_machine.r
        seen.append((p is r,p._completion_held_ik_position_bound(.022)))
        if p is r:raise Fault('coupled_ik_unreachable')
        assert p.cfg.validate() is p.cfg
        assert p.cfg.completion_held_ik_position_tolerance_m==.022
        assert p._place_private_position_bound_m==.10
        p.trace.event('planning_policy_deviation',code='held_ik_position_outside_strict_contract',
            detail={'planning_only':True,'completion_position_tolerance_m':.10,
                    'position_error_m':.09,'execution_confirmed':False})
        return ('descent','release')
    monkeypatch.setattr(primitives,'_plan_place_descent',prepare)
    assert primitives._plan_place_original_then_relaxed(machine,SimpleNamespace(tray=0),
        np.zeros(3),None,.8,True,None,['left','right'],False,None)==('descent','release')
    assert seen==[(True,.022),(False,.10)]
    assert not hasattr(r,'_place_private_position_bound_m')
    assert not r.strict_runtime_passed
    assert r.soft_guard_violation_by_code['held_ik_position_outside_strict_contract']==1


def test_private_position_marker_requires_loaded_place_state(machine):
    from r1pro_teleop.airport_fsm.contracts import State
    r=enabled(machine,private_position=.10)
    r._place_private_position_bound_m=.10
    r.fsm_state=State.TRANSPORT_TRAY
    assert r._completion_held_ik_position_bound(.022)==.022
    r.fsm_state=State.PLACE_TRAY;r.retained_contact=(0,'left')
    assert r._completion_held_ik_position_bound(.012)==.012
    r.retained_contact=None;r.holding=None
    assert r._completion_held_ik_position_bound(.04)==.04
    r.holding=0;r._place_private_position_bound_m=.11
    with pytest.raises(Fault,match='place_private_position_bound_invalid'):
        r._completion_held_ik_position_bound(.022)
