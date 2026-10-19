"""Fresh-state simulation expert for DAgger; never rolls back the live learner."""
from __future__ import annotations
import copy
import hashlib
import json
from pathlib import Path
import time
import numpy as np
from .dagger import ExpertLabel, state_digest


class TeacherError(RuntimeError):
    pass


RUNTIME_CONTEXT = (
    "allowed_tray", "holding", "grasp_rel", "retained_contact", "initial_bottom",
    "retained_support_missing_since", "retained_support_missing_step",
    "physics_step_count", "physics_clock_origin_time", "physics_clock_timestep",
    "fsm_state", "phase", "target_slot", "recovery", "steps", "physical_time_start",
    "previous_warning", "home", "tucked", "lost_time", "strict_runtime_passed",
    "soft_guard_violation_count", "soft_guard_violation_by_code", "soft_guard_violation_maxima",
    "soft_guard_last_step_by_code", "completion_speed_since_step", "_handoff_clearance_monitor",
    "primitive_lift_xy_shift_m", "primitive_lift_start_bottom", "_action_deadline",
    "primitive_deadline_step", "_approximate_deadline_extended", "_approximate_extended_deadline_step",
)
MACHINE_CONTEXT = ("pending_grasp_contact", "grasp_rim_pair", "verified_final_trays",
                   "operations", "recovery_used", "attempt", "transition_sequence")


def _file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def model_fingerprint(runtime):
    """Includes resolved model physics, so same XML with changed assets rejects."""
    model = runtime.m
    arrays = {}
    for field in ("body_mass", "body_inertia", "geom_size", "geom_friction", "geom_solref",
                  "geom_solimp", "dof_damping", "actuator_gainprm", "actuator_biasprm",
                  "actuator_forcerange", "actuator_gear", "jnt_range", "jnt_limited", "body_pos",
                  "body_quat", "geom_pos", "geom_quat", "geom_contype", "geom_conaffinity",
                  "mesh_vert", "mesh_face", "qpos0"):
        if hasattr(model, field):
            arrays[field] = np.asarray(getattr(model, field))
    digest = hashlib.sha256()
    digest.update(str((model.nq, model.nv, model.nu, float(model.opt.timestep))).encode())
    digest.update(str(getattr(runtime.mj, "__version__", "unknown")).encode())
    if hasattr(model.opt, "gravity"):
        digest.update(np.asarray(model.opt.gravity).tobytes())
    for key, value in sorted(arrays.items()):
        digest.update(key.encode()); digest.update(str(value.shape).encode()); digest.update(value.tobytes())
    return digest.hexdigest()


