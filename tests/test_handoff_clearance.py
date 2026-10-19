from contextlib import contextmanager
from dataclasses import replace
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from r1pro_teleop.airport_fsm.contracts import Config, Fault
from r1pro_teleop.airport_fsm.handoff_clearance import (
    check_monitor, finger_top_clearance, perform_handoff_clearance)


def candidate_config(**changes):
    return replace(Config(), acceptance_profile='completion_first',
        retained_support_integer_clock_enabled=True, fixed_primitives=True,
        keep_place_contact=True, completion_handoff_clearance_enabled=True,
        **changes)


def test_handoff_clearance_is_default_off_and_excludes_old_free_first():
    assert not Config().completion_handoff_clearance_enabled
    candidate_config().validate()
    with pytest.raises(ValueError, match='completion_handoff_clearance_enabled'):
        candidate_config(completion_push_free_first_enabled=True).validate()
    with pytest.raises(ValueError, match='completion_handoff_clearance_enabled'):
        candidate_config(completion_push_free_open_enabled=True).validate()
    path = Path(__file__).resolve().parents[1] / 'configs/airport_completion_handoff_clearance_retry3.json'
    configured = json.loads(path.read_text())
    assert configured['completion_handoff_clearance_enabled'] is True
    assert configured['completion_push_free_first_enabled'] is False
    assert configured['completion_push_free_open_enabled'] is False
    Config(**configured).validate()


@pytest.mark.parametrize('side', ['left', 'right'])
def test_precleared_free_arm_command_is_pinned_through_push_reference(side):
    from r1pro_teleop.airport_fsm.primitives import hold_precleared_free_arm
    target = np.arange(16, dtype=float) / 100.
    target[7 if side == 'left' else 15] = .1
    points = [target.copy(), target + .01, target + .02]
    held_columns = np.arange(8, 16) if side == 'left' else np.arange(0, 8)
    free_columns = np.arange(0, 8) if side == 'left' else np.arange(8, 16)
    before = np.stack([point[held_columns].copy() for point in points])
    hold_precleared_free_arm(points, target, side)
    for point in points:
        np.testing.assert_array_equal(point[free_columns], target[free_columns])
    np.testing.assert_array_equal(np.stack([point[held_columns] for point in points]), before)


def test_monitor_rejects_real_free_finger_recontact_and_lost_support():
    r = SimpleNamespace(cfg=Config(), g=SimpleNamespace(
        support_table=lambda _: 'table', tables={'table': {'dimensions_m': [1., 1., .8]}}))
    e = {'gripper_contact_force': np.array([[10., 0.]]),
         'table_contact': np.array([2]), 'min_z': np.array([.8]),
         'tray_pose': np.array([[0., 0., .8, 1., 0., 0., 0.]])}
    check_monitor(r, e, (0, 'right'))
    e['gripper_contact_force'][0, 1] = .6
    with pytest.raises(Fault, match='handoff_clearance_free_recontact'):
        check_monitor(r, e, (0, 'right'))
    e['gripper_contact_force'][0, 1] = 0.
    e['table_contact'][0] = 0
    e['min_z'][0] = .803
    with pytest.raises(Fault, match='handoff_clearance_support_lost'):
        check_monitor(r, e, (0, 'right'))
    e['min_z'][0] = .801
    check_monitor(r, e, (0, 'right'))  # Existing retained microbounce guard decides this case.


def test_finger_clearance_uses_both_actual_collision_boxes_not_tcp():
    class Model:
        ngeom = 2
        geom_group = np.array([3, 3])
        geom_bodyid = np.array([1, 2])
        geom_type = np.array([6, 6])
        geom_size = np.array([[.03, .005, .02], [.03, .005, .02]])
        def body(self, key):
            names = {'tray_0': 'tray_0', 1: 'right_gripper_finger_link1',
                     2: 'right_gripper_finger_link2'}
            return SimpleNamespace(id=0, name=names[key])
    data = SimpleNamespace(
        geom_xmat=np.tile(np.eye(3).reshape(1, 9), (2, 1)),
        geom_xpos=np.array([[0., 0., .935], [0., 0., .945]]),
        body=lambda key: SimpleNamespace(xmat=np.eye(3).reshape(9), xpos=np.array([0., 0., .8])))
    r = SimpleNamespace(m=Model(), d=data,
        mj=SimpleNamespace(mjtGeom=SimpleNamespace(mjGEOM_BOX=6)),
        g=SimpleNamespace(ids=['tray_0']),
        evidence=SimpleNamespace(local_vertices={0: np.array([[0., 0., 0.], [0., 0., .105]])}))
    assert finger_top_clearance(r, 0, 'right') == pytest.approx(.01)


