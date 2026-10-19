"""Stage-boundary checkpoints for separate diagnostic processes, never live rewind.

Port of the EmbodiedSWE workflow, with MuJoCo INTEGRATION state and controller
context instead of Isaac tensors. JSON/NPZ only; no pickle or arbitrary objects.
"""
from pathlib import Path
from enum import Enum
import time
import json
import numpy as np

from .common import read, name, fingerprint, source_stamp, versions, digest_file
from ..airport_fsm.contracts import atomic_json, State
from ..airport_fsm.rim_affordances import RimPair


def encode(value):
    if isinstance(value, RimPair):
        return {'__rim_pair__': {'axis': value.axis, 'face': float(value.face),
                'half_span': float(value.half_span), 'edge_half_length': float(value.edge_half_length)}}
    if isinstance(value, np.ndarray):
        return {"__array__": value.tolist(), "dtype": str(value.dtype)}
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, tuple):
        return {"__tuple__": [encode(v) for v in value]}
    if isinstance(value, set):
        return {"__set__": [encode(v) for v in sorted(value)]}
    if isinstance(value, list):
        return [encode(v) for v in value]
    if isinstance(value, dict):
        return {str(k): encode(v) for k, v in value.items()}
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    raise TypeError(f"unsupported_checkpoint_value: {type(value).__name__}")


def decode(value):
    if isinstance(value, list):
        return [decode(v) for v in value]
    if isinstance(value, dict):
        if '__rim_pair__' in value:
            return RimPair(**value['__rim_pair__'])
        if "__array__" in value:
            return np.asarray(value["__array__"], dtype=value["dtype"])
        if "__tuple__" in value:
            return tuple(decode(v) for v in value["__tuple__"])
        if "__set__" in value:
            return set(decode(v) for v in value["__set__"])
        return {k: decode(v) for k, v in value.items()}
    return value


COMPLETION_RUNTIME_FIELDS = (
    'strict_runtime_passed', 'soft_guard_violation_count', 'soft_guard_violation_by_code',
    'soft_guard_violation_maxima', 'soft_guard_last_step_by_code', 'completion_speed_since_step',
)


def validate_completion_context(cfg, context):
    if getattr(cfg, 'acceptance_profile', 'strict') != 'completion_first':
        return
    missing = sorted(set(COMPLETION_RUNTIME_FIELDS) - context.keys())
    if missing:
        raise ValueError('checkpoint_completion_context_missing: ' + ','.join(missing))
    step = context.get('completion_speed_since_step')
    count = context.get('physics_step_count')
    if step is not None and (type(step) is not int or type(count) is not int or not 0 <= step <= count):
        raise ValueError('checkpoint_completion_speed_clock_invalid')
    if type(context['strict_runtime_passed']) is not bool:
        raise ValueError('checkpoint_completion_strict_flag_invalid')
    violations = context['soft_guard_violation_count']
    if type(violations) is not int or violations < 0:
        raise ValueError('checkpoint_completion_violation_count_invalid')
    if violations and context['strict_runtime_passed']:
        raise ValueError('checkpoint_completion_strict_flag_invalid')


RUNTIME_FIELDS = (
    "allowed_tray", "holding", "retained_contact", "retained_support_missing_since",
    "grasp_rel", "lost_time", "fsm_state", "phase", "target_slot", "recovery",
    "steps", "peak_power", "id_calls", "id_slowdowns", "action_frames",
    "physical_time_start", "previous_warning", "initial_bottom", "primitive_deadline_step",
    "primitive_lift_xy_shift_m",
    "physics_step_count", "physics_clock_origin_time", "physics_clock_timestep",
    "retained_support_missing_step",
) + COMPLETION_RUNTIME_FIELDS
MACHINE_FIELDS = ("seed", "attempt", "recovery_used", "operations", "pending_grasp_contact",
                  "transition_sequence", "reach_pull_used", "verified_final_trays", "grasp_rim_pair", "stage_context",
                  "_physical_preview_sequence")


