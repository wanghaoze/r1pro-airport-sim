"""Train-only skill balancing over unchanged, verified source sample indices."""
from collections import Counter
import json
import math
from pathlib import Path

import numpy as np


def bc_frame_weights(episodes, expected_frames=None):
    """Equal probability per skill, uniform over its original real frames."""
    counts = Counter()
    for index, row in enumerate(episodes):
        if (row.get('episode_index') != index or row.get('split') != 'train'
                or not isinstance(row.get('skill'), str) or not row['skill']
                or isinstance(row.get('frames'), bool) or not isinstance(row.get('frames'), int)
                or row['frames'] <= 0):
            raise ValueError('invalid_skill_sampling_episode')
        counts[row['skill']] += row['frames']
    if not counts:
        raise ValueError('empty_skill_sampling_episodes')
    weights = np.concatenate([np.full(row['frames'], 1 / (len(counts) * counts[row['skill']]))
                              for row in episodes])
    if expected_frames is not None and len(weights) != expected_frames:
        raise ValueError('skill_sampling_frame_count_mismatch')
    return weights


def mixed_frame_weights(bc_weights, dagger_skills, mix_ratio):
    """Match BCMixedDaggerDataset interleave, including repeated fresh labels.

    BC and DAgger keep their declared total probability; skills are balanced
    independently in each group. Duplicate virtual indices split the probability
    of the same underlying label rather than increasing its expert evidence.
    """
    bc = np.asarray(bc_weights, dtype=float)
    if (bc.ndim != 1 or not len(bc) or not np.isfinite(bc).all() or np.any(bc <= 0)
            or not math.isfinite(mix_ratio) or not 0 < mix_ratio < 1 or not dagger_skills
            or any(not isinstance(s, str) or not s for s in dagger_skills)):
        raise ValueError('invalid_balanced_dagger_mixture')
    length = max(len(bc) + 1, math.ceil(len(bc) / (1 - mix_ratio)))
    dagger_count = length - len(bc)
    mapping = []
    for index in range(length):
        before = index * dagger_count // length
        after = (index + 1) * dagger_count // length
        mapping.append(('dagger', before % len(dagger_skills)) if after > before
                       else ('bc', (index - before) % len(bc)))
    multiplicities = Counter(mapping)
    # A tiny BC corpus can expose fewer labels than the full DAgger inventory.
    # Balance only labels that the official mixture actually exposes.
    exposed = {i for group, i in mapping if group == 'dagger'}
    counts = Counter(dagger_skills[i] for i in exposed)
    result = [((1 - mix_ratio) * bc[i] / bc.sum() if group == 'bc'
               else mix_ratio / (len(counts) * counts[dagger_skills[i]]))
              / multiplicities[group, i] for group, i in mapping]
    return np.asarray(result, dtype=float)


def install_skill_sampler(spec, *, data_loader=None, sampler_factory=None):
    """Install an in-process official-loader adapter, returning restore + audit.

    Only the matching repo with shuffle=True and skip_norm_stats=False is
    affected. Source datasets, videos, normalization and vendor files are intact.
    The existing DAgger create_torch_dataset wrapper remains in place.
    """
    if data_loader is None:
        from openpi.training import data_loader
    if sampler_factory is None:
        import torch
        def sampler_factory(weights, seed):
            generator = torch.Generator().manual_seed(seed)
            return torch.utils.data.WeightedRandomSampler(
                weights, num_samples=len(weights), replacement=True, generator=generator)
    manifest = json.loads((Path(spec.dataset_root) / 'airport_training_manifest.json').read_text())
    if manifest.get('split') != 'train':
        raise ValueError('skill_sampling_requires_train_split')
    weights = bc_frame_weights(manifest['episodes'])
    bc_skills = sorted({row['skill'] for row in manifest['episodes']})
    bc_mass = 1 - spec.dagger_mix_ratio if spec.aggregation_manifest else 1.
    audit = {'method': 'skill_balanced_weighted_random_sampler', 'replacement': True,
             'normalization': 'unchanged_train_only', 'actual_loader_installed_count': 0,
             'bc_skill_probability_mass': {skill: bc_mass / len(bc_skills) for skill in bc_skills},
             'dagger_mix_ratio': spec.dagger_mix_ratio if spec.aggregation_manifest else None}
    if spec.aggregation_manifest:
        aggregation = json.loads(Path(spec.aggregation_manifest).read_text())
        rows = aggregation['interventions']
        prompts = {row['language_prompt']: row['skill'] for row in manifest['episodes']
                   if row.get('language_prompt')}
        # Known shared prompts resolve to the same public DAG skill. Unknown
        # goals remain separate exact prompt classes, never guessed as expert.
        labels = [row.get('skill') or prompts.get(row.get('prompt')) or row.get('prompt') for row in rows]
        if any(row.get('split') != 'train' for row in rows):
            raise ValueError('skill_sampling_dagger_holdout')
        weights = mixed_frame_weights(weights, labels, spec.dagger_mix_ratio)
        audit['dagger_goal_classes'] = sorted(set(labels))
    audit['sample_indices'] = len(weights)
    original = data_loader.create_torch_data_loader
    if getattr(original, '_airport_skill_balanced', False):
        raise ValueError('skill_sampler_already_installed')

    def balanced(data_config, *args, **kwargs):
        if (data_config.repo_id != spec.dataset_repo_id or not kwargs.get('shuffle', False)
                or kwargs.get('skip_norm_stats', False)):
            return original(data_config, *args, **kwargs)
        base_class = data_loader.TorchDataLoader
        class SkillLoader(base_class):
            def __init__(self, dataset, *loader_args, **loader_kwargs):
                if len(dataset) != len(weights):
                    raise ValueError('skill_sampling_dataset_length_mismatch')
                if loader_kwargs.get('sampler') is not None:
                    raise ValueError('skill_sampling_distributed_sampler_unsupported')
                loader_kwargs['sampler'] = sampler_factory(weights, loader_kwargs.get('seed', 0))
                loader_kwargs['shuffle'] = False
                super().__init__(dataset, *loader_args, **loader_kwargs)
                audit['actual_loader_installed_count'] += 1
        data_loader.TorchDataLoader = SkillLoader
        try:
            return original(data_config, *args, **kwargs)
        finally:
            data_loader.TorchDataLoader = base_class
    balanced._airport_skill_balanced = True
    data_loader.create_torch_data_loader = balanced
    def restore():
        data_loader.create_torch_data_loader = original
    return restore, audit
