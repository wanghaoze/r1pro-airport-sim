"""Contract tests for exported instructions, with no GPU or native SDK imports."""
import copy
import importlib.util
import json
from pathlib import Path
import sys

import pytest

PROJECT = Path(__file__).resolve().parents[1]
BUNDLE = PROJECT / "exports/web_scene_agent_v1"
sys.path.insert(0, str(BUNDLE))
from executor import CATALOGS, PROFILE, VERSION, execute, make_plan, read_json, validate
from isaac_adapter import linear_rgb, materialize_config


def request(op, args, identity="test_request"):
    return dict(version=VERSION, request_id=identity, op=op, args=args)


def edit(changes=None):
    return request("scene.patch", dict(profile=PROFILE, rooms=[3], changes=changes or {"tray_color": "#2563EB"}))


def install_catalogs(destination):
    for path in CATALOGS.values():
        target = destination / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((PROJECT / path).read_bytes())


def recipe():
    return dict(dataset_ids=list(CATALOGS), model="pi05_lora", steps=1000, batch_size=8, seed=42)


def test_examples_and_schema_agree_on_operations():
    schema = read_json(BUNDLE / "command.schema.json")
    operations = {branch["properties"]["op"]["const"] for branch in schema["oneOf"]}
    examples = [read_json(p) for p in (BUNDLE / "examples").glob("*.json")]
    assert operations == {validate(e)["op"] for e in examples}


@pytest.mark.parametrize("patch", [
    {"shell": "echo injected"}, {"robot_base_pose": [True, 0., 0.]},
    {"tray_pose": [0., 0., float("nan"), 0.]}, {"robot_color": "#12345600"},
    {"collision": False}, {"robot_base_pose": [0., 0.]},
])
def test_reject_unknown_or_invalid_scene_fields(patch):
    with pytest.raises(ValueError):
        validate(edit(patch))


@pytest.mark.parametrize("identity", ["../old", "a/b", "C:\\old", "", "x" * 65])
def test_path_like_request_ids_rejected(identity):
    command = edit(); command["request_id"] = identity
    with pytest.raises(ValueError, match="invalid_request_id"):
        validate(command)


def test_unimplemented_start_not_executable():
    with pytest.raises(ValueError, match="unsupported_operation"):
        validate(request("training.start", {}))


def test_immutable_replay_and_conflict(tmp_path):
    receipt = execute(tmp_path, edit())
    assert execute(tmp_path, edit()) == receipt
    artifact = read_json(receipt["artifact"])
    assert artifact["native_scene_applied"] is False
    assert artifact["physical_demo_completed"] is False
    with pytest.raises(ValueError, match="request_id_conflict"):
        execute(tmp_path, edit({"tray_color": "#FFFFFF"}))
    Path(receipt["artifact"]).write_text("{}")
    with pytest.raises(ValueError, match="saved_artifact_changed"):
        execute(tmp_path, edit())


def test_incomplete_request_not_overwritten(tmp_path):
    (tmp_path / "runs/web_scene_agent/test_request").mkdir(parents=True)
    with pytest.raises(ValueError, match="pending_or_incomplete"):
        execute(tmp_path, edit())


def test_current_real_snapshot_plan_is_blocked(tmp_path):
    install_catalogs(tmp_path)
    result = execute(tmp_path, request("training.plan", recipe()))
    plan = read_json(result["artifact"])
    assert plan["complete_source_pairs"] == 59
    assert plan["action_segments"] == 118
    assert plan["camera_files"] == 472
    assert plan["source_pairs_by_split"] == {"train": 59, "val": 0, "test": 0}
    assert plan["distinct_parent_scenes"] == 1
    assert plan["status"] == "blocked" and plan["launch_argv"] is None
    assert plan["actual_completed_updates"] == 0
    assert "missing_legal_train_val_test_sources" in plan["blockers"]


def test_cross_catalog_parent_leakage_rejected(tmp_path):
    install_catalogs(tmp_path)
    path = tmp_path / CATALOGS["isaac32_wide_20261016"]
    data = read_json(path)
    for p in data["frozen_batches"]:
        p["split"] = "val"
        for segment in p["segments"]:
            segment["split"] = "val"
    data["source_pairs_by_split"] = {"train": 0, "val": 29, "test": 0}
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="selected_parent_split_leakage"):
        make_plan(tmp_path, recipe())


def test_pair_domain_tamper_rejected(tmp_path):
    install_catalogs(tmp_path)
    path = tmp_path / CATALOGS["isaac32_wide_20261016"]
    data = read_json(path)
    data["frozen_batches"][0]["segments"][0]["source_domain"] = "real_world/user_provided"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="ineligible_source_metadata"):
        make_plan(tmp_path, recipe())


def test_materialize_changes_only_selected_room_and_invalidates_precheck(tmp_path):
    config = dict(rooms=32, output="old", cases=[dict(initial_base_world=[0., 0., 0.],
        fixed_base_world=[0., 0., 0.], tray_pose=[1., 0., .8, 1., 0., 0., 0.],
        parent_split="train", private_path_available=True, private_precheck_report="old.json") for _ in range(32)])
    before = copy.deepcopy(config)
    command = edit(dict(robot_base_pose=[.3, .1, .2], tray_pose=[.85, .1, .801, 0.], tray_color="#FFFFFF"))
    result = materialize_config(config, command, str(tmp_path / "new_native"))
    assert config == before
    cases = result["config"]["cases"]
    assert cases[2] == before["cases"][2]
    assert cases[3]["initial_base_world"] == cases[3]["fixed_base_world"] == [.3, .1, .2]
    assert cases[3]["tray_pose"] == [.85, .1, .801, 1., 0., 0., 0.]
    assert cases[3]["private_path_available"] is False
    assert "private_precheck_report" not in cases[3]
    assert result["native_launchable"] is False
    assert result["visual_overrides"]["colors"] == {"tray_color": "#FFFFFF"}


def test_color_linear_conversion():
    assert linear_rgb("#FFFFFF") == [1., 1., 1.]
    assert linear_rgb("#000000") == [0., 0., 0.]
    assert linear_rgb("#808080")[0] == pytest.approx(.2158605)
