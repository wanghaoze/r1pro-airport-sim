"""Private loaded placement geometry predictions; never physical acceptance.

No route, force, support, servo compliance or dynamic success is certified.
The caller MUST navigate normally and replan from the resulting measured state.
"""
from __future__ import annotations
import copy
import math
from dataclasses import dataclass
from itertools import islice
import numpy as np
from .contracts import Fault, State, wrap_angle
from .geometry import quat_yaw_tilt, rz
from .placement_planner import touchdown_position, release_endpoint, descent_budget_frames
from .primitives import continue_loaded_reference, object_points, plan, checked_command_tcp


class _SilentTrace:
    def event(self, *args, **kwargs):
        pass


def _blocked(*args, **kwargs):
    raise RuntimeError('placement prediction cannot execute physical motion')


def loaded_planning_copy(runtime):
    """Own every mutable MuJoCo workspace and all state readers."""
    if runtime.holding is None or not runtime.grasp_rel or runtime.retained_contact is not None:
        raise Fault('placement_probe_requires_bilateral_loaded_state')
    probe = copy.copy(runtime)
    probe.sim = copy.copy(runtime.sim)
    probe.d = runtime.mj.MjData(runtime.m)
    state = np.empty(runtime.integration_size)
    runtime.mj.mj_getState(runtime.m, runtime.d, state, runtime.integration_spec)
    runtime.mj.mj_setState(runtime.m, probe.d, state, runtime.integration_spec)
    probe.sim.data = probe.d
    probe.sim.target = runtime.sim.target.copy()
    probe.sim.base_target = runtime.sim.base_target.copy()
    probe.sim.ik_data = runtime.mj.MjData(runtime.m)
    probe.shadow = runtime.mj.MjData(runtime.m)
    probe.inverse = runtime.mj.MjData(runtime.m)
    probe.evidence = copy.copy(runtime.evidence)
    probe.evidence.sim = probe.sim
    probe.grasp_rel = {side: value.copy() for side, value in runtime.grasp_rel.items()}
    probe.trace = _SilentTrace()
    probe.tick = probe.sim.step = probe.sim.apply_target = _blocked
    # Avoid any accidental shared renderer teardown on a planning clone.
    probe.close = probe.sim.close = _blocked
    runtime.mj.mj_forward(runtime.m, probe.d)
    return probe


def placement_candidates(nominal_base):
    """Nine deterministic proposals, with the original nominal goal first."""
    base = np.asarray(nominal_base, float)
    if base.shape != (3,) or not np.isfinite(base).all():
        raise ValueError('finite base XY/yaw required')
    forward = np.array([np.cos(base[2]), np.sin(base[2])])
    lateral = np.array([-forward[1], forward[0]])
    for along, sideways in ((0, 0), (0, .05), (0, -.05), (.04, 0), (-.04, 0),
                            (.04, .05), (.04, -.05), (-.04, .05), (-.04, -.05)):
        candidate = base.copy()
        candidate[:2] += along*forward + sideways*lateral
        yield candidate


