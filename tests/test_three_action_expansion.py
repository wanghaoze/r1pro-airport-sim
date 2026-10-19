"""Independent expansion gates and byte-preserving recovery boundaries."""
import importlib.util
import json
from pathlib import Path
import sys
import types

import pytest


def module():
    p = Path(__file__).resolve().parents[1] / 'scripts/supervise_three_action_expansion.py'
    spec = importlib.util.spec_from_file_location('expansion_fixture', p)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


def options(tmp_path):
    release = tmp_path / 'release'
    return dict(schema='airport_three_action_expansion_options/1', run_dir=str(tmp_path / 'run'),
                release=str(release), campaign_dir=str(tmp_path / 'run/campaign'),
                data_run_dir=str(tmp_path / 'run/data'), target_train_sources=67,
                sim_python='sim-python', vla_python='vla-python',
                campaign_command=['sim-python', str(release / 'scripts/collect_three_table_campaign.py'), '--execute'],
                data_command=['vla-python', str(release / 'scripts/supervise_three_table_single_tray_training.py'), '--data-only'])


def test_camera_count_never_reduces_67_source_target(tmp_path):
    m = module(); o = options(tmp_path)
    assert m.validate_options(o) == tmp_path / 'run'
    o['target_train_sources'] = 23
    with pytest.raises(ValueError, match='at_least_67'):
        m.validate_options(o)


def test_insufficient_actual_sources_block_before_data_or_archive(tmp_path, monkeypatch):
    m = module(); o = options(tmp_path); path = tmp_path / 'options.json'; write(path, o)
    called = []
    monkeypatch.setattr(m, 'lock', lambda p: object())
    monkeypatch.setattr(m, 'process_identity', lambda pid: dict(pid=pid))
    monkeypatch.setattr(m, 'owned_stage', lambda o, state, stage, argv, pulse: called.append(stage))
    monkeypatch.setattr(m, 'verified_source_gate', lambda o: ({}, dict(train=66, val=1, test=1)))
    monkeypatch.setattr(m, 'archive_actions', lambda *a: pytest.fail('unqualified export reached archive'))
    assert m.supervise(path) == 2
    state = json.loads((Path(o['run_dir']) / 'expansion_status.json').read_text())
    assert state['stage'] == 'blocked_target_not_met' and not state['dataset_ready']
    assert called == ['campaign']
    assert m.supervise(path) == 2 and called == ['campaign']


def test_demo_nonzero_exit_never_launches_new_demo_or_campaign(tmp_path, monkeypatch):
    m = module(); o = options(tmp_path)
    o['demo_gate'] = dict(owned_output='existing-demo', owned_options='existing-options', case='existing-case')
    path = tmp_path / 'options.json'; write(path, o)
    monkeypatch.setattr(m, 'lock', lambda p: object())
    monkeypatch.setattr(m, 'process_identity', lambda pid: dict(pid=pid))
    monkeypatch.setattr(m, 'command_state', lambda *a: dict(stage='closed', returncode=17))
    monkeypatch.setattr(m, 'owned_stage', lambda *a: pytest.fail('failed demo launched campaign'))
    assert m.supervise(path) == 2
    state = json.loads((Path(o['run_dir']) / 'expansion_status.json').read_text())
    assert state['stage'] == 'blocked_demo_failed'


def test_actual_exit_zero_reuses_owned_stage_without_spawn(tmp_path, monkeypatch):
    m = module(); o = options(tmp_path); Path(o['run_dir']).mkdir()
    monkeypatch.setattr(m, 'command_state', lambda *a: dict(stage='closed', returncode=0, receipt='real-exit', receipt_sha256='sha'))
    monkeypatch.setattr(m.subprocess, 'Popen', lambda *a, **k: pytest.fail('duplicate process launched'))
    state = {}; pulses = []
    m.owned_stage(o, state, 'campaign', o['campaign_command'], lambda stage, **fields: pulses.append(stage))
    assert state['campaign_exit']['returncode'] == 0
    assert pulses[-1] == 'campaign_exit_zero'


