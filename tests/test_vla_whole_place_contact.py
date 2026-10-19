"""Whole-action phase mapping against actual airport model geometry identities."""
from dataclasses import replace

import pytest

from test_substep_runtime_replay import airport
from r1pro_teleop.airport_fsm.contracts import State


def geometries(runtime):
    by_body = {}
    for geom, body in enumerate(runtime.m.geom_bodyid):
        by_body.setdefault(int(body), []).append(geom)
    tray_body = next(body for body in runtime.tray_bodies if body in by_body)
    table_body = next(body for body in runtime.table_bodies if body in by_body)
    finger_body = next(body for body in runtime.robot_bodies
                       if body in by_body and 'gripper_finger' in runtime.m.body(body).name)
    other_tray = next(body for body in runtime.tray_bodies
                      if body in by_body and runtime.tray_bodies[body] != runtime.tray_bodies[tray_body])
    return tuple(by_body[body][0] for body in (tray_body, table_body, finger_body, other_tray)), runtime.tray_bodies[tray_body]


@pytest.mark.parametrize('phase', ['descend', 'support_contact', 'unload'])
def test_existing_placement_payload_table_permission_is_unchanged(airport, phase):
    create, _, _ = airport
    runtime = create(); (tray, table, _, _), target = geometries(runtime)
    runtime.holding = target; runtime.fsm_state = State.PLACE_TRAY; runtime.phase = phase
    assert runtime._pair_allowed(tray, table)
    assert runtime._pair_allowed(table, tray)


@pytest.mark.parametrize('backend,mode,state,phase,allowed', [
    ('pi05', 'task_complete_action8_v1', State.PLACE_TRAY, 'vla_place_release_tray', True),
    ('pi05', 'legacy', State.PLACE_TRAY, 'vla_place_release_tray', False),
    ('pi05', 'skill_only_v1', State.PLACE_TRAY, 'vla_place_release_tray', False),
    ('teacher', 'task_complete_action8_v1', State.PLACE_TRAY, 'vla_place_release_tray', False),
    ('pi05', 'task_complete_action8_v1', State.PLACE_TRAY, 'vla_carry_tray', False),
    ('pi05', 'task_complete_action8_v1', State.TRANSPORT_TRAY, 'vla_place_release_tray', False),
])
def test_new_mapping_requires_exact_typed_model_node(airport, backend, mode, state, phase, allowed):
    create, _, _ = airport
    runtime = create(); (tray, table, finger, wrong_tray), target = geometries(runtime)
    runtime.cfg = replace(runtime.cfg, motion_backend=backend, vla_prompt_mode=mode)
    runtime.holding = target; runtime.allowed_tray = target
    runtime.fsm_state = state; runtime.phase = phase
    assert runtime._pair_allowed(tray, table) is allowed
    assert runtime._pair_allowed(table, tray) is allowed
    # No new finger/table, held/wrong-tray or wrong-target grasp exemption.
    assert not runtime._pair_allowed(finger, table)
    assert not runtime._pair_allowed(tray, wrong_tray)
    assert not runtime._pair_allowed(finger, wrong_tray)
    assert runtime._pair_allowed(finger, tray)

