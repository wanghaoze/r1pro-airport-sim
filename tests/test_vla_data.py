import json
from pathlib import Path

import h5py
import numpy as np
import pytest

from r1pro_teleop.vla.data import prepare_manifest, read_mobile19_segment, digest


def fixture(tmp_path, *, split='train', success=True, name='source'):
    root = tmp_path / name
    attempt = root / 'attempts' / 'scene1' / 'a000'
    attempt.mkdir(parents=True)
    (root / 'scenes').mkdir()
    def write(path, value):
        path.write_text(json.dumps(value), encoding='utf-8')
    write(root / 'collection.json', {'fingerprint': 'frozen'})
    write(root / 'scenes/index.json', [{'scene_id': 'scene1', 'split': split, 'source_json_sha256': 'original'}])
    write(attempt / 'result.json', {'physics_success': success, 'task_completed': success, 'strict_success': success})
    segment = {'segment_id': 'source_segment', 'scene_id': 'scene1', 'split': split,
               'start_frame': 0, 'end_frame': 6, 'skill': 'place_release_tray', 'phase': 'release',
               'state': 'PLACE_TRAY', 'needs_review': False, 'recovery': False,
               'target_tray_id': 'tray0', 'target_slot_id': 'slot0'}
    write(attempt / 'segments.json', [segment])
    (attempt / 'events.jsonl').write_text('\n'.join(json.dumps(e) for e in [
        {'event': 'operation_selected', 'frame': 0, 'operation_index': 1, 'operation': {'temporary': False}},
        {'event': 'state_transition', 'frame': 0, 'dag_node_id': 'transition_1'},
        {'event': 'operation_selected', 'frame': 3, 'operation_index': 2, 'operation': {'temporary': True}}]), encoding='utf-8')
    trace = attempt / 'trace.h5'
    with h5py.File(trace, 'w') as f:
        f.attrs['schema'] = 'airport_fsm_raw/1'
        f.attrs['num_frames'] = 6
        f.attrs['metadata_json'] = json.dumps({'scene_id': 'scene1', 'split': split, 'fps': 20,
            'scene': {'camera': {'width': 32, 'height': 24}}})
        f['state'] = np.arange(96, dtype=np.float32).reshape(6, 16)
        f['action'] = np.ones((6, 16), dtype=np.float32)
        f['base_action'] = np.full((6, 3), 2, dtype=np.float32)
        f['timestamp'] = np.arange(6) / 20
        f['transition_completed'] = np.ones(6, dtype=bool)
    return root, trace


def records(path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]


def refs(tmp_path, trace):
    result = []
    for camera in ('head', 'left_wrist', 'right_wrist'):
        video = tmp_path / (camera + '.mp4')
        video.write_bytes(b'actual-probe-is-injected-in-test')
        result.append({'trace': str(trace), 'camera': camera, 'path': str(video),
                       'source_start_frame': 0, 'video_start_frame': 10, 'frames': 6})
    return result


def test_partition_dag_alignment_and_public_action(tmp_path):
    root, trace = fixture(tmp_path)
    output = tmp_path / 'data.jsonl'
    summary = prepare_manifest([root], output)
    rows = records(output)
    assert summary['segments'] == 2
    assert [(r['start_frame'], r['end_frame'], r['operation_index']) for r in rows] == [(0, 3, 1), (3, 6, 2)]
    assert all(r['supervision_eligible'] and not r['training_ready'] for r in rows)
    assert rows[1]['operation']['temporary']
    assert 'temporary supported buffer' in rows[1]['language_prompt']
    data = read_mobile19_segment(rows[1])
    assert data['action'].shape == (3, 19)
    assert np.all(data['action'][:, :16] == 1)
    assert np.all(data['action'][:, 16:] == 2)
    assert set(data) == {'observation.state', 'action', 'task'}


