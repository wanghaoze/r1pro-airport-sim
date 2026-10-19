import json
from types import SimpleNamespace

import numpy as np
import pytest

from r1pro_teleop.vla.skill_sampling import bc_frame_weights, mixed_frame_weights, install_skill_sampler


def episodes():
    return [{'episode_index': 0, 'split': 'train', 'skill': 'initialize_posture', 'frames': 2},
            {'episode_index': 1, 'split': 'train', 'skill': 'carry_tray', 'frames': 100},
            {'episode_index': 2, 'split': 'train', 'skill': 'initialize_posture', 'frames': 3}]


def test_bc_balances_skill_mass_without_changing_frame_count():
    w = bc_frame_weights(episodes(), 105)
    assert w.shape == (105,)
    assert w[:2].sum() + w[-3:].sum() == pytest.approx(.5)
    assert w[2:102].sum() == pytest.approx(.5)
    # A seeded draw uses only the original indices and exposes rare skill often.
    indices = np.random.default_rng(123).choice(len(w), 10000, p=w)
    assert np.count_nonzero((indices < 2) | (indices >= 102)) / len(indices) == pytest.approx(.5, abs=.02)


def test_bc_rejects_holdout_unordered_and_wrong_frame_count():
    for change in ({'split': 'val'}, {'episode_index': 10}, {'frames': 0}, {'frames': True}):
        rows = episodes(); rows[0].update(change)
        with pytest.raises(ValueError): bc_frame_weights(rows)
    with pytest.raises(ValueError): bc_frame_weights(episodes(), 106)


def test_mixed_preserves_dagger_mass_despite_uneven_repeated_labels():
    bc = bc_frame_weights(episodes())
    skills = ['initialize_posture', 'initialize_posture', 'grasp_lift_tray']
    ratio = .2
    weights = mixed_frame_weights(bc, skills, ratio)
    dagger_count = len(weights) - len(bc)
    mass = {'bc': 0., 'initialize_posture': 0., 'grasp_lift_tray': 0.}
    for i, weight in enumerate(weights):
        before = i * dagger_count // len(weights)
        after = (i+1) * dagger_count // len(weights)
        key = skills[before % len(skills)] if after > before else 'bc'
        mass[key] += weight
    assert mass == pytest.approx({'bc': .8, 'initialize_posture': .1, 'grasp_lift_tray': .1})
    assert sum(weights) == pytest.approx(1.)


def test_official_loader_adapter_scoped_train_only_and_restored(tmp_path):
    (tmp_path/'airport_training_manifest.json').write_text(json.dumps({'split': 'train', 'episodes': episodes()}))
    spec = SimpleNamespace(dataset_root=str(tmp_path), dataset_repo_id='airport/train', aggregation_manifest=None)
    calls = []
    class Loader:
        def __init__(self, dataset, **kwargs): self.kwargs=kwargs
    module = SimpleNamespace(TorchDataLoader=Loader)
    def official(config, **kwargs):
        return module.TorchDataLoader(range(105), sampler=None, shuffle=kwargs.get('shuffle',False), seed=73)
    module.create_torch_data_loader=official
    def sampler(weights, seed):
        calls.append((weights.copy(), seed)); return 'actual_sampler'
    restore, audit = install_skill_sampler(spec, data_loader=module, sampler_factory=sampler)
    assert audit['actual_loader_installed_count'] == 0
    assert audit['bc_skill_probability_mass'] == {'carry_tray': .5, 'initialize_posture': .5}
    assert module.create_torch_data_loader(SimpleNamespace(repo_id='elsewhere'),shuffle=True).kwargs['sampler'] is None
    assert module.create_torch_data_loader(SimpleNamespace(repo_id='airport/train'),shuffle=True,skip_norm_stats=True).kwargs['sampler'] is None
    assert module.create_torch_data_loader(SimpleNamespace(repo_id='airport/train'),shuffle=False).kwargs['sampler'] is None
    loaded = module.create_torch_data_loader(SimpleNamespace(repo_id='airport/train'),shuffle=True)
    assert loaded.kwargs['sampler']=='actual_sampler'
    assert loaded.kwargs['shuffle'] is False
    assert len(calls)==1 and calls[0][1]==73
    assert audit['actual_loader_installed_count'] == 1
    json.dumps(audit, allow_nan=False)
    assert module.TorchDataLoader is Loader
    assert audit['normalization']=='unchanged_train_only'
    restore(); assert module.create_torch_data_loader is official


def test_loader_failure_restores_class(tmp_path):
    (tmp_path/'airport_training_manifest.json').write_text(json.dumps({'split':'train','episodes':episodes()}))
    spec=SimpleNamespace(dataset_root=str(tmp_path),dataset_repo_id='airport/train',aggregation_manifest=None)
    class Loader: pass
    module=SimpleNamespace(TorchDataLoader=Loader)
    def official(config, **kwargs): return module.TorchDataLoader(range(1),sampler=None)
    module.create_torch_data_loader=official
    restore,_=install_skill_sampler(spec,data_loader=module,sampler_factory=lambda *_:None)
    with pytest.raises(ValueError,match='length_mismatch'):
        module.create_torch_data_loader(SimpleNamespace(repo_id='airport/train'),shuffle=True)
    assert module.TorchDataLoader is Loader
    restore()