def carried_placement_candidates(runtime, nominal_base, anchor_xy, *, goal_tray_yaw,
                                 standoff_m=.57):
    """Original eighteen first, then optional bounded measured-grasp bases.

    This is a rigid transport prediction, not future contact/servo evidence.
    ``anchor_xy`` is the caller's placement anchor (including any retained-push
    midpoint choice); desired tray yaw is explicit, never inferred from base.
    The actual grasp orientation has a 2*pi period even for symmetric trays.
    Each proposal still needs route, arrival and complete placement validation.
    """
    nominal = np.asarray(nominal_base, float)
    anchor = np.asarray(anchor_xy, float)
    if (nominal.shape != (3,) or anchor.shape != (2,)
            or not np.isfinite(np.r_[nominal, anchor, goal_tray_yaw, standoff_m]).all()
            or standoff_m <= 0):
        raise ValueError('finite nominal base, anchor XY, goal yaw and positive standoff required')
    if runtime.holding is None or not runtime.grasp_rel or runtime.retained_contact is not None:
        raise Fault('placement_probe_requires_bilateral_loaded_state')
    measured_base = np.asarray(runtime.sim.base_state(), float)
    measured_pose = runtime.observation()['tray_pose'][runtime.holding]
    measured_yaw, _ = quat_yaw_tilt(measured_pose[3:])
    heading = float(wrap_angle(measured_base[2] + wrap_angle(goal_tray_yaw-measured_yaw)))
    carried_base = np.r_[anchor-standoff_m*np.array([np.cos(heading), np.sin(heading)]), heading]
    seen = set()
    for center in (nominal, carried_base):
        for candidate in placement_candidates(center):
            # Compare physical yaw modulo 2*pi, retaining the nominal values.
            key = tuple(np.round(np.r_[candidate[:2], wrap_angle(candidate[2])], 8))
            if key not in seen:
                seen.add(key)
                yield candidate
    cfg=getattr(runtime,'cfg',None)
    if not (getattr(cfg,'acceptance_profile',None)=='completion_first' and
            getattr(cfg,'completion_place_extended_base_search_enabled',False)):
        return
    # The old sequence above remains byte-for-byte identical. Explore only
    # additional standing poses relative to the measured carried orientation;
    # each still goes through the existing private screen and live replanning.
    additional=0
    for yaw_offset in (0., .12, -.12):
        proposed_heading=float(wrap_angle(heading+yaw_offset))
        forward=np.array([np.cos(proposed_heading),np.sin(proposed_heading)])
        lateral=np.array([-forward[1],forward[0]])
        for distance in (.47,.67):
            for sideways in (0.,.08,-.08):
                candidate=np.r_[anchor-distance*forward+sideways*lateral,proposed_heading]
                key=tuple(np.round(np.r_[candidate[:2],wrap_angle(candidate[2])],8))
                if key in seen:
                    continue
                seen.add(key)
                yield candidate
                additional+=1
                if additional==18:
                    return


def _project(probe, target=None, base=None):
    """Kinematic projection in private data only, with the held tray carried."""
    shadow = probe._shadow(target, base)
    probe.d.qpos[:] = shadow.qpos
    probe.d.qvel[:] = 0
    if target is not None:
        probe.sim.target = np.asarray(target, float).copy()
    if base is not None:
        probe.sim.base_target = np.asarray(base, float).copy()
    probe.mj.mj_forward(probe.m, probe.d)


_PURE_ALIGNMENT_REJECTIONS = frozenset({
    'ik_unreachable', 'coupled_ik_unreachable', 'ik_branch_jump',
    'cartesian_collision_or_wrist', 'primitive_path_infeasible',
})


def _qualify_combined_descent(probe, staged, destination, yaw, base, alignment_failure):
    """Plan the real place's direct descent/release on a zero-tick copy.

    An arrival projection cannot certify future contact, route, or actual
    alignment. This only makes a conservative screen aware of the existing
    full guarded combined-descent planning branch.
    """
    from types import SimpleNamespace
    from .primitives import _original_place_orientation, _plan_place_descent

    c = probe.cfg
    tray = probe.holding
    before_steps, before_time = probe.steps, float(probe.d.time)
    probe.fsm_state, probe.phase = State.PLACE_TRAY, 'descend'
    probe.primitive_deadline_step = before_steps + math.floor(c.primitive_seconds*c.fps)
    continue_loaded_reference(probe)
    observation = probe.observation()
    table = probe.g.support_table(staged)
    if table is None:
        raise Fault('primitive_place_no_table')
    top = probe.g.tables[table]['dimensions_m'][2]
    keep = None
    if np.linalg.norm(staged[:2]-destination[:2]) > .01 and c.keep_place_contact:
        direction = destination[:2]-staged[:2]
        keep = min(('left', 'right'), key=lambda side:
                   np.dot(probe.sim.tcp(side)[0][:2]-staged[:2], direction))
    release = [side for side in ('left', 'right') if side != keep]
    operation = SimpleNamespace(tray=tray, destination=destination, yaw=yaw)
    machine = SimpleNamespace(r=probe, c=c, g=probe.g, log=probe.trace)
    with _original_place_orientation(probe):
        descent, release_plan = _plan_place_descent(machine, operation, staged,
            observation, top, True, keep, release, False)
    if probe.steps != before_steps or float(probe.d.time) != before_time:
        raise Fault('placement_probe_modified_physical_state')
    return {'base': base.copy(), 'alignment_frames': 0,
            'descent_frames': descent[1], 'release_frames': release_plan[1],
            'support_reserve_frames': math.ceil(.1*c.fps),
            'retained_side': keep, 'prediction_mode': 'combined_descent',
            'separate_alignment_rejection': alignment_failure.code,
            'qualification': 'private_complete_combined_descent_reference_requires_live_replanning',
            'certifies_contact_or_route': False}


