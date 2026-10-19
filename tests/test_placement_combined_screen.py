"""The optional placement predictor cannot bypass live placement checks."""
from dataclasses import replace
import json
from pathlib import Path

import numpy as np
import pytest

from r1pro_teleop.airport_fsm import placement_reachability as p
from r1pro_teleop.airport_fsm.contracts import Config, Fault


@pytest.fixture
def loaded_runtime(tmp_path):
    from r1pro_teleop.airport_fsm.runtime import Runtime
    from r1pro_teleop.airport_mobile import make_mobile_scene
    scenes = sorted(Path('resources/scenes').rglob('scene.json'))
    scene = next((x for x in scenes if x.parent.name.startswith('airport_0004_')), scenes[0])
    spec = json.loads(scene.read_text())
    source = scene.parent / spec.get('scene_file', 'scene.xml')
    import mujoco
    model = mujoco.MjModel.from_xml_path(str(source))
    if mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, 'agent_base_x') < 0:
        xml = tmp_path / 'mobile.xml'
        make_mobile_scene(source, xml)
    else:
        xml = source
    cfg = Config(fixed_primitives=True, acceptance_profile='completion_first',
                 completion_place_private_combined_screen_enabled=True)
    runtime = Runtime(spec, xml, cfg, render=False)
    runtime.allowed_tray = 0
    runtime.remember_grasp(0)
    runtime.primitive_lift_xy_shift_m = .04
    yield runtime
    runtime.close()


def test_combined_screen_only_after_pure_alignment_fault(loaded_runtime, monkeypatch):
    r = loaded_runtime
    stage = r.observation()['tray_pose'][0, :3].copy()
    original_state = np.empty(r.integration_size)
    r.mj.mj_getState(r.m, r.d, original_state, r.integration_spec)
    called = []

    def alignment_failure(*args, **kwargs):
        raise Fault('coupled_ik_unreachable')

    def combined(probe, staged, destination, yaw, base, failure):
        called.append((failure.code, probe.steps, float(probe.d.time)))
        return {'base': base.copy(), 'prediction_mode': 'combined_descent',
                'certifies_contact_or_route': False}

    monkeypatch.setattr(p, 'object_points', alignment_failure)
    monkeypatch.setattr(p, '_qualify_combined_descent', combined)
    probe = p.loaded_planning_copy(r)
    monkeypatch.setattr(probe, 'collision', lambda *a, **kw: None)
    monkeypatch.setattr(probe, 'camera_guard', lambda *a, **kw: True)
    result = p.qualify_placement(probe, stage, stage, 0., r.sim.base_state())
    assert result['prediction_mode'] == 'combined_descent'
    assert called and called[0][0] == 'coupled_ik_unreachable'
    after = np.empty(r.integration_size)
    r.mj.mj_getState(r.m, r.d, after, r.integration_spec)
    np.testing.assert_array_equal(after, original_state)

    probe = p.loaded_planning_copy(r)
    monkeypatch.setattr(probe, 'collision', lambda *a, **kw: {'geoms': ['robot', 'table']})
    with pytest.raises(Fault, match='placement_probe_arrival_collision_or_camera'):
        p.qualify_placement(probe, stage, stage, 0., r.sim.base_state())
    assert len(called) == 1

    r.primitive_lift_xy_shift_m = 0.
    probe = p.loaded_planning_copy(r)
    monkeypatch.setattr(probe, 'collision', lambda *a, **kw: None)
    monkeypatch.setattr(probe, 'camera_guard', lambda *a, **kw: True)
    with pytest.raises(Fault, match='coupled_ik_unreachable'):
        p.qualify_placement(probe, stage, stage, 0., r.sim.base_state())
    assert len(called) == 1


def test_combined_screen_rejects_failed_full_path(loaded_runtime, monkeypatch):
    r = loaded_runtime
    stage = r.observation()['tray_pose'][0, :3].copy()
    probe = p.loaded_planning_copy(r)
    monkeypatch.setattr(probe, 'collision', lambda *a, **kw: None)
    monkeypatch.setattr(probe, 'camera_guard', lambda *a, **kw: True)
    monkeypatch.setattr(p, 'object_points', lambda *a, **kw: (_ for _ in ()).throw(Fault('coupled_ik_unreachable')))
    monkeypatch.setattr(p, '_qualify_combined_descent',
                        lambda *a: (_ for _ in ()).throw(Fault('primitive_path_infeasible')))
    with pytest.raises(Fault, match='coupled_ik_unreachable'):
        p.qualify_placement(probe, stage, stage, 0., r.sim.base_state())


def test_separate_qualification_precedes_combined_candidate(monkeypatch):
    from types import SimpleNamespace
    runtime = SimpleNamespace(cfg=Config(fixed_primitives=True, acceptance_profile='completion_first'))
    monkeypatch.setattr(p, 'loaded_planning_copy', lambda r: object())
    calls = []

    def qualify(probe, staged, destination, yaw, base):
        calls.append(float(base[1]))
        if base[1] == 0.:
            return {'base': base, 'prediction_mode': 'combined_descent'}
        return {'base': base, 'prediction_mode': 'separate_alignment'}

    monkeypatch.setattr(p, 'qualify_placement', qualify)
    bases = [np.array([0., 0., 0.]), np.array([0., 1., 0.])]
    result = p.screen_placement(runtime, [0, 0, 0], [0, 0, 0], 0., bases[0],
                                candidates=bases, max_candidates=2)
    assert calls == [0., 1.]
    assert result.examined == 2
    assert len(result.qualified) == 1
    assert result.qualified[0]['prediction_mode'] == 'separate_alignment'


def test_combined_screen_flag_requires_completion_first():
    with pytest.raises(ValueError, match='requires completion_first'):
        Config(completion_place_private_combined_screen_enabled=True).validate()
