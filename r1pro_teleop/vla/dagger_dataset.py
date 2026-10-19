"""One learner observation per fresh-state expert chunk; never fake a video episode."""
from __future__ import annotations
import hashlib
import json
import math
from pathlib import Path
import numpy as np
from .dagger import ExpertLabel, require_checkpoint, state_digest, verify_curriculum_context
from .teacher import SimulationExpert
from .training import AirportInputs, MODEL_CAMERAS


class DaggerChunkDataset:
    def __init__(self, manifest_path, *, action_horizon, train_scene_ids):
        self.action_horizon = action_horizon
        allowed = frozenset(train_scene_ids)
        manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
        if (manifest.get("method") != "simulation_expert_dagger" or manifest.get("split") != "train"
                or manifest.get("status") != "aggregation_manifest_not_trained"):
            raise ValueError("Invalid DAgger aggregation manifest")
        self.samples = []
        curriculum_samples = {str(Path(path).resolve()) for path in manifest.get('curriculum_sample_dirs', [])}
        context_hash_cache = {}
        for row in manifest.get("interventions", []):
            verify_curriculum_context(row, required=str(Path(row['sample_dir']).resolve()) in curriculum_samples,
                                      hash_cache=context_hash_cache)
            if (row.get("split") != "train" or row.get("scene_id") not in allowed
                    or row.get("label_source") != "fresh_state_expert_replan"
                    or row.get("action_semantics") != "absolute_mobile19" or row.get("fps") != 20):
                raise ValueError("DAgger training provenance or scene split mismatch")
            require_checkpoint(row["learner_checkpoint"])
            sample = Path(row["sample_dir"])
            label_path = sample / "label.npz"
            if hashlib.sha256(label_path.read_bytes()).hexdigest() != row["label_sha256"]:
                raise ValueError("Modified DAgger expert label")
            with np.load(label_path, allow_pickle=False) as file:
                physics = {key[8:]: file[key].copy() for key in file.files if key.startswith("physics_")}
                state = file["state"].astype(np.float32)
                actions = file["expert_actions"].astype(np.float32)
            if state_digest(physics) != row["state_sha256"]:
                raise ValueError("DAgger learner state hash mismatch")
            label = ExpertLabel(row["state_sha256"], actions, row["expert_id"],
                                replanned_from_learner_state=True, planning_verified=True,
                                teacher_artifact=row["teacher_artifact"])
            if not SimulationExpert.verify_label(physics, label):
                raise ValueError("DAgger teacher trace does not verify expert actions")
            if actions.ndim != 2 or actions.shape[1] != 19 or len(actions) < action_horizon:
                raise ValueError("DAgger chunk shorter than model horizon; cannot invent expert tail")
            images = {}
            for key in MODEL_CAMERAS.values():
                path = sample / (key + ".npy")
                if hashlib.sha256(path.read_bytes()).hexdigest() != row.get("image_sha256", {}).get(key):
                    raise ValueError("DAgger learner image hash missing or modified")
                images["image/" + key] = np.load(path, allow_pickle=False)
            AirportInputs()({"state": state, "actions": actions[:action_horizon], "prompt": row["prompt"], **images})
            self.samples.append({"observation.state": state, "action": actions[:action_horizon],
                                 "prompt": row["prompt"],
                                 **{"observation.images." + key: images["image/" + key] for key in MODEL_CAMERAS.values()}})
        if not self.samples:
            raise ValueError("No verified DAgger samples")

    def __len__(self): return len(self.samples)

    def __getitem__(self, index):
        # Torch loaders may mutate samples while transforming them.
        return {key: value.copy() if isinstance(value, np.ndarray) else value
                for key, value in self.samples[index].items()}


class BCMixedDaggerDataset:
    """Deterministic interleaving; ratio counts whole supervised chunks."""
    def __init__(self, bc_dataset, dagger_dataset, ratio):
        if not 0 < ratio < 1 or len(bc_dataset) == 0 or len(dagger_dataset) == 0:
            raise ValueError("DAgger mixture requires nonempty BC/DAgger and ratio in (0,1)")
        self.bc, self.dagger = bc_dataset, dagger_dataset
        self.length = max(len(bc_dataset) + 1, math.ceil(len(bc_dataset) / (1 - ratio)))
        self.dagger_count = self.length - len(bc_dataset)

    def __len__(self): return self.length

    def __getitem__(self, index):
        index = int(index)
        if index < 0: index += self.length
        if not 0 <= index < self.length: raise IndexError(index)
        before = index * self.dagger_count // self.length
        after = (index + 1) * self.dagger_count // self.length
        if after > before:
            return self.dagger[before % len(self.dagger)]
        return self.bc[(index - before) % len(self.bc)]


def install_mixed_loader(spec):
    """In-process project-owned wrapper, leaving openpi source files untouched."""
    from openpi.training import data_loader
    if getattr(data_loader.create_torch_dataset, "_airport_dagger", False):
        raise ValueError("DAgger loader already installed in this process")
    manifest = json.loads((Path(spec.dataset_root) / "airport_training_manifest.json").read_text(encoding="utf-8"))
    allowed = manifest.get("prepared_train_scene_ids") or [row["scene_id"] for row in manifest["episodes"]]
    dagger = DaggerChunkDataset(spec.aggregation_manifest, action_horizon=spec.action_horizon, train_scene_ids=allowed)
    original = data_loader.create_torch_dataset
    def mixed(data_config, action_horizon, model_config):
        base = original(data_config, action_horizon, model_config)
        if data_config.repo_id != spec.dataset_repo_id:
            return base
        if action_horizon != spec.action_horizon:
            raise ValueError("DAgger model horizon changed")
        return BCMixedDaggerDataset(base, dagger, spec.dagger_mix_ratio)
    mixed._airport_dagger = True
    data_loader.create_torch_dataset = mixed
    return original, data_loader
