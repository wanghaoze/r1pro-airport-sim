import numpy as np
import pytest
from r1pro_teleop.real2sim.isaac_parallel_collection import (
    room_origins, batched_joint_targets, validate_sources, sample_table_poses, CAMERAS)
from r1pro_teleop.real2sim.isaac_mobile import mobile_targets


def test_batch_preserves_independent_mobile_mapping():
    rng = np.random.default_rng(19)
    actions = rng.normal(size=(32, 19))
    actual = batched_joint_targets(actions)
    for i in range(32):
        np.testing.assert_allclose(actual[i], list(mobile_targets(actions[i]).values()))
    assert len(np.unique(actual[:, 0])) == 32


def test_grid_and_camera_aspect_preserve_scope():
    origins = room_origins(32)
    assert origins.shape == (32, 3)
    assert len(np.unique(origins, axis=0)) == 32
    assert min(np.linalg.norm(a-b) for i, a in enumerate(origins) for b in origins[i+1:]) >= 12
    assert CAMERAS['head_left'][0]/CAMERAS['head_left'][1] == 1920/1536
    assert CAMERAS['left_wrist'][0]/CAMERAS['left_wrist'][1] == 1280/720


def test_parent_variants_cannot_cross_splits():
    rows = [dict(parent_scene_id='p', parent_split='train')]*32
    assert validate_sources(rows) == {'p': 'train'}
    with pytest.raises(ValueError, match='leakage'):
        validate_sources(rows + [dict(parent_scene_id='p', parent_split='test')])


def test_invalid_actions_rejected_before_submission():
    with pytest.raises(ValueError):
        batched_joint_targets(np.zeros((32, 18)))
    a = np.zeros((4, 19)); a[2, 1] = np.nan
    with pytest.raises(ValueError):
        batched_joint_targets(a)


def test_large_pose_variants_are_supported_not_mislabeled_reachable():
    table=dict(table_id='front', dimensions_m=[1.5,.85,.75], center_world=[.8,0,0], yaw_world=.3)
    rows=sample_table_poses(table,[.56,.43,.105],200,9001)
    assert rows==sample_table_poses(table,[.56,.43,.105],200,9001)
    assert np.ptp([r['initial_yaw_rad'] for r in rows])>np.deg2rad(150)
    assert np.ptp([r['table_local_xy_m'][0] for r in rows])>.5
    for r in rows:
        a=r['initial_yaw_rad']-.3;c,s=abs(np.cos(a)),abs(np.sin(a))
        ext=np.array([c*.56+s*.43,s*.56+c*.43])/2
        assert np.all(abs(np.array(r['table_local_xy_m']))+ext<=np.array([.75,.425])+1e-12)
        assert r['reachability']=='not_checked' and not r['training_eligible']
def test_bc_native_resource_gate_does_not_start_training_without_wait(tmp_path,monkeypatch):
    import pytest
    pytest.importorskip('fcntl')
    import runpy,json,sys
    from pathlib import Path
    root=Path(__file__).resolve().parents[1]
    monkeypatch.syspath_prepend(str(root/'scripts'))
    run=tmp_path/'new_bc';run.mkdir();training=run/'training'
    cfg=tmp_path/'config.json';cfg.write_text(json.dumps(dict(run=str(run),training=str(training),wait_for_native_receipts=[str(tmp_path/'native.exit.json')])))
    module=runpy.run_path(str(root/'scripts/resume_isaacsim_bc_after_video.py'))
    monkeypatch.setattr(sys,'argv',['resume','--config',str(cfg)])
    def stop_wait(seconds):raise RuntimeError('test_end_while_waiting')
    monkeypatch.setattr(module['time'],'sleep',stop_wait)
    monkeypatch.setattr(module['subprocess'],'Popen',lambda *a,**kw:pytest.fail('training must not launch before native wait'))
    with pytest.raises(RuntimeError,match='test_end_while_waiting'):module['main']()
    assert not training.exists()
    state=json.loads((run/'pipeline_status.json').read_text())
    assert state['actual_completed_updates']==0 and state['training_started'] is False
    assert state['pending_actual_exit_receipts']==[str(tmp_path/'native.exit.json')]
