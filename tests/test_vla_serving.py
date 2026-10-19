import dataclasses
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import pytest
from scripts import serve_pi05_airport as serving
from r1pro_teleop.vla.training import TrainingSpec


def saved_run(tmp_path):
    run = tmp_path / 'run'
    spec = TrainingSpec(dataset_root=str(tmp_path / 'data'), dataset_repo_id='airport/train',
                        openpi_root=str(tmp_path / 'openpi'), base_params=str(tmp_path / 'base/params'),
                        run_dir=str(run), num_train_steps=10, action_horizon=20)
    checkpoint = run / 'checkpoints' / spec.name / 'training' / '9'
    for folder in ('params', 'train_state'):
        (checkpoint / folder).mkdir(parents=True)
        (checkpoint / folder / 'weights').write_bytes(b'actual-test-bytes')
    norms = checkpoint / 'assets' / spec.dataset_repo_id / 'norm_stats.json'
    norms.parent.mkdir(parents=True)
    norms.write_text('{"state": {}}', encoding='utf-8')
    status = {'status': 'checkpoint_saved', 'checkpoint_verified': True, 'model': 'pi05',
              'action_semantics': 'absolute_mobile19', 'fps': 20,
              'source': 'simulation/program_generated', 'training_steps': 10,
              'checkpoint_step': 9, 'spec': dataclasses.asdict(spec), 'checkpoint': str(checkpoint)}
    path = run / 'training_status.json'
    path.write_text(json.dumps(status), encoding='utf-8')
    return path, status, checkpoint


def rewrite(path, status):
    path.write_text(json.dumps(status), encoding='utf-8')


def test_language_mode_requires_explicit_matching_training_receipt(tmp_path):
    path, status, _ = saved_run(tmp_path)
    status['spec']['prompt_mode'] = 'skill_only_v1'
    rewrite(path, status)
    with pytest.raises(ValueError, match='prompt mode'):
        serving.verify_training_checkpoint(path)
    status['prompt_mode'] = 'skill_only_v1'
    rewrite(path, status)
    assert serving.verify_training_checkpoint(path)[2]['prompt_mode'] == 'skill_only_v1'


def test_old_status_without_language_mode_remains_legacy(tmp_path):
    path, status, _ = saved_run(tmp_path)
    status['spec'].pop('prompt_mode')
    rewrite(path, status)
    assert serving.verify_training_checkpoint(path)[0].prompt_mode == 'legacy'


def test_identity_binds_real_parameter_bytes_and_training_manifest(tmp_path):
    path, status, checkpoint = saved_run(tmp_path)
    _, _, identity = serving.verify_training_checkpoint(path)
    assert identity['checkpoint_id'].startswith('sha256:')
    assert identity == serving.verify_training_checkpoint(path)[2]
    (checkpoint / 'params/weights').write_bytes(b'different learned weights')
    assert identity['checkpoint_id'] != serving.verify_training_checkpoint(path)[2]['checkpoint_id']


@pytest.mark.parametrize('state', ['training', 'normalized_only', 'failed', 'initializing'])
def test_unfinished_training_not_advertised_as_finetuned(tmp_path, state):
    path, status, _ = saved_run(tmp_path)
    status['status'] = state
    rewrite(path, status)
    with pytest.raises(ValueError, match='completed'):
        serving.verify_training_checkpoint(path)


@pytest.mark.parametrize('steps', [0, -1, True, '10'])
def test_positive_completed_training_step_required(tmp_path, steps):
    path, status, _ = saved_run(tmp_path)
    status['training_steps'] = steps
    rewrite(path, status)
    with pytest.raises(ValueError, match='positive'):
        serving.verify_training_checkpoint(path)


@pytest.mark.parametrize('component', ['params/weights', 'train_state/weights',
                                      'assets/airport/train/norm_stats.json'])
def test_incomplete_checkpoint_rejected_before_loader(tmp_path, component):
    path, _, checkpoint = saved_run(tmp_path)
    (checkpoint / component).unlink()
    with pytest.raises(ValueError, match='Incomplete|normalization'):
        serving.verify_training_checkpoint(path)


def test_base_checkpoint_path_not_accepted(tmp_path):
    path, status, _ = saved_run(tmp_path)
    status['checkpoint'] = status['spec']['base_params']
    rewrite(path, status)
    with pytest.raises(ValueError, match='declared airport training run'):
        serving.verify_training_checkpoint(path)


