import json
import numpy as np
import pytest
from r1pro_teleop.vla.training import AirportInputs, AirportOutputs, TrainingSpec, resolved_lr_schedule


def _spawn_script_transform(transform):
    return type(transform).__module__, transform({'state': [1, 2], 'prompt': 'drop'})


def observation():
    return {"state": np.zeros(19), "actions": np.zeros((20, 19)), "prompt": "push tray",
            **{"image/" + key: np.ones((3, 8, 9), np.float32) for key in ("head_left", "left_wrist", "right_wrist")}}


def test_mobile19_native_image_conversion():
    result = AirportInputs()(observation())
    assert result["image"]["base_0_rgb"].shape == (8, 9, 3)
    assert result["image"]["base_0_rgb"].dtype == np.uint8
    assert np.all(result["image"]["base_0_rgb"] == 255)
    assert result["actions"].shape == (20, 19)
    assert set(result["image"]) == {"base_0_rgb", "left_wrist_0_rgb", "right_wrist_0_rgb"}


@pytest.mark.parametrize("field,value", [("state", np.zeros(18)), ("state", np.full(19, np.nan)),
                                         ("actions", np.zeros((20, 32)))])
def test_adapter_rejects_bad_schema(field, value):
    data = observation(); data[field] = value
    with pytest.raises(ValueError): AirportInputs()(data)


def test_outputs_trim_padding_keep_absolute():
    values = np.arange(640).reshape(20, 32)
    np.testing.assert_array_equal(AirportOutputs()({"actions": values})["actions"], values[:, :19])


def make_spec(tmp_path):
    dataset = tmp_path / "datasets/airport/train"; (dataset / "meta").mkdir(parents=True)
    features = {key: {"shape": [19]} for key in ("observation.state", "action")}
    features.update({"observation.images." + key: {"shape": [8, 9, 3]} for key in ("head_left", "left_wrist", "right_wrist")})
    (dataset / "meta/info.json").write_text(json.dumps({"fps": 20, "features": features, "total_frames": 100}))
    (dataset / "airport_training_manifest.json").write_text(json.dumps({"split": "train", "fps": 20,
        "action_semantics": "absolute_mobile19", "state_semantics": "measured_joint16_plus_base_origin_offset3",
        "episodes": [{"split": "train", "scene_id": "airport_1"}]}))
    source = tmp_path / "openpi/src/openpi/training"; source.mkdir(parents=True)
    (source / "config.py").write_text("")
    params = tmp_path / "params"; params.mkdir(); (params / "weights").write_bytes(b"test")
    return TrainingSpec(str(dataset), "airport/train", str(tmp_path / "openpi"), str(params), str(tmp_path / "run"))


def test_train_split_provenance(tmp_path):
    spec = make_spec(tmp_path); spec.validate()
    path = __import__('pathlib').Path(spec.dataset_root) / "airport_training_manifest.json"
    manifest = json.loads(path.read_text()); manifest["episodes"][0]["split"] = "test"
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="leaked"): spec.validate()


def test_dagger_cannot_silently_change_parent_language_mode(tmp_path):
    import dataclasses
    from pathlib import Path
    spec = make_spec(tmp_path)
    parent_spec = dataclasses.asdict(spec)
    parent_spec.pop('prompt_mode')  # Real historical parents have no field.
    parent = tmp_path / 'parent.json'
    parent.write_text(json.dumps(dict(status='checkpoint_saved', checkpoint_verified=True,
        model='pi05', training_steps=1000, fps=20, action_semantics='absolute_mobile19',
        checkpoint=str(Path(spec.base_params).parent), spec=parent_spec)))
    candidate = dataclasses.replace(spec, prompt_mode='skill_only_v1',
        parent_trained_status=str(parent), aggregation_manifest=str(tmp_path / 'aggregate.json'))
    with pytest.raises(ValueError, match='semantics changed: prompt_mode'):
        candidate.validate()


def test_missing_checkpoint_fails_before_training(tmp_path):
    import dataclasses
    spec = dataclasses.replace(make_spec(tmp_path), base_params=str(tmp_path / "missing"))
    with pytest.raises(ValueError, match="checkpoint"): spec.validate()


