import dataclasses
import hashlib
import json
from pathlib import Path
import h5py
import numpy as np
import pytest
from r1pro_teleop.vla.dagger import DaggerRound, ExpertLabel, aggregation_manifest, state_digest
from r1pro_teleop.vla.dagger_dataset import DaggerChunkDataset, BCMixedDaggerDataset
from r1pro_teleop.vla.teacher import SimulationExpert


def prepare(tmp_path):
    checkpoint = tmp_path / 'checkpoint/params'; checkpoint.mkdir(parents=True)
    (checkpoint / 'weights').write_bytes(b'weights')
    state = {'qpos': np.arange(19.), 'qvel': np.zeros(19), 'ctrl': np.zeros(19), 'time': np.array(.5)}
    actions = np.full((3, 19), .125, np.float32)
    teacher = tmp_path / 'teacher'; teacher.mkdir()
    artifact = teacher / 'trace.h5'
    with h5py.File(artifact, 'w') as trace:
        trace['action'] = actions[:, :16]; trace['base_action'] = actions[:, 16:]
        trace['qpos'] = np.tile(state['qpos'], (3, 1)); trace['qvel'] = np.zeros((3, 19))
        trace['transition_completed'] = np.ones(3, bool)
    (teacher / 'teacher_metadata.json').write_text(json.dumps({'status': 'label_verified',
        'start_state_sha256': state_digest(state), 'teacher_trace_sha256': hashlib.sha256(artifact.read_bytes()).hexdigest()}))
    obs = {'state': np.arange(19, dtype=np.float32), 'prompt': 'push tray', **{
        'image/' + key: np.full((8, 9, 3), 123, np.uint8) for key in ('head_left', 'left_wrist', 'right_wrist')}}
    round_ = DaggerRound(tmp_path / 'round', checkpoint.parent, round_index=1, train_scene_ids=['scene1'])
    def expert(snapshot, observation):
        return ExpertLabel(state_digest(snapshot), actions, 'simulation_expert', replanned_from_learner_state=True,
                           planning_verified=True, teacher_artifact=str(artifact))
    round_.collect_intervention(scene_id='scene1', split='train', simulator_state=state,
                                observation=obs, learner_action=np.full((3, 19), 9.), expert_replan=expert,
                                verify_label=SimulationExpert.verify_label, reason='learner_error')
    round_.finalize()
    manifest = tmp_path / 'aggregate.json'
    aggregation_manifest([round_.directory], manifest, train_scene_ids=['scene1'])
    return manifest


def test_one_real_observation_per_verified_chunk(tmp_path):
    dataset = DaggerChunkDataset(prepare(tmp_path), action_horizon=2, train_scene_ids=['scene1'])
    assert len(dataset) == 1
    sample = dataset[0]
    assert sample['action'].shape == (2, 19)
    assert np.all(sample['action'] == .125)
    assert sample['observation.images.head_left'].shape == (8, 9, 3)
    sample['action'][:] = 100
    assert np.all(dataset[0]['action'] == .125)


@pytest.mark.parametrize('mode', ['short', 'wrong_split', 'modified_image', 'modified_label'])
def test_invalid_training_samples_rejected(tmp_path, mode):
    path = prepare(tmp_path)
    manifest = json.loads(path.read_text()); row = manifest['interventions'][0]
    if mode == 'modified_image':
        np.save(Path(row['sample_dir']) / 'head_left.npy', np.zeros((8, 9, 3), np.uint8))
    if mode == 'modified_label': (Path(row['sample_dir']) / 'label.npz').write_bytes(b'changed')
    with pytest.raises(ValueError):
        DaggerChunkDataset(path, action_horizon=4 if mode == 'short' else 2,
                           train_scene_ids=['other_scene'] if mode == 'wrong_split' else ['scene1'])


def test_bc_dagger_mixture_counts_chunks(tmp_path):
    dagger = DaggerChunkDataset(prepare(tmp_path), action_horizon=2, train_scene_ids=['scene1'])
    bc = [{'bc': index} for index in range(10)]
    mixed = BCMixedDaggerDataset(bc, dagger, .5)
    assert len(mixed) == 20
    samples = [mixed[i] for i in range(20)]
    assert sum('bc' in sample for sample in samples) == 10
    assert sorted(sample['bc'] for sample in samples if 'bc' in sample) == list(range(10))


def test_dagger_parent_must_be_trained_and_shape_compatible(tmp_path):
    from test_vla_training import make_spec
    spec = make_spec(tmp_path)
    params = Path(spec.base_params)
    stats = tmp_path / 'norm_stats.json'; stats.write_text('{}')
    parent_spec = dataclasses.asdict(spec)
    parent = {'status': 'checkpoint_saved', 'checkpoint_verified': True, 'model': 'pi05',
              'training_steps': 10, 'fps': 20, 'action_semantics': 'absolute_mobile19',
              'checkpoint': str(params.parent), 'normalization': str(stats), 'spec': parent_spec}
    status = tmp_path / 'parent_status.json'; status.write_text(json.dumps(parent))
    aggregate = tmp_path / 'aggregate.json'; aggregate.write_text(json.dumps({
        'status': 'aggregation_manifest_not_trained', 'interventions': [{'sample': 'requires_loader_validation'}]}))
    child = dataclasses.replace(spec, aggregation_manifest=str(aggregate), parent_trained_status=str(status))
    child.validate()
    with pytest.raises(ValueError, match='semantics changed'):
        dataclasses.replace(child, lora=False).validate()
    parent['status'] = 'training'; status.write_text(json.dumps(parent))
    with pytest.raises(ValueError, match='not actually'):
        child.validate()
