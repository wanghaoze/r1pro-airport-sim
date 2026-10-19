"""Pure contracts. No simulator, rendering, or LeRobot import at module load."""
from __future__ import annotations
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any
import hashlib
import json
import math
import os
import tempfile
import numpy as np

CAMERAS = ("head", "left_wrist", "right_wrist")
NATIVE_CAMERA_SHAPES = {
    "head": (1536, 1920, 3),
    "left_wrist": (720, 1280, 3),
    "right_wrist": (720, 1280, 3),
}
FOUR_CAMERA_SHAPES = {
    "head_left": (1536, 1920, 3), "head_right": (1536, 1920, 3),
    "left_wrist": (720, 1280, 3), "right_wrist": (720, 1280, 3),
}
ARM_NAMES = [f"{s}_arm_joint{i}" for s in ("left", "right") for i in range(1, 8)]
NAMES = [f"left_arm_joint{i}" for i in range(1, 8)] + ["left_gripper_opening_m"] + [f"right_arm_joint{i}" for i in range(1, 8)] + ["right_gripper_opening_m"]
ARM_COLUMNS = np.array([*range(7), *range(8, 15)])
BASE_NAMES = ["initial_origin_world_dx_m", "initial_origin_world_dy_m", "initial_heading_dyaw_rad"]


def camera_shapes(spec: dict) -> dict[str, tuple[int, int, int]]:
    """Return HWC shapes without silently cropping a stream.

    New airport scenes carry an explicit per-camera contract.  Legacy unit
    fixtures retain their common width/height so old datasets remain readable.
    """
    camera = spec.get("camera", {})
    streams = camera.get("streams")
    if streams is None:
        width, height = int(camera.get("width", 1280)), int(camera.get("height", 720))
        return {name: (height, width, 3) for name in CAMERAS}
    result = {}
    names = tuple(FOUR_CAMERA_SHAPES) if set(streams) == set(FOUR_CAMERA_SHAPES) else CAMERAS
    if set(streams) != set(names):
        raise ValueError("Unsupported camera stream set")
    for name in names:
        item = streams.get(name, {})
        shape = (int(item.get("height", 0)), int(item.get("width", 0)), 3)
        if shape[0] <= 0 or shape[1] <= 0:
            raise ValueError(f"Invalid native camera shape: {name}")
        result[name] = shape
    return result

class State(str, Enum):
    SEARCH_TARGET = "SEARCH_TARGET"
    ALIGN_BASE = "ALIGN_BASE"
    APPROACH_TRAY = "APPROACH_TRAY"
    ADJUST_TRAY = "ADJUST_TRAY"
    GRASP_TRAY = "GRASP_TRAY"
    TRANSPORT_TRAY = "TRANSPORT_TRAY"
    PLACE_TRAY = "PLACE_TRAY"
    VERIFY_PLACEMENT = "VERIFY_PLACEMENT"
    RECOVER = "RECOVER"
    TASK_COMPLETE = "TASK_COMPLETE"

class Fault(RuntimeError):
    def __init__(self, code: str, detail: Any = None, *, recoverable: bool = False):
        self.code, self.detail, self.recoverable = code, detail, recoverable
        super().__init__(f"{code}: {detail}" if detail is not None else code)

@dataclass(frozen=True)
class Criteria:
    position_m: float = .03
    yaw_deg: float = 5.
    tilt_deg: float = 5.
    gap_min_m: float = 0.
    gap_max_m: float = .03
    stable_s: float = 1.
    max_speed_m_s: float = .01
    penetration_m: float = .003
    contact_n: float = .5
    lifted_m: float = .02

