"""Synthetic contract fixtures only; no fixture is an accepted physical source."""
import json
from pathlib import Path
import numpy as np
import pytest
from r1pro_teleop.vla.isaac_dataset import (
    CAMERAS, PROMPTS, sha, validate_episode, freeze_corpus)


def fixture(root, split='train', identity='source0'):
    root.mkdir()
    n = 12
    trace = root / 'trace.npz'
    np.savez(trace, time=np.arange(n + 1) * .05, state=np.zeros((n + 1, 19)),
        raw_action=np.zeros((n, 19)), action=np.zeros((n, 19)), submitted_control=np.zeros((n, 25, 21)),
        tray_pose=np.tile([0, 0, 0, 1, 0, 0, 0], (n + 1, 1)))
    # Unique bytes allow the duplicate-source guard to be exercised separately.
    with trace.open('ab') as f:
        f.write(identity.encode())
    (root / 'exit.json').write_text(json.dumps(dict(returncode=0, actual_child_wait=True)))
    qualification = dict(schema='airport_isaac_task_qualification/1', engine='isaacsim',
        physics_backend='physx', complete_task_success=True, trace_sha256=sha(trace),
        episode_id=identity, task_rule_revision='current')
    (root / 'qualification.json').write_text(json.dumps(qualification))
    videos = {}
    for camera in CAMERAS:
        p = root / (camera + '.mp4'); p.write_bytes(b'synthetic-not-video')
        videos[camera] = dict(path=p.name, sha256=sha(p))
    manifest = dict(schema='airport_isaac_episode/1', engine='isaacsim', physics_backend='physx',
        source='simulation/program_generated', execution_mode='expert_collection',
        free_run_diagnostic=False, episode_id=identity, parent_scene_id='parent_' + split,
        split=split, exit_receipt='exit.json', trace='trace.npz', qualification='qualification.json',
        task_rule_revision='current', fps=20, physics_dt=.002, substeps_per_frame=25,
        actions=[dict(prompt=p, start=s, end=e) for p, s, e in zip(PROMPTS, [0, 3, 8], [3, 6, 12])],
        payload_load_frame=6, videos=videos)
    (root / 'episode.json').write_text(json.dumps(manifest))
    return manifest


def probe(path):
    width, height = CAMERAS[Path(path).stem]
    return dict(width=width, height=height, frames=12, fps=20)


def test_episode_rejects_legacy_and_diagnostic_provenance(tmp_path):
    root = tmp_path / 'case'; m = fixture(root)
    assert validate_episode(root, {'parent_train': 'train'}, probe=probe)['frames'] == 12
    for key, value in [('engine', 'mujoco'), ('execution_mode', 'model_evaluation'),
                       ('free_run_diagnostic', True)]:
        wrong = dict(m, **{key: value})
        (root / 'episode.json').write_text(json.dumps(wrong))
        with pytest.raises(ValueError, match='provenance'):
            validate_episode(root, {'parent_train': 'train'}, probe=probe)


def test_split_exit_task_prompt_and_loading_gates(tmp_path):
    root = tmp_path / 'case'; m = fixture(root)
    with pytest.raises(ValueError, match='split_leakage'):
        validate_episode(root, {'parent_train': 'test'}, probe=probe)
    (root / 'exit.json').write_text(json.dumps(dict(returncode=-11, actual_child_wait=True)))
    with pytest.raises(ValueError, match='successful_process_exit'):
        validate_episode(root, {'parent_train': 'train'}, probe=probe)
    (root / 'exit.json').write_text(json.dumps(dict(returncode=0, actual_child_wait=True)))
    (root / 'episode.json').write_text(json.dumps(dict(m, payload_load_frame=9)))
    with pytest.raises(ValueError, match='payload_loading'):
        validate_episode(root, {'parent_train': 'train'}, probe=probe)
    m['actions'][0]['prompt'] += ' '
    (root / 'episode.json').write_text(json.dumps(m))
    with pytest.raises(ValueError, match='exact_three_prompts'):
        validate_episode(root, {'parent_train': 'train'}, probe=probe)


def test_native_video_frames_and_hash_are_not_optional(tmp_path):
    root = tmp_path / 'case'; fixture(root)
    def bad_probe(path):
        return dict(probe(path), frames=11)
    with pytest.raises(ValueError, match='time_alignment'):
        validate_episode(root, {'parent_train': 'train'}, probe=bad_probe)
    (root / 'left_wrist.mp4').write_bytes(b'changed')
    with pytest.raises(ValueError, match='hash_changed'):
        validate_episode(root, {'parent_train': 'train'}, probe=probe)


def test_episode_identifier_cannot_escape_action_directory(tmp_path):
    root = tmp_path / 'case'; m = fixture(root)
    m['episode_id'] = '../../old_collection'
    (root / 'episode.json').write_text(json.dumps(m))
    with pytest.raises(ValueError, match='safe_scene_and_episode'):
        validate_episode(root, {'parent_train': 'train'}, probe=probe)


def test_freeze_three_splits_and_action_indices_is_not_training_cache(tmp_path):
    roots = []
    registry = {}
    for split in ('train', 'val', 'test'):
        root = tmp_path / split; fixture(root, split, identity=split)
        roots.append(root); registry['parent_' + split] = split
    with pytest.raises(ValueError, match='requires_train_val_test'):
        freeze_corpus(roots[:1], registry, tmp_path / 'bad', probe=probe)
    manifest = freeze_corpus(roots, registry, tmp_path / 'frozen', probe=probe)
    assert manifest['full_sources'] == 3 and manifest['action_segments'] == 9
    assert manifest['data_index_ready'] and not manifest['training_cache_ready']
    assert len(list((tmp_path / 'frozen/by_action').glob('*/segments.jsonl'))) == 3
    with pytest.raises(FileExistsError):
        freeze_corpus(roots, registry, tmp_path / 'frozen', probe=probe)


def test_cache_keeps_action_boundaries_and_excludes_loading(tmp_path, monkeypatch):
    import r1pro_teleop.vla.isaac_dataset as module
    roots = []; registry = {}
    for split in ('train', 'val', 'test'):
        root = tmp_path / split; fixture(root, split, identity=split)
        roots.append(root); registry['parent_' + split] = split
    freeze_corpus(roots, registry, tmp_path / 'frozen', probe=probe)
    original = module.load_frozen
    monkeypatch.setattr(module, 'load_frozen', lambda path, registry: original(path, registry, probe=probe))
    calls = []
    def decode(path, indices, target):
        calls.append(indices.tolist())
        target[:] = indices[:, None, None, None]
        return 12
    module.materialize_cache(tmp_path / 'frozen/manifest.json', registry, tmp_path / 'cache', decode=decode)
    # Three cameras decoded exactly once per full source, not once per action.
    assert len(calls) == 9
    assert calls[0] == [0, 1, 2, 3, 4, 5, 8, 9, 10, 11]
    assert np.load(tmp_path / 'cache/train/end.npy').tolist() == [3, 3, 3, 6, 6, 6, 10, 10, 10, 10]
    assert np.load(tmp_path / 'cache/train/task.npy').tolist() == [0, 0, 0, 1, 1, 1, 2, 2, 2, 2]
    assert np.load(tmp_path / 'cache/train/state.npy').dtype == np.float32
    assert np.load(tmp_path / 'cache/train/head_left.npy').dtype == np.uint8