@pytest.mark.parametrize('steps,warmup', [(1, 0), (250, 25), (1000, 100), (10000, 1000), (30000, 1000)])
def test_short_and_long_run_lr_warmup(tmp_path, steps, warmup):
    import dataclasses
    spec = dataclasses.replace(make_spec(tmp_path), num_train_steps=steps)
    schedule = resolved_lr_schedule(spec)
    assert schedule['warmup_steps'] == warmup
    assert schedule['decay_steps'] == steps
    assert schedule['peak_lr'] > schedule['decay_lr'] > 0


@pytest.mark.parametrize('changes', [{'lr_warmup_steps': 250}, {'lr_warmup_steps': -1},
    {'lr_warmup_steps': True}, {'lr_peak': float('nan')}, {'lr_peak': 0}, {'lr_end': 1}])
def test_invalid_lr_schedule_rejected(tmp_path, changes):
    import dataclasses
    spec = dataclasses.replace(make_spec(tmp_path), num_train_steps=250, **changes)
    with pytest.raises(ValueError): spec.validate()


def test_dagger_round_can_choose_different_lr(tmp_path):
    import dataclasses
    spec = dataclasses.replace(make_spec(tmp_path), num_train_steps=250, lr_peak=5e-5, lr_end=5e-6,
                               lr_warmup_steps=10)
    assert resolved_lr_schedule(spec) == {'warmup_steps': 10, 'peak_lr': 5e-5,
                                         'decay_steps': 250, 'decay_lr': 5e-6}


def test_official_script_transform_importable_in_spawn_worker(tmp_path):
    import multiprocessing
    import sys
    from r1pro_teleop.vla.training import _load_script
    directory = tmp_path / 'openpi/scripts'; directory.mkdir(parents=True)
    (directory / 'compute_norm_stats.py').write_text(
        'class RemoveStrings:\n'
        '    def __call__(self, data):\n'
        '        return {key: value for key, value in data.items() if not isinstance(value, str)}\n')
    prior_path = sys.path[:]
    prior_module = sys.modules.pop('compute_norm_stats', None)
    try:
        module = _load_script(tmp_path / 'openpi', 'compute_norm_stats.py')
        assert module.__name__ == 'compute_norm_stats'
        with multiprocessing.get_context('spawn').Pool(1) as pool:
            result = pool.apply(_spawn_script_transform, (module.RemoveStrings(),))
        assert result == ('compute_norm_stats', {'state': [1, 2]})
    finally:
        sys.path[:] = prior_path
        sys.modules.pop('compute_norm_stats', None)
        if prior_module is not None:
            sys.modules['compute_norm_stats'] = prior_module


def test_official_script_import_rejects_foreign_module(tmp_path):
    import sys
    from types import ModuleType
    from r1pro_teleop.vla.training import _load_script
    directory = tmp_path / 'openpi/scripts'; directory.mkdir(parents=True)
    (directory / 'compute_norm_stats.py').write_text('')
    foreign = ModuleType('compute_norm_stats'); foreign.__file__ = str(tmp_path / 'foreign.py')
    prior = sys.modules.get('compute_norm_stats')
    prior_path = sys.path[:]
    sys.modules['compute_norm_stats'] = foreign
    try:
        with pytest.raises(ValueError, match='pinned official source'):
            _load_script(tmp_path / 'openpi', 'compute_norm_stats.py')
    finally:
        sys.path[:] = prior_path
        sys.modules.pop('compute_norm_stats', None)
        if prior is not None:
            sys.modules['compute_norm_stats'] = prior


def test_jax_cache_redirect_only_changes_cache_update_and_restores(tmp_path):
    from r1pro_teleop.vla.training import redirect_jax_compilation_cache
    class Config:
        def __init__(self): self.calls = []
        def update(self, name, val): self.calls.append((name, val))
    config = Config(); original = config.update
    with redirect_jax_compilation_cache(config, tmp_path / 'resources/jax_cache'):
        config.update('jax_compilation_cache_dir', '~/.cache/jax')
        config.update('jax_enable_x64', False)
        config.update(name='jax_compilation_cache_dir', val='/foreign/cache')
    assert config.update == original
    assert 'update' not in config.__dict__
    assert config.calls == [('jax_compilation_cache_dir', str((tmp_path / 'resources/jax_cache').resolve())),
                            ('jax_enable_x64', False),
                            ('jax_compilation_cache_dir', str((tmp_path / 'resources/jax_cache').resolve()))]