def test_native_video_ranges_require_actual_probe(tmp_path):
    root, trace = fixture(tmp_path)
    references = refs(tmp_path, trace)
    path = tmp_path / 'unverified.jsonl'
    prepare_manifest([root], path, video_references=references)
    assert not any(r['training_ready'] for r in records(path))
    calls = []
    def probe(path):
        calls.append(path)
        return {'width': 32, 'height': 24, 'fps': 20, 'frames': 16}
    output = tmp_path / 'verified.jsonl'
    prepare_manifest([root], output, video_references=references, video_probe=probe)
    rows = records(output)
    assert all(r['training_ready'] for r in rows)
    assert len(calls) == 3
    assert rows[1]['videos']['head']['start_frame'] == 13
    assert rows[1]['videos']['head']['end_time_s'] == .8


def test_video_missing_wrist_never_becomes_training(tmp_path):
    root, trace = fixture(tmp_path)
    output = tmp_path / 'data.jsonl'
    prepare_manifest([root], output, video_references=refs(tmp_path, trace)[:1],
        video_probe=lambda _: {'width': 32, 'height': 24, 'fps': 20, 'frames': 16})
    assert records(output)[0]['missing_or_unverified_cameras'] == ['left_wrist', 'right_wrist']
    assert not records(output)[0]['training_ready']


@pytest.mark.parametrize('measured,error', [
    ({'width': 31, 'height': 24, 'fps': 20, 'frames': 16}, 'video_native_contract'),
    ({'width': 32, 'height': 24, 'fps': 20, 'frames': 15}, 'video_frame_count')])
def test_video_probe_rejects_misalignment(tmp_path, measured, error):
    root, trace = fixture(tmp_path)
    with pytest.raises(ValueError, match=error):
        prepare_manifest([root], tmp_path / 'data.jsonl', video_references=refs(tmp_path, trace),
                         video_probe=lambda _: measured)
    assert not (tmp_path / 'data.jsonl').exists()


def test_failure_not_expert_requires_trace_bound_local_review(tmp_path):
    root, trace = fixture(tmp_path, success=False)
    output = tmp_path / 'data.jsonl'
    prepare_manifest([root], output)
    assert all(not r['supervision_eligible'] for r in records(output))
    qualification = {'segment_id': 'source_segment', 'trace_sha256': digest(trace),
                     'locally_verified': True, 'reviewer': 'physics-review', 'reason': 'supported release verified'}
    reviewed = tmp_path / 'reviewed.jsonl'
    prepare_manifest([root], reviewed, local_qualifications=[qualification])
    assert all(r['quality_class'] == 'reviewed_local_prefix' and r['supervision_eligible'] for r in records(reviewed))
    qualification['trace_sha256'] = 'wrong'
    with pytest.raises(ValueError, match='invalid_local_qualification'):
        prepare_manifest([root], tmp_path / 'bad.jsonl', local_qualifications=[qualification])


def test_split_and_scene_identity_cannot_leak(tmp_path):
    root, _ = fixture(tmp_path)
    other, _ = fixture(tmp_path, split='test', name='other')
    with pytest.raises(ValueError, match='scene_split_leakage'):
        prepare_manifest([root, other], tmp_path / 'data.jsonl')


def lift_fixture(tmp_path):
    root, trace = fixture(tmp_path)
    attempt = trace.parent
    result = json.loads((attempt / 'result.json').read_text())
    result.update(strict_success=False, approximate_completion_enabled=True, recovery_used=False,
                  strict_deviations=['strict_lift_height'], approximate_deviation_counts={'lift_height': 1})
    (attempt / 'result.json').write_text(json.dumps(result))
    segment = json.loads((attempt / 'segments.json').read_text())[0]
    segment.update(skill='grasp_lift_tray', state='GRASP_TRAY', phase='lift', needs_review=True, end_frame=5)
    end = {**segment, 'segment_id': 'end', 'start_frame': 5, 'end_frame': 6, 'phase': 'stabilize', 'needs_review': False}
    (attempt / 'segments.json').write_text(json.dumps([segment, end]))
    with h5py.File(trace, 'r+') as f:
        metadata = json.loads(f.attrs['metadata_json'])
        metadata.update(controller_source='program_generated', config={'approximate_completion_enabled': True,
            'acceptance_profile': 'completion_first', 'completion_lift_min_m': .1})
        f.attrs['metadata_json'] = json.dumps(metadata)
        f['target_tray'] = np.zeros(6, np.int32)
        f['gripper_contact_force'] = np.full((6, 1, 2), 12.)
        f['support_contact'] = np.array([1, 1, 0, 0, 0, 0])[:, None]
        f['min_z'] = np.array([.8, .801, .81, .84, .91, .95])[:, None]
        f['recovery'] = np.zeros(6, bool)
    return root, trace


