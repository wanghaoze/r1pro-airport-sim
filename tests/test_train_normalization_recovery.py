"""Interrupted cache preparation may reuse only the same certified train norm."""
import json
from pathlib import Path
import sys
from types import ModuleType,SimpleNamespace

import numpy as np
import pytest
from r1pro_teleop.vla.training_cache import compute_train_only_norm,file_sha


@pytest.fixture
def norm_fixture(tmp_path,monkeypatch):
    import r1pro_teleop.vla.training_cache as cache
    import r1pro_teleop.vla.training as training
    root=tmp_path/'train';(root/'meta').mkdir(parents=True);(root/'data').mkdir()
    source=root/'source.jsonl';source.write_text('source-train-only\n')
    parquet=root/'data/episode_0.parquet';parquet.write_bytes(b'original numeric rows')
    info=dict(chunks_size=1000,data_path='data/episode_{episode_index}.parquet')
    (root/'meta/info.json').write_text(json.dumps(info))
    manifest=dict(split='train',dataset_ready=True,all_parquet_values_verified={'verified':True},
        source_manifest=str(source),source_manifest_sha256=file_sha(source),episodes=[dict(episode_index=0,frames=2,split='train')])
    (root/'airport_training_manifest.json').write_text(json.dumps(manifest))
    spec=SimpleNamespace(dataset_root=str(root),dataset_repo_id='airport/train',prompt_mode='three_table_single_tray_action3_v1',
        action_horizon=20,normalization_policy='default_train_only',openpi_root=str(tmp_path/'openpi'),validate=lambda:None,batch_size=8)
    assets=tmp_path/'new_run/assets';config=SimpleNamespace(assets_dirs=assets)
    monkeypatch.setattr(training,'build_openpi_config',lambda spec:config)
    monkeypatch.setattr(cache,'validate_cache_source',lambda *a,**k:None)
    class Column:
        def to_pylist(self):return np.arange(38,dtype=float).reshape(2,19).tolist()
    class Table:
        def __getitem__(self,key):return Column()
    pq=ModuleType('pyarrow.parquet');pq.read_table=lambda p:Table()
    pa=ModuleType('pyarrow');pa.parquet=pq
    monkeypatch.setitem(sys.modules,'pyarrow',pa);monkeypatch.setitem(sys.modules,'pyarrow.parquet',pq)
    calls=[]
    class RunningStats:
        def __init__(self):self.rows=[];calls.append('new_stats')
        def update(self,array):self.rows.extend(array.tolist())
        def get_statistics(self):return dict(mean=np.mean(self.rows,axis=0).tolist(),rows=len(self.rows))
    def save(directory,stats):
        directory.mkdir(parents=True,exist_ok=True);(directory/'norm_stats.json').write_text(json.dumps(stats))
    normalize=ModuleType('openpi.shared.normalize');normalize.RunningStats=RunningStats;normalize.save=save
    shared=ModuleType('openpi.shared');shared.normalize=normalize;openpi=ModuleType('openpi');openpi.shared=shared
    for name,module in [('openpi',openpi),('openpi.shared',shared),('openpi.shared.normalize',normalize)]:monkeypatch.setitem(sys.modules,name,module)
    directory=assets/spec.dataset_repo_id
    return SimpleNamespace(spec=spec,directory=directory,root=root,source=source,parquet=parquet,calls=calls,manifest=manifest)


def test_cache_restart_reuses_same_train_norm_without_recomputing_or_overwriting(norm_fixture):
    f=norm_fixture;first=compute_train_only_norm(f.spec);norm=Path(first['path']);before=norm.read_bytes()
    second=compute_train_only_norm(f.spec)
    assert not first['safely_reused'] and second['safely_reused'] and norm.read_bytes()==before
    assert f.calls==['new_stats','new_stats']
    proof=json.loads((f.directory/'norm_provenance.json').read_text())
    assert proof['input_binding']['split']=='train' and proof['holdout_used'] is False
    assert proof['input_binding']['spec']['action_horizon']==20
    assert first['provenance_sha256']==second['provenance_sha256']


def test_legacy_or_parent_norm_without_certificate_is_rejected_unchanged(norm_fixture):
    f=norm_fixture;f.directory.mkdir(parents=True);norm=f.directory/'norm_stats.json';norm.write_text('parent or legacy norm')
    with pytest.raises(ValueError,match='uncertified'):compute_train_only_norm(f.spec)
    assert norm.read_text()=='parent or legacy norm' and not f.calls


@pytest.mark.parametrize('change',['horizon','source','manifest','parquet','normalization_policy'])
def test_changed_norm_inputs_cannot_reuse_or_overwrite_verified_stats(norm_fixture,change):
    f=norm_fixture;first=compute_train_only_norm(f.spec);before=Path(first['path']).read_bytes()
    if change=='horizon':f.spec.action_horizon=21
    elif change=='source':f.source.write_text('new source bytes')
    elif change=='manifest':(f.root/'airport_training_manifest.json').write_text(json.dumps(f.manifest)+'\n')
    elif change=='parquet':f.parquet.write_bytes(b'changed numeric rows')
    else:f.spec.normalization_policy='preserve_parent_stats'
    with pytest.raises(ValueError,match='source_or_configuration_changed'):compute_train_only_norm(f.spec)
    assert Path(first['path']).read_bytes()==before


def test_changed_norm_or_certificate_bytes_are_not_silently_repaired(norm_fixture):
    f=norm_fixture;first=compute_train_only_norm(f.spec);norm=Path(first['path']);original=norm.read_bytes()
    norm.write_text('tampered norm')
    with pytest.raises(ValueError,match='norm_bytes_changed'):compute_train_only_norm(f.spec)
    assert norm.read_text()=='tampered norm'
    norm.write_bytes(original);proof=f.directory/'norm_provenance.json';proof.write_text(proof.read_text()+'\n')
    with pytest.raises(ValueError,match='certificate_changed'):compute_train_only_norm(f.spec)


def test_batch_schedule_changes_do_not_recompute_identical_normalization(norm_fixture):
    f=norm_fixture;compute_train_only_norm(f.spec);f.spec.batch_size=4
    assert compute_train_only_norm(f.spec)['safely_reused']
