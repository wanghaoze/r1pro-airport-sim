"""Local instruction executor for the exported Isaac web-agent starter.

Only reads registered metadata and writes immutable drafts/plans. No shell,
network, simulator, training process or credential access is exposed to an LLM.
"""
from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import sys


VERSION = "web_scene_agent/1"
PROFILE = "isaac32_fixed_base_pickplace"
SCOPE = "fixed_base_pickplace_only"
PROMPTS = ["Pick up the tray", "Place the tray"]
CAMERAS = {"head_left", "head_right", "left_wrist", "right_wrist"}
CATALOGS = {
    "isaac32_narrow_20261016": "runs/isaac_parallel_live_deploy_20261016/closed32/narrow_catalog.json",
    "isaac32_wide_20261016": "runs/isaac_parallel_live_deploy_20261016/closed32/wide_catalog.json",
}


def fail(code):
    raise ValueError(code)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False,
                                     separators=(",", ":")).encode()).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"),
                      parse_constant=lambda _: fail("nonfinite_json"))


def keys(value, required, optional=()):
    if not isinstance(value, dict) or not set(required) <= set(value) or set(value) - set(required) - set(optional):
        fail("invalid_command_fields")


def vector(value, length):
    if not isinstance(value, list) or len(value) != length or any(
        type(v) not in (int, float) or not math.isfinite(v) for v in value
    ):
        fail("invalid_finite_vector")