class CheckpointTree:
    def __init__(self, machine, root):
        self.machine = machine
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def plan(self, stages):
        if not stages or len(stages) != len(set(stages)):
            raise ValueError("checkpoint_requires_unique_stages")
        for stage in stages:
            name(stage)
        path = self.root / "plan.json"
        if path.exists() and read(path) != stages:
            raise ValueError("checkpoint_plan_changed")
        atomic_json(path, stages)

    def identity(self):
        r = self.machine.r
        return {"spec": fingerprint(r.spec), "xml": digest_file(r.sim.scene),
                "config": fingerprint(r.cfg.dump()), "code": fingerprint(source_stamp()),
                "versions": versions(), "dependencies": getattr(r, "experiment_dependencies", None)}

    def save(self, stage, check, *, parent=None):
        name(stage)
        if stage not in read(self.root / "plan.json"):
            raise ValueError("undeclared_checkpoint_stage")
        if parent is not None:
            name(parent)
            if not (self.root / parent / "metadata.json").is_file():
                raise ValueError("checkpoint_parent_missing")
        m = self.machine
        r = m.r
        if getattr(m, '_physical_preview_active', False):
            raise ValueError('checkpoint_inside_physical_preview')
        if not check(m):
            raise ValueError("checkpoint_stage_check_failed")
        if getattr(r.cfg, 'retained_support_integer_clock_enabled', False):
            from ..airport_fsm.runtime import Runtime
            Runtime.validate_retained_clock_state(r)
        validate_completion_context(r.cfg, {k: getattr(r, k) for k in RUNTIME_FIELDS if hasattr(r, k)})
        from ..airport_fsm.reservation_plan import validate_context
        validate_context(getattr(m,'g',None),m.scheduler.mapping,getattr(m.scheduler,'reservation_plan',None),r.cfg)
        r.guard()
        if getattr(r, "primitive_deadline_step", None) is not None:
            raise ValueError("checkpoint_inside_primitive")
        if np.max(np.abs(r.d.qvel)) > .05:
            raise ValueError("checkpoint_not_settled")
        state = np.empty(r.integration_size)
        r.mj.mj_getState(r.m, r.d, state, r.integration_spec)
        context = {
            "runtime": {k: encode(getattr(r, k)) for k in RUNTIME_FIELDS if hasattr(r, k)},
            "machine": {k: encode(getattr(m, k)) for k in MACHINE_FIELDS if hasattr(m, k)},
            "target": encode(r.sim.target), "base_target": encode(r.sim.base_target),
            "rng": encode(m.rng.bit_generator.state), "mapping": encode(m.scheduler.mapping),
            "reservation_plan": encode(getattr(m.scheduler,'reservation_plan',None)),
            "elapsed_wall_s": time.monotonic() - r.wall_start,
        }
        directory = self.root / stage
        directory.mkdir(exist_ok=False)
        np.savez_compressed(directory / "state.npz", integration=state)
        atomic_json(directory / "metadata.json", {
            "schema": "mujoco_experiment_checkpoint/1", "identity": self.identity(),
            "stage": stage, "parent": parent, "context": context,
            "state_sha256": digest_file(directory / "state.npz"),
            "origin": m.experiment_origin, "experiment": m.experiment,
            "source_trace": str(m.directory.resolve()), "diagnostic_only": True,
        })
        return directory

    def restore(self, directory):
        """Only at the start of a NEW diagnostic run. Not a continuation of Machine.run()."""
        m = self.machine
        r = m.r
        if r.steps or m.log.count or getattr(m, "checkpoint_restored", False):
            raise ValueError("checkpoint_restore_requires_fresh_diagnostic_runtime")
        directory = Path(directory)
        record = read(directory / "metadata.json")
        if record["identity"] != self.identity():
            raise ValueError("checkpoint_identity_mismatch")
        if record["state_sha256"] != digest_file(directory / "state.npz"):
            raise ValueError("checkpoint_state_changed")
        with np.load(directory / "state.npz", allow_pickle=False) as data:
            state = data["integration"].copy()
        if state.shape != (r.integration_size,) or not np.isfinite(state).all():
            raise ValueError("checkpoint_state_invalid")
        context = record["context"]
        from ..airport_fsm.reservation_plan import validate_context
        reservation_plan=decode(context.get('reservation_plan'))
        validate_context(getattr(m,'g',None),decode(context['mapping']),reservation_plan,r.cfg)
        validate_completion_context(r.cfg, {k: decode(v) for k, v in context['runtime'].items()})
        if getattr(r.cfg, 'retained_support_integer_clock_enabled', False):
            required = {'physics_step_count', 'physics_clock_origin_time',
                        'physics_clock_timestep', 'retained_support_missing_step',
                        'retained_support_missing_since'}
            missing = sorted(required - context['runtime'].keys())
            if missing:
                # Never infer a new grace origin from old floating timestamps.
                raise ValueError('checkpoint_integer_clock_context_missing: '+','.join(missing))
            # Validate an independent decoded state before touching the destination.
            # Partial failed control ticks may contain more physics steps than
            # steps*nstep; the explicit counter, not that product, is authoritative.
            from ..airport_fsm.runtime import Runtime
            clock_probe = Runtime.__new__(Runtime)
            clock_probe.cfg, clock_probe.m = r.cfg, r.m
            clock_probe.d = r.mj.MjData(r.m)
            r.mj.mj_setState(r.m, clock_probe.d, state, r.integration_spec)
            for field in required:
                setattr(clock_probe, field, decode(context['runtime'][field]))
            clock_probe.validate_retained_clock_state()
        if context['machine'].get('_physical_preview_active', False):
            raise ValueError('checkpoint_inside_physical_preview')
        r.mj.mj_setState(r.m, r.d, state, r.integration_spec)
        r.mj.mj_forward(r.m, r.d)
        # forward() may rewrite warmstart; preserve the exact integration state after it.
        r.mj.mj_setState(r.m, r.d, state, r.integration_spec)
        for k, v in context["runtime"].items():
            setattr(r, k, State(v) if k == "fsm_state" else decode(v))
        for k, v in context["machine"].items():
            setattr(m, k, decode(v))
        m._physical_preview_active = False
        r.sim.target = decode(context["target"])
        r.sim.base_target = decode(context["base_target"])
        r.sim.workspace_rotation = r.d.body("base_link").xmat.reshape(3, 3).copy()
        from ..core import XR_TO_ROBOT
        r.sim.xr_to_world = r.sim.workspace_rotation @ XR_TO_ROBOT
        m.rng.bit_generator.state = decode(context["rng"])
        m.scheduler.mapping = decode(context["mapping"])
        m.scheduler.reservation_plan = reservation_plan
        r.wall_start = time.monotonic() - context["elapsed_wall_s"]
        m.experiment_origin = "checkpoint:" + str(directory.resolve())
        m.checkpoint_restored = True
        metadata = json.loads(m.log.file.attrs["metadata_json"])
        metadata.update(origin=m.experiment_origin, diagnostic_only=True, training_candidate=False,
                        initial_time=float(r.d.time), initial_step=r.steps)
        m.log.file.attrs["metadata_json"] = json.dumps(metadata)
        r.guard()
        m.log.event("diagnostic_checkpoint_restored", origin=m.experiment_origin,
                    source_trace=record["source_trace"], diagnostic_only=True)
        return record

    def run_stage(self, stage, run, check, *, parent=None):
        if parent is not None:
            self.restore(self.root / name(parent))
        run(self.machine)
        return self.save(stage, check, parent=parent)

    def show(self):
        return [read(p) for p in sorted(self.root.glob("*/metadata.json"))]