class SimulationExpert:
    def __init__(self, runtime, directory, *, machine=None, runtime_factory=None, machine_factory=None, private_contact_escape=False,
                 private_escape_measured_tracking=False):
        if type(private_contact_escape) is not bool:raise TeacherError("teacher_escape_gate_requires_bool")
        self.private_contact_escape = private_contact_escape
        if type(private_escape_measured_tracking) is not bool:raise TeacherError('teacher_escape_measured_tracking_requires_bool')
        if private_escape_measured_tracking and not private_contact_escape:raise TeacherError('teacher_escape_measured_tracking_requires_private_escape')
        self.private_escape_measured_tracking=private_escape_measured_tracking
        self.runtime, self.machine = runtime, machine
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=False)
        self.runtime_factory, self.machine_factory = runtime_factory, machine_factory
        self.xml_hash = _file_hash(runtime.sim.scene)
        self.physics_hash = model_fingerprint(runtime)
        self.config_hash = hashlib.sha256(json.dumps(runtime.cfg.dump(), sort_keys=True).encode()).hexdigest()
        self.sequence = 0

    def capture(self):
        r = self.runtime
        integration = np.empty(r.integration_size, dtype=np.float64)
        r.mj.mj_getState(r.m, r.d, integration, r.integration_spec)
        return {"qpos": r.d.qpos.copy(), "qvel": r.d.qvel.copy(), "ctrl": r.d.ctrl.copy(),
                "time": np.asarray(r.d.time, dtype=np.float64), "act": r.d.act.copy(),
                "qacc_warmstart": r.d.qacc_warmstart.copy(), "integration_state": integration,
                "joint_target": r.sim.target.copy(), "base_target": r.sim.base_target.copy()}

    def _restore(self, clone, snapshot):
        if _file_hash(clone.sim.scene) != self.xml_hash or model_fingerprint(clone) != self.physics_hash:
            raise TeacherError("teacher_physics_model_mismatch")
        config_hash = hashlib.sha256(json.dumps(clone.cfg.dump(), sort_keys=True).encode()).hexdigest()
        if config_hash != self.config_hash:
            raise TeacherError("teacher_config_mismatch")
        integration = np.asarray(snapshot["integration_state"], dtype=np.float64)
        if integration.shape != (clone.integration_size,):
            raise TeacherError("teacher_integration_state_shape_mismatch")
        clone.mj.mj_setState(clone.m, clone.d, integration, clone.integration_spec)
        clone.mj.mj_forward(clone.m, clone.d)
        # Forward recomputes derived contacts. Preserve the supplied warm start,
        # activations and controls before the first NEW physical interval.
        for field in ("qpos", "qvel", "ctrl", "act", "qacc_warmstart"):
            value = np.asarray(snapshot[field])
            target = getattr(clone.d, field)
            if value.shape != target.shape:
                raise TeacherError("teacher_snapshot_shape_mismatch:" + field)
            target[:] = value
        clone.d.time = float(snapshot["time"])
        clone.sim.target = np.asarray(snapshot["joint_target"]).copy()
        clone.sim.base_target = np.asarray(snapshot["base_target"]).copy()
        for field in RUNTIME_CONTEXT:
            if hasattr(self.runtime, field):
                setattr(clone, field, copy.deepcopy(getattr(self.runtime, field)))
        clone.wall_start = time.monotonic()

    @staticmethod
    def measured_holding_qualification(runtime, tray):
        e=runtime.observation()
        forces=np.asarray(e['gripper_contact_force'][tray],dtype=float)
        clearance=float(e['min_z'][tray]-runtime.initial_bottom[tray])
        support=int(e['support_contact'][tray])
        report=dict(tray=int(tray),declared_holding=runtime.holding,
                    bilateral_force_n=forces.tolist(),clearance_m=clearance,support_contact=support,
                    sim_time=float(runtime.d.time),physics_step_count=int(runtime.steps),
                    verified=bool(forces.shape==(2,) and np.isfinite(forces).all() and
                                  np.isfinite(clearance) and (forces>.5).all() and
                                  clearance>=float(runtime.cfg.criteria.lifted_m) and support==0))
        return report

    def _dispatch(self, machine, operation, skill):
        if skill == "initialize_posture":
            machine.r.joints(machine.r.tucked, minimum_seconds=.5)
        elif skill == "navigate_to_tray":
            machine.prepare_pick(operation.tray, operation.slot)
        elif skill == "grasp_lift_tray":
            r = machine.r
            if r.holding == operation.tray:
                from ..airport_fsm.primitives import lift
                lift(machine, operation.tray)
            elif r.holding is not None:
                raise TeacherError("teacher_holding_different_tray")
            else:
                # Learner navigation does not certify an IK face/rim proposal.
                # Replan and physically realign from this exact visited state.
                face, rim_x = machine.prepare_pick(operation.tray, operation.slot)
                machine.grasp(operation.tray, face, rim_x)
        elif skill == "carry_tray":
            if machine.r.holding != operation.tray or machine.r.grasp_rel is None:
                raise TeacherError("teacher_carry_requires_measured_grasp")
            measured=self.measured_holding_qualification(machine.r,operation.tray)
            if not measured["verified"]:raise TeacherError("teacher_stale_holding:"+json.dumps(measured))
            machine.carry_place(operation)
        elif skill == "place_release_tray":
            if machine.r.holding != operation.tray or machine.r.grasp_rel is None:
                raise TeacherError("teacher_place_requires_measured_grasp")
            measured=self.measured_holding_qualification(machine.r,operation.tray)
            if not measured["verified"]:raise TeacherError("teacher_stale_holding:"+json.dumps(measured))
            from ..airport_fsm.primitives import place
            place(machine, operation, machine._place_location(operation))
        elif skill == "push_adjust_tray":
            if machine.r.holding is not None:
                raise TeacherError("teacher_push_cannot_start_while_carrying")
            retained = machine.r.retained_contact
            if retained is not None and retained[0] != operation.tray:
                raise TeacherError("teacher_retained_contact_wrong_tray")
            machine.push(operation, retained_side=None if retained is None else retained[1])
        else:
            raise TeacherError("teacher_unsupported_skill:" + str(skill))

    def label(self, operation, skill, snapshot, horizon):
        try:
            return self._label_once(operation,skill,snapshot,horizon)
        except Exception as original:
            if (not self.private_contact_escape or skill!='grasp_lift_tray'
                    or self.runtime.holding is not None or 'joint_path_collision' not in str(original)):
                raise
            from .contact_escape import RuntimeEscapeAdapter
            try:candidates=RuntimeEscapeAdapter(self.runtime).candidates()
            except Exception as rejected:
                raise TeacherError('teacher_private_escape_initial_state_rejected:'+str(rejected)) from original
            failures=[]
            for candidate in candidates:
                try:return self._label_once(operation,skill,snapshot,horizon,escape_target=candidate)
                except Exception as rejected:failures.append(repr(rejected))
            raise TeacherError('teacher_all_private_escape_candidates_rejected:'+json.dumps(failures)) from original

    def _label_once(self, operation, skill, snapshot, horizon, *, escape_target=None):
        if type(horizon) is not int or horizon <= 0:
            raise TeacherError("teacher_invalid_horizon")
        before = state_digest(snapshot)
        if before != state_digest(self.capture()):
            raise TeacherError("teacher_stale_learner_state")
        if _file_hash(self.runtime.sim.scene) != self.xml_hash or model_fingerprint(self.runtime) != self.physics_hash:
            raise TeacherError("teacher_live_physics_changed")
        directory = self.directory / f"expert_{self.sequence:06d}"
        self.sequence += 1
        clone, machine = None, None
        metadata = {"status": "planning", "start_state_sha256": before, "skill": skill,
                    "scene_xml_sha256": self.xml_hash, "physics_sha256": self.physics_hash,
                    "config_sha256": self.config_hash, "source": "simulation/program_generated",
                    "initial_physics_time":float(snapshot['time']),
                    "initial_runtime_context":dict(holding=self.runtime.holding,allowed_tray=self.runtime.allowed_tray,
                        phase=str(self.runtime.phase),fsm_state=str(self.runtime.fsm_state),
                        steps=int(self.runtime.steps),retained_contact=repr(self.runtime.retained_contact))}
        try:
            if self.runtime_factory is None:
                from ..airport_fsm.runtime import Runtime
                factory = Runtime
            else:
                factory = self.runtime_factory
            clone = factory(copy.deepcopy(self.runtime.spec), self.runtime.sim.scene, copy.deepcopy(self.runtime.cfg))
            self._restore(clone, snapshot)
            if self.machine_factory is None:
                from ..airport_fsm.machine import Machine
                machine_factory = Machine
            else:
                machine_factory = self.machine_factory
            machine = machine_factory(clone, directory, attempt=getattr(self.machine, "attempt", 0),
                                      seed=int(self.runtime.spec["seed"]))
            for field in MACHINE_CONTEXT:
                if self.machine is not None and hasattr(self.machine, field):
                    setattr(machine, field, copy.deepcopy(getattr(self.machine, field)))
            if self.machine is not None and hasattr(self.machine, "rng"):
                machine.rng.bit_generator.state = copy.deepcopy(self.machine.rng.bit_generator.state)
            if self.machine is not None and hasattr(self.machine, "scheduler"):
                for field in ("mapping", "reservation_plan"):
                    if hasattr(self.machine.scheduler, field):
                        setattr(machine.scheduler, field, copy.deepcopy(getattr(self.machine.scheduler, field)))
            # Machine constructor emits a SEARCH transition; restore the learner
            # context after construction rather than changing its live FSM.
            for field in ("fsm_state", "phase", "allowed_tray", "target_slot"):
                setattr(clone, field, copy.deepcopy(getattr(self.runtime, field)))
            if skill in ('carry_tray','place_release_tray') and clone.holding is not None:
                metadata['measured_holding_qualification']=self.measured_holding_qualification(clone,operation.tray)
            if escape_target is not None:
                metadata['private_contact_escape']=dict(status='screening',target_world=np.asarray(escape_target).tolist(),
                    learner_state_sha256=before,full_task_success_claimed=False)
                from .contact_escape import RuntimeEscapeAdapter
                kwargs={'measured_tracking':True} if getattr(self,'private_escape_measured_tracking',False) else {}
                RuntimeEscapeAdapter(clone,**kwargs).execute(escape_target,audit=metadata['private_contact_escape'])
            self._dispatch(machine, copy.deepcopy(operation), skill)
            rows = machine.log.arrays(include={"qpos", "qvel", "action", "base_action", "transition_completed"})
            original_frames = len(rows.get("action", []))
            metadata.update(skill_expert_frames=original_frames, terminal_hold_frames=0)
            # A successful short initialization can end before the model's H.
            # Execute and record real guarded physics at the completed expert
            # target. Never repeat arrays, synthesize states or pad a label.
            if skill == "initialize_posture" and 0 < original_frames < horizon:
                if (not np.asarray(rows.get("transition_completed", []), dtype=bool).all()
                        or not np.isfinite(rows["qpos"]).all() or not np.isfinite(rows["qvel"]).all()
                        or not np.array_equal(np.asarray(clone.sim.target, dtype=np.float32),
                                              np.asarray(clone.tucked, dtype=np.float32))):
                    raise TeacherError("teacher_invalid_initialization_terminal_target")
                metadata["terminal_hold_start_sim_time"] = float(clone.d.time)
                for _ in range(horizon - original_frames):
                    previous_time, previous_step = float(clone.d.time), int(clone.steps)
                    clone.tick()
                    if float(clone.d.time) <= previous_time or int(clone.steps) <= previous_step:
                        raise TeacherError("teacher_terminal_hold_did_not_advance_physics")
                    metadata["terminal_hold_frames"] += 1
                metadata["terminal_hold_end_sim_time"] = float(clone.d.time)
                rows = machine.log.arrays(include={"qpos", "qvel", "action", "base_action", "transition_completed"})
                if len(rows.get("action", [])) != horizon:
                    raise TeacherError("teacher_terminal_hold_missing_physical_records")
            completed = np.asarray(rows.get("transition_completed", []), dtype=bool)
            actions = np.asarray(rows.get("action", []))
            base = np.asarray(rows.get("base_action", []))
            if (len(actions) == 0 or actions.ndim != 2 or actions.shape[1] != 16
                    or base.shape != (len(actions), 3) or completed.shape != (len(actions),)
                    or not completed.all() or not np.isfinite(actions).all() or not np.isfinite(base).all()
                    or not np.isfinite(rows["qpos"]).all() or not np.isfinite(rows["qvel"]).all()
                    or not np.array_equal(rows["qpos"][0], snapshot["qpos"])
                    or not np.array_equal(rows["qvel"][0], snapshot["qvel"])):
                raise TeacherError("teacher_incomplete_or_invalid_physical_transition")
            machine.log.close()
            artifact = directory / "trace.h5"
            metadata.update(status="label_verified", teacher_trace_sha256=_file_hash(artifact),
                            total_expert_frames=len(actions), labeled_frames=min(horizon, len(actions)))
            (directory / "teacher_metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
            return ExpertLabel(before, np.concatenate((actions, base), axis=1)[:horizon].astype(np.float32),
                               "simulation_expert:" + self.config_hash,
                               replanned_from_learner_state=True, planning_verified=True,
                               teacher_artifact=str(artifact))
        except BaseException as exc:
            if machine is not None:
                machine.log.close()
            directory.mkdir(parents=True, exist_ok=True)
            metadata.update(status="label_rejected", error=repr(exc))
            (directory / "teacher_metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
            raise
        finally:
            if clone is not None:
                clone.close()
            if before != state_digest(self.capture()):
                raise TeacherError("teacher_modified_live_learner_state")

    @staticmethod
    def verify_label(snapshot, label):
        if state_digest(snapshot) != label.start_state_sha256:
            return False
        artifact = Path(label.teacher_artifact)
        try:
            metadata = json.loads((artifact.parent / "teacher_metadata.json").read_text(encoding="utf-8"))
            valid = (metadata["status"] == "label_verified"
                    and metadata["start_state_sha256"] == label.start_state_sha256
                    and metadata["teacher_trace_sha256"] == _file_hash(artifact))
            if not valid:
                return False
            import h5py
            with h5py.File(artifact, "r") as trace:
                n = len(label.actions)
                actions = np.concatenate((trace["action"][:n], trace["base_action"][:n]), axis=1).astype(np.float32)
                return (n > 0 and np.array_equal(actions, label.actions)
                        and np.array_equal(trace["qpos"][0], snapshot["qpos"])
                        and np.array_equal(trace["qvel"][0], snapshot["qvel"])
                        and bool(np.asarray(trace["transition_completed"]).all()))
        except (OSError, KeyError, ValueError):
            return False
