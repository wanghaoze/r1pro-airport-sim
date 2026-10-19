"""Rejected proposals remain auditable; accepted yaw/splits are never rewritten."""
import json
import os
from pathlib import Path
import sys
import types

import pytest
from r1pro_teleop.single_tray_3table.initial_pose_preflight import freeze_selection, evaluate_proposal
from r1pro_teleop.single_tray_3table.campaign import digest


@pytest.fixture(autouse=True)
def windows_unit_lock_stub(monkeypatch):
    # Linux integration uses the real OS lock; Windows tests only exercise data
    # and source-binding semantics, not platform process locking.
    if os.name == 'nt':
        monkeypatch.setitem(sys.modules, 'fcntl', types.SimpleNamespace(LOCK_EX=1, LOCK_NB=2, flock=lambda *a: None))


def test_selected_proposals_preserve_original_seed_parent_split_and_quota():
    records = [dict(parent_scene_id='train-parent', seed=i, split='train', accepted=i != 0,
                    initial_pose=dict(yaw_world=1.55)) for i in range(4)]
    records.extend([dict(parent_scene_id='val-parent', seed=10, split='val', accepted=True),
                    dict(parent_scene_id='test-parent', seed=20, split='test', accepted=True)])
    selection, counts = freeze_selection(records, dict(train=2, val=1, test=1))
    assert selection['variants'] == [dict(parent_scene_id='train-parent', variant_seed=1),
        dict(parent_scene_id='train-parent', variant_seed=2), dict(parent_scene_id='val-parent', variant_seed=10),
        dict(parent_scene_id='test-parent', variant_seed=20)]
    assert counts == dict(train=2, val=1, test=1)
    assert records[0]['accepted'] is False and records[1]['initial_pose']['yaw_world'] == 1.55


def test_preflight_reuse_requires_config_and_scene_bytes_unchanged(tmp_path):
    job = dict(directory=str(tmp_path / 'proposal'), config=str(tmp_path / 'config.json'))
    Path(job['config']).write_text('{}')
    scene = tmp_path / 'scene.json'; scene.write_text('{"yaw":1.55}')
    xml = tmp_path / 'mobile.xml'; xml.write_text('<mujoco/>')
    directory = Path(job['directory']); directory.mkdir()
    receipt = dict(proposal_binding={k:v for k,v in job.items() if k != 'directory'},
                   config_sha256=digest(job['config']), scene=str(scene), scene_sha256=digest(scene),
                   scene_xml=str(xml), scene_xml_sha256=digest(xml), accepted=True)
    (directory / 'preflight.json').write_text(json.dumps(receipt))
    assert evaluate_proposal(job) == receipt
    Path(job['config']).write_text('{"ik_tolerance":1}')
    with pytest.raises(ValueError, match='reuse_source_bytes_changed'):
        evaluate_proposal(job)


def test_geometrically_valid_sideways_proposal_is_preserved_when_private_rejected(tmp_path, monkeypatch):
    import r1pro_teleop.single_tray_3table.initial_pose_preflight as module
    import r1pro_teleop.single_tray_lab.three_table_scene as generator
    import r1pro_teleop.airport_fsm.contracts as contracts
    config = tmp_path / 'config.json'; config.write_text('{}')
    scene = dict(seed=42, parent_scene_id='train-parent', split='train', initial_tray_pose=dict(yaw_world=1.55))
    def generate(directory, parent, manifest, seed, **kwargs):
        directory.mkdir(parents=True); xml = directory / 'mobile.xml'; xml.write_text('<mujoco/>')
        scene['xml'] = str(xml)
        (directory / 'scene.json').write_text(json.dumps(scene))
        assert seed == 42 and kwargs['source_base_distance_m'] == .5
        return dict(scene)
    monkeypatch.setattr(generator, 'generate_three_table_scene', generate)
    monkeypatch.setattr(contracts.Config, 'load', lambda path: object())
    def probe(actual_scene, config):
        assert actual_scene['initial_tray_pose']['yaw_world'] == 1.55
        return dict(accepted=False, seed=42, parent_scene_id='train-parent', split='train',
                    initial_pose=actual_scene['initial_tray_pose'], physical_ticks=0, examined=24)
    monkeypatch.setattr(module, 'probe_initial_pose', probe)
    job = dict(directory=str(tmp_path / 'proposal'), seed=42, parent_scene_id='train-parent', split='train',
               parent_scene='parent', parent_manifest='manifest', split_registry='registry',
               config=str(config), source_base_distance=.5, source_bindings={str(config):digest(config)})
    result = evaluate_proposal(job)
    assert not result['accepted'] and result['initial_pose']['yaw_world'] == 1.55 and result['physical_ticks'] == 0


def test_finite_proposal_budget_stops_with_all_rejections_retained(tmp_path, monkeypatch):
    import r1pro_teleop.single_tray_3table.initial_pose_preflight as m
    config = tmp_path / 'config.json'; config.write_text('{}')
    parents = dict(train=['train-parent'], val=['val-parent'], test=['test-parent'])
    monkeypatch.setattr(m, 'build_plan', lambda *a, **k: dict(variants=[dict(parent_scene_id=p, split=s, parent_scene_json='original-'+p) for s, values in parents.items() for p in values]))
    class Future:
        def __init__(self, job): self.job = job
        def done(self): return True
        def result(self):
            return dict(parent_scene_id=self.job['parent_scene_id'], seed=self.job['seed'], split=self.job['split'],
                        accepted=False, scene=str(Path(self.job['directory']) / 'scene/scene.json'), initial_pose=dict(yaw_world=1.55))
    class Pool:
        def __init__(self, **kwargs): assert kwargs['max_workers'] == 8
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def submit(self, function, job): return Future(job)
    monkeypatch.setattr(m, 'ProcessPoolExecutor', Pool)
    options = dict(schema='airport_three_table_preflight_plan_options/1', output=str(tmp_path / 'output'),
                   inventory='inventory', parent_manifest='manifest', split_registry='registry', config=str(config),
                   seed_start=202610080000, parents=parents, workers=8,
                   targets=dict(train=100, val=10, test=10), proposal_limits=dict(train=100, val=10, test=10))
    assert m.collect_plan(options) is False
    root = Path(options['output']); state = json.loads((root / 'status.json').read_text())
    index = json.loads((root / 'proposal_index.json').read_text())
    assert state['stage'] == 'blocked_preflight_proposal_budget_exhausted'
    assert len(index['records']) == 120 and not index['selection']['variants']
    assert state['statistics']['train'] == dict(proposals=100, accepted=0, rejected=100)
    assert all(r['initial_pose']['yaw_world'] == 1.55 for r in index['records'])