@dataclass(frozen=True)
class Config:
    motion_backend: str = 'teacher'
    vla_host: str = '127.0.0.1'
    vla_port: int = 8765
    vla_checkpoint_id: str | None = None
    vla_prompt_mode: str = 'legacy'
    vla_action_horizon: int = 20
    vla_execute_steps: int = 5
    vla_max_skill_steps: int = 6000
    vla_model_render_max_dim: int = 0
    vla_initialize_arm_tolerance_rad: float = .06
    vla_initialize_gripper_tolerance_m: float = .005
    vla_initializer_base_hold_enabled: bool = False
    vla_grasp_base_hold_enabled: bool = False
    vla_navigation_readiness_mode: str = 'legacy'
    vla_navigation_target_bearing_max_rad: float = .55
    vla_navigation_target_lateral_max_m: float = .28
    vla_navigation_target_forward_min_m: float = .4
    vla_navigation_stable_frames: int = 4
    vla_servo_projection_enabled: bool = False
    vla_servo_projection_mode: str = 'bounded'
    vla_reference_rate_limit_enabled: bool = False
    vla_reference_rate_fraction: float = .5
    acceptance_profile: str = 'strict'
    approximate_completion_enabled: bool = False
    allow_supported_overhang: bool = False
    completion_supported_push_fallback_attempt_enabled: bool = False
    completion_supported_push_fallback_distance_m: float = .6
    completion_supported_push_fallback_yaw_deg: float = 90.
    completion_release_gap_m: float = .02
    completion_collision_penetration_m: float = .02
    completion_speed_ratio_max: float = 1.05
    completion_speed_excursion_s: float = .20
    completion_support_grace_s: float = .30
    completion_position_m: float = .05
    completion_yaw_deg: float = 10.
    completion_gap_max_m: float = .05
    completion_held_ik_position_tolerance_m: float = .022
    completion_held_ik_orientation_tolerance_rad: float = .05
    completion_place_private_position_tolerance_m: float = .08
    completion_lift_min_m: float = .15
    completion_release_replan_enabled: bool = False
    completion_adaptive_reservation_enabled: bool = False
    completion_push_free_open_enabled: bool = False
    completion_lift_strict_orientation_first_enabled: bool = False
    completion_place_ik_fallback_enabled: bool = False
    completion_place_coupled_position_refit_enabled: bool = False
    completion_place_coupled_interval_subdivision_enabled: bool = False
    completion_place_extended_base_search_enabled: bool = False
    completion_place_private_joint_endpoint_enabled: bool = False
    completion_place_coupled_multistart_enabled: bool = False
    completion_supported_staging_enabled: bool = False
    completion_place_private_combined_screen_enabled: bool = False
    completion_place_zero_shift_combined_fallback_enabled: bool = False
    completion_push_free_first_enabled: bool = False
    completion_handoff_clearance_enabled: bool = False
    completion_preserve_nominal_timing_enabled: bool = False
    completion_direct_buffer_enabled: bool = False
    fps: int = 20
    expected_scenes: int = 400
    split_counts: tuple[int, int, int] = (300, 50, 50)
    split_seed: int = 20260916
    max_attempts_per_scene: int = 6
    successes_per_scene: int = 1
    max_local_retries: int = 3
    max_operations: int = 18
    max_episode_seconds: float = 600.
    max_attempt_wall_seconds: float = 1800.
    max_phase_seconds: float = 45.
    max_candidate_count: int = 12
    reachability_screen_enabled: bool = False
    release_preflight_enabled: bool = False
    push_use_full_budget: bool = False
    transport_align_use_full_budget: bool = False
    placement_preserve_command_grasp_enabled: bool = False
    placement_alignment_xy_feedforward_enabled: bool = False
    placement_alignment_xy_feedforward_scope: str = 'all'
    empty_arm_shortcut_headroom_enabled: bool = True
    retreat_joint_speed_scale: float = 1.
    push_withdraw_preload_scale: float = 1.5
    push_withdraw_path_search_enabled: bool = False
    push_withdraw_merge_fallback_enabled: bool = False
    push_yaw_feedback_enabled: bool = False
    push_yaw_feedback_additive_fallback_enabled: bool = False
    push_yaw_feedback_scope: str = 'all'
    push_yaw_feedback_seconds: float = 1.5
    push_yaw_feedback_gain: float = 2.
    push_yaw_feedback_max_deg: float = 1.5
    retained_support_integer_clock_enabled: bool = False
    push_physical_preview_enabled: bool = False
    push_physical_preview_max_candidates: int = 3
    substep_control_enabled: bool = False
    alternate_rim_enabled: bool = False
    carry_lateral_compensation_enabled: bool = False
    loaded_command_reference_enabled: bool = False
    loaded_command_reference_scope: str = 'all'
    placement_screen_enabled: bool = False
    placement_arrival_rescreen_enabled: bool = False
    temporary_buffer_serviceability_enabled: bool = False
    placement_max_probes: int = 18
    reachability_max_probes: int = 24
    reachability_max_qualified: int = 2
    max_ik_iterations: int = 160
    trajectory_mode: str = 'legacy'
    adaptive_push_distance: bool = False
    base_cruise: bool = False
    online_push: bool = False
    online_push_mode: str = 'position'
    online_push_seconds: float = 12.
    online_push_handoff_m: float = .04
    stop_push_at_contract: bool = False
    consistent_placement: bool = False
    single_contact_separation: bool = False
    keep_pick_contact: bool = False
    keep_place_contact: bool = False
    fixed_primitives: bool = False
    reach_pull_enabled: bool = False
    reach_pull_distance_m: float = .08
    reach_pull_dual_radius_m: float = .65
    reach_pull_single_radius_m: float = .78
    reach_pull_min_progress_m: float = .02
    primitive_seconds: float = 3.
    primitive_lift_m: float = .18
    primitive_lift_compensation_m: float = 0.
    primitive_settle_s: float = .15
    primitive_release_clearance_m: float = .02
    primitive_touchdown_preload_m: float = .002
    primitive_push_compensation_m: float = .035
    push_step_max_m: float = .09
    free_space_joint_shortcut: bool = False
    prefer_direct_grasp: bool = False
    robust_planning: bool = False
    robust_endpoint_paths: bool = False
    ik_reference_regularization: float = .0001
    # These are ENGINEERING simulation caps, NOT manufacturer maximum power.
    limit_mode: str = "model80"
    limit_fraction: float = .8
    arm_velocity_fallback: tuple[float, ...] = (1.5, 1.5, 1.5, 1.5, 2.2, 2.2, 2.2)
    arm_acceleration: float = 3.
    arm_jerk: float = 30.
    gripper_velocity: float = .08
    gripper_acceleration: float = .4
    gripper_jerk: float = 4.
    base_speed: float = .30
    base_yaw_speed: float = .45
    base_acceleration: float = .35
    base_yaw_acceleration: float = .6
    base_jerk: float = 1.5
    base_yaw_jerk: float = 2.5
    transit_tcp_speed: float = .18
    contact_tcp_speed: float = .04
    carry_tcp_speed: float = .10
    joint_margin_rad: float = .015
    ik_position_tolerance_m: float = .040
    ik_orientation_tolerance_rad: float = .12
    # Position must dominate at the tray rim.  Orientation remains bounded by
    # its own tolerance and the wrist-camera-front collision check.
    ik_orientation_weight: float = .40
    max_ik_branch_step_rad: float = .65
    joint_tracking_error_rad: float = .18
    tracking_error_grace_s: float = .3
    camera_front_margin_m: float = .002
    camera_forward_dot: float = .010
    camera_guard_mode: str = "legacy_base_forward"
    camera_self_cone_deg: float = 5.
    # Explicit, provenance-tracked validated rim template from airport_arrange.py.
    rim_inset_m: float = .010
    rim_height_local_m: float = .082
    rim_pitch_deg: float = -30.
    rim_roll_deg: float = 10.
    pregrasp_clearance_m: float = .25
    rim_x_jitter_m: float = .025
    gripper_open_m: float = .1
    gripper_close_m: float = .004
    carry_clearance_m: float = .10
    staging_clearance_m: float = .08
    push_max_distance_m: float = .18
    push_max_yaw_deg: float = 15.
    push_iterations: int = 5
    planner_margin_m: float = .001
    replay_tolerance: float = 1e-5
    include_recovered_in_bc: bool = False
    hardware_profile: str | None = None
    urdf: str | None = None
    criteria: Criteria = field(default_factory=Criteria)

    def validate(self) -> "Config":
        if type(self.vla_servo_projection_enabled) is not bool:
            raise ValueError('vla_servo_projection_enabled must be boolean')
        if self.vla_servo_projection_mode not in ('bounded','actuator_saturation'):
            raise ValueError('vla_servo_projection_mode must be bounded or actuator_saturation')
        if self.vla_servo_projection_mode=='actuator_saturation' and (
                not self.vla_servo_projection_enabled or not self.vla_reference_rate_limit_enabled):
            raise ValueError('actuator_saturation requires projection and reference rate limiting')
        if type(self.vla_reference_rate_limit_enabled) is not bool:
            raise ValueError('vla_reference_rate_limit_enabled must be boolean')
        if isinstance(self.vla_reference_rate_fraction,bool) or not np.isfinite(self.vla_reference_rate_fraction) or not 0 < self.vla_reference_rate_fraction <= 1:
            raise ValueError('vla_reference_rate_fraction must be in (0,1]')
        if type(self.vla_model_render_max_dim) is not int or self.vla_model_render_max_dim < 0:
            raise ValueError('vla_model_render_max_dim must be a nonnegative integer')
        for key in ('vla_initialize_arm_tolerance_rad','vla_initialize_gripper_tolerance_m'):
            value=getattr(self,key)
            if isinstance(value,bool) or not isinstance(value,(int,float)) or not np.isfinite(value) or value<=0:
                raise ValueError(key+' must be finite and positive')
        if type(self.vla_initializer_base_hold_enabled) is not bool:
            raise ValueError('vla_initializer_base_hold_enabled must be boolean')
        if self.vla_initializer_base_hold_enabled and not self.vla_reference_rate_limit_enabled:
            raise ValueError('Initializer base hold requires reference rate limiter')
        if type(self.vla_grasp_base_hold_enabled) is not bool:
            raise ValueError('vla_grasp_base_hold_enabled must be boolean')
        if self.vla_grasp_base_hold_enabled and not self.vla_reference_rate_limit_enabled:
            raise ValueError('Grasp base hold requires reference rate limiter')
        from ..vla.prompts import validate_prompt_mode
        validate_prompt_mode(self.vla_prompt_mode)
        if self.vla_navigation_readiness_mode not in ('legacy','wide_target_cone'):
            raise ValueError('Unknown VLA navigation readiness mode')
        for key,maximum in (('vla_navigation_target_bearing_max_rad',np.pi),
                            ('vla_navigation_target_lateral_max_m',.75),
                            ('vla_navigation_target_forward_min_m',.75)):
            value=getattr(self,key)
            if isinstance(value,bool) or not isinstance(value,(int,float)) or not np.isfinite(value) or not 0<value<=maximum:
                raise ValueError(key+' must be finite and in (0,'+str(maximum)+']')
        if type(self.vla_navigation_stable_frames) is not int or self.vla_navigation_stable_frames<1:
            raise ValueError('vla_navigation_stable_frames must be a positive integer')
        if self.motion_backend not in ('teacher', 'pi05'):
            raise ValueError('Unknown motion_backend')
        if not isinstance(self.vla_host, str) or not self.vla_host.strip():
            raise ValueError('vla_host is required')
        for name in ('vla_port', 'vla_action_horizon', 'vla_execute_steps', 'vla_max_skill_steps'):
            value = getattr(self, name)
            if type(value) is not int or value < 1:
                raise ValueError(name + ' must be a positive integer')
        if self.vla_port > 65535 or self.vla_execute_steps > self.vla_action_horizon:
            raise ValueError('Invalid VLA port or chunk execution length')
        if self.motion_backend == 'pi05' and (self.fps != 20 or not isinstance(self.vla_checkpoint_id, str) or not self.vla_checkpoint_id.strip()):
            raise ValueError('pi05 requires 20Hz and an explicit trained checkpoint identity')
        if self.acceptance_profile not in ('strict', 'completion_first'):
            raise ValueError('acceptance_profile must be strict or completion_first')
        if not isinstance(self.approximate_completion_enabled, bool):
            raise ValueError('approximate_completion_enabled must be boolean')
        if self.approximate_completion_enabled and self.acceptance_profile != 'completion_first':
            raise ValueError('approximate_completion_enabled requires completion_first')
        if not isinstance(self.allow_supported_overhang, bool):
            raise ValueError('allow_supported_overhang must be boolean')
        if self.allow_supported_overhang and not self.approximate_completion_enabled:
            raise ValueError('allow_supported_overhang requires approximate_completion_enabled')
        if not isinstance(self.completion_supported_push_fallback_attempt_enabled, bool):
            raise ValueError('completion_supported_push_fallback_attempt_enabled must be boolean')
        if self.completion_supported_push_fallback_attempt_enabled and not self.approximate_completion_enabled:
            raise ValueError('completion_supported_push_fallback_attempt_enabled requires approximate_completion_enabled')
        for name, low, high in (
                ('completion_supported_push_fallback_distance_m', .18, .8),
                ('completion_supported_push_fallback_yaw_deg', 15., 90.)):
            value = getattr(self, name)
            if (isinstance(value, bool) or not isinstance(value, (int, float)) or
                    not math.isfinite(value) or not low <= value <= high):
                raise ValueError(f'{name} must be finite and in [{low}, {high}]')
        for name, maximum in (('completion_release_gap_m', .02),
                              ('completion_collision_penetration_m', .03)):
            value = getattr(self, name)
            if (isinstance(value, bool) or not isinstance(value, (int, float)) or
                    not math.isfinite(value) or not 0. <= value <= maximum):
                raise ValueError(f'{name} must be finite and in [0, {maximum}]')
        for name, low, high in (('completion_speed_ratio_max', 1.01, 1.10),
                                ('completion_speed_excursion_s', .002, .50),
                                ('completion_support_grace_s', .15, .50),
                                ('completion_position_m', .001, .10 if self.approximate_completion_enabled else .08),
                                ('completion_yaw_deg', .1, 15.),
                                ('completion_gap_max_m', .001, .10 if self.approximate_completion_enabled else .08),
                                ('completion_held_ik_position_tolerance_m', .022, .10 if self.approximate_completion_enabled else .080),
                                ('completion_held_ik_orientation_tolerance_rad', .05, .20 if self.approximate_completion_enabled else .12),
                                ('completion_lift_min_m', .08, .15)):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
                raise ValueError(f'{name} must be finite and in [{low}, {high}]')
        if self.acceptance_profile == 'completion_first' and not self.retained_support_integer_clock_enabled:
            raise ValueError('completion_first requires retained_support_integer_clock_enabled')
        if not isinstance(self.completion_lift_strict_orientation_first_enabled,bool):
            raise ValueError('completion_lift_strict_orientation_first_enabled must be boolean')
        if self.completion_lift_strict_orientation_first_enabled and self.acceptance_profile!='completion_first':
            raise ValueError('completion_lift_strict_orientation_first_enabled requires completion_first')
        if not isinstance(self.completion_place_ik_fallback_enabled,bool):
            raise ValueError('completion_place_ik_fallback_enabled must be boolean')
        if self.completion_place_ik_fallback_enabled and self.acceptance_profile!='completion_first':
            raise ValueError('completion_place_ik_fallback_enabled requires completion_first')
        value=self.completion_place_private_position_tolerance_m
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not .08 <= value <= .10:
            raise ValueError('completion_place_private_position_tolerance_m must be finite and in [0.08, 0.10]')
        if value>.08 and (self.acceptance_profile!='completion_first' or not self.completion_place_ik_fallback_enabled):
            raise ValueError('nondefault completion_place_private_position_tolerance_m requires completion_first place fallback')
        if not isinstance(self.completion_place_coupled_position_refit_enabled,bool):
            raise ValueError('completion_place_coupled_position_refit_enabled must be boolean')
        if self.completion_place_coupled_position_refit_enabled and self.acceptance_profile!='completion_first':
            raise ValueError('completion_place_coupled_position_refit_enabled requires completion_first')
        if not isinstance(self.completion_place_coupled_interval_subdivision_enabled,bool):
            raise ValueError('completion_place_coupled_interval_subdivision_enabled must be boolean')
        if self.completion_place_coupled_interval_subdivision_enabled and self.acceptance_profile!='completion_first':
            raise ValueError('completion_place_coupled_interval_subdivision_enabled requires completion_first')
        if not isinstance(self.completion_place_extended_base_search_enabled,bool):
            raise ValueError('completion_place_extended_base_search_enabled must be boolean')
        if self.completion_place_extended_base_search_enabled and self.acceptance_profile!='completion_first':
            raise ValueError('completion_place_extended_base_search_enabled requires completion_first')
        if not isinstance(self.completion_place_private_joint_endpoint_enabled,bool):
            raise ValueError('completion_place_private_joint_endpoint_enabled must be boolean')
        if self.completion_place_private_joint_endpoint_enabled and (self.acceptance_profile!='completion_first' or not self.completion_place_ik_fallback_enabled):
            raise ValueError('completion_place_private_joint_endpoint_enabled requires completion_first place fallback')
        if not isinstance(self.completion_place_coupled_multistart_enabled,bool):
            raise ValueError('completion_place_coupled_multistart_enabled must be boolean')
        if self.completion_place_coupled_multistart_enabled and self.acceptance_profile!='completion_first':
            raise ValueError('completion_place_coupled_multistart_enabled requires completion_first')
        if not isinstance(self.completion_supported_staging_enabled, bool):
            raise ValueError('completion_supported_staging_enabled must be boolean')
        if self.completion_supported_staging_enabled and (self.acceptance_profile!='completion_first' or
                not self.fixed_primitives or not self.keep_place_contact):
            raise ValueError('completion_supported_staging_enabled requires completion_first fixed place with retained push contact')
        if not isinstance(self.completion_place_private_combined_screen_enabled, bool):
            raise ValueError('completion_place_private_combined_screen_enabled must be boolean')
        if self.completion_place_private_combined_screen_enabled and (self.acceptance_profile!='completion_first' or
                not self.fixed_primitives):
            raise ValueError('completion_place_private_combined_screen_enabled requires completion_first fixed place')
        if not isinstance(self.completion_place_zero_shift_combined_fallback_enabled, bool):
            raise ValueError('completion_place_zero_shift_combined_fallback_enabled must be boolean')
        if self.completion_place_zero_shift_combined_fallback_enabled and (
                self.acceptance_profile != 'completion_first' or not self.fixed_primitives):
            raise ValueError('completion_place_zero_shift_combined_fallback_enabled requires completion_first fixed place')
        if not isinstance(self.completion_push_free_first_enabled,bool):
            raise ValueError('completion_push_free_first_enabled must be boolean')
        if self.completion_push_free_first_enabled and self.acceptance_profile!='completion_first':
            raise ValueError('completion_push_free_first_enabled requires completion_first')
        if not isinstance(self.completion_handoff_clearance_enabled,bool):
            raise ValueError('completion_handoff_clearance_enabled must be boolean')
        if self.completion_handoff_clearance_enabled and (
                self.acceptance_profile!='completion_first' or not self.fixed_primitives or
                not self.keep_place_contact or self.completion_push_free_first_enabled or
                self.completion_push_free_open_enabled):
            raise ValueError('completion_handoff_clearance_enabled requires completion_first fixed retained place and excludes free-first/free-open')
        if not isinstance(self.completion_push_free_open_enabled,bool):
            raise ValueError('completion_push_free_open_enabled must be boolean')
        if self.completion_push_free_open_enabled and self.acceptance_profile!='completion_first':
            raise ValueError('completion_push_free_open_enabled requires completion_first')
        if not isinstance(self.completion_adaptive_reservation_enabled,bool):
            raise ValueError('completion_adaptive_reservation_enabled must be boolean')
        if self.completion_adaptive_reservation_enabled and self.acceptance_profile!='completion_first':
            raise ValueError('completion_adaptive_reservation_enabled requires completion_first')
        if not isinstance(self.completion_release_replan_enabled,bool):
            raise ValueError('completion_release_replan_enabled must be boolean')
        if self.completion_release_replan_enabled and self.acceptance_profile!='completion_first':
            raise ValueError('completion_release_replan_enabled requires completion_first')
        if not isinstance(self.completion_preserve_nominal_timing_enabled,bool):
            raise ValueError('completion_preserve_nominal_timing_enabled must be boolean')
        if self.completion_preserve_nominal_timing_enabled and self.acceptance_profile!='completion_first':
            raise ValueError('completion_preserve_nominal_timing_enabled requires completion_first')
        if not isinstance(self.completion_direct_buffer_enabled, bool):
            raise ValueError('completion_direct_buffer_enabled must be boolean')
        if self.completion_direct_buffer_enabled and not (
                self.acceptance_profile == 'completion_first' and
                self.temporary_buffer_serviceability_enabled):
            raise ValueError('completion_direct_buffer_enabled requires completion_first and temporary_buffer_serviceability_enabled')
        if not isinstance(self.reachability_screen_enabled, bool):
            raise ValueError('reachability_screen_enabled must be boolean')
        if not isinstance(self.release_preflight_enabled, bool):
            raise ValueError('release_preflight_enabled must be boolean')
        if not isinstance(self.push_use_full_budget, bool):
            raise ValueError('push_use_full_budget must be boolean')
        if not isinstance(self.transport_align_use_full_budget, bool):
            raise ValueError('transport_align_use_full_budget must be boolean')
        if not isinstance(self.placement_preserve_command_grasp_enabled, bool):
            raise ValueError('placement_preserve_command_grasp_enabled must be boolean')
        if not isinstance(self.placement_alignment_xy_feedforward_enabled, bool):
            raise ValueError('placement_alignment_xy_feedforward_enabled must be boolean')
        if self.placement_alignment_xy_feedforward_scope not in ('all', 'support_risk'):
            raise ValueError('placement_alignment_xy_feedforward_scope must be all or support_risk')
        if self.placement_alignment_xy_feedforward_enabled and not self.fixed_primitives:
            raise ValueError('placement_alignment_xy_feedforward_enabled requires fixed_primitives')
        if self.placement_preserve_command_grasp_enabled and not self.fixed_primitives:
            raise ValueError('placement_preserve_command_grasp_enabled requires fixed_primitives')
        if self.transport_align_use_full_budget and not self.fixed_primitives:
            raise ValueError('Transport alignment retiming requires fixed primitives')
        if not isinstance(self.empty_arm_shortcut_headroom_enabled, bool):
            raise ValueError('empty_arm_shortcut_headroom_enabled must be boolean')
        value=self.retreat_joint_speed_scale
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not .25<=value<=1.:
            raise ValueError('retreat_joint_speed_scale must be finite and in [0.25, 1]')
        if not isinstance(self.push_yaw_feedback_enabled, bool):
            raise ValueError('push_yaw_feedback_enabled must be boolean')
        if not isinstance(self.retained_support_integer_clock_enabled, bool):
            raise ValueError('retained_support_integer_clock_enabled must be boolean')
        if not isinstance(self.push_physical_preview_enabled, bool):
            raise ValueError('push_physical_preview_enabled must be boolean')
        if (type(self.push_physical_preview_max_candidates) is not int or
                not 1 <= self.push_physical_preview_max_candidates <= 3):
            raise ValueError('push_physical_preview_max_candidates must be an integer in [1,3]')
        if self.push_physical_preview_enabled and not self.fixed_primitives:
            raise ValueError('Physical push preview requires fixed primitives')
        if not isinstance(self.push_yaw_feedback_additive_fallback_enabled, bool):
            raise ValueError('push_yaw_feedback_additive_fallback_enabled must be boolean')
        if self.push_yaw_feedback_scope not in ('all', 'placement'):
            raise ValueError('push_yaw_feedback_scope must be all or placement')
        if not isinstance(self.push_withdraw_path_search_enabled, bool):
            raise ValueError('push_withdraw_path_search_enabled must be boolean')
        if not isinstance(self.push_withdraw_merge_fallback_enabled, bool):
            raise ValueError('push_withdraw_merge_fallback_enabled must be boolean')
        if self.push_withdraw_merge_fallback_enabled and not self.push_withdraw_path_search_enabled:
            raise ValueError('push_withdraw_merge_fallback_enabled requires push_withdraw_path_search_enabled')
        if self.push_withdraw_path_search_enabled and not self.fixed_primitives:
            raise ValueError('Withdraw path search requires fixed primitives')
        if self.push_yaw_feedback_enabled and not self.fixed_primitives:
            raise ValueError('Push yaw feedback requires fixed primitives')
        for name,low,high in (('push_yaw_feedback_seconds',.05,2.5),
                              ('push_yaw_feedback_gain',0.,2.),('push_yaw_feedback_max_deg',0.,1.5)):
            value=getattr(self,name)
            if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not low<=value<=high:
                raise ValueError(f'{name} must be finite and in [{low}, {high}]')
        scale = self.push_withdraw_preload_scale
        if (isinstance(scale, bool) or not isinstance(scale, (int, float)) or
                not math.isfinite(scale) or not 0. <= scale <= 1.5):
            raise ValueError('push_withdraw_preload_scale must be finite and in [0, 1.5]')
        if not isinstance(self.substep_control_enabled, bool):
            raise ValueError('substep_control_enabled must be boolean')
        if not isinstance(self.alternate_rim_enabled, bool):
            raise ValueError('alternate_rim_enabled must be boolean')
        if not isinstance(self.carry_lateral_compensation_enabled, bool):
            raise ValueError('carry_lateral_compensation_enabled must be boolean')
        if not isinstance(self.loaded_command_reference_enabled, bool):
            raise ValueError('loaded_command_reference_enabled must be boolean')
        if self.loaded_command_reference_scope not in ('all','push'):
            raise ValueError('loaded_command_reference_scope must be all or push')
        if not isinstance(self.temporary_buffer_serviceability_enabled, bool):
            raise ValueError('temporary_buffer_serviceability_enabled must be boolean')
        if self.temporary_buffer_serviceability_enabled and not (self.fixed_primitives and self.release_preflight_enabled):
            raise ValueError('temporary buffer serviceability requires fixed primitives and release preflight')
        if not isinstance(self.placement_screen_enabled, bool):
            raise ValueError('placement_screen_enabled must be boolean')
        if not isinstance(self.placement_arrival_rescreen_enabled, bool):
            raise ValueError('placement_arrival_rescreen_enabled must be boolean')
        if self.placement_arrival_rescreen_enabled and not self.fixed_primitives:
            raise ValueError('Placement arrival rescreen requires fixed primitives')
        max_placement_probes=36 if self.completion_place_extended_base_search_enabled else 18
        if (isinstance(self.placement_max_probes, bool) or
                not isinstance(self.placement_max_probes, int) or
                not 1 <= self.placement_max_probes <= max_placement_probes):
            raise ValueError(f'placement_max_probes must be an integer in [1, {max_placement_probes}]')
        if self.placement_screen_enabled and not self.fixed_primitives:
            raise ValueError('Placement screening requires fixed primitives')
        for name in ('reachability_max_probes', 'reachability_max_qualified'):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f'{name} must be a positive integer')
        if not .02 <= self.reach_pull_distance_m <= .12:
            raise ValueError('Reach pull distance must be 2-12 cm')
        if not 0 < self.reach_pull_min_progress_m <= self.reach_pull_distance_m:
            raise ValueError('Reach pull minimum progress must fit requested distance')
        if not self.reach_pull_dual_radius_m < self.reach_pull_single_radius_m:
            raise ValueError('Reach pull radii must distinguish dual and single reach')
        if self.reach_pull_enabled and not (self.fixed_primitives and self.keep_pick_contact):
            raise ValueError('Reach pull requires fixed primitives and retained pick contact')
        primitive_limit = (20. if self.approximate_completion_enabled else
                           6. if self.acceptance_profile == 'completion_first' else 3.)
        if not 0 < self.primitive_seconds <= primitive_limit:
            raise ValueError(f'Primitive duration must not exceed {primitive_limit:g} seconds for {self.acceptance_profile}')
        if not .15 <= self.primitive_lift_m <= .20:
            raise ValueError('Measured lift target must be 15-20 cm')
        if self.primitive_lift_compensation_m > .04:
            raise ValueError('Lift feedforward compensation exceeds 4 cm')
        if self.primitive_touchdown_preload_m > .003:
            raise ValueError('Touchdown reference preload exceeds 3 mm')
        if self.primitive_push_compensation_m > .04:
            raise ValueError('Push feedforward compensation exceeds 4 cm')
        if self.online_push_mode not in ('position','velocity'):
            raise ValueError('Unknown online push mode')
        if self.trajectory_mode not in ('legacy', 'blended', 'hybrid', 'cruise'):
            raise ValueError('Unknown trajectory mode')
        if self.fps != 20:
            raise ValueError("The approved corpus contract is 20 Hz")
        if sum(self.split_counts) != self.expected_scenes or min(self.split_counts) < 0:
            raise ValueError("Split counts must partition every scene")
        for name in ("max_attempts_per_scene", "successes_per_scene", "max_local_retries", "max_operations", "max_candidate_count"):
            if getattr(self, name) < 1:
                raise ValueError(f"{name} must be positive")
        if not 0 < self.limit_fraction <= .8:
            raise ValueError("limit_fraction must be in (0, 0.8]")
        if self.limit_mode not in ("model80", "verified80"):
            raise ValueError("Unknown limit_mode")
        if self.camera_guard_mode not in ("legacy_base_forward", "body_ray_cone"):
            raise ValueError("Unknown camera guard mode")
        if not 0 < self.camera_self_cone_deg <= 30:
            raise ValueError("Invalid camera self-view cone")
        if self.limit_mode == "verified80" and not self.hardware_profile:
            raise ValueError("verified80 needs a measured/manufacturer hardware_profile; no invented Pmax")
        if len(self.arm_velocity_fallback) != 7 or min(self.arm_velocity_fallback) <= 0:
            raise ValueError("Seven positive arm velocity caps are required")
        signed_finite = {"rim_pitch_deg"}
        nonnegative = {"gripper_close_m", "primitive_lift_compensation_m", "primitive_push_compensation_m", "push_withdraw_preload_scale", "push_yaw_feedback_gain", "push_yaw_feedback_max_deg", "completion_release_gap_m", "completion_collision_penetration_m"}
        for key, val in asdict(self).items():
            if not isinstance(val, float):
                continue
            if not math.isfinite(val):
                raise ValueError(f"Invalid finite config value: {key}")
            if key in signed_finite:
                continue
            if key in nonnegative:
                if val < 0:
                    raise ValueError(f"Invalid nonnegative config value: {key}")
            elif val <= 0:
                raise ValueError(f"Invalid positive config value: {key}")
        if not -60. <= self.rim_pitch_deg <= 0. or not 0. <= self.rim_roll_deg <= 30.:
            raise ValueError("Rim wrist angles are outside the direct-grasp envelope")
        if self.include_recovered_in_bc:
            raise ValueError("Unmasked recovered episodes must not be ordinary BC data; use recovery manifests")
        return self

    def dump(self) -> dict:
        return asdict(self)

    @classmethod
    def load(cls, path: str | Path | None = None) -> "Config":
        value = {} if path is None else json.loads(Path(path).read_text(encoding="utf-8"))
        if "criteria" in value:
            value["criteria"] = Criteria(**value["criteria"])
        for key in ("split_counts", "arm_velocity_fallback"):
            if key in value:
                value[key] = tuple(value[key])
        return cls(**value).validate()