def qualify_placement(probe, staged, destination, yaw, base):
    """Privately plan separate alignment first, then the enabled combined path.

    Neither mode predicts contact deformation after real navigation or ticks.
    A qualified reference must still be replanned and executed physically.
    """
    c = probe.cfg
    staged = np.asarray(staged, float)
    destination = np.asarray(destination, float)
    base = np.asarray(base, float)
    if (staged.shape != (3,) or destination.shape != (3,) or base.shape != (3,)
            or not np.isfinite(np.r_[staged, destination, base, yaw]).all()):
        raise ValueError('finite placement XYZ, destination XYZ, yaw and base required')
    if not c.fixed_primitives:
        raise Fault('placement_probe_requires_fixed_primitives')
    tray = probe.holding
    # Use the actual initial measured object/hand transform for rigid transport.
    probe.remember_grasp(tray)
    probe.fsm_state, probe.phase = State.TRANSPORT_TRAY, 'transport'
    _project(probe, base=base)
    collision = probe.collision(probe.d, planning=True)
    if collision or not probe.camera_guard(probe.d):
        raise Fault('placement_probe_arrival_collision_or_camera', {'collision': collision})
    probe.remember_grasp(tray)
    combined_enabled = (c.acceptance_profile == 'completion_first' and
        getattr(c, 'completion_place_private_combined_screen_enabled', False) and
        getattr(probe, 'primitive_lift_xy_shift_m', 0.) > .005)
    fallback_probe = loaded_planning_copy(probe) if combined_enabled else None
    try:
        continue_loaded_reference(probe)
        current = probe.observation()['tray_pose'][tray]
        aligned = current[:3].copy()
        aligned[:2] = staged[:2]
        current_yaw, _ = quat_yaw_tilt(current[3:])
        goal_yaw = current_yaw + float(wrap_angle(yaw-current_yaw, probe.g.period))
        if combined_enabled:
            from .primitives import _original_place_orientation
            with _original_place_orientation(probe):
                points = object_points(probe, aligned, goal_yaw)
                alignment = plan(probe, points,
                    available=c.primitive_seconds-c.primitive_settle_s,
                    allow_shortcut=True)
        else:
            points = object_points(probe, aligned, goal_yaw)
            alignment = plan(probe, points,
                available=c.primitive_seconds-c.primitive_settle_s,
                allow_shortcut=True)
    except Fault as exc:
        if not combined_enabled or exc.code not in _PURE_ALIGNMENT_REJECTIONS:
            raise
        try:
            return _qualify_combined_descent(fallback_probe, staged, destination,
                                             yaw, base, exc)
        except Fault as fallback_failure:
            raise exc from fallback_failure
    saved_alignment_relation = {side:value.copy() for side,value in probe.grasp_rel.items()}
    _project(probe, alignment[0].evaluate(1., alignment[1]/c.fps)[0])
    need_push = np.linalg.norm(staged[:2]-destination[:2]) > .01
    keep = None
    if need_push and c.keep_place_contact:
        direction = destination[:2]-staged[:2]
        keep = min(('left', 'right'), key=lambda side:
                   np.dot(probe.sim.tcp(side)[0][:2]-staged[:2], direction))
    release = [side for side in ('left', 'right') if side != keep]
    table = probe.g.support_table(staged)
    if table is None:
        raise Fault('primitive_place_no_table')
    top = probe.g.tables[table]['dimensions_m'][2]
    probe.fsm_state, probe.phase = State.PLACE_TRAY, 'descend'
    continue_loaded_reference(probe)
    def prepare_descent():
        current = probe.observation()['tray_pose'][tray]
        actual_yaw, _ = quat_yaw_tilt(current[3:])
        goal_yaw = actual_yaw + float(wrap_angle(yaw-actual_yaw, probe.g.period))
        vertices = probe.evidence.local_vertices[probe.m.body(probe.g.ids[tray]).id]
        target = touchdown_position(staged, vertices, rz(goal_yaw), table_height=top,
                                    preload=c.primitive_touchdown_preload_m)
        points = object_points(probe, target, goal_yaw)
        release_start = np.asarray(points[-1], float)
        release_end = release_endpoint(release_start, probe.sim.state(), release,
                                      open_limit=c.gripper_open_m,
                                      clearance=c.primitive_release_clearance_m)
        release_plan = plan(probe, [release_start, release_end], available=c.primitive_seconds-.3)
        descent_frames = descent_budget_frames(remaining_frames=math.floor(c.primitive_seconds*c.fps),
            release_frames=release_plan[1], support_frames=math.ceil(.1*c.fps))
        descent = plan(probe, points, available=descent_frames/c.fps, allow_shortcut=True)
        return {'base': base.copy(), 'alignment_frames': alignment[1], 'descent_frames': descent[1],
                'release_frames': release_plan[1], 'support_reserve_frames': math.ceil(.1*c.fps),
                'retained_side': keep, 'target_position': target,
                'qualification': 'kinematic_prediction_requires_live_navigation_and_replanning',
                'certifies_contact_or_route': False}
    from .reference_candidates import plan_reference_candidate
    # This alternate relation comes from a private ideal alignment. It remains
    # a geometric prediction, never a completed physical alignment or an XY
    # residual measurement. In particular, no XY feedforward is invented here.
    return plan_reference_candidate(probe, prepare_descent, saved_alignment_relation,
        enabled=c.placement_preserve_command_grasp_enabled,
        check_command=checked_command_tcp, actual_alignment=False)