def test_handoff_separates_open_and_vertical_with_measured_gate(monkeypatch):
    from r1pro_teleop.airport_fsm import handoff_clearance as module
    from r1pro_teleop.airport_fsm import primitives

    calls = []
    events = []
    target = np.zeros(16)
    target[15] = .04
    e = {'table_contact': np.array([4]),
         'gripper_contact_force': np.array([[12., 0.]])}
    r = SimpleNamespace(holding=None, retained_contact=(0, 'left'),
        primitive_deadline_step=None, _handoff_clearance_monitor=None,
        cfg=candidate_config(), sim=SimpleNamespace(
            target=target, state=lambda: r.sim.target.copy(),
            tcp=lambda side: (np.array([.8, -.6, .89]), np.eye(3))),
        observation=lambda: e, check_retained_contact=lambda: calls.append('retained_checked'),
        wait=lambda seconds, predicate, stable: calls.append('measured_gate') or predicate(e),
        cartesian=lambda goals, **kwargs: (calls.append('vertical_preview') or
            [r.sim.target.copy(), np.r_[np.zeros(14), goals['right'][0][2], .1]]))
    machine = SimpleNamespace(r=r, c=r.cfg,
        transition=lambda *args: calls.append(args[1]),
        log=SimpleNamespace(event=lambda name, **kw: (calls.append(name), events.append((name, kw)))))
    operation = SimpleNamespace(tray=0)

    @contextmanager
    def fake_action(_machine, name, **kwargs):
        calls.append('action:' + name)
        r.primitive_deadline_step = 100
        try:
            yield
        finally:
            r.primitive_deadline_step = None

    def fake_plan(_r, points, **kwargs):
        calls.append('plan')
        return np.asarray(points), 1

    def fake_execute(_r, planned):
        calls.append('execute')
        r.sim.target = planned[0][-1].copy()

    monkeypatch.setattr(primitives, 'action', fake_action)
    monkeypatch.setattr(primitives, 'plan', fake_plan)
    monkeypatch.setattr(primitives, 'execute', fake_execute)
    monkeypatch.setattr(primitives, 'remaining', lambda _r: 5.)
    # The v53 6 cm endpoint had 8.7–10.2 mm predicted yet only 3–4.3 mm
    # measured. A candidate must now clear 20 mm in prediction; the physical
    # measurement still has the original independent 5 mm interlock.
    monkeypatch.setattr(module, 'finger_top_clearance',
        lambda _r, _tray, _free, target=None:
            (.005 + (target[14] - .89) * .2) if target is not None else .006)

    perform_handoff_clearance(machine, operation, 'left')
    assert r._handoff_clearance_monitor == (0, 'right')
    assert calls.index('measured_gate') < calls.index('vertical_preview')
    assert calls.index('handoff_clearance_open_verified') < calls.index('handoff_clearance_vertical_selected')
    chosen = next(data for name, data in events if name == 'handoff_clearance_vertical_selected')
    assert chosen['rise_m'] == pytest.approx(.08)
    assert [item['rise_m'] for item in chosen['rejected']] == [.04, .06]
    assert chosen['predicted_finger_top_clearance_m'] >= .020
    assert calls[-1] == 'handoff_clearance_verified'


def test_handoff_failure_clears_monitor_before_push(monkeypatch):
    from r1pro_teleop.airport_fsm import handoff_clearance as module
    from r1pro_teleop.airport_fsm import primitives

    r = SimpleNamespace(holding=None, retained_contact=(0, 'left'),
        primitive_deadline_step=None, _handoff_clearance_monitor=None,
        cfg=candidate_config(), sim=SimpleNamespace(target=np.zeros(16)),
        observation=lambda: {'table_contact': np.array([1]),
                             'gripper_contact_force': np.array([[10., 0.]])},
        check_retained_contact=lambda: None)
    machine = SimpleNamespace(r=r, c=r.cfg, transition=lambda *a: None,
        log=SimpleNamespace(event=lambda *a, **k: None))
    @contextmanager
    def fake_action(*a, **k):
        yield
    monkeypatch.setattr(primitives, 'action', fake_action)
    monkeypatch.setattr(primitives, 'remaining', lambda _: 5.)
    monkeypatch.setattr(primitives, 'plan', lambda *a, **k: (_ for _ in ()).throw(Fault('planned_failure')))
    with pytest.raises(Fault, match='planned_failure'):
        perform_handoff_clearance(machine, SimpleNamespace(tray=0), 'left')
    assert r._handoff_clearance_monitor is None
