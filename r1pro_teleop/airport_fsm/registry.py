"""Immutable source enumeration and process-safe collection metadata."""
from __future__ import annotations
from collections import Counter
from pathlib import Path
import json
import re
import shutil
import xml.etree.ElementTree as ET
import numpy as np
from . import BASE_COMMIT, __version__
from .contracts import Config, atomic_json, fingerprint, sha256_file, Fault, camera_shapes, NATIVE_CAMERA_SHAPES, FOUR_CAMERA_SHAPES
from .geometry import Geometry


def load_sources(manifest: str | Path, expected: int) -> list[dict]:
    manifest = Path(manifest).resolve()
    contents = json.loads(manifest.read_text(encoding="utf-8"))
    entries = contents["scenes"] if isinstance(contents, dict) else contents
    if len(entries) != expected:
        raise Fault("scene_count_mismatch", {"required": expected, "actual": len(entries)})
    seen = set()
    result = []
    for e in entries:
        path = (manifest.parent / e["json"]).resolve()
        try:
            path.relative_to(manifest.parent)
        except ValueError as exc:
            raise Fault("manifest_path_escape", str(path)) from exc
        spec = json.loads(path.read_text(encoding="utf-8"))
        sid = spec["scene_id"]
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", sid) or sid in (".", "..") or sid in seen:
            raise Fault("unsafe_or_duplicate_scene_id", sid)
        if e.get("scene_id", sid) != sid:
            raise Fault("manifest_scene_identity_mismatch", sid)
        seen.add(sid)
        Geometry(spec)
        try:
            shapes = camera_shapes(spec)
        except (TypeError, ValueError) as exc:
            raise Fault("camera_contract_mismatch", sid) from exc
        # Formal collection uses the real-calibrated, uncropped streams.  The
        # legacy common 720p form remains accepted only for old unit fixtures.
        if spec.get("camera", {}).get("streams") is not None and shapes not in (NATIVE_CAMERA_SHAPES, FOUR_CAMERA_SHAPES):
            raise Fault("camera_contract_mismatch", {"scene": sid, "shapes": shapes})
        xml = path.with_name(spec.get("scene_file", "scene.xml"))
        digest = sha256_file(xml)
        if not spec.get("xml_sha256") or digest != spec["xml_sha256"]:
            raise Fault("source_xml_checksum_mismatch", sid)
        result.append({"scene_id": sid, "source_json": str(path), "source_xml": str(xml), "source_json_sha256": sha256_file(path), "source_xml_sha256": digest, "source_seed": int(spec["seed"]), "source_split": spec.get("split"), "difficulty": spec["difficulty"], "front_count": int(spec["front_count"]), "lighting": spec["lighting"]["mode"]})
    return sorted(result, key=lambda x: x["scene_id"])


def split_scenes(ids: list[str], counts, seed: int) -> dict[str, str]:
    if len(ids) != len(set(ids)) or len(ids) != sum(counts):
        raise ValueError("Splits require unique scene IDs and exact coverage")
    order = sorted(ids)
    np.random.default_rng(seed).shuffle(order)
    a, b, _ = counts
    return {sid: "train" if i < a else "val" if i < a+b else "test" for i, sid in enumerate(order)}


def prepare(manifest: str | Path, root: str | Path, cfg: Config, *, half_turn_equivalent: bool = False) -> dict:
    cfg.validate()
    manifest, root = Path(manifest).resolve(), Path(root).resolve()
    entries = load_sources(manifest, cfg.expected_scenes)
    splits = split_scenes([x["scene_id"] for x in entries], cfg.split_counts, cfg.split_seed)
    contract = {"version": __version__, "base_commit": BASE_COMMIT, "manifest": str(manifest), "manifest_sha256": sha256_file(manifest), "sources": entries, "config": cfg.dump(), "half_turn_equivalent": half_turn_equivalent}
    digest = fingerprint(contract)
    if root.exists():
        previous = json.loads((root / "collection.json").read_text(encoding="utf-8")) if (root / "collection.json").exists() else {}
        if previous.get("fingerprint") != digest:
            raise Fault("refuse_overwrite_or_mixed_config", str(root))
        return previous
    root.mkdir(parents=True, exist_ok=False)
    for directory in ("scenes", "attempts", "views", "quality", "datasets", "logs", "splits"):
        (root / directory).mkdir()
    # Metadata allocation does not mutate source scenes or call the old smoke-only init.
    for row in entries:
        row["split"] = splits[row["scene_id"]]
    record = {"schema": "airport_fsm_collection/1", "fingerprint": digest, "source_manifest": str(manifest), "source_manifest_sha256": contract["manifest_sha256"], "config": cfg.dump(), "half_turn_equivalent": half_turn_equivalent, "base_commit": BASE_COMMIT, "controller_source": "program_generated", "environment_source": "simulation", "human_demonstration": False, "real_base_driver_available": False, "base_model": "simulation_ideal_planar_position_servo_v1", "privileged_observations_exported": False, "registered_scenes": len(entries)}
    atomic_json(root / "scenes/index.json", entries)
    atomic_json(root / "splits/scenes.json", splits)
    atomic_json(root / "collection.json", record)
    return record