@dataclass
class PlacementScreen:
    qualified: list
    rejected: list
    examined: int


def screen_placement(runtime, staged_xyz, final_xyz, yaw, nominal_base, *,
                     candidates=None, max_candidates=9, max_qualified=1):
    cfg=getattr(runtime,'cfg',None)
    maximum=(36 if getattr(cfg,'acceptance_profile',None)=='completion_first' and
             getattr(cfg,'completion_place_extended_base_search_enabled',False) else 18)
    if (isinstance(max_candidates, bool) or not isinstance(max_candidates, int)
            or not 1 <= max_candidates <= maximum or isinstance(max_qualified, bool)
            or not isinstance(max_qualified, int) or not 1 <= max_qualified <= max_candidates):
        raise ValueError(f'one to {maximum} candidates and a bounded qualified count required')
    proposals = placement_candidates(nominal_base) if candidates is None else iter(candidates)
    qualified, fallback_qualified, rejected = [], [], []
    examined = 0
    for base in islice(proposals, max_candidates):
        probe = loaded_planning_copy(runtime)
        examined += 1
        try:
            result = qualify_placement(probe, staged_xyz, final_xyz, yaw, base)
        except Fault as exc:
            rejected.append({'base': np.asarray(base, float).copy(), 'reason': exc.code,
                             'detail': exc.detail})
        else:
            if result.get('prediction_mode') == 'combined_descent':
                fallback_qualified.append(result)
            else:
                qualified.append(result)
                if len(qualified) >= max_qualified:
                    break
    qualified.extend(fallback_qualified[:max_qualified-len(qualified)])
    return PlacementScreen(qualified, rejected, examined)