def validate(command):
    keys(command, ("version", "request_id", "op", "args"))
    if command["version"] != VERSION:
        fail("unsupported_command_version")
    if not isinstance(command["request_id"], str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", command["request_id"]):
        fail("invalid_request_id")
    op, args = command["op"], command["args"]
    if op in ("scene.describe", "datasets.list"):
        keys(args, ())
    elif op == "scene.patch":
        keys(args, ("profile", "rooms", "changes"))
        if args["profile"] != PROFILE:
            fail("unsupported_scene_profile")
        rooms = args["rooms"]
        if not isinstance(rooms, list) or not rooms or any(type(r) is not int or not 0 <= r < 32 for r in rooms) or len(set(rooms)) != len(rooms):
            fail("invalid_room_selection")
        changes = args["changes"]
        keys(changes, (), ("robot_base_pose", "tray_pose", "robot_color", "tray_color"))
        if not changes:
            fail("empty_scene_patch")
        for name in ("robot_base_pose", "tray_pose"):
            if name in changes:
                vector(changes[name], 3 if name == "robot_base_pose" else 4)
        for name in ("robot_color", "tray_color"):
            if name in changes and (not isinstance(changes[name], str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", changes[name])):
                fail("invalid_opaque_srgb_color")
    elif op == "training.plan":
        keys(args, ("dataset_ids", "model", "steps", "batch_size", "seed"))
        ids = args["dataset_ids"]
        if not isinstance(ids, list) or not ids or any(not isinstance(i, str) or i not in CATALOGS for i in ids) or len(set(ids)) != len(ids):
            fail("invalid_registered_dataset_selection")
        if args["model"] != "pi05_lora":
            fail("unsupported_model_recipe")
        for name in ("steps", "batch_size", "seed"):
            if type(args[name]) is not int or args[name] < (0 if name == "seed" else 1):
                fail("invalid_training_integer")
    else:
        fail("unsupported_operation")
    return command


def catalog(project, dataset_id):
    """Validate metadata identity; this does NOT verify remote media/physics."""
    path = project / CATALOGS[dataset_id]
    data = read_json(path)
    if data.get("schema") != "parallel_pickplace_export/1":
        fail("unsupported_catalog_schema")
    pairs, parents, seen = [], {}, set()
    for batch in data["frozen_batches"]:
        segments = batch["segments"]
        if [s.get("prompt") for s in segments] != PROMPTS:
            fail("exact_pick_place_pair_required")
        first = segments[0]
        identity = first["source_room"]
        if identity in seen:
            fail("duplicate_source_pair")
        seen.add(identity)
        for s in segments:
            if (s.get("ready") is not True or s.get("complete_pick_place_pair") is not True
                    or s.get("eligible_for_training_scope") != SCOPE
                    or s.get("source_domain") != "simulation/program_generated"
                    or s.get("controller") != "expert" or s.get("model_executed") is not False
                    or s.get("full_three_tray_task") is not False or s.get("fps") != 20):
                fail("ineligible_source_metadata")
            if s.get("split") not in ("train", "val", "test") or s.get("split") != batch.get("split"):
                fail("invalid_parent_split")
            for key in ("source_room", "parent_scene_id", "split", "source_trace_sha256", "source_result_sha256"):
                if s.get(key) != first.get(key):
                    fail("pair_source_identity_mismatch")
            if not s.get("parent_scene_id") or not s.get("actual_engine_exit_receipt"):
                fail("missing_source_identity")
            for key in ("source_trace_sha256", "source_result_sha256", "trajectory_sha256"):
                if not re.fullmatch(r"[0-9a-f]{64}", s.get(key, "")):
                    fail("missing_source_hash")
            if len(s.get("videos", [])) != 4 or {v.get("camera") for v in s["videos"]} != CAMERAS:
                fail("four_native_cameras_required")
            if any(not re.fullmatch(r"[0-9a-f]{64}", v.get("sha256", "")) for v in s["videos"]):
                fail("missing_video_hash")
        parent, split = first["parent_scene_id"], first["split"]
        if parents.setdefault(parent, split) != split:
            fail("parent_split_leakage")
        if segments[0]["source_frame_interval"][1] != segments[1]["source_frame_interval"][0]:
            fail("pick_place_not_contiguous")
        pairs.append(copy.deepcopy(batch))
    counts = {s: sum(p["split"] == s for p in pairs) for s in ("train", "val", "test")}
    if data["complete_source_pairs"] != len(pairs) or data["action_segments"] != 2 * len(pairs) or data["source_pairs_by_split"] != counts:
        fail("catalog_counts_mismatch")
    return dict(dataset_id=dataset_id, catalog=str(path), catalog_sha256=sha(path),
                evidence_date="2026-10-16", verification="local_metadata_only",
                source_domain="simulation/program_generated", scope=SCOPE, prompts=PROMPTS,
                complete_source_pairs=len(pairs), action_segments=2 * len(pairs),
                camera_files=8 * len(pairs), source_pairs_by_split=counts, pairs=pairs)


def make_plan(project, args):
    sources = [catalog(project, name) for name in args["dataset_ids"]]
    parents, pairs, seen = {}, [], set()
    for source in sources:
        for pair in source["pairs"]:
            s = pair["segments"][0]
            key = s["source_room"]
            if key in seen:
                fail("duplicate_selected_source")
            seen.add(key)
            if parents.setdefault(s["parent_scene_id"], s["split"]) != s["split"]:
                fail("selected_parent_split_leakage")
            pairs.append(pair)
    counts = {split: sum(p["split"] == split for p in pairs) for split in ("train", "val", "test")}
    blockers = ["server_source_media_and_exit_revalidation_required", "web_training_launch_adapter_not_connected"]
    if not all(counts.values()):
        blockers.insert(0, "missing_legal_train_val_test_sources")
    return dict(status="blocked", scope=SCOPE, recipe_scope="selected_simulation_only_export_plan", requested_recipe=args,
                source_domain="simulation/program_generated", method="BC_LoRA",
                prompts=PROMPTS, source_pairs_by_split=counts,
                complete_source_pairs=len(pairs), action_segments=2 * len(pairs),
                camera_files=8 * len(pairs), distinct_parent_scenes=len(parents),
                parent_split_registry=parents, blockers=blockers, launchable=False,
                training_started=False, actual_completed_updates=0,
                selected_catalogs=[{k: v for k, v in s.items() if k != "pairs"} for s in sources],
                frozen_selection=pairs, training_split="train", normalization_split="train",
                evaluation_splits=["val", "test"], launch_argv=None,
                rejected_existing_adapter="scripts/train_pi05_isaac_three_tray.py requires tasks {0,1,2}",
                separate_authorized_recipe=dict(decision="DEC-055", entry="scripts/train_pi05_parallel_real_mix.py",
                    scope="new_300_pairs_plus_real_50_50_duration_weighted_BC",
                    selected_by_this_plan=False, real_holdouts_preserved=True))


def persist(project, command, artifact):
    """Exclusive request directory; reuse identical requests, never overwrite."""
    root = (project / "runs/web_scene_agent").resolve()
    if not root.is_relative_to(project):
        fail("output_outside_project")
    root.mkdir(parents=True, exist_ok=True)
    out = root / command["request_id"]
    if out.resolve().parent != root:
        fail("output_outside_project")
    request_hash = digest(command)
    try:
        out.mkdir()
    except FileExistsError:
        receipt = out / "receipt.json"
        if not receipt.is_file():
            fail("request_pending_or_incomplete_use_new_request_id")
        prior = read_json(receipt)
        if prior["request_sha256"] != request_hash:
            fail("request_id_conflict")
        for name, expected in prior["files"].items():
            if Path(name).name != name or sha(out / name) != expected:
                fail("saved_artifact_changed")
        return prior
    payload = dict(artifact, version=VERSION, request_id=command["request_id"],
                   created_at=datetime.now(timezone.utc).isoformat())
    for name, value in (("command.json", command), ("artifact.json", payload)):
        (out / name).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf8")
    receipt = dict(status=artifact["status"], request_sha256=request_hash,
                   artifact=str(out / "artifact.json"), training_started=False,
                   files={name: sha(out / name) for name in ("command.json", "artifact.json")})
    temp = out / "receipt.tmp"
    temp.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf8")
    temp.replace(out / "receipt.json")
    return receipt


def execute(project, command):
    project = Path(project).resolve()
    validate(command)
    op, args = command["op"], command["args"]
    if op == "scene.describe":
        return dict(status="snapshot_only", profile=PROFILE, engine="isaacsim_physx", rooms=32,
                    physics_dt=.002, record_hz=20, global_substeps_per_frame=25,
                    prompts=PROMPTS, scope=SCOPE, coordinate_frame="room_local",
                    robot_base_pose_format=["x_m", "y_m", "yaw_rad"],
                    tray_pose_format=["x_m", "y_m", "z_m", "yaw_rad"],
                    initialization_only_before_first_step=True,
                    pose_state="load_exact_cases_from_server_config_before_preview",
                    source_config_server=None, source_config_path_verified=False,
                    authoritative_entry="scripts/run_isaac_parallel_pickplace.py",
                    live_server_queried=False, training_started=False)
    if op == "datasets.list":
        rows = [catalog(project, name) for name in CATALOGS]
        return dict(status="snapshot_only", datasets=[{k: v for k, v in row.items() if k != "pairs"} for row in rows], live_server_queried=False)
    if op == "scene.patch":
        artifact = dict(status="draft_saved", profile=PROFILE, scope=SCOPE,
                        coordinate_frame="room_local", rooms=args["rooms"], changes=args["changes"],
                        initialization_only_before_first_step=True, physical_demo_completed=False,
                        training_eligible=False, native_scene_applied=False,
                        required_checks=["hydrate_registered_32_room_config", "front_station_and_opposed_grasp_preflight",
                                         "visual_collision_inertia_camera_fingerprint", "new_native_episode_and_media_closure"])
    else:
        artifact = make_plan(project, args)
    return persist(project, command, artifact)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--project", type=Path, default=Path(__file__).resolve().parents[2])
    p.add_argument("--command", required=True, help="JSON filename or - for stdin")
    a = p.parse_args()
    try:
        command = json.loads(sys.stdin.read()) if a.command == "-" else read_json(a.command)
        result = execute(a.project, command)
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
        return 0
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(json.dumps(dict(status="rejected", error=str(exc), training_started=False), ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