def config_for(root) -> Config:
    data = json.loads((Path(root) / "collection.json").read_text(encoding="utf-8"))["config"]
    from .contracts import Criteria
    data["criteria"] = Criteria(**data["criteria"])
    data["split_counts"] = tuple(data["split_counts"])
    data["arm_velocity_fallback"] = tuple(data["arm_velocity_fallback"])
    return Config(**data).validate()


def scene_rows(root):
    return json.loads((Path(root) / "scenes/index.json").read_text(encoding="utf-8"))


def select_registered(rows, scene_ids=None):
    """None means all; an explicit empty/unknown selection is never all."""
    if scene_ids is None:return list(rows)
    requested=set(scene_ids)
    if not requested:raise Fault('empty_scene_selection')
    unknown=requested-{r['scene_id'] for r in rows}
    if unknown:raise Fault('unregistered_scene_requested',sorted(unknown))
    return [r for r in rows if r['scene_id'] in requested]


def preflight_coverage(root, rows=None, selected_ids=None):
    root=Path(root);rows=scene_rows(root) if rows is None else rows
    selected=select_registered(rows,selected_ids)
    checked=set();verified=set()
    for row in rows:
        path=root/'scenes'/row['scene_id']/'preflight.json'
        if not path.exists():continue
        record=json.loads(path.read_text(encoding='utf-8'))
        if record.get('scene_id')!=row['scene_id'] or record.get('split')!=row['split']:
            raise Fault('preflight_scene_identity_mismatch',row['scene_id'])
        checked.add(row['scene_id'])
        if record.get('valid') is True:verified.add(row['scene_id'])
    selected_set={r['scene_id'] for r in selected}
    return {'registered':len(rows),'selected':len(selected),'selected_scene_ids':sorted(selected_set),
            'checked':len(checked),'verified':len(verified),'missing':len(rows)-len(checked),
            'selected_checked':len(checked&selected_set),'selected_verified':len(verified&selected_set),
            'all_registered_verified':len(verified)==len(rows),
            'qualification':'Initial physics preflight only; no complete task or rendering validation'}


def materialize_scene(root: str | Path, row: dict) -> tuple[dict, Path]:
    """Make a new mobile XML only; all visual/contact assets remain unchanged."""
    from ..airport_mobile import make_mobile_scene
    root = Path(root).resolve()
    out = root / "scenes" / row["scene_id"]
    source = Path(row["source_xml"])
    if sha256_file(source) != row["source_xml_sha256"] or sha256_file(row["source_json"]) != row["source_json_sha256"]:
        raise Fault("source_changed_after_registration", row["scene_id"])
    if (out / "scene.json").exists():
        spec = json.loads((out / "scene.json").read_text(encoding="utf-8"))
        path = out / "mobile.xml"
        if sha256_file(path) != spec["xml_sha256"]:
            raise Fault("collection_scene_changed", row["scene_id"])
        return spec, path
    out.mkdir(exist_ok=True)
    destination = out / "mobile.xml"
    # An interrupted partial scene is retained, never silently reused.
    if destination.exists():
        raise Fault("incomplete_scene_materialization", str(destination))
    original = ET.parse(source).getroot()
    if original.find(".//joint[@name='agent_base_x']") is not None:
        import os
        for node in original.iter():
            if "file" in node.attrib:
                node.set("file", os.path.relpath((source.parent/node.get("file")).resolve(), out).replace("\\", "/"))
        ET.ElementTree(original).write(destination, encoding="unicode")
    else:
        make_mobile_scene(source, destination)
    spec = json.loads(Path(row["source_json"]).read_text(encoding="utf-8"))
    collection = json.loads((root / "collection.json").read_text(encoding="utf-8"))
    spec.update(source_split=spec.get("split"), split=row["split"], source_scene_xml_sha256=row["source_xml_sha256"], xml_sha256=sha256_file(destination), scene_file="mobile.xml", base_control_available=True, real_base_driver_available=False, base_model="simulation_ideal_planar_position_servo_v1")
    spec["robot"]["base_control_available"] = True
    if collection["half_turn_equivalent"]:
        spec["source_yaw_period_rad"] = spec.get("yaw_period_rad", 2*np.pi)
        spec["yaw_period_rad"] = float(np.pi)
        spec["orientation_contract"] = "Explicit batch option: unmarked rectangular tray long-axis; pi rotation equivalent"
    atomic_json(out / "scene.json", spec)
    return spec, destination


