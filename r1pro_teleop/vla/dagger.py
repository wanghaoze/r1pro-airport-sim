"""Simulation-expert DAgger provenance and immutable aggregation interfaces.

The simulator integration supplies a fresh learner-visited snapshot and replans
the expert in an isolated simulator restored to that exact state. Historical
teacher actions cannot label off-trajectory learner observations.
"""
from __future__ import annotations
import copy
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import numpy as np


def state_digest(state):
    """Hash complete supplied physics state, preserving shapes and dtypes."""
    digest = hashlib.sha256()
    for key in sorted(state):
        value = np.asarray(state[key])
        if not np.issubdtype(value.dtype, np.number) or not np.isfinite(value).all():
            raise ValueError("Simulator snapshot must contain finite numeric arrays")
        digest.update(key.encode()); digest.update(str(value.shape).encode())
        digest.update(str(value.dtype).encode()); digest.update(value.tobytes())
    for required in ("qpos", "qvel", "ctrl", "time"):
        if required not in state:
            raise ValueError("Missing learner simulator state " + required)
    return digest.hexdigest()


def require_checkpoint(checkpoint):
    path = Path(checkpoint).resolve()
    params = path if path.name == "params" else path / "params"
    if not params.is_dir() or not any(p.is_file() for p in params.rglob("*")):
        raise ValueError("DAgger rollout requires a saved real model checkpoint")
    return str(path)


def verify_curriculum_context(row, *, required=False, hash_cache=None):
    """Optional extra provenance; legacy standard DAgger rows stay unchanged."""
    sample = Path(row['sample_dir']).resolve()
    path = sample / 'curriculum_context.json'
    present = any(key in row for key in ('curriculum_context', 'curriculum_context_sha256'))
    if not (required or present or path.exists() or row.get('collection_mode') == 'expert_snapshot_curriculum'):
        return
    context = row.get('curriculum_context', {})
    if (not isinstance(context, dict) or not path.is_file() or path.resolve().parent != sample or
            hashlib.sha256(path.read_bytes()).hexdigest() != row.get('curriculum_context_sha256') or
            json.loads(path.read_text(encoding='utf-8')) != context):
        raise ValueError('Curriculum context file/hash/content mismatch')
    keys = ('source_trace', 'source_trace_sha256', 'source_frame', 'source_scene_sha256', 'scene_xml_sha256',
            'episode_index', 'skill', 'initial_restore_count', 'learner_state_sha256', 'step', 'decision', 'prompt')
    skills = ('initialize_posture', 'navigate_to_tray', 'push_adjust_tray', 'grasp_lift_tray', 'carry_tray', 'place_release_tray')
    if (any(key not in context for key in keys) or context.get('collection_mode') != 'expert_snapshot_curriculum' or
            context.get('initial_restore_count') != 1 or context.get('skill') not in skills or
            context.get('learner_state_sha256') != row.get('state_sha256') or context.get('prompt') != row.get('prompt') or
            row.get('split') != 'train' or
            any(type(context.get(key)) is not int or context[key] < minimum
                for key, minimum in (('source_frame', 0), ('episode_index', 0), ('step', 1), ('decision', 2)))):
        raise ValueError('Curriculum source/skill/prompt/visited-state binding mismatch')
    trace = Path(context['source_trace'])
    if not trace.is_absolute() or not trace.is_file():
        raise ValueError('Curriculum source trace missing')
    trace = trace.resolve()
    if len(trace.parents) < 4 or trace.parent.parent.name != row['scene_id'] or trace.parent.parent.parent.name != 'attempts':
        raise ValueError('Curriculum source path/scene mismatch')
    collection = trace.parents[3]
    scene_dir = collection / 'scenes' / row['scene_id']
    def file_hash(file):
        file = file.resolve();stat = file.stat();key = (str(file), stat.st_size, stat.st_mtime_ns)
        if hash_cache is not None and key in hash_cache:return hash_cache[key]
        digest = hashlib.sha256()
        with file.open('rb') as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b''):digest.update(block)
        value = digest.hexdigest()
        if hash_cache is not None:hash_cache[key] = value
        return value
    if any(file_hash(file) != context[key] for file, key in ((trace, 'source_trace_sha256'),
            (scene_dir / 'scene.json', 'source_scene_sha256'), (scene_dir / 'mobile.xml', 'scene_xml_sha256'))):
        raise ValueError('Curriculum source trace/scene/XML modified')
    scene = json.loads((scene_dir / 'scene.json').read_text(encoding='utf-8'))
    result = json.loads((trace.parent / 'result.json').read_text(encoding='utf-8'))
    if (scene.get('scene_id') != row['scene_id'] or scene.get('split') != 'train' or
            result.get('task_completed') is not True or result.get('controller_source', 'program_generated') != 'program_generated'):
        raise ValueError('Curriculum initial source is not an actual train simulation expert success')