def test_official_loader_restores_exact_verified_path_then_advertises_metadata(tmp_path, monkeypatch):
    path, _, checkpoint = saved_run(tmp_path)
    config, policy = object(), object()
    calls = []
    monkeypatch.setattr(serving, 'register_openpi_config', lambda spec: config)
    def restore(actual_config, actual_checkpoint):
        calls.append((actual_config, actual_checkpoint))
        return policy
    monkeypatch.setitem(sys.modules, 'openpi', SimpleNamespace())
    monkeypatch.setitem(sys.modules, 'openpi.policies', SimpleNamespace(
        policy_config=SimpleNamespace(create_trained_policy=restore)))
    loaded, metadata, identity = serving.load_airport_policy(path)
    assert loaded is policy and calls == [(config, checkpoint)]
    assert metadata['checkpoint_id'] == identity['checkpoint_id']
    assert metadata['fine_tuned'] is True
    assert metadata['action_width'] == 19 and metadata['action_horizon'] == 20
    assert metadata['action_space'] == 'mobile19_absolute_v1'
    assert metadata['control_hz'] == 20 and metadata['model'] == 'pi05'
    assert metadata['denoising_steps'] == 10


@pytest.mark.parametrize('steps', [20, 30, 50])
def test_alternate_sampler_restores_same_weights_and_publishes_actual_setting(tmp_path, monkeypatch, steps):
    path, _, checkpoint = saved_run(tmp_path)
    expected_identity = serving.verify_training_checkpoint(path)[2]
    config = object()
    calls = []
    monkeypatch.setattr(serving, 'register_openpi_config', lambda spec: config)
    def restore(actual_config, actual_checkpoint, *, sample_kwargs):
        calls.append((actual_config, actual_checkpoint, sample_kwargs))
        return SimpleNamespace(_sample_kwargs=dict(sample_kwargs))
    monkeypatch.setitem(sys.modules, 'openpi', SimpleNamespace())
    monkeypatch.setitem(sys.modules, 'openpi.policies', SimpleNamespace(
        policy_config=SimpleNamespace(create_trained_policy=restore)))
    _, metadata, identity = serving.load_airport_policy(path, denoising_steps=steps)
    assert calls == [(config, checkpoint, {'num_steps': steps})]
    assert identity == expected_identity
    assert metadata['denoising_steps'] == steps
    assert metadata['checkpoint_id'] == expected_identity['checkpoint_id']


@pytest.mark.parametrize('steps', [0, -1, 11, True, 20.0, '20'])
def test_invalid_sampler_rejected_before_checkpoint_or_model_load(monkeypatch, steps):
    def unexpected(*args):
        pytest.fail('invalid sampler must not load model or checkpoint')
    monkeypatch.setattr(serving, 'verify_training_checkpoint', unexpected)
    with pytest.raises(ValueError, match='denoising_steps'):
        serving.load_airport_policy('unused', denoising_steps=steps)


def test_ignored_sampler_setting_cannot_be_advertised(tmp_path, monkeypatch):
    path, _, _ = saved_run(tmp_path)
    monkeypatch.setattr(serving, 'register_openpi_config', lambda spec: object())
    monkeypatch.setitem(sys.modules, 'openpi', SimpleNamespace())
    monkeypatch.setitem(sys.modules, 'openpi.policies', SimpleNamespace(
        policy_config=SimpleNamespace(create_trained_policy=lambda *a, **k: SimpleNamespace(_sample_kwargs={}))))
    with pytest.raises(ValueError, match='did not retain'):
        serving.load_airport_policy(path, denoising_steps=20)


def test_restore_failure_never_serves_metadata(tmp_path, monkeypatch):
    path, _, _ = saved_run(tmp_path)
    monkeypatch.setattr(serving, 'register_openpi_config', lambda spec: object())
    def failed_restore(*_):
        raise RuntimeError('checkpoint restore incomplete')
    monkeypatch.setitem(sys.modules, 'openpi', SimpleNamespace())
    monkeypatch.setitem(sys.modules, 'openpi.policies', SimpleNamespace(
        policy_config=SimpleNamespace(create_trained_policy=failed_restore)))
    with pytest.raises(RuntimeError, match='restore incomplete'):
        serving.load_airport_policy(path)


