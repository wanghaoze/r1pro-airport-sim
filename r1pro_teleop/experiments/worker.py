"""One trial per interpreter; exceptions and partial traces remain evidence."""
from pathlib import Path
import traceback
import numpy as np

from .common import read, assert_campaign, require_conda
from .adapter import ExperimentMachine
from .checkpoint_tree import CheckpointTree
from ..airport_fsm.contracts import atomic_json, Fault


def run_stage(machine, stage):
    """Small built-in stages; add custom modules before freezing a new campaign."""
    r = machine.r
    if stage == "settled":
        if machine.experiment_origin != "fresh":
            raise ValueError("settled_stage_requires_fresh_origin")
        r.wait(2.)
        r.initial_bottom = r.observation()["min_z"].copy()
        return bool(np.all(r.observation()["support_contact"] > 0))
    if stage == "approach":
        if not machine.experiment_origin.startswith("checkpoint:") or getattr(machine, "restored_stage", None) != "settled":
            raise ValueError("approach_requires_settled_checkpoint")
        r.joints(r.tucked, minimum_seconds=.5)
        op = machine.scheduler.choose(machine._poses())
        if op is None:
            raise ValueError("no_remaining_operation")
        face, rim = machine.prepare_pick(op.tray, op.slot)
        machine.stage_context = {"tray": op.tray, "slot": op.slot, "face": face, "rim": rim}
        return True  # prepare_pick already applied original path and closure checks
    if stage == "lift":
        if getattr(machine, "restored_stage", None) != "approach":
            raise ValueError("lift_requires_approach_checkpoint")
        ctx = machine.stage_context
        machine.grasp(ctx["tray"], ctx["face"], ctx["rim"])
        e = r.observation()
        tray = ctx["tray"]
        return bool(r.holding == tray and np.all(e["gripper_contact_force"][tray] > machine.c.criteria.contact_n)
                    and e["support_contact"][tray] == 0)
    raise ValueError("unknown_diagnostic_stage")


def worker(request_path):
    require_conda()
    request = read(request_path)
    root, directory = Path(request["campaign"]), Path(request["output"])
    runtime = machine = None
    try:
        record = assert_campaign(root)
        from ..airport_fsm.registry import config_for, materialize_scene, scene_rows
        from ..airport_fsm.runtime import Runtime
        collection = root / "collection"
        rows = {r["scene_id"]: r for r in scene_rows(collection)}
        pf = read(collection / "scenes" / request["scene"] / "preflight.json")
        if not pf.get("valid"):
            raise Fault("experiment_preflight_required")
        cfg = config_for(collection)
        if not 0 <= request["attempt"] < cfg.max_attempts_per_scene:
            raise ValueError("experiment_attempt_out_of_budget")
        spec, xml = materialize_scene(collection, rows[request["scene"]])
        runtime = Runtime(spec, xml, cfg)
        runtime.experiment_dependencies = record["dependencies"]
        machine = ExperimentMachine(runtime, directory, experiment=request["candidate"],
                                    attempt=request["attempt"], seed=int(spec["seed"]))
        if request.get("checkpoint") and not request.get("stage"):
            raise ValueError("checkpoint_cannot_be_full_episode")
        if request.get("stage"):
            tree = CheckpointTree(machine, directory / "checkpoints")
            tree.plan(["settled", "approach", "lift"])
            if request.get("checkpoint"):
                restored = tree.restore(request["checkpoint"])
                machine.restored_stage = restored["stage"]
            passed = run_stage(machine, request["stage"])
            checkpoint = tree.save(request["stage"], lambda _: passed)
            result = machine.finish(False)
            result.update(stage_passed=passed, checkpoint=str(checkpoint.resolve()),
                          stage=request["stage"], failure_code=None)
            atomic_json(directory / "result.json", result)
        else:
            acceptance = machine.run()
            result = machine.finish(True, acceptance)
        return result
    except Exception as exc:
        error_text = traceback.format_exc()
        if machine is not None and not machine.log.closed:
            result = machine.finish(False, error=exc)
        else:
            if runtime is not None:
                runtime.close()
            directory.mkdir(parents=True, exist_ok=True)
            result = {"scene_id": request["scene"], "physics_success": False, "training_candidate": False,
                      "complete_episode_verified": False, "diagnostic_only": True,
                      "failure_code": getattr(exc, "code", "experiment_exception"), "error": str(exc),
                      "origin": "checkpoint:" + str(request["checkpoint"]) if request.get("checkpoint") else "fresh"}
            atomic_json(directory / "result.json", result)
        (directory / "exception.txt").write_text(error_text, encoding="utf-8")
        return result