@dataclass(frozen=True)
class ExpertLabel:
    start_state_sha256: str
    actions: np.ndarray
    expert_id: str
    source: str = "simulation/program_generated"
    replanned_from_learner_state: bool = False
    planning_verified: bool = False
    teacher_artifact: str = ""


class DaggerRound:
    """New round directory per learner checkpoint; collection never trains itself."""
    def __init__(self, directory, learner_checkpoint, *, round_index, train_scene_ids):
        if type(round_index) is not int or round_index < 0:
            raise ValueError("Round index must be nonnegative integer")
        self.checkpoint = require_checkpoint(learner_checkpoint)
        self.train_scene_ids = frozenset(train_scene_ids)
        if not self.train_scene_ids:
            raise ValueError("Prepared train scene identity list is required")
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=False)
        self.rows = []
        self.metadata = {"round": round_index, "learner_checkpoint": self.checkpoint,
                         "method": "simulation_expert_dagger", "status": "collecting",
                         "label_count": 0, "source": "simulation/program_generated"}
        self._write()

    def _write(self):
        (self.directory / "round.json").write_text(json.dumps(self.metadata, indent=2), encoding="utf-8")

    def collect_intervention(self, *, scene_id, split, simulator_state, observation,
                             learner_action, expert_replan, verify_label, reason):
        """Callbacks must restore isolated physics and validate the resulting plan.

        verify_label(state,label) must inspect/replay the expert artifact. It is
        never a license to call a learner prediction an expert action.
        """
        if split != "train" or scene_id not in self.train_scene_ids:
            raise ValueError("DAgger cannot train on validation/test scenes")
        before = state_digest(simulator_state)
        state_copy = copy.deepcopy(simulator_state)
        label = expert_replan(state_copy, copy.deepcopy(observation))
        if state_digest(state_copy) != before or state_digest(simulator_state) != before:
            raise ValueError("Expert replanning mutated the live learner snapshot")
        if not isinstance(label, ExpertLabel):
            raise ValueError("Expert must return a provenance-bearing label")
        if (label.start_state_sha256 != before or not label.replanned_from_learner_state
                or not label.planning_verified or label.source != "simulation/program_generated"
                or not label.expert_id or not label.teacher_artifact):
            raise ValueError("Expert label lacks fresh-state verified provenance")
        actions = np.asarray(label.actions, dtype=np.float32)
        state = np.asarray(observation["state"], dtype=np.float32)
        predicted = np.asarray(learner_action, dtype=np.float32)
        if state.shape != (19,) or not np.isfinite(state).all():
            raise ValueError("Invalid learner mobile19 observation")
        if actions.ndim != 2 or actions.shape[-1] != 19 or len(actions) == 0 or not np.isfinite(actions).all():
            raise ValueError("Invalid expert absolute mobile19 chunk")
        if not np.isfinite(predicted).all() or predicted.ndim != 2 or predicted.shape[-1] != 19:
            raise ValueError("Invalid recorded learner chunk")
        if verify_label(copy.deepcopy(simulator_state), label) is not True:
            raise ValueError("Expert label physics verification failed")
        image_keys = ("image/head_left", "image/left_wrist", "image/right_wrist")
        images = {}
        for key in image_keys:
            image = np.asarray(observation[key])
            if image.ndim != 3 or image.shape[-1] != 3 or not np.isfinite(image).all():
                raise ValueError("Invalid DAgger RGB observation")
            images[key] = image
        if not str(observation.get("prompt", "")).strip():
            raise ValueError("DAgger intervention needs a skill prompt")
        idx = len(self.rows)
        sample_dir = self.directory / f"intervention_{idx:06d}"
        sample_dir.mkdir(exist_ok=False)
        np.savez_compressed(sample_dir / "label.npz", state=state, expert_actions=actions,
                            learner_actions=predicted,
                            **{"physics_" + key: value for key, value in simulator_state.items()})
        for key, image in images.items():
            np.save(sample_dir / (key.split("/")[-1] + ".npy"), image)
        row = {"scene_id": scene_id, "split": split, "state_sha256": before,
               "expert_id": label.expert_id, "teacher_artifact": label.teacher_artifact,
               "learner_checkpoint": self.checkpoint, "prompt": str(observation["prompt"]),
               "reason": str(reason), "sample_dir": str(sample_dir),
               "action_semantics": "absolute_mobile19", "fps": 20,
               "label_sha256": hashlib.sha256((sample_dir / "label.npz").read_bytes()).hexdigest(),
               "image_sha256": {key.split("/")[-1]: hashlib.sha256(
                   (sample_dir / (key.split("/")[-1] + ".npy")).read_bytes()).hexdigest() for key in images},
               "label_source": "fresh_state_expert_replan"}
        (sample_dir / "metadata.json").write_text(json.dumps(row, indent=2), encoding="utf-8")
        self.rows.append(row)
        with (self.directory / "interventions.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(row) + "\n")
        self.metadata["label_count"] = len(self.rows); self._write()
        return row

    def finalize(self):
        if not self.rows:
            raise ValueError("Empty DAgger round cannot be claimed as training data")
        self.metadata["status"] = "labels_collected_not_trained"; self._write()
        return self.metadata


def aggregation_manifest(round_directories, output_path, *, train_scene_ids):
    """Validate round labels before a data exporter materializes BC+DAgger data."""
    allowed = frozenset(train_scene_ids)
    rows, seen, curriculum_samples, context_hash_cache = [], set(), [], {}
    for directory in round_directories:
        root = Path(directory)
        info = json.loads((root / "round.json").read_text(encoding="utf-8"))
        if info.get("status") != "labels_collected_not_trained":
            raise ValueError("Cannot aggregate incomplete DAgger collection")
        require_checkpoint(info["learner_checkpoint"])
        current = [json.loads(line) for line in (root / "interventions.jsonl").read_text(encoding="utf-8").splitlines()]
        if len(current) != info["label_count"]:
            raise ValueError("DAgger label count mismatch")
        for row in current:
            verify_curriculum_context(row, required=info.get('collection_mode') == 'expert_snapshot_curriculum',
                                      hash_cache=context_hash_cache)
            if row["split"] != "train" or row["scene_id"] not in allowed or row["label_source"] != "fresh_state_expert_replan":
                raise ValueError("Invalid aggregation provenance")
            identity = (row["scene_id"], row["state_sha256"], row["learner_checkpoint"])
            if identity in seen:
                continue
            label_path = Path(row["sample_dir"]) / "label.npz"
            if not label_path.is_file():
                raise ValueError("DAgger label artifact missing")
            if hashlib.sha256(label_path.read_bytes()).hexdigest() != row["label_sha256"]:
                raise ValueError("DAgger label artifact modified after collection")
            with np.load(label_path, allow_pickle=False) as label:
                physics = {key[8:]: label[key] for key in label.files if key.startswith("physics_")}
                if state_digest(physics) != row["state_sha256"]:
                    raise ValueError("DAgger physics state provenance mismatch")
            seen.add(identity); rows.append(row)
            if row.get('curriculum_context') is not None:curriculum_samples.append(row['sample_dir'])
    if not rows:
        raise ValueError("No valid DAgger interventions")
    path = Path(output_path)
    with path.open("x", encoding="utf-8") as stream:
        value = {"method": "simulation_expert_dagger", "split": "train", "interventions": rows,
                 "status": "aggregation_manifest_not_trained"}
        if curriculum_samples:value['curriculum_sample_dirs'] = curriculum_samples
        json.dump(value, stream, indent=2)
    return rows
