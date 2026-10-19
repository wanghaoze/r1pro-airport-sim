"""MuJoCo adapter: continuous controls, shadow planning, real contact execution.

No ROS/socket interface. qpos assignments occur only in private planning data or
at the INITIAL state of a separate replay. Live objects are never attached,
welded, teleported or moved by artificial external forces.
"""
from __future__ import annotations
from dataclasses import asdict
from fractions import Fraction
from pathlib import Path
import json
import math
import time
import xml.etree.ElementTree as ET
import numpy as np
from scipy.optimize import least_squares
from scipy.spatial.transform import Rotation, Slerp
from .contracts import Config, Fault, ARM_COLUMNS, ARM_NAMES, CAMERAS, minimum_duration, quintic, wrap_angle, atomic_json, State, camera_shapes
from .geometry import Geometry, rz, quat_yaw_tilt, carried_pose_at_base


def _homogeneous(p, R):
    T = np.eye(4)
    T[:3, :3], T[:3, 3] = R, p
    return T


class Runtime:
    def __init__(self, spec, xml, cfg: Config, *, render=False, geometry=None):
        import mujoco
        from ..airport_recording import AirportSimulation, Evidence
        self.mj = mujoco
        self.cfg, self.spec = cfg, spec
        if geometry is not None and (not isinstance(geometry,Geometry) or geometry.spec is not spec):
            raise Fault('injected_geometry_spec_identity_mismatch')
        self.g = Geometry(spec) if geometry is None else geometry
        shapes = camera_shapes(spec)
        if render:
            class NativeCameraSimulation(AirportSimulation):
                def __init__(self, scene):
                    super().__init__(scene, fps=cfg.fps, render=False)
                    self.camera_shapes = shapes
                    self._camera_renderers = {}
                def image(self, name="overview"):
                    if name not in self.camera_shapes:
                        raise ValueError(f"Unknown native camera: {name}")
                    h, w, _ = self.camera_shapes[name]
                    renderer = self._camera_renderers.get(name)
                    if renderer is None:
                        renderer = self._camera_renderers[name] = mujoco.Renderer(self.model, height=h, width=w)
                    renderer.update_scene(self.data, camera=name, scene_option=self.options)
                    renderer.scene.flags[mujoco.mjtRndFlag.mjRND_SHADOW] = False
                    renderer.scene.flags[mujoco.mjtRndFlag.mjRND_REFLECTION] = False
                    return renderer.render().copy()
                def close(self):
                    for renderer in self._camera_renderers.values(): renderer.close()
                    self._camera_renderers = {}
                    super().close()
            self.sim = NativeCameraSimulation(xml)
        else:
            # Rendering is intentionally absent during the fast physics pass.
            self.sim = AirportSimulation(xml, fps=cfg.fps, render=False,
                                         width=spec["camera"].get("width", 1280),
                                         height=spec["camera"].get("height", 720))
            self.sim.camera_shapes = shapes
        self.m, self.d = self.sim.model, self.sim.data
        if not self.sim.base_control_available:
            raise Fault("missing_actuated_sim_base")
        self.integration_spec = mujoco.mjtState.mjSTATE_INTEGRATION
        self.integration_size = mujoco.mj_stateSize(self.m, self.integration_spec)
        self.shadow = mujoco.MjData(self.m)
        self.inverse = mujoco.MjData(self.m)
        self.evidence = Evidence(self.sim, self.g.ids)
        if any(v.size == 0 for v in self.evidence.local_vertices.values()):
            raise Fault("missing_tray_collision_vertices", "This adapter requires the repository's decomposed mesh contact assets")
        self.qids, self.dofs, self.aids = [], [], []
        for name in ARM_NAMES:
            j = self.m.joint(name).id
            self.qids.append(int(self.m.jnt_qposadr[j]))
            self.dofs.append(int(self.m.jnt_dofadr[j]))
            self.aids.append(self.m.actuator(name+"_target").id)
        self.qids, self.dofs, self.aids = map(np.array, (self.qids, self.dofs, self.aids))
        self.jids = np.array([self.m.joint(n).id for n in ARM_NAMES])
        self.base_joints = [self.m.joint("agent_base_"+n).id for n in ("x", "y", "yaw")]
        self.base_qids = np.array([self.m.jnt_qposadr[j] for j in self.base_joints])
        self.base_dofs = np.array([self.m.jnt_dofadr[j] for j in self.base_joints])
        self.base_aids = np.array([self.m.actuator("agent_base_"+n+"_target").id for n in ("x", "y", "yaw")])
        self.robot_bodies = self._descendants(self.m.body("base_link").id)
        self.tray_bodies = {bid: t for t, name in enumerate(self.g.ids) for bid in self._descendants(self.m.body(name).id)}
        self.table_bodies = {bid for name in self.g.tables for bid in self._descendants(self.m.body(name).id)}
        self.robot_geoms = np.array([g for g in range(self.m.ngeom) if self.m.geom_bodyid[g] in self.robot_bodies and (self.m.geom_contype[g] or self.m.geom_conaffinity[g])], int)
        self.self_view_geoms = [int(g) for g in self.robot_geoms if self.m.body(int(self.m.geom_bodyid[g])).name in
                               ('base_link', 'torso_link1', 'torso_link2', 'torso_link3', 'torso_link4', 'zed_link')]
        self.table_geoms = np.array([g for g in range(self.m.ngeom) if self.m.geom_bodyid[g] in self.table_bodies and (self.m.geom_contype[g] or self.m.geom_conaffinity[g])], int)
        self.allowed_tray = None
        self.holding = None
        self.retained_contact = None
        self.retained_support_missing_since = None
        self.strict_runtime_passed = True
        self.soft_guard_violation_count = 0
        self.soft_guard_violation_by_code = {}
        self.soft_guard_violation_maxima = {}
        self.soft_guard_last_step_by_code = {}
        self.completion_speed_since_step = None
        self.retained_support_missing_step = None
        self.physics_step_count = 0
        self.physics_clock_origin_time = float(self.d.time)
        self.physics_clock_timestep = float(self.m.opt.timestep)
        self.grasp_rel = None
        self.lost_time = 0.
        self.trace = None
        self.record_ctrl_substeps = False
        self.fsm_state, self.phase = State.SEARCH_TARGET, "unknown"
        self.target_slot = -1
        self.recovery = False
        self.wall_start = time.monotonic()
        self.steps = 0
        self.peak_power = 0.
        self.id_calls = 0
        self.id_slowdowns = 0
        self.action_frames = 0
        self.physical_time_start = float(self.d.time)
        self.previous_warning = np.array([w.number for w in self.d.warning])
        self.home = self.sim.target.copy()
        self.tucked = self.home.copy()
        # Existing validated navigation profile: arms clear trays, cameras down/forward.
        self.tucked[[3, 11]] = -1.70
        self.tucked[[0, 8]] = -.35
        self.tucked[[5, 13]] = .9
        self.limits = self._limits()
        self.initial_bottom = self.observation()["min_z"].copy()
        for name in shapes:
            if mujoco.mj_name2id(self.m, mujoco.mjtObj.mjOBJ_CAMERA, name) < 0:
                raise Fault("missing_native_camera", name)
        for side in ("left", "right"):
            if mujoco.mj_name2id(self.m, mujoco.mjtObj.mjOBJ_BODY, side+"_realsense_link") < 0:
                raise Fault("missing_wrist_camera_body", side)

    def _descendants(self, root):
        result = set()
        for b in range(1, self.m.nbody):
            node = b
            while node and node != root:
                node = int(self.m.body_parentid[node])
            if node == root:
                result.add(b)
        return result

    def _limits(self):
        cfg = self.cfg
        velocity = np.tile(cfg.arm_velocity_fallback, 2).astype(float)
        source = "engineering_simulation_caps_from_previous_teleop_configuration"
        urdf = None
        if cfg.urdf:
            urdf = Path(cfg.urdf).expanduser().resolve()
            if not urdf.is_file():
                raise Fault("configured_urdf_missing", str(urdf))
        else:
            root = Path(__file__).resolve().parents[2]
            for p in (root/"vendor/GalaxeaManipSim/galaxea_sim/assets/r1_pro/robot.urdf", root/"outputs/r1pro_tray_scene/assets/r1_pro/robot.urdf"):
                if p.is_file():
                    urdf = p
                    break
        urdf_effort = np.full(14, np.inf)
        if urdf:
            tree = ET.parse(urdf)
            for i, name in enumerate(ARM_NAMES):
                limit = tree.find(f".//joint[@name='{name}']/limit")
                if limit is None or not limit.get("velocity") or not limit.get("effort"):
                    raise Fault("incomplete_urdf_limits", name)
                velocity[i] = min(velocity[i], float(limit.get("velocity")))
                urdf_effort[i] = float(limit.get("effort"))
            source = "min(URDF_joint_limits,engineering_simulation_caps)"
        profile = None
        if cfg.hardware_profile:
            profile = json.loads(Path(cfg.hardware_profile).read_text(encoding="utf-8"))
        self.power_cap = None
        if cfg.limit_mode == "verified80":
            required = ("robot_model", "source", "verified", "joint_velocity_rad_s", "joint_effort_nm", "mechanical_power_abs_sum_w", "power_definition")
            if not profile or any(k not in profile for k in required) or profile["verified"] is not True or profile["robot_model"] != "R1 Pro":
                raise Fault("hardware_profile_unverified")
            if profile["power_definition"] != "sum_abs_actuator_mechanical_power":
                raise Fault("incompatible_power_definition", "Electrical input watts cannot be silently used as mechanical power")
            v = np.array([profile["joint_velocity_rad_s"][n] for n in ARM_NAMES], float)
            e = np.array([profile["joint_effort_nm"][n] for n in ARM_NAMES], float)
            if min(v.min(), e.min(), float(profile["mechanical_power_abs_sum_w"])) <= 0 or not np.isfinite(np.r_[v, e, profile["mechanical_power_abs_sum_w"]]).all():
                raise Fault("invalid_hardware_limits")
            velocity, urdf_effort = np.minimum(velocity, v), np.minimum(urdf_effort, e)
            self.power_cap = cfg.limit_fraction*float(profile["mechanical_power_abs_sum_w"])
            source += "; externally_verified_profile"
        # Position servo force limits are SIMULATION parameters; record the distinction.
        fraction = cfg.limit_fraction
        for a in range(self.m.nu):
            if not self.m.actuator_forcelimited[a]:
                raise Fault("unlimited_actuator", self.m.actuator(a).name)
            self.m.actuator_forcerange[a] *= fraction
        for i, a in enumerate(self.aids):
            gear = abs(float(self.m.actuator_gear[a, 0]))
            if not np.isclose(gear, 1.):
                raise Fault("unsupported_nonunit_joint_transmission", self.m.actuator(a).name)
            cap = min(float(np.min(np.abs(self.m.actuator_forcerange[a]))), urdf_effort[i]*fraction)
            self.m.actuator_forcerange[a] = [-cap, cap]
        self.v = np.zeros(16)
        self.a = np.zeros(16)
        self.j = np.zeros(16)
        self.actual_velocity_cap = velocity*fraction
        # The MuJoCo position servo can overshoot a sampled reference slightly
        # between 20 Hz frames.  A 22% reference margin keeps measured velocity
        # inside the hard 80% cap without hiding or tolerating an overspeed.
        # Position-servo tracking can overshoot the analytic reference near a
        # multi-segment fallback boundary.  A 72% reference inside the hard
        # 80% measured cap keeps the physical rollout below that cap even on
        # the fast wrist joints; the hard guard remains unchanged.
        self.v[ARM_COLUMNS] = self.actual_velocity_cap*.72
        # Leave acceleration headroom as well; the force-limited position
        # servo otherwise produces a short inter-frame velocity overshoot.
        self.a[ARM_COLUMNS] = cfg.arm_acceleration*fraction*.80
        self.j[ARM_COLUMNS] = cfg.arm_jerk*fraction
        self.v[[7, 15]] = cfg.gripper_velocity*fraction
        self.a[[7, 15]] = cfg.gripper_acceleration*fraction
        self.j[[7, 15]] = cfg.gripper_jerk*fraction
        self.effort = np.min(np.abs(self.m.actuator_forcerange[self.aids]), axis=1)
        return {"mode": cfg.limit_mode, "fraction": fraction, "arm_velocity_rad_s": self.actual_velocity_cap.tolist(), "reference_arm_velocity_rad_s": self.v[ARM_COLUMNS].tolist(), "arm_effort_nm": self.effort.tolist(), "actuator_forcerange": self.m.actuator_forcerange.tolist(), "velocity_source": source, "urdf": str(urdf) if urdf else None, "hardware_profile": profile, "mechanical_power_abs_sum_cap_w": self.power_cap, "external_profile_declares_80_percent_mechanical_power": cfg.limit_mode == "verified80", "real_robot_driver": False, "acceleration_and_jerk_source": "engineering_simulation_reference_caps", "base_reference_caps": {"translation_m_s": cfg.base_speed*fraction, "yaw_rad_s": cfg.base_yaw_speed*fraction}, "inverse_dynamics_role": "arm reference feasibility and retiming; actual execution is force-limited position servo"}

    def observation(self):
        return {key.split("/")[-1]: value for key, value in self.evidence.row().items()}

    def camera_metrics(self, data=None, contact_sides=None):
        d = self.d if data is None else data
        R = d.body("base_link").xmat.reshape(3, 3)
        sides = ("left", "right") if contact_sides is None else contact_sides
        metrics = {}
        for side in sides:
            tcp = d.site(side+"_tcp")
            front = float((d.body(side+"_realsense_link").xpos-tcp.xpos) @ R[:, 0])
            upright = float(tcp.xmat.reshape(3, 3)[:, 1] @ R[:, 1])
            camera = self.m.camera(side+"_wrist").id
            optical = -d.cam_xmat[camera].reshape(3, 3)[:, 2]
            metrics[side] = {"camera_ahead_m": front, "wrist_upright_dot": upright,
                             "optical_forward_dot": float(optical @ R[:, 0])}
            if self.cfg.camera_guard_mode == 'body_ray_cone':
                from .camera_guard import self_view_hits
                metrics[side]['self_view_geoms'] = self_view_hits(
                    self.m, d, d.cam_xpos[camera], d.cam_xmat[camera],
                    self.self_view_geoms, self.cfg.camera_self_cone_deg)
        return metrics

    def camera_guard(self, data=None, contact_sides=None):
        metrics = self.camera_metrics(data, contact_sides)
        return all(v["camera_ahead_m"] > self.cfg.camera_front_margin_m and
                   v["wrist_upright_dot"] > 0 and
                   (not v['self_view_geoms'] if self.cfg.camera_guard_mode == 'body_ray_cone'
                    else v["optical_forward_dot"] > -self.cfg.camera_forward_dot)
                   for v in metrics.values())

    def _pair_allowed(self, ga, gb):
        ba, bb = int(self.m.geom_bodyid[ga]), int(self.m.geom_bodyid[gb])
        if ba not in self.robot_bodies and bb not in self.robot_bodies:
            ta, tb = self.tray_bodies.get(ba), self.tray_bodies.get(bb)
            if self.holding is not None and self.holding in (ta, tb):
                other = bb if ta == self.holding else ba
                # Carrying needs a collision-free PAYLOAD, not just free arms.
                if other == 0: return False
                pickup_contact = self.fsm_state == State.GRASP_TRAY and self.phase in ('load_transfer', 'lift')
                # The whole-action model keeps one typed phase through lowering,
                # supported adjustment and release. Map only that placement node
                # to the existing held-payload/table exemption; robot/table and
                # global penetration checks remain unchanged.
                cfg = getattr(self, 'cfg', None)
                whole_action_place = (
                    getattr(cfg, 'motion_backend', 'teacher') == 'pi05' and
                    getattr(cfg, 'vla_prompt_mode', 'legacy') == 'task_complete_action8_v1' and
                    self.phase == 'vla_place_release_tray')
                placement_contact = self.fsm_state == State.PLACE_TRAY and (
                    self.phase in ('descend','support_contact','unload') or whole_action_place)
                if other in self.table_bodies:
                    return pickup_contact or placement_contact or self.fsm_state == State.RECOVER
                if other in self.tray_bodies:
                    return pickup_contact  # separation from the initial lower tray
                return False
            if self.fsm_state == State.ADJUST_TRAY and self.allowed_tray in (ta, tb) and ta is not None and tb is not None:
                return False
            return True
        # Only the named floor, not arbitrary world-body walls, is allowed.
        if ba == 0 or bb == 0:
            body = bb if ba == 0 else ba
            floor_geom = ga if ba == 0 else gb
            name = self.m.body(body).name
            return self.m.geom(int(floor_geom)).name == 'floor' and name.startswith(("wheel_", "steer_", "base_link"))
        for b, other in ((ba, bb), (bb, ba)):
            if b in self.robot_bodies and other in self.tray_bodies:
                return "gripper_finger" in self.m.body(b).name and self.tray_bodies[other] == self.allowed_tray
        return False

    def collision(self, data=None, *, planning=False, limit_override=None):
        d = self.d if data is None else data
        # Ignore sub-0.2 mm contact jitter during live integration.  Planning
        # still keeps the configured positive clearance, and deeper contact is
        # rejected below and by the global penetration criterion.
        approximate = bool(getattr(self.cfg, 'approximate_completion_enabled', False))
        relaxed_planning = (approximate and planning and
                            bool(getattr(self, '_approximate_planning_relaxed', False)))
        contact_limit = (float(limit_override) if limit_override is not None else
                         -float(self.cfg.completion_collision_penetration_m)
                         if approximate and (not planning or relaxed_planning) else
                         self.cfg.planner_margin_m if planning else -.0002)
        for contact in d.contact:
            if not np.isfinite(contact.dist):
                raise Fault('nonfinite_physics')
            if contact.dist > contact_limit:
                continue
            if not self._pair_allowed(contact.geom1, contact.geom2):
                # No blanket exception for fingers: finger/table and finger/wrong-tray fail.
                return {"geoms": [self.m.geom(int(g)).name for g in (contact.geom1, contact.geom2)], "distance_m": float(contact.dist)}
        # Static/welded body pairs can be missing from the contact list. Explicitly
        # check nearby robot/table hulls; broad phase limits the pair count.
        for g in self.robot_geoms:
            if not len(self.table_geoms):
                continue
            distances = np.linalg.norm(d.geom_xpos[self.table_geoms]-d.geom_xpos[g], axis=1)
            query_margin = max(.001, self.cfg.planner_margin_m) if planning else .001
            candidates = self.table_geoms[distances < self.m.geom_rbound[self.table_geoms]+self.m.geom_rbound[g]+query_margin]
            for other in candidates:
                if not ((self.m.geom_contype[g] & self.m.geom_conaffinity[other]) or (self.m.geom_contype[other] & self.m.geom_conaffinity[g])):
                    continue
                distance = self.mj.mj_geomDistance(self.m, d, int(g), int(other), query_margin, None)
                if not np.isfinite(distance):
                    raise Fault('nonfinite_physics')
                if distance < contact_limit:
                    return {"geoms": [self.m.geom(int(g)).name, self.m.geom(int(other)).name], "distance_m": float(distance)}
        return None

    def record_strict_deviation(self, code, detail):
        """Record relaxed acceptance, deduplicating checks at one physical step."""
        self.strict_runtime_passed = False
        count = int(getattr(self, 'physics_step_count', getattr(self, 'steps', 0)))
        by_code = getattr(self, 'soft_guard_violation_by_code', {})
        maxima = getattr(self, 'soft_guard_violation_maxima', {})
        last = getattr(self, 'soft_guard_last_step_by_code', {})
        values = maxima.setdefault(str(code), {})
        for key, value in detail.items():
            if isinstance(value, (bool, str, dict)) or value is None:
                continue
            try:
                array = np.asarray(value, dtype=float)
            except (TypeError, ValueError):
                continue
            if array.size and np.isfinite(array).all():
                values[str(key)] = max(values.get(str(key), 0.), float(np.max(np.abs(array))))
        self.soft_guard_violation_maxima = maxima
        if last.get(str(code)) == count:
            return
        last[str(code)] = count
        by_code[str(code)] = by_code.get(str(code), 0) + 1
        self.soft_guard_last_step_by_code = last
        self.soft_guard_violation_by_code = by_code
        self.soft_guard_violation_count = getattr(self, 'soft_guard_violation_count', 0) + 1
        if self.trace:
            self.trace.event('strict_deviation', code=str(code), detail=detail,
                profile=getattr(self.cfg, 'acceptance_profile', 'strict'),
                physics_step_count=count, physics_time_s=float(self.d.time),
                strict_runtime_passed=False, qualification='acceptance_policy_relaxation_not_control_improvement')

    def _approximate_deviation(self, code, detail):
        """Bound log volume while preserving actual soft-fault counts and peaks."""
        if not getattr(self.cfg, 'approximate_completion_enabled', False):
            raise Fault(code, detail)
        self.strict_runtime_passed = False
        counts = getattr(self, 'approximate_deviation_counts', None)
        if counts is None:
            counts = self.approximate_deviation_counts = {}
        count = counts[code] = counts.get(code, 0) + 1
        maxima = getattr(self, 'soft_guard_violation_maxima', {})
        values = maxima.setdefault(code, {})
        for key, value in detail.items():
            if isinstance(value, (bool, str, dict)) or value is None:
                continue
            try:
                array = np.asarray(value, dtype=float)
            except (TypeError, ValueError):
                continue
            if array.size and np.isfinite(array).all():
                values[key] = max(values.get(key, 0.), float(np.max(np.abs(array))))
        self.soft_guard_violation_maxima = maxima
        step = int(getattr(self, 'physics_step_count', 0))
        last = getattr(self, 'soft_guard_last_step_by_code', {})
        if last.get(code) != step:
            last[code] = step
            self.soft_guard_last_step_by_code = last
            by_code = getattr(self, 'soft_guard_violation_by_code', {})
            by_code[code] = by_code.get(code, 0) + 1
            self.soft_guard_violation_by_code = by_code
            self.soft_guard_violation_count = getattr(self, 'soft_guard_violation_count', 0) + 1
        if count == 1 or count % max(1, round(.5 / float(self.m.opt.timestep))) == 0:
            if self.trace:
                self.trace.event('approximate_guard_deviation', code=code, detail=detail,
                    count=count, physics_step_count=int(getattr(self, 'physics_step_count', 0)),
                    qualification='observed_midcourse_deviation_not_final_acceptance')

    def _check_measured_arm_speed(self, measured, ratio):
        """Keep the strict rule; optionally tolerate one bounded transient."""
        if not np.any(ratio > 1.01):
            self.completion_speed_since_step = None
            return
        joint = int(np.argmax(ratio))
        detail = {'joint': ARM_NAMES[joint], 'measured_rad_s': float(measured[joint]),
            'cap_rad_s': float(self.actual_velocity_cap[joint]), 'ratio': float(ratio[joint]),
            'physics_time_s': float(self.d.time)}
        if getattr(self.cfg, 'approximate_completion_enabled', False):
            self._approximate_deviation('measured_joint_overspeed', detail)
            return
        if getattr(self.cfg, 'acceptance_profile', 'strict') != 'completion_first':
            raise Fault('measured_joint_overspeed', detail)
        self.validate_retained_clock_state()
        if self.completion_speed_since_step is None:
            self.completion_speed_since_step = self.physics_step_count
        elapsed_steps = self.physics_step_count-self.completion_speed_since_step
        if elapsed_steps < 0:
            raise Fault('completion_speed_clock_inconsistent')
        elapsed = elapsed_steps * Fraction(str(self.physics_clock_timestep))
        allowed = (float(ratio[joint]) <= self.cfg.completion_speed_ratio_max and
                   elapsed <= Fraction(str(self.cfg.completion_speed_excursion_s)))
        detail.update(strict_ratio_max=1.01, completion_ratio_max=self.cfg.completion_speed_ratio_max,
            excursion_physics_steps=int(elapsed_steps), excursion_seconds=float(elapsed),
            completion_excursion_seconds=self.cfg.completion_speed_excursion_s)
        if not allowed:
            raise Fault('measured_joint_overspeed', detail)
        self.record_strict_deviation('measured_joint_overspeed', detail)

    def guard(self):
        if (not np.isfinite(self.d.qpos).all() or not np.isfinite(self.d.qvel).all() or
                not np.isfinite(self.d.time) or not np.isfinite(self.d.actuator_force).all() or
                not np.isfinite(self.d.actuator_velocity).all()):
            raise Fault("nonfinite_physics")
        warnings = np.array([w.number for w in self.d.warning])
        if np.any(warnings > self.previous_warning):
            raise Fault("mujoco_warning", (warnings-self.previous_warning).tolist())
        approximate = bool(getattr(self.cfg, 'approximate_completion_enabled', False))
        bad = self.collision()
        if bad:
            raise Fault("illegal_collision", bad)
        if approximate:
            old_bad = self.collision(limit_override=-.0002)
            if old_bad:
                self._approximate_deviation('illegal_collision', old_bad)
        e = self.observation()
        if any(not np.isfinite(e[key]).all() for key in
               ('tray_pose', 'min_z', 'gripper_contact_force', 'max_penetration')):
            raise Fault('nonfinite_physics')
        if np.any(e["floor_contact"]):
            if approximate:
                self._approximate_deviation('tray_on_floor', {'trays': np.flatnonzero(e['floor_contact']).tolist()})
            else:
                raise Fault("tray_on_floor")
        if float(e["max_penetration"]) > self.cfg.criteria.penetration_m:
            if approximate and float(e['max_penetration']) <= self.cfg.completion_collision_penetration_m:
                self._approximate_deviation('excess_penetration',
                    {'measured_m': float(e['max_penetration']), 'cap_m': self.cfg.completion_collision_penetration_m})
            else:
                raise Fault("excess_penetration", float(e["max_penetration"]))
        monitor = getattr(self, '_handoff_clearance_monitor', None)
        if monitor is not None:
            from .handoff_clearance import check_monitor
            check_monitor(self, e, monitor)
        sides = [side for j, side in enumerate(("left", "right")) if np.any(e["gripper_contact_force"][:, j] > .5)]
        if sides and not self.camera_guard(contact_sides=sides):
            raise Fault("wrist_camera_front_guard", {"sides": sides,
                                                       "camera_metrics": self.camera_metrics(contact_sides=sides)})
        measured=np.abs(self.d.qvel[self.dofs]);ratio=measured/self.actual_velocity_cap
        # MuJoCo's 2 ms position-servo substeps can show a one-sample numerical
        # peak just above the engineering velocity cap even when the 20 Hz
        # reference remains well below it.  Keep a bounded 1% integration
        # tolerance in strict mode. The explicit completion-first policy below
        # records an original failure before permitting a bounded transient.
        self._check_measured_arm_speed(measured, ratio)
        base_velocity = self.d.qvel[self.base_dofs]
        if np.linalg.norm(base_velocity[:2]) > self.cfg.base_speed*self.cfg.limit_fraction+1e-5 or abs(base_velocity[2]) > self.cfg.base_yaw_speed*self.cfg.limit_fraction+1e-5:
            if approximate:
                self._approximate_deviation('measured_base_overspeed', {'velocity': base_velocity.tolist()})
            else:
                raise Fault('measured_base_overspeed')
        power = float(np.sum(np.abs(self.d.actuator_force*self.d.actuator_velocity)))
        self.peak_power = max(self.peak_power, power)
        if self.power_cap is not None and power > self.power_cap:
            if approximate:
                self._approximate_deviation('mechanical_power_cap', {"measured_w": power, "cap_w": self.power_cap})
            else:
                raise Fault("mechanical_power_cap", {"measured_w": power, "cap_w": self.power_cap})
        if self.holding is not None:
            t = self.holding
            if self.fsm_state == State.TRANSPORT_TRAY and e["support_contact"][t] > 0:
                detail = {
                    "tray": t, "support_contacts": int(e["support_contact"][t]),
                    "bottom_clearance_m": float(e["min_z"][t]-self.initial_bottom[t]),
                }
                if approximate: self._approximate_deviation('carried_payload_support_contact', detail)
                else: raise Fault('carried_payload_support_contact', detail)
            if np.any(e["gripper_contact_force"][t] <= .5):
                self.lost_time += float(self.m.opt.timestep)
            else:
                self.lost_time = 0.
            if self.lost_time > .12:
                if approximate: self._approximate_deviation('bilateral_contact_lost', {"tray": t, "seconds": self.lost_time})
                else: raise Fault("bilateral_contact_lost", {"tray": t, "seconds": self.lost_time})
            _, tilt = quat_yaw_tilt(e["tray_pose"][t, 3:])
            if tilt > np.deg2rad(20):
                if approximate: self._approximate_deviation('carried_tray_tilt', {"tray": t, "tilt_rad": float(tilt)})
                else: raise Fault("carried_tray_tilt")
            for other in range(len(self.g.ids)):
                if other != t and e["support_contact"][other] == 0 and e["min_z"][other]-self.initial_bottom[other] > .02:
                    if approximate: self._approximate_deviation('multiple_trays_lifted', {"intended": t, "other": other})
                    else: raise Fault("multiple_trays_lifted", {"intended": t, "other": other})
        return e

    # 唯一实时推进入口：检查动作预算、积分物理、同步记录并执行安全守卫。
    def tick(self, *, substep_targets=None):
        if substep_targets is not None:
            if not self.cfg.substep_control_enabled:
                raise Fault('substep_control_not_enabled')
            substep_targets = np.asarray(substep_targets, dtype=np.float32)
            if substep_targets.shape != (self.sim.nstep, 16) or not np.isfinite(substep_targets).all():
                raise Fault('invalid_substep_targets')
            if not np.array_equal(substep_targets[-1], np.asarray(self.sim.target, dtype=np.float32)):
                raise Fault('substep_endpoint_mismatch')
        deadline = getattr(self, 'primitive_deadline_step', None)
        if deadline != getattr(self, '_approximate_extended_deadline_step', None):
            self._approximate_deadline_extended = False
        if deadline is not None and self.steps >= deadline:
            if getattr(self.cfg, 'approximate_completion_enabled', False):
                self._approximate_deviation('primitive_deadline_exceeded',
                    {'configured_s': self.cfg.primitive_seconds, 'numerical_window_s': 120.,
                     'qualification': 'rolling_planning_window_not_time_failure'})
                extended = self.steps + math.ceil(120*self.cfg.fps)
                self.primitive_deadline_step = extended
                self._approximate_deadline_extended = True
                self._approximate_extended_deadline_step = extended
            else:
                raise Fault('primitive_deadline_exceeded', {'limit_s': self.cfg.primitive_seconds})
        elif deadline is None:
            self._approximate_deadline_extended = False
        if getattr(self.cfg, 'retained_support_integer_clock_enabled', False):
            self.validate_retained_clock_state()
        self.check_retained_contact()
        c = self.cfg
        if self.steps >= round(c.max_episode_seconds*c.fps) or time.monotonic()-self.wall_start > c.max_attempt_wall_seconds:
            if getattr(c, 'approximate_completion_enabled', False):
                self._approximate_deviation('episode_budget_exhausted',
                    {'simulation_s': float(self.d.time), 'wall_s': float(time.monotonic()-self.wall_start)})
            else:
                raise Fault("episode_budget_exhausted")
        self.sim.target = np.asarray(self.sim.target, np.float32)
        self.sim.base_target = np.asarray(self.sim.base_target, np.float32)
        e = self.observation()
        integration = np.empty(self.integration_size, dtype=np.float64)
        self.mj.mj_getState(self.m, self.d, integration, self.integration_spec)
        row = dict(integration_state=integration, ctrl=self.d.ctrl.copy(), timestamp=np.float64(self.steps/c.fps), sim_time=np.float64(self.d.time), qpos=self.d.qpos.copy(), qvel=self.d.qvel.copy(), qacc_warmstart=self.d.qacc_warmstart.copy(), act=self.d.act.copy(), state=self.sim.state(), action=self.sim.target.copy(), base_action=self.sim.base_target.copy(), base_state=self.sim.base_state(), fsm_state=self.fsm_state.value, phase=self.phase, target_tray=np.int32(-1 if self.allowed_tray is None else self.allowed_tray), target_slot=np.int32(self.target_slot), recovery=np.bool_(self.recovery), wrist_violation=np.bool_(False), transition_completed=np.bool_(False), **e)
        record_substeps = c.substep_control_enabled or self.record_ctrl_substeps
        if record_substeps:
            row['ctrl_substeps'] = np.zeros((self.sim.nstep, self.m.nu), dtype=np.float64)
            row['executed_substeps'] = np.int32(0)
        t0 = float(self.d.time)
        self.sim.apply_target()
        try:
            for substep in range(self.sim.nstep):
                if substep_targets is not None:
                    self.sim.target = substep_targets[substep].copy()
                    self.sim.apply_target()
                if record_substeps:
                    row['ctrl_substeps'][substep] = self.d.ctrl
                self.mj.mj_step(self.m, self.d)
                self.physics_step_count = getattr(self, 'physics_step_count', 0) + 1
                if record_substeps:
                    row['executed_substeps'] = np.int32(substep+1)
                # mj_step advances qpos; synchronize derived poses/contacts for
                # guards and RGB rather than mixing pre/post-integration state.
                self.mj.mj_forward(self.m, self.d)
                self.guard()
            if not math.isclose(self.d.time-t0, 1/c.fps, abs_tol=1e-9):
                raise Fault("physics_time_reset_or_drift")
            self.check_retained_contact()
            row["transition_completed"] = np.bool_(True)
        except Fault as exc:
            row['wrist_violation'] = np.bool_(exc.code == 'wrist_camera_front_guard')
            if exc.code == 'illegal_collision': row['illegal_collision'] = np.int32(1)
            raise
        finally:
            if self.trace:
                self.trace.append(row)
        self.steps += 1
        self.sim.workspace_rotation = self.d.body("base_link").xmat.reshape(3, 3).copy()
        from ..core import XR_TO_ROBOT
        self.sim.xr_to_world = self.sim.workspace_rotation @ XR_TO_ROBOT

    def validate_retained_clock_state(self):
        """Validate actual-step history without reconstructing or resetting it."""
        if not getattr(self.cfg, 'retained_support_integer_clock_enabled', False):
            return None
        required = ('physics_step_count', 'physics_clock_origin_time',
                    'physics_clock_timestep', 'retained_support_missing_step')
        if any(not hasattr(self, name) for name in required):
            raise Fault('retained_support_clock_inconsistent', {'reason': 'missing_clock_fields'})
        count = getattr(self, 'physics_step_count', None)
        origin = getattr(self, 'physics_clock_origin_time', None)
        dt = getattr(self, 'physics_clock_timestep', None)
        missing = getattr(self, 'retained_support_missing_step', None)
        since = getattr(self, 'retained_support_missing_since', None)
        def reject(reason):
            raise Fault('retained_support_clock_inconsistent', {'reason': reason})
        if isinstance(count, bool) or not isinstance(count, (int, np.integer)) or count < 0:
            reject('invalid_physics_step_count')
        if (isinstance(origin, bool) or not isinstance(origin, (int, float)) or not math.isfinite(origin) or origin < 0 or
                isinstance(dt, bool) or not isinstance(dt, (int, float)) or not math.isfinite(dt) or dt <= 0 or
                dt != float(self.m.opt.timestep)):
            reject('invalid_origin_or_changed_timestep')
        expected = origin + count * dt
        # Only a consistency bound for accumulated floating integration time;
        # never added to the grace threshold or used to round elapsed steps.
        tolerance = max(1e-9, 8*np.finfo(float).eps*(count+1)*max(abs(origin), abs(expected), dt))
        if tolerance >= dt/4 or not math.isfinite(self.d.time) or abs(self.d.time-expected) > tolerance:
            reject('physical_time_counter_mismatch')
        if (since is None) != (missing is None):
            reject('missing_timer_context')
        if missing is not None:
            if isinstance(missing, bool) or not isinstance(missing, (int, np.integer)) or not 0 <= missing <= count:
                reject('invalid_missing_step')
            if isinstance(since, bool) or not isinstance(since, (int, float)) or not math.isfinite(since) or abs(since-(origin+missing*dt)) > tolerance:
                reject('missing_time_counter_mismatch')
        return {'physics_step_count': int(count), 'physics_clock_origin_time': origin,
                'physics_timestep_s': dt, 'missing_step': missing,
                'observed_physics_time_s': float(self.d.time), 'missing_since_s': since}

    def check_retained_contact(self):
        """20 Hz handoff contract; never synthesize a contact or freeze an object."""
        if getattr(self,'retained_contact',None) is None:return
        clock = self.validate_retained_clock_state() if getattr(self.cfg, 'retained_support_integer_clock_enabled', False) else None
        tray,side=self.retained_contact
        i=0 if side=='left' else 1;col=7 if side=='left' else 15
        e=self.observation()
        supported=e['table_contact'][tray]>0
        support_grace=False
        completion_support_grace=False
        completion_support_detail=None
        if supported:
            self.retained_support_missing_since=None
            self.retained_support_missing_step=None
            if clock is not None:
                clock.update(missing_step=None, missing_since_s=None)
        elif 'min_z' in e and 'tray_pose' in e:
            table=self.g.support_table(e['tray_pose'][tray,:3])
            if table is not None:
                if self.retained_support_missing_since is None:
                    self.retained_support_missing_since=float(self.d.time)
                    if clock is not None:
                        self.retained_support_missing_step=self.physics_step_count
                    if self.trace:self.trace.event('retained_support_microbounce',tray=tray,side=side,
                        measured_bottom_gap_m=float(e['min_z'][tray]-self.g.tables[table]['dimensions_m'][2]))
                gap=float(e['min_z'][tray]-self.g.tables[table]['dimensions_m'][2])
                # A rotated overhanging corner may be slightly below table
                # height without intersecting it. Actual penetration remains
                # checked by guard(); upward separation is limited to 2 mm.
                elapsed = self.d.time-self.retained_support_missing_since
                time_allowed = elapsed <= .15
                if clock is not None:
                    delta = int(self.physics_step_count-self.retained_support_missing_step)
                    exact_elapsed = delta * Fraction(str(self.physics_clock_timestep))
                    time_allowed = exact_elapsed <= Fraction('0.15')
                    clock.update(missing_step=int(self.retained_support_missing_step),
                        missing_since_s=float(self.retained_support_missing_since),
                        elapsed_physics_steps=delta, elapsed_float_s=float(elapsed),
                        elapsed_exact_numerator=exact_elapsed.numerator,
                        elapsed_exact_denominator=exact_elapsed.denominator,
                        integer_time_allowed=time_allowed, legacy_float_time_allowed=elapsed<=.15,
                        boundary_only_difference=(exact_elapsed==Fraction('0.15') and elapsed>.15))
                    if self.trace:
                        self.trace.event('retained_support_integer_clock',tray=tray,side=side,**clock)
                support_grace=(-self.cfg.criteria.penetration_m<=gap<=.002 and time_allowed)
                if (not support_grace and clock is not None and
                        getattr(self.cfg, 'acceptance_profile', 'strict') == 'completion_first'):
                    completion_support_grace=(-self.cfg.criteria.penetration_m<=gap<=.002 and
                        exact_elapsed <= Fraction(str(self.cfg.completion_support_grace_s)))
                    completion_support_detail={'tray':tray,'side':side,'table_contact':int(e['table_contact'][tray]),
                        'force_n':float(e['gripper_contact_force'][tray,i]),'command_opening_m':float(self.sim.target[col]),
                        'measured_bottom_gap_m':gap,'missing_physics_steps':delta,
                        'missing_seconds':float(exact_elapsed),'strict_grace_seconds':.15,
                        'completion_grace_seconds':self.cfg.completion_support_grace_s}
        if (completion_support_grace and e['gripper_contact_force'][tray,i]>self.cfg.criteria.contact_n and
                self.sim.target[col]<=self.cfg.gripper_close_m+1e-5):
            self.record_strict_deviation('retained_contact_lost',completion_support_detail)
        if (not (supported or support_grace or completion_support_grace) or
            e['gripper_contact_force'][tray,i]<=self.cfg.criteria.contact_n or
            self.sim.target[col]>self.cfg.gripper_close_m+1e-5):
            detail={'tray':tray,'side':side,
                'table_contact':int(e['table_contact'][tray]),
                'force_n':float(e['gripper_contact_force'][tray,i]),
                'command_opening_m':float(self.sim.target[col]),
                **({'clock': clock} if clock is not None else {})}
            if getattr(self.cfg, 'approximate_completion_enabled', False):
                self._approximate_deviation('retained_contact_lost', detail)
            else:
                raise Fault('retained_contact_lost', detail)

    def wait(self, seconds, predicate=None, stable_seconds=None):
        from .contracts import StableGate
        gate = StableGate(stable_seconds or .1, self.cfg.fps)
        for _ in range(max(1, math.ceil(seconds*self.cfg.fps))):
            self.tick()
            if predicate is not None and gate.update(bool(predicate(self.observation()))):
                return True
        return predicate is None

    def _shadow(self, target=None, base_world=None):
        d = self.shadow
        d.qpos[:] = self.d.qpos
        d.qvel[:] = 0.
        if target is not None:
            target = np.asarray(target)
            d.qpos[self.qids] = target[ARM_COLUMNS]
            # Both hands observe the same unchanged live state. Do not rebuild
            # all tray/contact evidence separately for each aperture decision.
            contact_forces = (self.observation()['gripper_contact_force'][self.allowed_tray]
                              if self.allowed_tray is not None else None)
            for side, col in (("left", 7), ("right", 15)):
                opening = float(target[col])
                side_index = 0 if side == "left" else 1
                contact_closing = (contact_forces is not None and contact_forces[side_index] > .5)
                if self.holding is not None or contact_closing:
                    # The force-limited close target may be zero while the
                    # payload physically holds the fingers apart.  Planning
                    # must use the measured aperture, otherwise the shadow
                    # model invents finger/finger overlap inside the tray.
                    opening = max(opening, float(self.sim.state()[col]))
                for j in self.sim.fingers[side]:
                    d.qpos[self.m.jnt_qposadr[j]] = opening/2
        if base_world is not None:
            origin = self.m.body_pos[self.m.body("base_link").id]
            q = self.m.body_quat[self.m.body("base_link").id]
            initial_yaw = 2*np.arctan2(q[3], q[0])
            current = float(self.d.qpos[self.base_qids[2]])
            angle = current + float(wrap_angle(base_world[2]-initial_yaw-current))
            d.qpos[self.base_qids] = [base_world[0]-origin[0], base_world[1]-origin[1], angle]
        self.mj.mj_kinematics(self.m, d)
        if self.holding is not None and self.grasp_rel:
            left = d.site("left_tcp")
            object_T = _homogeneous(left.xpos, left.xmat.reshape(3, 3)) @ np.linalg.inv(self.grasp_rel["left"])
            body_id = self.m.body(self.g.ids[self.holding]).id
            joint = int(self.m.body_jntadr[body_id])
            if self.m.jnt_type[joint] != self.mj.mjtJoint.mjJNT_FREE:
                raise Fault("tray_not_free_body")
            adr = self.m.jnt_qposadr[joint]
            quat = Rotation.from_matrix(object_T[:3, :3]).as_quat()[[3, 0, 1, 2]]
            d.qpos[adr:adr+7] = np.r_[object_T[:3, 3], quat]
        self.mj.mj_forward(self.m, d)
        return d

    def _target_valid(self, target, base_world=None, *, wrist=False):
        d = self._shadow(target, base_world)
        if self.collision(d, planning=True):
            return False
        if wrist and not self.camera_guard(d):
            return False
        if self.holding is not None and self.grasp_rel:
            l, r = d.site("left_tcp"), d.site("right_tcp")
            TL = _homogeneous(l.xpos, l.xmat.reshape(3, 3)) @ np.linalg.inv(self.grasp_rel["left"])
            TR = _homogeneous(r.xpos, r.xmat.reshape(3, 3)) @ np.linalg.inv(self.grasp_rel["right"])
            if np.linalg.norm(TL[:3, 3]-TR[:3, 3]) > .015 or Rotation.from_matrix(TL[:3, :3] @ TR[:3, :3].T).magnitude() > .10:
                return False
        return True

    def _rigid_grasp_error(self, data):
        """Return disagreement between the two payload poses implied by the TCPs."""
        if self.holding is None or not self.grasp_rel:
            return None
        left, right = data.site("left_tcp"), data.site("right_tcp")
        left_object = (_homogeneous(left.xpos, left.xmat.reshape(3, 3)) @
                       np.linalg.inv(self.grasp_rel["left"]))
        right_object = (_homogeneous(right.xpos, right.xmat.reshape(3, 3)) @
                        np.linalg.inv(self.grasp_rel["right"]))
        return {
            "position_m": float(np.linalg.norm(left_object[:3, 3]-right_object[:3, 3])),
            "rotation_rad": float(Rotation.from_matrix(
                left_object[:3, :3] @ right_object[:3, :3].T).magnitude()),
        }

    def _ik_tolerances(self, side):
        position=min(self.cfg.ik_position_tolerance_m,.022) if self.holding is not None else self.cfg.ik_position_tolerance_m
        orientation=min(self.cfg.ik_orientation_tolerance_rad,.05) if self.holding is not None else self.cfg.ik_orientation_tolerance_rad
        if self.retained_contact is not None and (self.retained_contact[1]==side or
                not (self.cfg.fixed_primitives and self.fsm_state==State.ADJUST_TRAY)):
            position=min(position,.012);orientation=min(orientation,.08)
        return position,orientation

    def _completion_held_ik_position_bound(self, original):
        # Retained-contact pushing keeps its original positional/normal contract.
        if (getattr(self.cfg, 'acceptance_profile', 'strict') != 'completion_first' or
                self.holding is None or self.retained_contact is not None):
            return original
        # This declared held-only policy is independent of the empty-arm bound.
        bound=max(original, self.cfg.completion_held_ik_position_tolerance_m)
        private=getattr(self,'_place_private_position_bound_m',None)
        if private is not None and self.fsm_state==State.PLACE_TRAY:
            # This transient marker exists only on the independent place
            # planning copy. The globally validated Config remains <=80 mm.
            if (isinstance(private,bool) or not isinstance(private,(int,float)) or
                    not np.isfinite(private) or not .08<=private<=.10):
                raise Fault('place_private_position_bound_invalid')
            bound=max(bound,float(private))
        return bound

    def _completion_held_ik_orientation_bound(self, original):
        if (getattr(self.cfg, 'acceptance_profile', 'strict') != 'completion_first' or
                self.holding is None or self.retained_contact is not None):
            return original
        return max(original, self.cfg.completion_held_ik_orientation_tolerance_rad)

    def _record_held_ik_policy(self, deviations, *, goals, target):
        # Kinematic planning copies have no trace and can shallow-share counters.
        # Do not mutate those shared structures. Physical previews own their trace
        # and deep-copied counters, so their accepted policies remain private.
        if not deviations or getattr(self, 'trace', None) is None:
            return
        # This is one accepted solver query, NOT a selected path or execution.
        # Refresh FK for the returned solution; the last tried seed may differ.
        d=self.shadow
        d.qpos[self.qids]=np.asarray(target)[ARM_COLUMNS]
        self.mj.mj_kinematics(self.m,d)
        self.mj.mj_comPos(self.m,d)
        query_errors={}
        for side,(desired_p,desired_R) in goals.items():
            site=d.site(side+'_tcp');solved_R=site.xmat.reshape(3,3)
            error=np.asarray(desired_p)-site.xpos
            query_errors[side]={
                'desired_position_world_m':np.asarray(desired_p).tolist(),
                'solved_position_world_m':site.xpos.copy().tolist(),
                'desired_rotation_world':np.asarray(desired_R).tolist(),
                'solved_rotation_world':solved_R.copy().tolist(),
                'position_error_vector_m':error.tolist(),
                'position_error_m':float(np.linalg.norm(error)),
                'rotation_error_rad':float(Rotation.from_matrix(np.asarray(desired_R)@solved_R.T).magnitude())}
        query={'planning_only':True,'execution_confirmed':False,'selected_path_confirmed':False,
               'scope':'single_accepted_solver_query', 'selected_path_max_position_error_m':None,
               'tcp_errors':query_errors,
               'query_max_position_error_m':max(v['position_error_m'] for v in query_errors.values()),
               'rigid_grasp_error':self._rigid_grasp_error(d),
               'qualification':'may_be_discarded_by_later_path_or_candidate_validation'}
        returned_position=any(v['position_error_m']>self._ik_tolerances(s)[0] for s,v in query_errors.items())
        returned_orientation=any(v['rotation_error_rad']>self._ik_tolerances(s)[1] for s,v in query_errors.items())
        returned_relaxed=returned_position or returned_orientation
        if returned_relaxed:
            self.trace.event('held_ik_query_diagnostic',**query)
        detail = {'planning_only': True, 'execution_confirmed': False,
                  'selected_path_confirmed':False,
                  'selected_path_max_position_error_m':None,
                  'returned_solution_outside_strict_position':returned_position,
                  'returned_solution_outside_strict_orientation':returned_orientation,
                  'query_tcp_errors':query_errors if returned_relaxed else {},
                  'accepted_solution_errors': deviations,
                  'qualification': 'accepted_planning_policy_not_actual_control_violation'}
        codes=[]
        if any(v['position_error_m']>v['strict_position_tolerance_m'] for v in deviations):
            codes.append('held_ik_position_outside_strict_contract')
        if any(v.get('rotation_error_rad',0)>v.get('strict_orientation_tolerance_rad',float('inf')) for v in deviations):
            codes.append('held_ik_orientation_outside_strict_contract')
        # Loaded kinematic clones use a silent trace with shallow-copied Runtime
        # fields. Detach mutable aggregates before recording on this receiver.
        import copy
        for name in ('soft_guard_violation_by_code', 'soft_guard_violation_maxima',
                     'soft_guard_last_step_by_code'):
            setattr(self, name, copy.deepcopy(getattr(self, name, {})))
        for code in codes:
            self.trace.event('planning_policy_deviation',code=code,detail=detail)
            self.record_strict_deviation(code,detail)

    # IK 只求参考关节位置；实际运动仍需限力伺服和接触动力学验证。
    def solve_pair(self, goals: dict, seed=None, *, free_endpoint=False):
        # A collision-checked, time-parameterized empty-arm joint route may
        # connect distant endpoint configurations. This is not permission for
        # an instantaneous branch jump in a Cartesian/contact trajectory.
        if free_endpoint and (self.holding is not None or self.retained_contact is not None or
                              np.max(self.observation()['gripper_contact_force']) > .5):
            raise Fault('endpoint_ik_requires_empty_arms')
        branch_limit = np.inf if free_endpoint else self.cfg.max_ik_branch_step_rad
        target = self.sim.target.copy().astype(float) if seed is None else np.array(seed, float)
        reference = target.copy()
        policy_deviations = []
        d = self.shadow
        d.qpos[:] = self.d.qpos
        d.qpos[self.qids] = target[ARM_COLUMNS]
        low, high = self.m.jnt_range[self.jids].T
        low, high = low+self.cfg.joint_margin_rad, high-self.cfg.joint_margin_rad
        multistart_scope = (getattr(self.cfg,'completion_place_coupled_multistart_enabled',False) and
            self.cfg.acceptance_profile=='completion_first' and self.holding is not None and
            self.retained_contact is None and self.fsm_state==State.PLACE_TRAY and
            not free_endpoint and all(side in goals for side in ('left','right')))
        independent_searches = {}
        # A two-hand rigid payload is mildly over-constrained by the measured
        # contact transforms.  Permit 22 mm planning residual while the live
        # rollout still requires bilateral force, loss of table support and
        # >20 mm measured bottom clearance before accepting a lift.
        for side, offset, index in (("left", 0, 0), ("right", 8, 7)):
            if side not in goals:
                continue
            position_tolerance,orientation_tolerance=self._ik_tolerances(side)
            completion_position_tolerance=self._completion_held_ik_position_bound(position_tolerance)
            completion_orientation_tolerance=self._completion_held_ik_orientation_bound(orientation_tolerance)
            position_weights=np.ones(3)
            supported_push=(self.cfg.fixed_primitives and self.retained_contact is not None and
                            self.retained_contact[1]==side and self.fsm_state==State.ADJUST_TRAY)
            # A centimetre-scale reach tolerance cannot preserve a table
            # contact. Constrain only the support normal; preserve the existing
            # tangential/orientation/branch criteria and bounded solver budget.
            normal_tolerance=.00025 if supported_push else np.inf
            if supported_push:
                position_weights[2]=20.
            p, R = goals[side]
            qids = self.qids[index:index+7]
            q0 = target[offset:offset+7].copy()
            siteid = self.m.site(side+"_tcp").id
            lo, hi = low[index:index+7], high[index:index+7]
            orientation_weight = self.cfg.ik_orientation_weight
            regularization = .01 if self.holding is not None else self.cfg.ik_reference_regularization

            def residual(q):
                d.qpos[qids] = q
                self.mj.mj_kinematics(self.m, d)
                self.mj.mj_comPos(self.m, d)
                pos_error = p-d.site_xpos[siteid]
                rot_error = Rotation.from_matrix(R @ d.site_xmat[siteid].reshape(3, 3).T).as_rotvec()
                return np.r_[position_weights*pos_error, orientation_weight*rot_error, regularization*(q-q0)]

            # This bounded multi-start solver is the same family that passed
            # the existing direct-grasp fixture.  Seeds are fixed so an
            # episode remains exactly reproducible.
            rng = np.random.default_rng(410+index)
            initials = [np.clip(q0, lo, hi)]
            initials += [np.clip(q0+rng.normal(0., .55, 7), lo, hi) for _ in range(7)]
            best = None
            completion_best = None
            original_orientation_best = None
            strict_accepted = False
            qualified_seeds = []
            tested_seeds = 0
            for initial in initials:
                tested_seeds += 1
                fit = least_squares(residual, initial, bounds=(lo, hi),
                                    max_nfev=self.cfg.max_ik_iterations)
                residual(fit.x)
                pos_error = p-d.site_xpos[siteid]
                rot_error = Rotation.from_matrix(R @ d.site_xmat[siteid].reshape(3, 3).T).as_rotvec()
                branch = float(np.max(np.abs(fit.x-q0)))
                score = (np.linalg.norm(pos_error)/position_tolerance +
                         np.linalg.norm(rot_error)/orientation_tolerance +
                         abs(pos_error[2])/normal_tolerance +
                         .01*np.linalg.norm(fit.x-q0) +
                         10.*max(0., branch-branch_limit))
                accepted=(np.linalg.norm(pos_error) <= position_tolerance and
                          abs(pos_error[2]) <= normal_tolerance and
                          np.linalg.norm(rot_error) <= orientation_tolerance and
                          branch <= branch_limit)
                if (multistart_scope and
                        np.linalg.norm(pos_error) <= completion_position_tolerance and
                        abs(pos_error[2]) <= normal_tolerance and
                        np.linalg.norm(rot_error) <= completion_orientation_tolerance and
                        branch <= branch_limit):
                    qualified_seeds.append(fit.x.copy())
                # An admissible solution takes precedence over a lower-score
                # candidate which violates one of the hard acceptance limits.
                if accepted or best is None or score < best[0]:
                    best = (score, fit.x.copy(), pos_error.copy(), rot_error.copy())
                if (not accepted and np.linalg.norm(pos_error) <= completion_position_tolerance and
                        abs(pos_error[2]) <= normal_tolerance and
                        np.linalg.norm(rot_error) <= completion_orientation_tolerance and branch <= branch_limit and
                        (completion_best is None or score < completion_best[0])):
                    completion_best = (score, fit.x.copy(), pos_error.copy(), rot_error.copy())
                # A widened orientation bound can select a different independent
                # seed and then drive coupled refinement outside the unchanged
                # 80 mm position ceiling. In the private place fallback, retain
                # the best candidate from the original 0.05 rad seed set first.
                if (getattr(self,'_prefer_original_held_ik_seed',False) and not accepted and
                        np.linalg.norm(pos_error) <= completion_position_tolerance and
                        abs(pos_error[2]) <= normal_tolerance and
                        np.linalg.norm(rot_error) <= min(.05,completion_orientation_tolerance) and
                        branch <= branch_limit and
                        (original_orientation_best is None or score < original_orientation_best[0])):
                    original_orientation_best = (score, fit.x.copy(), pos_error.copy(), rot_error.copy())
                if accepted:
                    strict_accepted = True
                    break
            # Exhaust the SAME strict seeds first; a later strict solution takes
            # precedence over every earlier completion-only solution.
            if (not strict_accepted and (completion_position_tolerance > position_tolerance or
                    completion_orientation_tolerance > orientation_tolerance) and
                    completion_best is not None):
                best = original_orientation_best or completion_best
            _, q, pos_error, rot_error = best
            d.qpos[qids] = q
            if (np.linalg.norm(pos_error) > completion_position_tolerance or
                    abs(pos_error[2]) > normal_tolerance or
                    np.linalg.norm(rot_error) > completion_orientation_tolerance):
                detail={"side": side, "position_error_m": float(np.linalg.norm(pos_error)),
                        "rotation_error_rad": float(np.linalg.norm(rot_error))}
                if supported_push:
                    detail.update(normal_error_m=float(abs(pos_error[2])),normal_tolerance_m=normal_tolerance)
                raise Fault("ik_unreachable", detail, recoverable=True)
            if np.max(np.abs(q-q0)) > branch_limit:
                raise Fault("ik_branch_jump", {"side": side, "max_rad": float(np.max(np.abs(q-q0)))}, recoverable=True)
            target[offset:offset+7] = q
            if multistart_scope:
                independent_searches[side]={
                    'selected':q.copy(),'qualified':qualified_seeds,
                    'initials':initials,'tested':tested_seeds,'qids':qids.copy(),
                    'q0':q0.copy(),'lo':lo.copy(),'hi':hi.copy(),
                    'p':np.asarray(p).copy(),'R':np.asarray(R).copy(),
                    'siteid':siteid,'position_weights':position_weights.copy(),
                    'orientation_weight':orientation_weight,'regularization':regularization,
                    'position_bound':completion_position_tolerance,
                    'rotation_bound':completion_orientation_tolerance,
                    'normal_bound':normal_tolerance}
            if (np.linalg.norm(pos_error) > position_tolerance or
                    np.linalg.norm(rot_error) > orientation_tolerance):
                policy_deviations.append({'stage': 'independent', 'side': side,
                    'position_error_m': float(np.linalg.norm(pos_error)),
                    'strict_position_tolerance_m': float(position_tolerance),
                    'completion_position_tolerance_m': float(completion_position_tolerance),
                    'rotation_error_rad': float(np.linalg.norm(rot_error)),
                    'strict_orientation_tolerance_rad':float(orientation_tolerance),
                    'completion_orientation_tolerance_rad':float(completion_orientation_tolerance)})

        if self.holding is not None and all(side in goals for side in ("left", "right")):
            # Refine both arms together.  Independent IK can put each TCP
            # inside its own tolerance while the two TCPs imply payload poses
            # more than 15 mm apart.  The coupled residual trades a few
            # millimetres of absolute TCP error for a physically consistent
            # two-hand grasp; the live rollout remains contact/force driven.
            initial = target[ARM_COLUMNS].copy()

            def pair_residual(q, *, orientation_weight=None, reference_q=None):
                d.qpos[self.qids] = q
                self.mj.mj_kinematics(self.m, d)
                self.mj.mj_comPos(self.m, d)
                values = []
                implied = {}
                if orientation_weight is None:
                    orientation_weight = self.cfg.ik_orientation_weight
                for side in ("left", "right"):
                    desired_p, desired_R = goals[side]
                    site = d.site(side+"_tcp")
                    actual_R = site.xmat.reshape(3, 3)
                    values.extend(desired_p-site.xpos)
                    values.extend(orientation_weight *
                                  Rotation.from_matrix(desired_R @ actual_R.T).as_rotvec())
                    implied[side] = (_homogeneous(site.xpos, actual_R) @
                                     np.linalg.inv(self.grasp_rel[side]))
                values.extend(3.0*(implied["left"][:3, 3]-implied["right"][:3, 3]))
                values.extend(.6*Rotation.from_matrix(
                    implied["left"][:3, :3] @ implied["right"][:3, :3].T).as_rotvec())
                values.extend(.002*(q-(initial if reference_q is None else reference_q)))
                return np.asarray(values)

            fit = least_squares(pair_residual, initial, bounds=(low, high),
                                max_nfev=min(60, self.cfg.max_ik_iterations))
            def evaluate_pair(q):
                # Re-evaluate FK after every fit: the last residual call made
                # by least_squares need not use its returned joint vector.
                pair_residual(q)
                errors = {}
                for side in ("left", "right"):
                    desired_p, desired_R = goals[side]
                    site = d.site(side+"_tcp")
                    errors[side] = {
                        "position_m": float(np.linalg.norm(desired_p-site.xpos)),
                        "rotation_rad": float(Rotation.from_matrix(
                            desired_R @ site.xmat.reshape(3, 3).T).magnitude()),
                    }
                rigid = self._rigid_grasp_error(d)
                branch = float(np.max(np.abs(q-reference[ARM_COLUMNS])))
                qualified = (all(value["position_m"] <= completion_position_tolerance and
                                 value["rotation_rad"] <= completion_orientation_tolerance
                                 for value in errors.values()) and
                             rigid["position_m"] <= .015 and rigid["rotation_rad"] <= .10 and
                             branch <= self.cfg.max_ik_branch_step_rad)
                return errors, rigid, branch, qualified

            errors, rigid, branch, qualified = evaluate_pair(fit.x)
            original_fit = fit
            refit_attempts = []
            # The legacy answer always wins. The optional position-priority
            # search is only for an otherwise failed, held, non-retained place
            # query; all existing hard bounds and later path guards still run.
            use_refit = (not qualified and
                         any(v['position_m'] > completion_position_tolerance for v in errors.values()) and
                         getattr(self.cfg, 'completion_place_coupled_position_refit_enabled', False) and
                         self.cfg.acceptance_profile == 'completion_first' and
                         self.holding is not None and self.retained_contact is None and
                         self.fsm_state == State.PLACE_TRAY and not free_endpoint)
            if use_refit:
                for seed_name, qseed in (('original_fit', original_fit.x), ('independent_fit', initial)):
                    started = time.monotonic()
                    trial = least_squares(
                        lambda q: pair_residual(q, orientation_weight=.25),
                        np.clip(qseed, low, high), bounds=(low, high),
                        max_nfev=min(60, self.cfg.max_ik_iterations))
                    trial_errors, trial_rigid, trial_branch, trial_qualified = evaluate_pair(trial.x)
                    refit_attempts.append({
                        'seed': seed_name, 'orientation_weight': .25,
                        'max_nfev': min(60, self.cfg.max_ik_iterations),
                        'actual_nfev': int(getattr(trial, 'nfev', 0)),
                        'wall_seconds': float(time.monotonic()-started),
                        'tcp_errors': trial_errors, 'rigid_grasp_error': trial_rigid,
                        'max_branch_rad': trial_branch, 'qualified': trial_qualified})
                    if trial_qualified:
                        fit, errors, rigid, branch, qualified = (
                            trial, trial_errors, trial_rigid, trial_branch, True)
                        break
                if self.trace is not None:
                    self.trace.event('place_coupled_position_refit',
                                     planning_only=True, execution_confirmed=False,
                                     original_fit_qualified=False, attempts=refit_attempts,
                                     selected_seed=(refit_attempts[-1]['seed'] if qualified else None))
            multistart_attempts = []
            if not qualified and multistart_scope:
                # Complete only the unused members of each side's ORIGINAL
                # eight-seed list. A strict independent answer may have ended
                # its search early; no seed is fitted twice in this query.
                def side_candidates(state):
                    p, R = state['p'], state['R']
                    qids, siteid, q0 = state['qids'], state['siteid'], state['q0']
                    def residual(q):
                        d.qpos[qids] = q
                        self.mj.mj_kinematics(self.m, d)
                        self.mj.mj_comPos(self.m, d)
                        pos_error = p-d.site_xpos[siteid]
                        rot_error = Rotation.from_matrix(
                            R @ d.site_xmat[siteid].reshape(3, 3).T).as_rotvec()
                        return np.r_[state['position_weights']*pos_error,
                                     state['orientation_weight']*rot_error,
                                     state['regularization']*(q-q0)]
                    fitted = list(state['qualified'])
                    for seed in state['initials'][state['tested']:]:
                        trial = least_squares(residual,seed,
                            bounds=(state['lo'],state['hi']),
                            max_nfev=self.cfg.max_ik_iterations)
                        residual(trial.x)
                        pos_error=p-d.site_xpos[siteid]
                        rot_error=Rotation.from_matrix(
                            R @ d.site_xmat[siteid].reshape(3, 3).T).as_rotvec()
                        if (np.linalg.norm(pos_error)<=state['position_bound'] and
                                abs(pos_error[2])<=state['normal_bound'] and
                                np.linalg.norm(rot_error)<=state['rotation_bound'] and
                                np.max(np.abs(trial.x-q0))<=branch_limit):
                            fitted.append(trial.x.copy())
                    ordered=[state['selected'].copy()]
                    for candidate in fitted:
                        if all(np.max(np.abs(candidate-prior))>.01 for prior in ordered):
                            ordered.append(candidate.copy())
                            if len(ordered)==3:
                                break
                    return ordered

                left_choices=side_candidates(independent_searches['left'])
                right_choices=side_candidates(independent_searches['right'])
                combinations=((1,0),(0,1),(1,1),(2,0),(0,2),(2,1),(1,2),(2,2))
                for li,ri in combinations:
                    if li>=len(left_choices) or ri>=len(right_choices):
                        continue
                    seed_pair=np.r_[left_choices[li],right_choices[ri]]
                    started=time.monotonic()
                    trial=least_squares(
                        lambda q,center=seed_pair:pair_residual(q,reference_q=center),
                        np.clip(seed_pair,low,high),bounds=(low,high),
                        max_nfev=min(60,self.cfg.max_ik_iterations))
                    trial_errors,trial_rigid,trial_branch,trial_qualified=evaluate_pair(trial.x)
                    multistart_attempts.append({
                        'left_choice':li,'right_choice':ri,
                        'max_nfev':min(60,self.cfg.max_ik_iterations),
                        'actual_nfev':int(getattr(trial,'nfev',0)),
                        'wall_seconds':float(time.monotonic()-started),
                        'tcp_errors':trial_errors,'rigid_grasp_error':trial_rigid,
                        'max_branch_rad':trial_branch,'qualified':trial_qualified})
                    if trial_qualified:
                        fit,errors,rigid,branch,qualified=(
                            trial,trial_errors,trial_rigid,trial_branch,True)
                        break
                    if len(multistart_attempts)==4:
                        break
                if self.trace is not None:
                    self.trace.event('place_coupled_multistart',
                        planning_only=True,execution_confirmed=False,
                        original_fit_qualified=False,
                        independent_choices={'left':len(left_choices),'right':len(right_choices)},
                        attempts=multistart_attempts,
                        selected_pair=([multistart_attempts[-1]['left_choice'],
                                        multistart_attempts[-1]['right_choice']]
                                       if qualified else None))
            target[ARM_COLUMNS] = fit.x
            if not qualified:
                # Keep the original failure as primary when both bounded
                # retries fail, so a diagnostic solve cannot alter the reason.
                if refit_attempts or multistart_attempts:
                    errors, rigid, branch, _ = evaluate_pair(original_fit.x)
                raise Fault("coupled_ik_unreachable", {
                    "tcp_errors": errors, "rigid_grasp_error": rigid,
                    "max_branch_rad": branch,
                    **({'position_refit_attempts': refit_attempts} if refit_attempts else {}),
                    **({'coupled_multistart_attempts': multistart_attempts} if multistart_attempts else {}),
                }, recoverable=True)
            for side,value in errors.items():
                if value['position_m'] > position_tolerance or value['rotation_rad'] > orientation_tolerance:
                    policy_deviations.append({'stage': 'coupled', 'side': side,
                        'position_error_m': value['position_m'],
                        'strict_position_tolerance_m': float(position_tolerance),
                        'completion_position_tolerance_m': float(completion_position_tolerance),
                        'rotation_error_rad':value['rotation_rad'],
                        'strict_orientation_tolerance_rad':float(orientation_tolerance),
                        'completion_orientation_tolerance_rad':float(completion_orientation_tolerance)})
        self._record_held_ik_policy(policy_deviations,goals=goals,target=target)
        return target

    def _inverse_ratio(self, start, target, duration):
        """Conservative sampled reference-torque audit; rollout remains authoritative.

        Contacts on the free tray are not prescribed as fictitious constraints.
        This is NOT a certified whole-body inverse-dynamics controller.
        """
        peak = 0.
        for u in (.2, .5, .8):
            q = start+(target-start)*quintic(u)
            d = self._shadow(q)
            self.inverse.qpos[:] = d.qpos
            # The inverse audit sizes the arm reference.  Move free scene
            # objects out of contact so mj_inverse is not asked to satisfy an
            # inconsistent zero-acceleration tray/table constraint.  Payload
            # contact remains physical and force-limited in the live rollout.
            for name in self.g.ids:
                body_id = self.m.body(name).id
                joint = int(self.m.body_jntadr[body_id])
                adr = int(self.m.jnt_qposadr[joint])
                self.inverse.qpos[adr+2] += 10.
            self.inverse.qvel[:] = 0.
            self.inverse.qacc[:] = 0.
            ds = 30*u**2-60*u**3+30*u**4
            dds = 60*u-180*u**2+120*u**3
            self.inverse.qvel[self.dofs] = (target-start)[ARM_COLUMNS]*ds/duration
            self.inverse.qacc[self.dofs] = (target-start)[ARM_COLUMNS]*dds/duration**2
            self.mj.mj_forward(self.m, self.inverse)
            self.mj.mj_inverse(self.m, self.inverse)
            required = np.abs(self.inverse.qfrc_inverse[self.dofs])
            if not np.isfinite(required).all():
                raise Fault("nonfinite_inverse_dynamics")
            peak = max(peak, float(np.max(required/self.effort)))
            self.id_calls += 1
        return peak

    def joints(self, target, *, minimum_seconds=.1, wrist=False, audit=True):
        # Re-time from measured state.  Starting from the previous command can
        # hide servo lag and create a discontinuous recovery command.
        start = self.sim.state().astype(float)
        contact_columns = []
        if self.allowed_tray is not None:
            forces = self.observation()['gripper_contact_force'][self.allowed_tray]
            contact_columns = [col for col, force in zip((7, 15), forces) if force > .5]
        if self.holding is not None:
            contact_columns = [7, 15]
        if contact_columns:
            # Contact compliance intentionally leaves the measured finger
            # aperture above the close target.  Starting a fallback arm
            # segment from that measured aperture would command both grippers
            # open before closing them again, releasing the payload.
            start[contact_columns] = self.sim.target[contact_columns]
        target = np.asarray(target, float)
        if target.shape != (16,) or not np.isfinite(target).all():
            raise Fault("invalid_action_target")
        q = target[ARM_COLUMNS]
        low, high = self.m.jnt_range[self.jids].T
        lower, upper = low+self.cfg.joint_margin_rad, high-self.cfg.joint_margin_rad
        if np.any(q < lower-1e-6) or np.any(q > upper+1e-6) or np.any(target[[7, 15]] < -1e-6) or np.any(target[[7, 15]] > .1+1e-6):
            raise Fault("joint_or_gripper_limit", {"minimum_margin_rad": float(np.min(q-lower)),
                                                    "maximum_margin_rad": float(np.min(upper-q)),
                                                    "grippers_m": target[[7,15]].tolist()})
        target[ARM_COLUMNS] = np.clip(q, lower, upper)
        # target is stored as float32 between ticks; 0.1 is represented a few
        # nanometres above 0.1 after promotion to float64.
        target[[7, 15]] = np.clip(target[[7, 15]], 0., .1)
        samples = max(2, int(math.ceil(np.max(np.abs(target-start))/.025)))
        for u in np.linspace(0., 1., samples+1)[1:]:
            candidate = start+(target-start)*u
            if not self._target_valid(candidate, wrist=wrist):
                shadow = self._shadow(candidate)
                raise Fault("joint_path_collision_or_wrist", {
                    "path_fraction": float(u),
                    "collision": self.collision(shadow, planning=True),
                    "wrist_camera_front": bool(wrist and not self.camera_guard(shadow)),
                    "camera_metrics": self.camera_metrics(shadow) if wrist else None,
                    "rigid_grasp_error": self._rigid_grasp_error(shadow),
                }, recoverable=True)
        # The force-limited position servo has a small transient beyond the
        # analytic reference; retain time headroom instead of tolerating an
        # over-cap measured velocity.
        T = 1.12*minimum_duration(target-start, self.v, self.a, self.j, minimum_seconds)
        if audit and np.max(np.abs((target-start)[ARM_COLUMNS])) > .001:
            for retry in range(4):
                ratio = self._inverse_ratio(start, target, T)
                if ratio <= 1.+1e-6:
                    break
                T *= 1.5
                self.id_slowdowns += 1
            else:
                raise Fault("inverse_dynamics_infeasible", {"required_to_available_ratio": ratio}, recoverable=True)
        if T > self.cfg.max_phase_seconds:
            if getattr(self.cfg, 'approximate_completion_enabled', False):
                self._approximate_deviation('phase_duration_budget',
                    {'planned_s': float(T), 'configured_s': float(self.cfg.max_phase_seconds)})
            else:
                raise Fault("phase_duration_budget", T, recoverable=True)
        frames = max(2, math.ceil(T*self.cfg.fps))
        for frame in range(1, frames+1):
            self.sim.target = start+(target-start)*quintic(frame/frames)
            self.tick()
        tracking = np.max(np.abs(self.sim.state()[ARM_COLUMNS]-target[ARM_COLUMNS]))
        if tracking > self.cfg.joint_tracking_error_rad:
            ok = self.wait(self.cfg.tracking_error_grace_s, lambda _: np.max(np.abs(self.sim.state()[ARM_COLUMNS]-target[ARM_COLUMNS])) <= self.cfg.joint_tracking_error_rad)
            if not ok:
                raise Fault("joint_tracking_error", float(tracking))

    def close_grippers_on_contact(self, opening, sides=("left", "right")):
        """Force-limited contact close without a fictitious free-space endpoint.

        A normal joint path validator assumes the fingers reach the commanded
        aperture and therefore reports the intended finger/tray contact as a
        swept collision.  Here the position target is ramped continuously and
        MuJoCo contact stops the fingers physically.  ``tick`` remains the
        only motion sink and keeps all live collision, velocity and camera
        guards active.
        """
        if not 0. <= opening <= .1:
            raise Fault("invalid_gripper_contact_target", opening)
        mapping = {"left": 7, "right": 15}
        if not sides or any(side not in mapping for side in sides):
            raise Fault("invalid_gripper_contact_sides", list(sides))
        cols = np.array([mapping[side] for side in sides], int)
        start = self.sim.target[cols].astype(float).copy()
        target = np.full(len(cols), float(opening))
        delta = target-start
        # Use the configured velocity/acceleration/jerk limits with the same
        # servo headroom as ordinary joint motion.
        T = 1.10*minimum_duration(delta, self.v[cols], self.a[cols], self.j[cols], .3)
        frames = max(2, math.ceil(T*self.cfg.fps))
        for frame in range(1, frames+1):
            self.sim.target[cols] = start+delta*quintic(frame/frames)
            self.tick()

    def cartesian(self, goals: dict, *, speed=None, opening=None, wrist=False, preview_only=False,
                  start_from_command=False):
        """Preplan the whole Cartesian segment before the first live action."""
        speed = speed or self.cfg.transit_tcp_speed
        starts = {s: self.sim.tcp(s) for s in goals}
        if start_from_command:
            # Loaded endpoints preserve servo compression in their command
            # relationship. Interpolating from measured TCPs would introduce
            # an unintended detour immediately after the command's first knot.
            # Only private forward kinematics are read; live state is unchanged.
            commanded = self._shadow(self.sim.target)
            starts = {s: (commanded.site(s+'_tcp').xpos.copy(),
                          commanded.site(s+'_tcp').xmat.reshape(3, 3).copy()) for s in goals}
        distance = max(np.linalg.norm(goals[s][0]-starts[s][0]) for s in goals)
        angle = max(Rotation.from_matrix(goals[s][1]@starts[s][1].T).magnitude() for s in goals)
        knots = max(1, math.ceil(distance/.025), math.ceil(angle/.12))
        interpolation = {s: Slerp([0, 1], Rotation.from_matrix(np.stack([starts[s][1], goals[s][1]]))) for s in goals}
        previous = self.sim.target.copy()
        planned = []
        subdivisions = 0
        coupled_subdivisions = 0
        def advance(lo, u, seed, depth=0):
            nonlocal subdivisions, coupled_subdivisions
            request = {s: (starts[s][0]+u*(goals[s][0]-starts[s][0]), interpolation[s](u).as_matrix()) for s in goals}
            try:
                target = self.solve_pair(request, seed)
            except Fault as exc:
                # Refine a difficult interpolation interval in private planning
                # space; never relax branch/pose limits or execute a partial path.
                branch_retry = exc.code == 'ik_branch_jump'
                coupled_retry = (exc.code == 'coupled_ik_unreachable' and
                    getattr(self.cfg, 'completion_place_coupled_interval_subdivision_enabled', False) and
                    self.cfg.acceptance_profile == 'completion_first' and
                    self.holding is not None and self.retained_contact is None and
                    self.fsm_state == State.PLACE_TRAY and
                    all(side in goals for side in ('left', 'right')))
                if not (branch_retry or coupled_retry) or not exc.recoverable or depth >= 4:
                    raise
                if branch_retry:
                    subdivisions += 1
                else:
                    coupled_subdivisions += 1
                mid = (lo+u)/2
                middle = advance(lo, mid, seed, depth+1)
                return advance(mid, u, middle, depth+1)
            if opening is not None:
                for side, col in (("left", 7), ("right", 15)):
                    if side in goals:
                        target[col] = opening
            if not self._target_valid(target, wrist=wrist):
                shadow = self._shadow(target)
                raise Fault("cartesian_collision_or_wrist", {
                    "collision": self.collision(shadow, planning=True),
                    "wrist_camera_front": bool(wrist and not self.camera_guard(shadow)),
                    "camera_metrics": self.camera_metrics(shadow) if wrist else None,
                    "rigid_grasp_error": self._rigid_grasp_error(shadow),
                }, recoverable=True)
            planned.append(target)
            return target
        lo = 0.
        endpoint_fallback = False
        try:
            for u in np.linspace(0, 1, knots+1)[1:]:
                previous = advance(lo, u, previous)
                lo = u
        except Fault as original:
            if coupled_subdivisions and self.trace:
                self.trace.event('cartesian_coupled_interval_subdivision',
                    subdivisions=coupled_subdivisions,max_depth=4,
                    planned_knots=len(planned),qualified=False,
                    failure_reason=original.code,executed=False,
                    qualification='private_waypoints_only_no_physical_motion')
            eligible=(self.cfg.free_space_joint_shortcut and not wrist and
                      self.holding is None and self.retained_contact is None and
                      original.code in ('ik_unreachable','ik_branch_jump') and
                      original.recoverable and
                      np.max(self.observation()['gripper_contact_force']) <= .5)
            if not eligible:raise
            try:
                start=self.sim.state().astype(float)
                finish=self.solve_pair(goals,start,free_endpoint=True)
                if opening is not None:
                    for side,col in (('left',7),('right',15)):
                        if side in goals:finish[col]=opening
                count=max(32,math.ceil(float(np.max(abs(finish-start)))/.02))
                if not all(self._target_valid(start+(finish-start)*u)
                           for u in np.linspace(0,1,count+1)):
                    raise original
            except Fault:
                raise original
            planned=[finish]
            endpoint_fallback = True
            if self.trace:self.trace.event('free_space_endpoint_fallback',
                cartesian_failure=original.code,collision_samples=count+1,
                endpoint_max_joint_displacement_rad=float(np.max(abs(finish-start))))
        if subdivisions and self.trace:
            self.trace.event('cartesian_branch_subdivision',subdivisions=subdivisions,
                             max_depth=4,planned_knots=len(planned),executed=False)
        if coupled_subdivisions and self.trace:
            self.trace.event('cartesian_coupled_interval_subdivision',
                subdivisions=coupled_subdivisions,max_depth=4,
                planned_knots=len(planned),qualified=True,executed=False,
                qualification='complete_cartesian_waypoints_before_path_validation_and_motion')
        # One C2 path, not a stop-and-start at each 2.5 cm IK waypoint.
        if preview_only:
            return [self.sim.target.copy()]+planned
        if (self.cfg.free_space_joint_shortcut and not wrist and self.holding is None
                and np.max(self.observation()['gripper_contact_force']) <= .5):
            start=self.sim.state().astype(float)
            finish=planned[-1]
            count=max(32,math.ceil(float(np.max(abs(finish-start)))/.02))
            if all(self._target_valid(start+(finish-start)*u) for u in np.linspace(0,1,count+1)):
                if self.trace:self.trace.event('free_space_joint_shortcut',discarded_ik_waypoints=len(planned)-1)
                duration = max(.15, 1.875*distance/speed)
                # Optional normal-shortcut reference policy; hard measured
                # guards still run in joints/tick. An IK-failure endpoint
                # fallback always retains its existing extra headroom.
                original_minimum = duration
                headroom = endpoint_fallback or self.cfg.empty_arm_shortcut_headroom_enabled
                if headroom:
                    duration = max(duration, minimum_duration(
                        finish-start, self.v*.5, self.a*.5, self.j*.5))
                if self.trace:
                    self.trace.event('empty_arm_shortcut_timing',
                        endpoint_fallback=endpoint_fallback, headroom_applied=headroom,
                        normal_headroom_enabled=self.cfg.empty_arm_shortcut_headroom_enabled,
                        original_minimum_seconds=original_minimum, minimum_seconds=duration,
                        qualification='reference_timing_only_measured_guards_unchanged')
                self.joints(finish,minimum_seconds=duration)
                return
        self.follow_joint_path([self.sim.target.copy()]+planned,
                               minimum_seconds=max(.15, (1. if self.cfg.trajectory_mode=='cruise' else 1.875)*distance/speed), wrist=wrist)

    def follow_joint_path(self, points, *, minimum_seconds=.1, wrist=False):
        from .trajectory import TimedJointPath, BlendedJointPath, CruiseJointPath, entry_limit_envelope
        points = [np.asarray(point, float).copy() for point in points]
        if self.holding is not None:
            # The measured aperture is useful only to place the fingers in the
            # collision-checking shadow model.  It is not a command.  Keep the
            # live grasp target closed throughout every arm spline.
            for point in points:
                point[[7, 15]] = self.cfg.gripper_close_m
        path_type = {'blended':BlendedJointPath,'cruise':CruiseJointPath}.get(self.cfg.trajectory_mode,TimedJointPath)
        path = path_type(points, self.v, self.a, self.j, minimum_seconds)
        low, high = self.m.jnt_range[self.jids].T
        count = max(32, len(points)*12)
        path_low, path_high = low+self.cfg.joint_margin_rad, high-self.cfg.joint_margin_rad
        selected_mode = self.cfg.trajectory_mode
        if self.cfg.trajectory_mode in ('hybrid','cruise'):
            # An old command can be inside the physical limit but outside the
            # IK planning margin. Permit inward entry, never a new outward knot.
            try:
                path_low, path_high = entry_limit_envelope(
                    np.asarray(points)[:,ARM_COLUMNS], low, high, self.cfg.joint_margin_rad)
            except ValueError as exc:
                raise Fault('path_entry_joint_limit', str(exc), recoverable=True) from exc
            rejected = []
            for mode, candidate in (
                    ('cruise' if self.cfg.trajectory_mode=='cruise' else 'legacy', path),
                    ('blended', BlendedJointPath(points, self.v, self.a, self.j,
                        minimum_seconds*(1.875 if self.cfg.trajectory_mode=='cruise' else 1.)))):
                reason = self._path_rejection(candidate, count, path_low, path_high, wrist)
                if reason is None:
                    path, selected_mode = candidate, mode
                    if self.trace:
                        self.trace.event('continuous_path_selected', selected=mode, rejected=rejected,
                                         waypoints=len(points)-1)
                    break
                rejected.append(dict(mode=mode, **reason))
            else:
                if self.trace:
                    self.trace.event('joint_path_fallback', reason='both_continuous_paths_rejected',
                                     rejected=rejected, waypoints=len(points)-1)
                for target in points[1:]:
                    self.joints(target, minimum_seconds=max(.08, minimum_seconds*(1.875 if self.cfg.trajectory_mode=='cruise' else 1.)/(len(points)-1)), wrist=wrist)
                return
        if self.cfg.trajectory_mode == 'blended':
            try:
                path_low,path_high=entry_limit_envelope(np.asarray(points)[:,ARM_COLUMNS],low,high,self.cfg.joint_margin_rad)
            except ValueError as exc:
                raise Fault('blended_path_joint_limit',str(exc),recoverable=True) from exc
        # Cubic interpolation can overshoot its knots. Check the actual spline,
        # including collisions and the two-hand rigid-grasp relationship.
        spline_limit = False
        for u in np.linspace(0., 1., count+1):
            q = path.evaluate(u)[0]
            if np.any(q[ARM_COLUMNS] < path_low) or np.any(q[ARM_COLUMNS] > path_high) or np.any(q[[7,15]] < -1e-8) or np.any(q[[7,15]] > .1+1e-8):
                spline_limit = True
                break
            if not self._target_valid(q, wrist=wrist):
                shadow=self._shadow(q)
                raise Fault('spline_collision_or_wrist', {
                    'progress':float(u),'collision':self.collision(shadow,planning=True),
                    'wrist_camera_front':bool(wrist and not self.camera_guard(shadow)),
                    'rigid_grasp_error':self._rigid_grasp_error(shadow),
                }, recoverable=True)
        if spline_limit:
            if self.cfg.trajectory_mode == 'blended':
                raise Fault('blended_path_joint_limit', recoverable=True)
            # A cubic through safe IK knots may overshoot a joint bound.  A
            # sequence of zero-velocity/zero-acceleration quintics remains C2
            # at every knot and stays inside the convex joint interval.
            if self.trace:
                self.trace.event('joint_path_fallback', reason='cubic_spline_joint_limit',
                                 waypoints=len(points)-1)
            per_segment = max(.08, minimum_seconds/max(1, len(points)-1))
            for target in points[1:]:
                self.joints(target, minimum_seconds=per_segment, wrist=wrist)
            return
        T = path.duration
        for retry in range(4):
            ratio = 0.
            for u in np.linspace(.05, .95, 11):
                q, velocity, acceleration, _ = path.evaluate(u, T)
                d = self._shadow(q)
                self.inverse.qpos[:] = d.qpos
                for name in self.g.ids:
                    body_id = self.m.body(name).id
                    joint = int(self.m.body_jntadr[body_id])
                    adr = int(self.m.jnt_qposadr[joint])
                    self.inverse.qpos[adr+2] += 10.
                self.inverse.qvel[:] = 0.; self.inverse.qacc[:] = 0.
                self.inverse.qvel[self.dofs] = velocity[ARM_COLUMNS]
                self.inverse.qacc[self.dofs] = acceleration[ARM_COLUMNS]
                self.mj.mj_forward(self.m, self.inverse)
                self.mj.mj_inverse(self.m, self.inverse)
                required = np.abs(self.inverse.qfrc_inverse[self.dofs])
                if not np.isfinite(required).all(): raise Fault('nonfinite_inverse_dynamics')
                ratio = max(ratio, float(np.max(required/self.effort)))
                self.id_calls += 1
            if ratio <= 1.+1e-6: break
            T *= 1.5; self.id_slowdowns += 1
        else:
            raise Fault('inverse_dynamics_infeasible', {'ratio':ratio}, recoverable=True)
        if T > self.cfg.max_phase_seconds:
            if getattr(self.cfg, 'approximate_completion_enabled', False):
                self._approximate_deviation('phase_duration_budget',
                    {'planned_s': float(T), 'configured_s': float(self.cfg.max_phase_seconds)})
            else:
                raise Fault('phase_duration_budget', T, recoverable=True)
        frames = max(2, math.ceil(T*self.cfg.fps))
        if self.trace:
            self.trace.event('timed_joint_path', mode=selected_mode,
                             waypoints=len(points)-1, duration_s=frames/self.cfg.fps,
                             minimum_seconds=minimum_seconds, inverse_ratio=ratio)
        # Increasing to a whole frame count only reduces derivative maxima.
        for i in range(1, frames+1):
            self.sim.target = path.evaluate(i/frames, frames/self.cfg.fps)[0]
            self.tick()
        target = np.asarray(points[-1])
        if not self.wait(max(.15, self.cfg.tracking_error_grace_s),
                         lambda _: np.max(np.abs(self.sim.state()[ARM_COLUMNS]-target[ARM_COLUMNS])) <= self.cfg.joint_tracking_error_rad):
            raise Fault('joint_tracking_error')

    def _path_rejection(self, path, count, low, high, wrist):
        """Plan-only validation; the same physical guards still run every step."""
        for u in np.linspace(0., 1., count+1):
            q = path.evaluate(u)[0]
            if (np.any(q[ARM_COLUMNS] < low) or np.any(q[ARM_COLUMNS] > high)
                    or np.any(q[[7,15]] < -1e-8) or np.any(q[[7,15]] > .1+1e-8)):
                return {'reason':'joint_limit', 'progress':float(u)}
            if not self._target_valid(q, wrist=wrist):
                shadow = self._shadow(q)
                return {'reason':'collision_or_grasp_or_camera', 'progress':float(u),
                        'collision':self.collision(shadow, planning=True),
                        'wrist_camera_front':bool(wrist and not self.camera_guard(shadow)),
                        'rigid_grasp_error':self._rigid_grasp_error(shadow)}
        return None

    def audit_online_reference(self, q, velocity, acceleration):
        from .contracts import ARM_COLUMNS
        shadow=self._shadow(q)
        self.inverse.qpos[:]=shadow.qpos
        for name in self.g.ids:
            joint=int(self.m.body_jntadr[self.m.body(name).id])
            self.inverse.qpos[int(self.m.jnt_qposadr[joint])+2]+=10.
        self.inverse.qvel[:]=0.;self.inverse.qacc[:]=0.
        self.inverse.qvel[self.dofs]=np.asarray(velocity)[ARM_COLUMNS]
        self.inverse.qacc[self.dofs]=np.asarray(acceleration)[ARM_COLUMNS]
        self.mj.mj_forward(self.m,self.inverse);self.mj.mj_inverse(self.m,self.inverse)
        required=np.abs(self.inverse.qfrc_inverse[self.dofs]);self.id_calls+=1
        if not np.isfinite(required).all():raise Fault('nonfinite_inverse_dynamics')
        ratio=float(np.max(required/self.effort))
        if ratio>1.+1e-6:raise Fault('online_reference_effort_limit',ratio)

    def grasp_goals(self, center, face, *, rim_pair=None, x_offset=0., sides=("left", "right")):
        """Explicit pickup geometry; pushing retains its separate rim template."""
        if rim_pair is None:
            return self.rim_goals(center, face, x_offset=x_offset, sides=sides)
        if abs(float(wrap_angle(face-rim_pair.face))) > 1e-7:
            raise ValueError('Grasp face does not match the selected rim pair')
        return rim_pair.goals(center, x_offset=x_offset, sides=sides,
                              pitch_deg=self.cfg.rim_pitch_deg, roll_deg=self.cfg.rim_roll_deg)

    def rim_goals(self, center, face, *, x_offset=0., sides=("left", "right")):
        R = rz(face)
        t = self.allowed_tray
        half_width = self.g.sizes[t, 1]/2-self.cfg.rim_inset_m
        result = {}
        for side, sign in (("left", 1), ("right", -1)):
            if side in sides:
                # Direct-grasp profile measured from the validated 720p replay:
                # about -30 degree pitch with mirrored +/-10 degree roll.  Its
                # physical cameras are ~2 cm ahead and their optical axes point
                # outward (minimum validated dot product 0.844).
                orientation = R @ (Rotation.from_euler("y", self.cfg.rim_pitch_deg, degrees=True) *
                                   Rotation.from_euler("x", -self.cfg.rim_roll_deg*sign, degrees=True)).as_matrix()
                result[side] = (np.asarray(center)+R@np.array([x_offset, sign*half_width, 0.]), orientation)
        return result

    def remember_grasp(self, tray):
        b = self.d.body(self.g.ids[tray])
        T = _homogeneous(b.xpos, b.xmat.reshape(3, 3))
        self.grasp_rel = {s: np.linalg.inv(T)@_homogeneous(*self.sim.tcp(s)) for s in ("left", "right")}
        self.holding, self.lost_time = tray, 0.

    def object_motion(self, position, yaw=None, *, speed=None):
        if self.holding is None or not self.grasp_rel:
            raise Fault("object_motion_without_grasp")
        b = self.d.body(self.g.ids[self.holding])
        R = b.xmat.reshape(3, 3).copy() if yaw is None else rz(yaw)
        T = _homogeneous(position, R)
        goals = {s: ((T@rel)[:3, 3], (T@rel)[:3, :3]) for s, rel in self.grasp_rel.items()}
        # A rigid-object move must keep commanding the grasp aperture.  The IK
        # seed contains measured gripper openings because contact holds the
        # fingers apart; allowing those values into the joint spline briefly
        # reopens both grippers at every object-motion segment and drops the
        # tray.  Arm IK never owns the gripper columns.
        self.cartesian(goals, speed=speed or self.cfg.carry_tcp_speed,
                       opening=self.cfg.gripper_close_m, wrist=True)

    def _base_segment_valid(self, start, end):
        delta = np.asarray(end)-start
        delta[2] = wrap_angle(delta[2])
        count = max(2, math.ceil(np.linalg.norm(delta[:2])/.025), math.ceil(abs(delta[2])/.07))
        for u in np.linspace(0, 1, count+1):
            proposed = np.asarray(start)+u*delta
            if not self._target_valid(self.sim.target, proposed, wrist=self.holding is not None):
                return False
            if self.holding is not None and not self._measured_payload_clear(proposed):
                return False
        return True

    def _measured_payload_clear(self, proposed_base):
        """Second carry envelope accounts for measured load sag/rotation.

        Command-compliance transforms are still needed to check arm kinematics.
        They cannot substitute for the measured payload pose when navigating
        around stacked neighbours. Only self.shadow is changed here; live
        qpos, controls, contact forces and recorded evidence remain untouched.
        """
        body = self.d.body(self.g.ids[self.holding])
        position, rotation = carried_pose_at_base(
            body.xpos, body.xmat.reshape(3, 3), self.sim.base_state(), proposed_base)
        bid = self.m.body(self.g.ids[self.holding]).id
        adr = int(self.m.jnt_qposadr[int(self.m.body_jntadr[bid])])
        self.shadow.qpos[adr:adr+7] = np.r_[
            position, Rotation.from_matrix(rotation).as_quat()[[3, 0, 1, 2]]]
        self.mj.mj_forward(self.m, self.shadow)
        payload = np.flatnonzero(self.m.geom_bodyid == bid)
        obstacles = [i for i in range(self.m.ngeom)
                     if int(self.m.geom_bodyid[i]) not in self.robot_bodies
                     and int(self.m.geom_bodyid[i]) != bid]
        # Planning-only 15 mm clearance; live collision gates are unchanged.
        margin = .015
        for a in payload:
            for b in obstacles:
                if not ((self.m.geom_contype[a] & self.m.geom_conaffinity[b]) or
                        (self.m.geom_contype[b] & self.m.geom_conaffinity[a])):
                    continue
                if self.m.geom_type[b] != self.mj.mjtGeom.mjGEOM_PLANE and np.linalg.norm(self.shadow.geom_xpos[a]-self.shadow.geom_xpos[b]) > (
                        self.m.geom_rbound[a]+self.m.geom_rbound[b]+margin):
                    continue
                if self.mj.mj_geomDistance(self.m, self.shadow, int(a), b, margin, None) < margin:
                    return False
        return True

    # 仿真平面底盘目标；不可直接当作真机速度命令。
    def navigate(self, goal):
        start = self.sim.base_state().astype(float)
        goal = np.asarray(goal, float)
        gap = float(self.spec["aisle_gap_m"])
        bg = self.g.to_belt(np.r_[goal[:2], self.g.origin[2]])
        # All route selection below reads one immutable live state. Preserve
        # query order and exact values, reusing only identical segment checks.
        # This cache belongs to this call and is discarded BEFORE any tick;
        # subsequent navigation must recheck the new measured state/payload.
        segment_checks = {}
        def segment_valid(a, b):
            aa, bb = np.asarray(a), np.asarray(b)
            key = (aa.dtype.str, aa.shape, aa.tobytes(), bb.dtype.str, bb.shape, bb.tobytes())
            if key not in segment_checks:
                segment_checks[key] = self._base_segment_valid(a, b)
            return segment_checks[key]

        def routes_from(route_start):
            bs = self.g.to_belt(np.r_[route_start[:2], self.g.origin[2]])
            routes = [[goal]]
            for fraction in (.5, .35, .65):
                lane = -gap*fraction
                a = self.g.to_world([bs[0], lane, 0.])
                b = self.g.to_world([bg[0], lane, 0.])
                routes.append([np.r_[a[:2], route_start[2]],
                               np.r_[a[:2], goal[2]],
                               np.r_[b[:2], goal[2]], goal])
            # Fallback: turn beyond a belt end, preserving the source layout.
            for u in (-.8, self.g.belt_length+.8):
                a = self.g.to_world([bs[0], -gap/2, 0.])
                b = self.g.to_world([u, -gap/2, 0.])
                c = self.g.to_world([bg[0], -gap/2, 0.])
                routes.append([np.r_[a[:2], route_start[2]],
                               np.r_[b[:2], route_start[2]],
                               np.r_[b[:2], goal[2]],
                               np.r_[c[:2], goal[2]], goal])
            return routes

        candidates = routes_from(start)
        # When a freshly lifted payload is close to its source neighbour, an
        # in-place turn can be invalid even though translating away first
        # opens a safe route.  The previous implementation added this escape
        # only *after* a route had already passed validation, so it could never
        # rescue the exact case it was intended for.  Include the physical
        # escape in every candidate before validating complete segments.
        preferred_escape_candidates = []
        alternate_escape_candidates = []
        if self.holding is not None:
            poses = self.observation()['tray_pose']
            carried = poses[self.holding, :2]
            neighbours = [poses[i, :2] for i in range(len(poses)) if i != self.holding]
            directions = []
            if neighbours:
                nearest = min(neighbours, key=lambda p: np.linalg.norm(carried-p))
                away = carried-nearest
                if np.linalg.norm(away) > 1e-6:
                    directions.append(away/np.linalg.norm(away))
            # Privileged-state planner: try a deterministic ring around the
            # current base because avoiding the nearest tray alone can steer
            # the carried tray into a second neighbour.
            directions += [np.array([np.cos(a), np.sin(a)])
                           for a in np.linspace(-np.pi, np.pi, 16, endpoint=False)]
            seen = set()
            for direction_index, direction in enumerate(directions):
                key = tuple(np.round(direction, 5))
                if key in seen:
                    continue
                seen.add(key)
                escape = start.copy(); escape[:2] += .18*direction
                if segment_valid(start, escape):
                    expanded = [[escape]+route for route in routes_from(escape)]
                    if neighbours and direction_index == 0:
                        preferred_escape_candidates += expanded
                    else:
                        alternate_escape_candidates += expanded
        def cost(route):
            seq = [start]+route
            return sum(np.linalg.norm(y[:2]-x[:2])+.2*abs(wrap_angle(y[2]-x[2])) for x, y in zip(seq[:-1], seq[1:]))
        chosen = None
        # Prefer the clearance-restoring prefix while carrying.  A nominally
        # valid shorter shadow route can lose a few tenths of a millimetre to
        # physical pad compliance near the table; the escape restores measured
        # payload clearance before the turn without relaxing collision limits.
        ordered = (sorted(preferred_escape_candidates, key=cost)+
                   sorted(alternate_escape_candidates, key=cost)+
                   sorted(candidates, key=cost))
        for route in ordered:
            previous = start
            if all(segment_valid(a, b) for a, b in zip([start]+route[:-1], route)):
                chosen = route
                break
        if chosen is None:
            raise Fault("no_collision_free_base_route", recoverable=True)
        segment_checks.clear()
        del segment_valid
        for target in chosen:
            start = self.sim.base_state().astype(float)
            delta = target-start
            delta[2] = wrap_angle(delta[2])
            # Bound norm of translation, not just x and y separately.
            distance = np.linalg.norm(delta[:2])
            payload_scale = .8 if self.holding is not None else 1.
            T = max(minimum_duration(distance, self.cfg.base_speed*self.cfg.limit_fraction*.85*payload_scale, self.cfg.base_acceleration*self.cfg.limit_fraction*payload_scale, self.cfg.base_jerk*self.cfg.limit_fraction*payload_scale), minimum_duration(abs(delta[2]), self.cfg.base_yaw_speed*self.cfg.limit_fraction*.85*payload_scale, self.cfg.base_yaw_acceleration*self.cfg.limit_fraction*payload_scale, self.cfg.base_yaw_jerk*self.cfg.limit_fraction*payload_scale))
            base_path = None
            if self.cfg.base_cruise and max(distance, abs(delta[2])) > 1e-8:
                from .trajectory import CruiseJointPath
                scale=self.cfg.limit_fraction*payload_scale
                base_path=CruiseJointPath([[0.,0.],[distance,abs(delta[2])]],
                    np.array([self.cfg.base_speed,self.cfg.base_yaw_speed])*scale*.85,
                    np.array([self.cfg.base_acceleration,self.cfg.base_yaw_acceleration])*scale,
                    np.array([self.cfg.base_jerk,self.cfg.base_yaw_jerk])*scale,
                    minimum_seconds=.05)
                T=base_path.duration
            if self.trace:
                self.trace.event('base_timed_segment',duration_s=math.ceil(T*self.cfg.fps)/self.cfg.fps,
                                 distance_m=float(distance),angle_rad=float(abs(delta[2])),
                                 mode='cruise' if base_path is not None else 'quintic')
            for i in range(1, max(2, math.ceil(T*self.cfg.fps))+1):
                u = i/max(2, math.ceil(T*self.cfg.fps))
                progress=quintic(u)
                if base_path is not None:
                    index=0 if distance>1e-8 else 1
                    progress=base_path.evaluate(u)[0][index]/(distance if index==0 else abs(delta[2]))
                self.sim.set_base_world_target(start+delta*progress)
                self.tick()
            def arrived(_):
                e = target-self.sim.base_state()
                return np.linalg.norm(e[:2]) < .015 and abs(wrap_angle(e[2])) < .03
            if not self.wait(1., arrived, .1):
                raise Fault("base_tracking_error", recoverable=True)

    def close(self):
        self.sim.close()