def test_legal_takeoff_review_does_not_remove_successful_lift(tmp_path):
    root, trace = lift_fixture(tmp_path)
    before = digest(trace), digest(trace.parent / 'segments.json')
    output = tmp_path / 'corrected.jsonl'; prepare_manifest([root], output)
    rows = [row for row in records(output) if row['phase'] == 'lift']
    assert rows and all(row['supervision_eligible'] for row in rows)
    assert all(row['source_needs_review'] is True for row in rows)
    assert rows[0]['verified_lift_takeoff']['endpoint_observation_frame'] == 5
    assert rows[0]['verified_lift_takeoff']['initial_supported_frames'] == 2
    assert rows[0]['strict_deviations'] == ['strict_lift_height']
    assert (digest(trace), digest(trace.parent / 'segments.json')) == before


@pytest.mark.parametrize('bad', ['failed', 'learner', 'incomplete', 'weak_force', 'low_clearance',
                               'endpoint_support', 'recovery', 'episode_recovery', 'recontact', 'no_endpoint'])
def test_takeoff_selection_rejects_nonexpert_or_invalid_interval(tmp_path, bad):
    root, trace = lift_fixture(tmp_path)
    if bad in ('failed', 'episode_recovery'):
        path = trace.parent / 'result.json'; value = json.loads(path.read_text())
        if bad == 'failed': value.update(task_completed=False, physics_success=False)
        else: value['recovery_used'] = True
        path.write_text(json.dumps(value))
    if bad == 'no_endpoint':
        path = trace.parent / 'segments.json'; value = json.loads(path.read_text())
        value[0]['end_frame'] = 6; path.write_text(json.dumps(value[:1]))
    with h5py.File(trace, 'r+') as f:
        if bad == 'learner':
            metadata = json.loads(f.attrs['metadata_json']); metadata['controller_source'] = 'vla_generated'
            f.attrs['metadata_json'] = json.dumps(metadata)
        if bad == 'incomplete': f['transition_completed'][1] = False
        if bad == 'weak_force': f['gripper_contact_force'][2, 0, 0] = .1
        if bad == 'low_clearance': f['min_z'][5, 0] = .85
        if bad == 'endpoint_support': f['support_contact'][5, 0] = 1
        if bad == 'recovery': f['recovery'][1] = True
        if bad == 'recontact': f['support_contact'][3, 0] = 1
    output = tmp_path / 'corrected.jsonl'; prepare_manifest([root], output)
    rows = [row for row in records(output) if row['phase'] == 'lift']
    assert all(not row['supervision_eligible'] and row['verified_lift_takeoff'] is None for row in rows)


def test_initial_tuck_only_after_settle_before_first_operation(tmp_path):
    root, trace = fixture(tmp_path)
    with h5py.File(trace, 'r+') as f:
        for key in list(f):
            old = f[key][:]; del f[key]
            f[key] = np.concatenate([old] * 14, axis=0)[:80]
        f['timestamp'][:] = np.arange(80) / 20
        f.attrs['num_frames'] = 80
    segment = json.loads((trace.parent / 'segments.json').read_text())[0]
    segment.update(skill='verify_or_recover', phase='unknown', state='SEARCH_TARGET', end_frame=78,
                   target_tray_id=None, target_slot_id=None)
    end = {**segment, 'segment_id': 'end', 'start_frame': 78, 'end_frame': 80, 'phase': 'verified'}
    (trace.parent / 'segments.json').write_text(json.dumps([segment, end]))
    (trace.parent / 'events.jsonl').write_text(json.dumps({'event': 'operation_selected', 'frame': 78,
        'operation_index': 1, 'operation': {'temporary': False}}))
    output = tmp_path / 'initialized.jsonl'; prepare_manifest([root], output)
    rows = records(output)
    assert [(row['start_frame'], row['end_frame'], row['skill']) for row in rows] == [
        (0, 40, 'verify_or_recover'), (40, 78, 'initialize_posture'), (78, 80, 'verify_or_recover')]
    assert [row['supervision_eligible'] for row in rows] == [False, True, False]
    assert rows[1]['language_prompt'] == 'Move both arms to the initial tucked posture.'
    assert rows[1]['source_skill'] == 'verify_or_recover'