def test_nonzero_child_preserves_actual_code_and_never_succeeds(tmp_path, monkeypatch):
    m = module(); o = options(tmp_path); Path(o['run_dir']).mkdir()
    monkeypatch.setattr(m, 'command_state', lambda *a: dict(stage='closed', returncode=9))
    with pytest.raises(ValueError, match='nonzero:campaign:9'):
        m.owned_stage(o, {}, 'campaign', o['campaign_command'], lambda *a, **k: None)


def test_archive_copy_recovers_identical_files_preserves_prompt_ids_split(tmp_path, monkeypatch):
    m = module(); data = tmp_path / 'data'; out = tmp_path / 'by_action'
    tables = {}
    class Column:
        def __init__(self, values): self.values = values
        def to_pylist(self): return self.values
    class Table:
        def __init__(self, i): self.i = i
        def __len__(self): return 2
        def __getitem__(self, key):
            return Column([self.i, self.i] if key in ('task_index', 'episode_index') else [[0.] * 19] * 2)
    fake = types.ModuleType('pyarrow.parquet'); fake.read_table = lambda p: tables[str(p)]
    package = types.ModuleType('pyarrow'); package.parquet = fake
    monkeypatch.setitem(sys.modules, 'pyarrow', package); monkeypatch.setitem(sys.modules, 'pyarrow.parquet', fake)
    for split in ('train', 'val', 'test'):
        root = data / 'datasets' / split; episodes = []
        # Actual official source paths, verified against first-batch info.json.
        write(root / 'meta/info.json', dict(chunks_size=1000, data_path='data/chunk-{episode_chunk:03d}/episode_{episode_index:06d}.parquet', video_path='videos/chunk-{episode_chunk:03d}/{video_key}/episode_{episode_index:06d}.mp4'))
        for i in range(3):
            episode = dict(episode_index=i, task_index=i, language_prompt=m.PROMPTS[i], parent_scene_id=split + '-parent', scene_id=split + '-scene', frames=2)
            episodes.append(episode); p = root / f'data/chunk-000/episode_{i:06d}.parquet'; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(bytes([i])); tables[str(p)] = Table(i)
            for camera in ('head_left', 'left_wrist', 'right_wrist'):
                p = root / f'videos/chunk-000/observation.images.{camera}/episode_{i:06d}.mp4'; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes((split + camera + str(i)).encode())
        write(root / 'airport_training_manifest.json', dict(dataset_ready=True, split=split, episodes=episodes))
    result = m.archive_actions(data, out, 1, lambda *a, **k: None)
    assert len(result['rows']) == 9 and result['counts']['train'] == dict(complete_sources=1, action_segments=3)
    assert len((out / 'VIDEO_PATHS.txt').read_text().splitlines()) == 27
    assert m.archive_actions(data, out, 1, lambda *a, **k: None)['counts'] == result['counts']
    p = out / 'pick_up_the_tray/train/episode_000000/trajectory.parquet'; p.write_bytes(b'changed')
    with pytest.raises(ValueError, match='partial_archive_file_changed'):
        m.archive_actions(data, out, 1, lambda *a, **k: None)


def test_guardian_has_only_three_recoveries_after_initial_launch(tmp_path, monkeypatch):
    m = module(); o = options(tmp_path); path = tmp_path / 'options.json'; write(path, o)
    monkeypatch.setattr(m, 'lock', lambda p: object())
    monkeypatch.setattr(m, 'process_identity', lambda pid: dict(pid=pid, start_ticks='123'))
    monkeypatch.setattr(m, 'checked_process', lambda job: None)
    sleeps = []; launches = []
    monkeypatch.setattr(m.time, 'sleep', lambda seconds: sleeps.append(seconds))
    class Child:
        pid = 123
        def poll(self): return 3
        def wait(self): return 3
    monkeypatch.setattr(m.subprocess, 'Popen', lambda *a, **k: launches.append(a) or Child())
    m.guardian(path)
    state = json.loads((Path(o['run_dir']) / 'expansion_guardian_status.json').read_text())
    assert len(launches) == 4 and sleeps == [10, 30, 90]
    assert state['stage'] == 'blocked_recovery_limit' and state['last_actual_supervisor_exit'] == 3


