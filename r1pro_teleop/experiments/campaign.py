"""Immutable campaigns, process-isolated trials and held-out verification."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from collections import Counter
import json
import os
import subprocess
import sys
import time
import uuid

from .common import (ROOT, TIMING, read, name, candidate, source_stamp, versions,
                     require_conda, assert_campaign)
from ..airport_fsm.contracts import atomic_json


def init_campaign(source, output, development, holdout, regression):
    require_conda()
    from ..airport_fsm.registry import prepare, config_for, scene_rows
    from ..airport_fsm.batch import freeze_dependencies, preflight_one
    source, output = Path(source).resolve(), Path(output).resolve()
    source_record = read(source / "collection.json")
    groups = dict(development=development, holdout=holdout, regression=regression)
    flat = [s for ids in groups.values() for s in ids]
    available = {r["scene_id"] for r in scene_rows(source)}
    if not all(groups.values()) or len(flat) != len(set(flat)) or set(flat) - available:
        raise ValueError("campaign_requires_disjoint_nonempty_scene_groups")
    cfg = config_for(source)
    if cfg.primitive_seconds != 3. or not cfg.fixed_primitives:
        raise ValueError("campaign_requires_fixed_three_second_contract")
    output.mkdir(parents=True, exist_ok=False)
    collection = output / "collection"
    prepare(source_record["source_manifest"], collection, cfg,
            half_turn_equivalent=source_record["half_turn_equivalent"])
    if read(collection / "splits/scenes.json") != read(source / "splits/scenes.json"):
        raise ValueError("experiment_source_split_mismatch")
    dependencies = freeze_dependencies(collection)
    record = {"schema": "airport_experiment_campaign/1", "source_collection": str(source),
              "groups": groups, "code": source_stamp(), "versions": versions(),
              "dependencies": dependencies["fingerprint"], "timing": TIMING,
              "environment_source": "simulation", "controller_source": "program_generated",
              "training_export_enabled": False, "created_unix": time.time()}
    atomic_json(output / "campaign.json", record)
    rows = {r["scene_id"]: r for r in scene_rows(collection)}
    reports = [preflight_one(collection, rows[s]) for s in flat]
    atomic_json(output / "preflight_summary.json", reports)
    if not all(r["valid"] for r in reports):
        raise RuntimeError("experiment_preflight_rejected")
    return record


def rank(rows):
    """Only complete, clean episodes earn success credit. Longer failures get no reward."""
    successes = sum(bool(r.get("complete_episode_verified") and not r.get("recovery_used")) for r in rows)
    return (-successes, sum(float(r.get("simulation_seconds", 600.)) for r in rows
                           if r.get("complete_episode_verified") and not r.get("recovery_used")))


def _trial(root, run, scene, spec, attempt, timeout, checkpoint=None, stage=None):
    destination = Path(root) / "experiments" / run / spec["name"] / scene / f"a{attempt:03d}"
    destination.parent.mkdir(parents=True, exist_ok=True)
    request = destination.with_suffix(".request.json")
    if request.exists() or destination.exists():
        raise FileExistsError(destination)
    atomic_json(request, {"campaign": str(Path(root).resolve()), "output": str(destination.resolve()),
                          "scene": scene, "candidate": spec, "attempt": attempt,
                          "checkpoint": str(Path(checkpoint).resolve()) if checkpoint else None,
                          "stage": stage})
    env = os.environ.copy()
    env.update(OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1",
               PYTHONPATH=str(ROOT))
    with open(destination.with_suffix(".log"), "x", encoding="utf-8") as log:
        try:
            proc = subprocess.run([sys.executable, "-m", "r1pro_teleop.experiments", "worker", str(request)],
                                  cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT, timeout=timeout)
            status = "worker_crashed" if proc.returncode else None
        except subprocess.TimeoutExpired:
            status = "experiment_wall_timeout"
    result_path = destination / "result.json"
    if result_path.exists():
        result = read(result_path)
    else:
        result = {"scene_id": scene, "physics_success": False, "complete_episode_verified": False,
                  "failure_code": status or "experiment_missing_result", "training_candidate": False,
                  "diagnostic_only": True, "origin": "checkpoint:" + str(checkpoint) if checkpoint else "fresh"}
        atomic_json(destination.parent / (destination.name + ".failure.json"), result)
    result["result_path"] = str(result_path)
    return result


def evaluate(root, candidates, *, run=None, group="development", workers=2, repeats=1,
             timeout=1800, checkpoint=None, stage=None):
    require_conda()
    root = Path(root)
    record = assert_campaign(root)
    if workers < 1 or repeats < 1 or timeout <= 0:
        raise ValueError("invalid_experiment_budget")
    if group not in ("development", "holdout", "regression"):
        raise ValueError("invalid_experiment_group")
    if group != "development":
        raise ValueError("heldout_access_requires_verify")
    specs = [candidate(c) for c in candidates]
    if not specs or len({s["name"] for s in specs}) != len(specs):
        raise ValueError("duplicate_or_empty_candidates")
    run = name(run or "sweep_" + uuid.uuid4().hex[:12])
    directory = root / "experiments" / run
    directory.mkdir(parents=True, exist_ok=False)
    scenes = record["groups"][group]
    if checkpoint:
        if not stage:
            raise ValueError("checkpoint_requires_explicit_stage")
        meta = read(Path(checkpoint) / "metadata.json")
        # Checkpoint is tied to exactly one scene; recover it from the source trace.
        source_request = Path(meta["source_trace"]).with_suffix(".request.json")
        scenes = [read(source_request)["scene"]]
        if scenes[0] not in record["groups"]["development"]:
            raise ValueError("checkpoint_outside_development_group")
    atomic_json(directory / "plan.json", {"candidates": specs, "scenes": scenes, "group": group,
                                           "repeats": repeats, "timeout": timeout,
                                           "checkpoint": checkpoint, "stage": stage})
    rows = {s["name"]: [] for s in specs}
    from ..airport_fsm.registry import config_for
    if repeats > config_for(root / "collection").max_attempts_per_scene:
        raise ValueError("experiment_repeat_budget_exceeded")
    with ThreadPoolExecutor(max_workers=workers) as pool:
        jobs = {pool.submit(_trial, root, run, scene, spec, attempt, timeout, checkpoint, stage): spec["name"]
                for spec in specs for scene in scenes for attempt in range(repeats)}
        for job in as_completed(jobs):
            rows[jobs[job]].append(job.result())
            atomic_json(directory / "progress.json", {"completed": sum(map(len, rows.values())),
                                                       "total": len(jobs), "running": True})
    summaries = [{"candidate": spec, "rows": sorted(rows[spec["name"]], key=lambda r: (r["scene_id"], r.get("attempt", 0))),
                  "ranking_key": list(rank(rows[spec["name"]]))} for spec in specs]
    # Stage success is a separate diagnostic metric and cannot win episode ranking.
    if stage:
        for entry in summaries:
            entry["stage_passes"] = sum(bool(r.get("stage_passed")) for r in entry["rows"])
    summaries.sort(key=lambda s: ((-s["stage_passes"],) if stage else tuple(s["ranking_key"])) + (s["candidate"]["name"],))
    result = {"run": run, "group": group, "diagnostic_only": True, "stage": stage,
              "origin": "checkpoint:" + str(checkpoint) if checkpoint else "fresh", "ranking": summaries,
              "winner": summaries[0]["candidate"] if not stage and summaries[0]["ranking_key"][0] < 0 else None,
              "stage_winner": summaries[0]["candidate"] if stage and summaries[0]["stage_passes"] else None}
    atomic_json(directory / "summary.json", result)
    atomic_json(directory / "progress.json", {"completed": len(jobs), "total": len(jobs), "running": False})
    return result


def verify(root, candidate_spec, *, workers=2, repeats=1, timeout=1800):
    """Freeze a winner before holdout exposure; compare with baseline from fresh initial states."""
    root = Path(root)
    require_conda()
    record = assert_campaign(root)
    from ..airport_fsm.registry import config_for
    if repeats > config_for(root / "collection").max_attempts_per_scene:
        raise ValueError("experiment_repeat_budget_exceeded")
    chosen = candidate(candidate_spec)
    if chosen["name"] == "baseline":
        raise ValueError("verification_candidate_name_reserved")
    if workers < 1 or repeats < 1 or timeout <= 0:
        raise ValueError("invalid_experiment_budget")
    directory = root / "verification"
    directory.mkdir(exist_ok=False)  # one-shot holdout gate, no repeated tuning on it
    atomic_json(directory / "candidate.json", chosen)
    specs = [{"name": "baseline", "strategy": "baseline", "params": {}}, chosen]
    scenes = record["groups"]["regression"] + record["groups"]["holdout"]
    rows = {s["name"]: [] for s in specs}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        jobs = {pool.submit(_trial, root, "verification", scene, spec, a, timeout): spec["name"]
                for spec in specs for scene in scenes for a in range(repeats)}
        for job in as_completed(jobs):
            rows[jobs[job]].append(job.result())
    def passed(r):
        return bool(r.get("complete_episode_verified") and not r.get("recovery_used"))
    baseline_success = {(r["scene_id"], r.get("attempt", 0)) for r in rows["baseline"] if passed(r)}
    chosen_success = {(r["scene_id"], r.get("attempt", 0)) for r in rows[chosen["name"]] if passed(r)}
    protected = {(s, a) for s in record["groups"]["regression"] for a in range(repeats)}
    lost = sorted((baseline_success | protected) - chosen_success)
    report = {"candidate": chosen, "rows": rows, "regressions": lost,
              "passed": not lost and any(s in record["groups"]["holdout"] for s, _ in chosen_success),
              "baseline_successes": len(baseline_success), "candidate_successes": len(chosen_success),
              "training_export_enabled": False, "origin": "fresh", "timing": TIMING}
    atomic_json(directory / "report.json", report)
    return report


def report(root):
    root = Path(root)
    return {"campaign": read(root / "campaign.json"),
            "experiments": [read(p) for p in sorted(root.glob("experiments/*/summary.json"))],
            "verification": read(root / "verification/report.json") if (root / "verification/report.json").exists() else None}