def atomic_json(path: str | Path, value: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".partial", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False, default=json_default)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def json_default(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, (Path, Enum)):
        return str(value.value if isinstance(value, Enum) else value)
    raise TypeError(type(value).__name__)


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def fingerprint(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=json_default, allow_nan=False).encode()).hexdigest()


def seed_for(scene_id: str, seed: int, attempt: int) -> int:
    # Python hash() is deliberately not used: it varies between worker processes.
    return int.from_bytes(hashlib.sha256(f"{scene_id}:{seed}:{attempt}".encode()).digest()[:8], "big")


def wrap_angle(angle: Any, period: float = 2 * np.pi) -> Any:
    if not np.isfinite(period) or period <= 0:
        raise ValueError("Invalid angle period")
    return (np.asarray(angle) + period / 2) % period - period / 2


def quintic(u: Any) -> Any:
    u = np.clip(u, 0., 1.)
    return 10 * u**3 - 15 * u**4 + 6 * u**5


def minimum_duration(delta: Any, velocity: Any, acceleration: Any, jerk: Any, floor: float = .1) -> float:
    """Exact conservative extrema of a rest-to-rest quintic scalar time law."""
    d, v, a, j = np.broadcast_arrays(np.abs(delta), velocity, acceleration, jerk)
    if not all(np.isfinite(x).all() for x in (d, v, a, j)) or np.any(v <= 0) or np.any(a <= 0) or np.any(j <= 0):
        raise ValueError("Nonfinite or nonpositive motion limits")
    return float(max(floor, np.max(1.875*d/v), np.max(np.sqrt((10/np.sqrt(3))*d/a)), np.max(np.cbrt(60*d/j))))


class StableGate:
    def __init__(self, seconds: float, fps: int):
        self.required = math.ceil(seconds * fps) + 1
        self.count = 0
    def update(self, condition: bool) -> bool:
        self.count = self.count + 1 if condition else 0
        return self.count >= self.required
