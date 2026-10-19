"""Command-continuous paths must not restart at a deflected measured TCP."""
import json
import math
from pathlib import Path
import numpy as np
import pytest


@pytest.mark.parametrize('enabled,scope,expected', [(False,'all',False),(True,'all',True),(True,'push',False)])
def test_loaded_path_scope_preserves_measured_reference_for_push_only(enabled,scope,expected):
    from types import SimpleNamespace
    from r1pro_teleop.airport_fsm.contracts import Config
    from r1pro_teleop.airport_fsm.primitives import object_points
    calls=[]
    r=SimpleNamespace(cfg=Config(loaded_command_reference_enabled=enabled,
                                loaded_command_reference_scope=scope),
        holding=0,g=SimpleNamespace(ids=['tray']),
        d=SimpleNamespace(body=lambda name:SimpleNamespace(xmat=np.eye(3).ravel())),
        grasp_rel={'left':np.eye(4),'right':np.eye(4)},
        cartesian=lambda goals,**kwargs:calls.append(kwargs))
    object_points(r,np.array([0.,0.,1.]),0.)
    assert calls[0]['start_from_command'] is expected


@pytest.fixture
def runtime(tmp_path):
    import mujoco
    from r1pro_teleop.airport_fsm.runtime import Runtime
    from r1pro_teleop.airport_fsm.contracts import Config
    from r1pro_teleop.airport_mobile import make_mobile_scene
    scene = next(Path('resources/scenes').rglob('scene.json'))
    spec = json.loads(scene.read_text())
    source = scene.parent/spec.get('scene_file', 'scene.xml')
    model = mujoco.MjModel.from_xml_path(str(source))
    if mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, 'agent_base_x') < 0:
        xml = tmp_path/'mobile.xml'
        make_mobile_scene(source, xml)
    else:
        xml = source
    r = Runtime(spec, xml, Config())
    yield r
    r.sim.close()


@pytest.mark.parametrize('from_command', [False, True])
def test_cartesian_uses_requested_reference_and_copies_shadow_views(runtime, monkeypatch, from_command):
    r = runtime
    measured_p, measured_R = r.sim.tcp('left')
    measured_p, measured_R = measured_p.copy(), measured_R.copy()
    r.sim.target[1] += .12
    shadow = r._shadow(r.sim.target).site('left_tcp')
    command_p, command_R = shadow.xpos.copy(), shadow.xmat.reshape(3,3).copy()
    assert np.linalg.norm(command_p-measured_p) > .005
    source_p = command_p if from_command else measured_p
    source_R = command_R if from_command else measured_R
    target_p = source_p+np.array([.06, .01, .04])
    before = np.empty(r.integration_size)
    r.mj.mj_getState(r.m, r.d, before, r.integration_spec)
    received = []
    other_reference = r.sim.target.copy(); other_reference[1] -= .2
    def solve(goals, seed, **kwargs):
        received.append((goals['left'][0].copy(), goals['left'][1].copy()))
        # Actual IK also reuses shadow. A view captured as its starting TCP
        # would drift after the first solve, corrupting later waypoints.
        r._shadow(other_reference)
        return seed.copy()
    monkeypatch.setattr(r, 'solve_pair', solve)
    monkeypatch.setattr(r, '_target_valid', lambda *a, **kw: True)
    monkeypatch.setattr(r, 'tick', lambda *a, **kw: pytest.fail('Preview executed live motion'))
    r.cartesian({'left':(target_p,source_R)}, preview_only=True, start_from_command=from_command)
    count = math.ceil(np.linalg.norm(target_p-source_p)/.025)
    assert len(received) == count
    for index, (position, orientation) in enumerate(received, 1):
        np.testing.assert_allclose(position, source_p+(target_p-source_p)*index/count, atol=1e-12)
        np.testing.assert_allclose(orientation, source_R, atol=1e-12)
    after = np.empty(r.integration_size)
    r.mj.mj_getState(r.m, r.d, after, r.integration_spec)
    np.testing.assert_array_equal(before, after)


@pytest.mark.parametrize('midpoint_offset', [-.00286, .00286])
def test_supported_normal_guard_rejects_midpath_excursion_with_equal_endpoints(midpoint_offset):
    from types import SimpleNamespace
    from r1pro_teleop.airport_fsm.primitives import supported_normal_path_rejection
    path = SimpleNamespace(evaluate=lambda u: (np.array([.907+4*u*(1-u)*midpoint_offset]),))
    runtime = SimpleNamespace(_shadow=lambda q: SimpleNamespace(
        site=lambda name: SimpleNamespace(xpos=np.array([0.,0.,q[0]]))))
    rejection = supported_normal_path_rejection(runtime, path, 'right', .907, .907)
    assert rejection['reason'] == 'supported_normal_reference_excursion'
    assert 0. < rejection['path_fraction'] < 1.
    assert rejection['tolerance_m'] == .00025


def test_supported_normal_guard_preserves_explicit_endpoint_preload():
    from types import SimpleNamespace
    from r1pro_teleop.airport_fsm.primitives import supported_normal_path_rejection
    runtime = SimpleNamespace(_shadow=lambda q: SimpleNamespace(
        site=lambda name: SimpleNamespace(xpos=np.array([0.,0.,q[0]]))))
    path = SimpleNamespace(evaluate=lambda u: (np.array([.907-.0045*u]),))
    assert supported_normal_path_rejection(runtime, path, 'right', .907, .9025) is None
    nearly_level = SimpleNamespace(evaluate=lambda u: (np.array([.907+4*u*(1-u)*.000014]),))
    assert supported_normal_path_rejection(runtime, nearly_level, 'right', .907, .907) is None


def test_plan_requires_additional_check_before_accepting_any_candidate(runtime, monkeypatch):
    from r1pro_teleop.airport_fsm.contracts import Fault, ARM_COLUMNS
    from r1pro_teleop.airport_fsm.primitives import plan
    r = runtime
    # Frozen server scenes may start against a joint stop. This test isolates
    # the additional path callback, so both inputs must already be interior.
    low, high = r.m.jnt_range[r.jids].T
    margin = 2*r.cfg.joint_margin_rad+.02
    start = r.tucked.copy()
    start[ARM_COLUMNS] = np.clip(start[ARM_COLUMNS], low+margin, high-margin)
    end = start.copy(); end[0] += .01
    monkeypatch.setattr(r, '_path_rejection', lambda *a, **kw: None)
    monkeypatch.setattr(r, 'audit_online_reference', lambda *a: None)
    checked = []
    def reject(path):
        checked.append(path)
        return {'reason':'supported_normal_reference_excursion'}
    with pytest.raises(Fault, match='primitive_path_infeasible') as error:
        plan(r, [start,end], available=3., extra_path_check=reject)
    assert len(checked) == 2
    assert all(row['reason']=='supported_normal_reference_excursion' for row in error.value.detail['candidates'])
    checked.clear()
    def reject_first(path):
        checked.append(path)
        return {'reason':'supported_normal_reference_excursion'} if len(checked)==1 else None
    accepted, frames = plan(r, [start,end], available=3., extra_path_check=reject_first)
    assert len(checked)==2 and accepted is checked[-1]
    assert frames/r.cfg.fps <= 3.