@pytest.mark.parametrize('pattern', [[0, 1, 0, 0, 0, 0], [1, 0, 1, 0, 0, 0], [1, 1, 0, 1, 0, 0]])
def test_takeoff_contact_chatter_near_initial_height_is_valid(pattern, tmp_path):
    root, trace = lift_fixture(tmp_path)
    with h5py.File(trace, 'r+') as f:
        f['support_contact'][:, 0] = pattern
        last_supported = max(i for i, value in enumerate(pattern[:5]) if value)
        f['min_z'][:last_supported + 1, 0] = .8 + np.linspace(0, .0000653, last_supported + 1)
    output = tmp_path / 'corrected.jsonl'; prepare_manifest([root], output)
    rows = [row for row in records(output) if row['phase'] == 'lift']
    assert all(row['supervision_eligible'] for row in rows)
    qualification = rows[0]['verified_lift_takeoff']
    assert qualification['rule_version'] == 2
    assert qualification['early_support_nonmonotonic']
    assert qualification['takeoff_max_abs_initial_height_delta_m'] <= .0000653001
    assert qualification['airborne_tail_start_frame'] == last_supported + 1
    assert qualification['airborne_tail_interval_frames'] >= 1
    assert qualification['takeoff_near_initial_height_tolerance_m'] == .02


def test_late_recontact_after_real_airborne_lift_remains_rejected(tmp_path):
    root, trace = lift_fixture(tmp_path)
    with h5py.File(trace, 'r+') as f:
        f['support_contact'][:, 0] = [1, 0, 0, 1, 0, 0]
        f['min_z'][:, 0] = [.8, .84, .9, .80001, .91, .95]
    output = tmp_path / 'corrected.jsonl'; prepare_manifest([root], output)
    assert all(row['verified_lift_takeoff'] is None for row in records(output) if row['phase'] == 'lift')


def test_nonfinite_and_changed_hash_rejected(tmp_path):
    root, trace = fixture(tmp_path)
    output = tmp_path / 'data.jsonl'
    prepare_manifest([root], output)
    row = records(output)[0]
    with h5py.File(trace, 'a') as f:
        f['action'][2, 0] = np.nan
    with pytest.raises(ValueError, match='trace_hash_changed'):
        read_mobile19_segment(row)
    with pytest.raises(ValueError, match='nonfinite_trace'):
        prepare_manifest([root], tmp_path / 'bad.jsonl')


def test_refuse_mutation_of_existing_collection(tmp_path):
    root, _ = fixture(tmp_path)
    with pytest.raises(ValueError, match='output_must_not_mutate'):
        prepare_manifest([root], root / 'new.jsonl')


def test_choose_one_success_per_scene_across_collections(tmp_path):
    root, _ = fixture(tmp_path)
    other, _ = fixture(tmp_path, name='other')
    output = tmp_path / 'data.jsonl'
    prepare_manifest([root, other], output)
    rows = records(output)
    assert len(rows) == 4
    assert sum(r['supervision_eligible'] for r in rows) == 2
    assert all(not r['supervision_eligible'] for r in rows[2:])


def test_train_split_iterator_excludes_local_failure_by_default(tmp_path):
    from r1pro_teleop.vla.data import iter_training_records
    output = tmp_path / 'example.jsonl'
    rows = [{'schema': 'airport_vla_segments/1', 'split': split,
             'training_ready': True, 'quality_class': quality} for split, quality in
            [('train', 'complete_task'), ('val', 'complete_task'), ('train', 'reviewed_local_prefix')]]
    output.write_text('\n'.join(json.dumps(r) for r in rows), encoding='utf-8')
    assert len(list(iter_training_records(output))) == 1
    assert len(list(iter_training_records(output, include_reviewed_local=True))) == 2