def milestone_run(tmp_path):
    path, status, checkpoint = saved_run(tmp_path)
    status.update(schema='airport_pi05_training_milestone/1',
                  status='milestone_checkpoint', actual_completed_updates=10,
                  planned_total_steps=100000, prompt_mode='task_complete_action8_v1')
    status['spec'].update(num_train_steps=100000, prompt_mode='task_complete_action8_v1')
    dataset = Path(status['spec']['dataset_root'])
    dataset.mkdir()
    source = dataset / 'whole_action_source_manifest.jsonl'
    source.write_text('{"scene_id":"fixture_train"}\n')
    sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    status['dataset_source_manifest_sha256'] = sha(source)
    manifest = dataset / 'airport_training_manifest.json'
    manifest.write_text(json.dumps(dict(dataset_ready=True, split='train',
        repo_id=status['spec']['dataset_repo_id'], prompt_mode='task_complete_action8_v1',
        source_manifest_sha256=sha(source))))
    status['dataset_training_manifest_sha256'] = sha(manifest)
    cache = path.parent / 'data_cache/cache_manifest.json'
    cache.parent.mkdir()
    cache.write_text('{"fixture":true}')
    acceleration = path.parent / 'acceleration_spec.json'
    acceleration.write_text('{"backend":"jax_dp","freeze_visual_encoder":true}')
    status.update(cache_manifest=str(cache), cache_manifest_sha256=sha(cache),
                  acceleration_spec=str(acceleration), acceleration_spec_sha256=sha(acceleration),
                  norm_sha256=sha(checkpoint/'assets'/status['spec']['dataset_repo_id']/'norm_stats.json'))
    rewrite(path, status)
    return path, status, checkpoint


def test_saved_milestone_serves_real_weights_without_claiming_finished_budget(tmp_path, monkeypatch):
    path, _, checkpoint = milestone_run(tmp_path)
    monkeypatch.setattr(serving, 'register_openpi_config', lambda spec: object())
    calls = []
    def restore(config, actual_checkpoint):
        calls.append(actual_checkpoint)
        return object()
    monkeypatch.setitem(sys.modules, 'openpi', SimpleNamespace())
    monkeypatch.setitem(sys.modules, 'openpi.policies', SimpleNamespace(
        policy_config=SimpleNamespace(create_trained_policy=restore)))
    _, metadata, identity = serving.load_airport_policy(path)
    assert calls == [checkpoint]
    assert metadata['training_complete'] is False
    assert metadata['training_steps'] == metadata['actual_completed_updates'] == 10
    assert metadata['planned_total_steps'] == 100000
    assert identity['resume_state_files'][0]['path'] == 'train_state/weights'


@pytest.mark.parametrize('changes', [
    {'schema': 'airport_pi05_training_milestone/unknown'},
    {'actual_completed_updates': 9}, {'actual_completed_updates': True},
    {'planned_total_steps': 10000}, {'planned_total_steps': True},
    {'training_steps': 100001, 'actual_completed_updates': 100001},
    {'checkpoint_step': 8}, {'status': 'training'},
])
def test_milestone_rejects_inconsistent_or_unverified_receipt(tmp_path, changes):
    path, status, _ = milestone_run(tmp_path)
    status.update(changes)
    rewrite(path, status)
    with pytest.raises(ValueError):
        serving.verify_training_checkpoint(path)


def test_milestone_binds_resume_state_bytes_to_identity(tmp_path):
    path, _, checkpoint = milestone_run(tmp_path)
    identity = serving.verify_training_checkpoint(path)[2]['checkpoint_id']
    (checkpoint / 'train_state/weights').write_bytes(b'changed optimizer state')
    assert serving.verify_training_checkpoint(path)[2]['checkpoint_id'] != identity


def test_partial_steps_without_milestone_schema_still_rejected(tmp_path):
    path, status, _ = saved_run(tmp_path)
    status['spec']['num_train_steps'] = 100000
    rewrite(path, status)
    with pytest.raises(ValueError, match='steps disagree'):
        serving.verify_training_checkpoint(path)


@pytest.mark.parametrize('artifact', [
    'data_cache/cache_manifest.json',
    'acceleration_spec.json',
    '../data/airport_training_manifest.json', '../data/whole_action_source_manifest.jsonl',
])
def test_milestone_rejects_changed_input_artifacts(tmp_path, artifact):
    path, _, _ = milestone_run(tmp_path)
    (path.parent / artifact).write_text('changed input')
    with pytest.raises(ValueError, match='hash disagrees'):
        serving.verify_training_checkpoint(path)


def test_milestone_cannot_serve_validation_or_unfinished_data(tmp_path):
    path, status, _ = milestone_run(tmp_path)
    manifest = Path(status['spec']['dataset_root'])/'airport_training_manifest.json'
    body = json.loads(manifest.read_text())
    body.update(split='test', dataset_ready=False)
    manifest.write_text(json.dumps(body))
    status['dataset_training_manifest_sha256'] = hashlib.sha256(manifest.read_bytes()).hexdigest()
    rewrite(path, status)
    with pytest.raises(ValueError, match='ready train split'):
        serving.verify_training_checkpoint(path)


def test_milestone_norm_hash_must_match_saved_checkpoint(tmp_path):
    path, _, checkpoint = milestone_run(tmp_path)
    (checkpoint/'assets/airport/train/norm_stats.json').write_text('changed norm')
    with pytest.raises(ValueError, match='normalization hash disagrees'):
        serving.verify_training_checkpoint(path)
