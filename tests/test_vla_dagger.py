import dataclasses
import numpy as np
import pytest
from r1pro_teleop.vla.dagger import DaggerRound, ExpertLabel, aggregation_manifest, state_digest


def inputs(tmp_path):
    checkpoint = tmp_path / "checkpoint/params"; checkpoint.mkdir(parents=True)
    (checkpoint / "weights").write_bytes(b"test")
    state = {"qpos": np.arange(19.), "qvel": np.zeros(19), "ctrl": np.zeros(19), "time": np.array(.5)}
    obs = {"state": np.arange(19.), "prompt": "place tray", **{
        "image/" + key: np.zeros((8, 9, 3), np.uint8) for key in ("head_left", "left_wrist", "right_wrist")}}
    round_ = DaggerRound(tmp_path / "round_0", checkpoint.parent, round_index=0, train_scene_ids=["scene1"])
    args = dict(scene_id="scene1", split="train", simulator_state=state, observation=obs,
                learner_action=np.ones((20, 19)), verify_label=lambda state, label: True, reason="intervention")
    return round_, args


def expert(state, obs):
    return ExpertLabel(state_digest(state), np.zeros((20, 19)), "teacher_v62", replanned_from_learner_state=True,
                       planning_verified=True, teacher_artifact="validated_plan.h5")


def test_fresh_state_label_round_and_aggregation(tmp_path):
    round_, args = inputs(tmp_path)
    row = round_.collect_intervention(**args, expert_replan=expert)
    assert row["label_source"] == "fresh_state_expert_replan"
    assert round_.finalize()["status"] == "labels_collected_not_trained"
    rows = aggregation_manifest([round_.directory], tmp_path / "aggregate.json", train_scene_ids=["scene1"])
    assert len(rows) == 1


@pytest.mark.parametrize("change", ["stale", "learner_label", "mutation", "test_scene", "verification"])
def test_rejects_invalid_expert_labels(tmp_path, change):
    round_, args = inputs(tmp_path)
    def bad(state, obs):
        label = expert(state, obs)
        if change == "stale": return dataclasses.replace(label, start_state_sha256="old_teacher_state")
        if change == "learner_label": return dataclasses.replace(label, expert_id="", replanned_from_learner_state=False)
        if change == "mutation": state["qpos"][0] += 1
        return label
    if change == "test_scene": args["split"] = "test"
    if change == "verification": args["verify_label"] = lambda state, label: False
    with pytest.raises(ValueError): round_.collect_intervention(**args, expert_replan=bad)


def test_round_never_overwrites(tmp_path):
    round_, _ = inputs(tmp_path)
    with pytest.raises(FileExistsError):
        DaggerRound(round_.directory, round_.checkpoint, round_index=1, train_scene_ids=["scene1"])


def test_missing_learner_checkpoint_rejected(tmp_path):
    with pytest.raises(ValueError, match="checkpoint"):
        DaggerRound(tmp_path / "round", tmp_path / "not_trained", round_index=0, train_scene_ids=["scene1"])


def test_aggregation_rejects_modified_labels(tmp_path):
    round_, args = inputs(tmp_path)
    row = round_.collect_intervention(**args, expert_replan=expert)
    round_.finalize()
    (__import__('pathlib').Path(row['sample_dir']) / 'label.npz').write_bytes(b'changed')
    with pytest.raises(ValueError, match='modified'):
        aggregation_manifest([round_.directory], tmp_path / 'aggregate.json', train_scene_ids=['scene1'])