def test_jax_cache_redirect_restores_on_exception(tmp_path):
    from r1pro_teleop.vla.training import redirect_jax_compilation_cache
    from types import SimpleNamespace
    calls = []
    original = lambda *args, **kwargs: calls.append((args, kwargs))
    config = SimpleNamespace(update=original)
    with pytest.raises(RuntimeError):
        with redirect_jax_compilation_cache(config, tmp_path / 'cache'):
            config.update('unrelated_setting', 1)
            raise RuntimeError('training_failure')
    assert config.update is original
    assert calls == [(('unrelated_setting', 1), {})]


def test_project_jax_cache_path_comes_from_project_owned_openpi(tmp_path):
    import dataclasses
    from r1pro_teleop.vla.training import project_jax_cache_dir
    spec = dataclasses.replace(make_spec(tmp_path), openpi_root=str(tmp_path / 'third_party/openpi'),
                               run_dir=str(tmp_path / 'runs/round1'))
    assert project_jax_cache_dir(spec) == tmp_path / 'resources/jax_cache'


@pytest.mark.parametrize('value', [1, 'true', None])
def test_skill_sampling_requires_explicit_boolean(tmp_path, value):
    import dataclasses
    spec = dataclasses.replace(make_spec(tmp_path), bc_skill_balance=value)
    with pytest.raises(ValueError, match='bc_skill_balance'):
        spec.validate()


@pytest.mark.parametrize("visible_devices", [1, 2])
def test_training_failure_restores_sampler_and_persists_actual_audit(tmp_path, monkeypatch, visible_devices):
    import dataclasses
    import sys
    from pathlib import Path
    from types import SimpleNamespace
    from r1pro_teleop.vla import training, skill_sampling
    spec = dataclasses.replace(make_spec(tmp_path), bc_skill_balance=True)
    config = SimpleNamespace(name=spec.name, assets_dirs=tmp_path / 'assets',
                             checkpoint_dir=tmp_path / 'checkpoints')
    monkeypatch.setenv('HF_LEROBOT_HOME', str(Path(spec.dataset_root).parents[1]))
    monkeypatch.setattr(training, 'register_openpi_config', lambda value: config)
    def normalization(name):
        path = config.assets_dirs / spec.dataset_repo_id / 'norm_stats.json'
        path.parent.mkdir(parents=True)
        path.write_text('{}')
    def train(value):
        audit['actual_loader_installed_count'] += 1
        raise RuntimeError('actual_trainer_error')
    monkeypatch.setattr(training, '_load_script', lambda root, filename:
                        SimpleNamespace(main=normalization if filename == 'compute_norm_stats.py' else train))
    restored = []
    audit = {'actual_loader_installed_count': 0}
    monkeypatch.setattr(skill_sampling, 'install_skill_sampler', lambda value:
                        (lambda: restored.append(True), audit))
    monkeypatch.setitem(sys.modules, 'jax', SimpleNamespace(config=SimpleNamespace(update=lambda *args, **kwargs: None), device_count=lambda: visible_devices))
    from contextlib import contextmanager
    from r1pro_teleop.vla import training_preview
    adapter_called=[]
    @contextmanager
    def preview(module, path, **kwargs):
        adapter_called.append(kwargs['bridge_inputs'])
        yield {'scope':'fixture_actual_device_gate'}
    monkeypatch.setattr(training_preview,'host_first_training_preview',preview)
    with pytest.raises(RuntimeError, match='actual_trainer_error'):
        training.launch_training(spec)
    assert restored == [True]
    assert adapter_called == ([True] if visible_devices == 2 else [])
    status = json.loads((Path(spec.run_dir) / 'training_status.json').read_text())
    assert status['status'] == 'failed'
    assert status['training_steps'] == 0 and status['checkpoint_verified'] is False
    assert status['sampling_audit']['actual_loader_installed_count'] == 1