def coverage(root: str | Path) -> dict:
    root = Path(root)
    rows, cfg = scene_rows(root), config_for(root)
    expected_splits = json.loads((root / "splits/scenes.json").read_text(encoding="utf-8"))
    report_rows = []
    totals = Counter()
    failure_codes = Counter()
    strata = {}
    for row in rows:
        reports = []
        for path in sorted((root / "attempts" / row["scene_id"]).glob("a*/result.json")):
            attempt = json.loads(path.read_text(encoding="utf-8"))
            if attempt["scene_id"] != row["scene_id"] or attempt["split"] != expected_splits[row["scene_id"]]:
                raise Fault("scene_split_leak", str(path))
            quality=path.parent/'export_quality.json'
            attempt['export_rejected']=quality.exists() and json.loads(quality.read_text()).get('status')=='rejected'
            reports.append(attempt)
        physical = [r for r in reports if r.get("physics_success") and not r.get("recovery_used")]
        clean = [r for r in physical if not r.get('export_rejected')]
        recovered = [r for r in reports if r.get("physics_success") and r.get("recovery_used")]
        for r in reports:
            if r.get("failure_code"):
                failure_codes[r["failure_code"]] += 1
        preflight = root / "scenes" / row["scene_id"] / "preflight.json"
        invalid = preflight.exists() and not json.loads(preflight.read_text()).get("valid", False)
        status = "physics_ready" if len(clean) >= cfg.successes_per_scene else "preflight_rejected" if invalid else "export_quality_rejected" if physical else "recovery_only" if recovered else "attempted_failed" if reports else "not_attempted"
        totals[status] += 1
        for dim in ("difficulty", "front_count", "lighting", "split"):
            counts = strata.setdefault(dim, {}).setdefault(str(row[dim]), Counter())
            counts[status] += 1
        report_rows.append({**{k: row[k] for k in ("scene_id", "split", "difficulty", "front_count", "lighting")}, "status": status, "attempts": len(reports), "clean_successes": len(clean), "recovered_successes": len(recovered)})
    catalog_path = root / "datasets/catalog.json"
    catalog = json.loads(catalog_path.read_text()) if catalog_path.exists() else {"shards": []}
    exported = set()
    exported_attempts = set()
    for shard in catalog.get("shards", []):
        if not shard.get('complete') or not shard.get('loader_every_episode_first_last'):
            raise Fault('unvalidated_shard_in_catalog')
        directory=root/shard['path']
        if not (directory/'source_manifest.json').is_file():raise Fault('catalog_shard_missing',str(directory))
        for name,info in shard.get('files',{}).items():
            p=directory/name
            if not p.is_file() or p.stat().st_size!=info['bytes']:raise Fault('catalog_artifact_missing_or_size_changed',str(p))
        for entry in shard.get('sources',[]):
            exported_attempts.add((entry['scene_id'],entry['attempt']))
        for sid in shard.get("scene_ids", []):
            if sid not in expected_splits or expected_splits[sid] != shard["split"]:
                raise Fault("dataset_split_leak", sid)
            exported.add(sid)
    enough_exported = all(sum(sid == row['scene_id'] for sid,attempt in exported_attempts) >= cfg.successes_per_scene for row in rows)
    result = {"registered": len(rows), "accounted": sum(totals.values()), "counts": dict(totals), "failure_codes": dict(failure_codes), "strata": {k: {v: dict(c) for v, c in values.items()} for k, values in strata.items()}, "exported_scene_count": len(exported), "all_scenes_attempted_or_rejected": totals["not_attempted"] == 0, "all_scenes_have_clean_physics_success": totals["physics_ready"] == len(rows), "all_scenes_have_validated_lerobot": len(exported) == len(rows) and enough_exported, "scene_leakage": [], "scenes": report_rows}
    preflight_report=root/'quality/preflight.json'
    selected_ids=(json.loads(preflight_report.read_text(encoding='utf-8')).get('selected_scene_ids')
                  if preflight_report.exists() else None)
    result['preflight_coverage']=preflight_coverage(root,rows,selected_ids)
    from .completion import outcome_counts
    all_results = [json.loads(p.read_text(encoding='utf-8'))
                   for p in root.glob('attempts/*/a*/result.json')]
    result.update(outcome_counts(all_results))
    result['acceptance_profile'] = getattr(cfg, 'acceptance_profile', 'strict')
    atomic_json(root / "quality/coverage.json", result)
    return result
