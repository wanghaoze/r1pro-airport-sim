"""Frozen inputs, bounded candidate space and experiment identity."""
from pathlib import Path
import hashlib
import importlib.metadata
import json
import math
import re
import sys

from ..airport_fsm.contracts import atomic_json, fingerprint

ROOT = Path(__file__).resolve().parents[2]
BOUNDS = {
    "base_distance_delta_m": (-.04, .04),
    "base_lateral_delta_m": (-.05, .05),
    "base_yaw_delta_rad": (-.15, .15),
    "rim_x_delta_m": (-.02, .02),
}
STRATEGIES = ("baseline", "reverse_candidates", "full_approach_preview")
TIMING = {
    "primitive_seconds": 3.0,
    "excluded": ["initial_grasp", "base_navigation", "push_release_retreat",
                 "final_stability_check", "CPU_planning_wall_time"],
    "separate_budget": "ordinary endpoint alignment",
    "all_scenes_feasible_within_budget": False,
}


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def name(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,95}", value):
        raise ValueError("invalid_experiment_name")
    return value


def candidate(value):
    if set(value) - {"name", "strategy", "params"}:
        raise ValueError("unknown_candidate_field")
    result = {"name": name(value["name"]), "strategy": value.get("strategy", "baseline"),
              "params": dict(value.get("params", {}))}
    if result["strategy"] not in STRATEGIES:
        raise ValueError("unknown_experiment_strategy")
    for key, val in result["params"].items():
        if key not in BOUNDS or isinstance(val, bool) or not isinstance(val, (int, float)):
            raise ValueError("forbidden_experiment_parameter")
        lo, hi = BOUNDS[key]
        if not math.isfinite(val) or not lo <= val <= hi:
            raise ValueError("experiment_parameter_out_of_bounds")
    return result


def source_stamp():
    paths = sorted((ROOT / "r1pro_teleop").rglob("*.py"))
    paths += sorted((ROOT / "prompts/airport_experiments").rglob("*.md"))
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def versions():
    values = {"python": sys.version.split()[0]}
    for package in ("numpy", "scipy", "mujoco", "h5py", "cma"):
        try:
            values[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            values[package] = None
    return values


def require_conda():
    # Checking conda-meta works for `conda run` and direct env/python as well.
    prefix = Path(sys.prefix)
    if not (prefix / "conda-meta").is_dir() or (prefix / "condabin").exists():
        raise RuntimeError("experiment_requires_nonbase_conda")


def assert_campaign(root):
    record = read(Path(root) / "campaign.json")
    if record["code"] != source_stamp() or record["versions"] != versions():
        raise RuntimeError("experiment_inputs_changed_use_new_campaign")
    from ..airport_fsm.batch import assert_environment
    assert_environment(Path(root) / "collection")
    return record


def digest_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()