def preflight_fixture(tmp_path):
    m = module(); o = options(tmp_path); root = Path(o['run_dir']) / 'preflight'
    config = tmp_path / 'config.json'; write(config, {'existing_configuration': True})
    records = []; variants = []
    for split, count in [('train', 67), ('val', 1), ('test', 1)]:
        for i in range(count):
            seed = len(variants); parent = split + '-parent'; folder = root / split / str(i)
            scene = folder / 'scene.json'; xml = folder / 'scene.xml'
            write(scene, {'initial_tray_pose': {'yaw_world': .1}}); xml.write_text('<mujoco/>')
            receipt = folder / 'preflight.json'
            write(receipt, dict(accepted=True, live_state_unchanged=True, physical_ticks=0,
                proposal_yaw_changed=False, config_sha256=m.sha(config), initial_pose={'yaw_world': .1},
                parent_scene_id=parent, seed=seed, split=split, scene=str(scene), scene_sha256=m.sha(scene),
                scene_xml=str(xml), scene_xml_sha256=m.sha(xml), accepted_candidates=[{'rim_geometry': {'axis': 'width'}}]))
            records.append(dict(parent_scene_id=parent, variant_seed=seed, split=split,
                initial_pose={'yaw_world': .1}, preflight=str(receipt)))
            variants.append(dict(parent_scene_id=parent, variant_seed=seed))
    selection = root / 'accepted_selection.json'; write(selection, {'variants': variants})
    index = root / 'qualified_initial_pose_index.json'
    write(index, dict(records=records, fixed_angle_filter_used=False, proposal_yaw_changed=False))
    report = root / 'status.json'
    write(report, dict(schema='airport_three_table_preflight_plan_status/1', stage='preflight_candidates_ready',
        task_success_not_certified=True, selection=str(selection), selection_sha256=m.sha(selection),
        qualified_candidate_counts=dict(train=67, val=1, test=1)))
    o.update(preflight_command=['sim-python', str(Path(o['release']) / 'scripts/plan_three_table_reachable_initial_poses.py')],
        preflight_report=str(report))
    o['campaign_command'] += ['--selection', str(selection), '--config', str(config)]
    return m, o, records


def test_preflight_binds_actual_receipts_and_exact_campaign_selection(tmp_path):
    m, o, rows = preflight_fixture(tmp_path)
    proof = m.preflight_proof(o)
    assert proof['qualified_candidate_counts'] == dict(train=67, val=1, test=1)
    assert proof['task_success_not_certified'] is True
    selection = Path(o['campaign_command'][o['campaign_command'].index('--selection') + 1])
    write(selection, {'variants': []})
    with pytest.raises(ValueError, match='selection_binding_changed'):
        m.preflight_proof(o)


@pytest.mark.parametrize('change,reason', [
    ({'accepted_candidates': [{'rim_geometry': {'axis': 'length'}}]}, 'short_rim'),
    ({'live_state_unchanged': False}, 'identity_changed'),
    ({'physical_ticks': 1}, 'identity_changed'),
    ({'proposal_yaw_changed': True}, 'identity_changed')])
def test_preflight_rejects_short_rim_or_changed_actual_state(tmp_path, change, reason):
    m, o, rows = preflight_fixture(tmp_path)
    path = Path(rows[0]['preflight']); receipt = json.loads(path.read_text()); receipt.update(change); write(path, receipt)
    with pytest.raises(ValueError, match=reason):
        m.preflight_proof(o)


def test_preflight_stage_must_close_before_any_physical_campaign(tmp_path, monkeypatch):
    m, o, rows = preflight_fixture(tmp_path); path = tmp_path / 'options.json'; write(path, o)
    monkeypatch.setattr(m, 'lock', lambda p: object())
    monkeypatch.setattr(m, 'process_identity', lambda pid: dict(pid=pid))
    called = []
    def stage(o, state, name, argv, pulse):
        called.append(name)
        if name == 'preflight':
            write(Path(o['preflight_report']), {'stage': 'blocked_preflight_proposal_budget_exhausted'})
    monkeypatch.setattr(m, 'owned_stage', stage)
    assert m.supervise(path) == 2 and called == ['preflight']
