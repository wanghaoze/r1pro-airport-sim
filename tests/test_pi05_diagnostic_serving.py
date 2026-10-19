import json
from pathlib import Path
import pytest
from scripts.serve_pi05_diagnostic import verify_diagnostic_checkpoint,sha
from scripts.serve_pi05_airport import verify_training_checkpoint


def fixture(tmp_path):
    root=tmp_path/'diagnostic';checkpoint=root/'checkpoints/diag/training/3'
    for name in ('params','train_state'):
        folder=checkpoint/name;folder.mkdir(parents=True);(folder/'actual_bytes').write_bytes(name.encode())
    norm=checkpoint/'assets/airport/diagnostic/norm_stats.json';norm.parent.mkdir(parents=True);norm.write_text('{}')
    cache=root/'cache.json';cache.write_text('{}')
    spec=dict(dataset_root=str(tmp_path/'dataset'),dataset_repo_id='airport/diagnostic',
        openpi_root=str(tmp_path/'openpi'),base_params=str(tmp_path/'base'),run_dir=str(root),
        name='diag',num_train_steps=100000,prompt_mode='task_complete_action8_v1')
    status=dict(schema='airport_pi05_training_diagnostic/1',status='diagnostic_checkpoint',
        checkpoint_verified=True,training_complete=False,prompt_mode='task_complete_action8_v1',model='pi05',
        fps=20,action_semantics='absolute_mobile19',source='simulation/program_generated',
        actual_completed_updates=4,checkpoint_step=3,checkpoint=str(checkpoint),spec=spec,
        norm_sha256=sha(norm),cache_manifest=str(cache),cache_manifest_sha256=sha(cache))
    path=root/'milestone_000004.json';path.write_text(json.dumps(status));return path,status


def test_actual_file_identity_includes_params_optimizer_norm_and_diagnostic_status(tmp_path):
    path,status=fixture(tmp_path);_,checkpoint,identity=verify_diagnostic_checkpoint(path)
    assert identity['actual_completed_updates']==4 and identity['diagnostic'] is True
    paths={row['path'] for row in identity['checkpoint_files']}
    assert 'params/actual_bytes' in paths and 'train_state/actual_bytes' in paths
    (checkpoint/'params/actual_bytes').write_bytes(b'changed_actual_weights')
    changed=verify_diagnostic_checkpoint(path)[2]
    assert changed['checkpoint_id']!=identity['checkpoint_id']


@pytest.mark.parametrize('changed',[{'training_complete':True},{'schema':'formal'},
    {'checkpoint_step':4},{'actual_completed_updates':0},{'prompt_mode':'skill_only_v1'}])
def test_diagnostic_identity_refuses_wrong_scope_or_unverified_step(tmp_path,changed):
    path,status=fixture(tmp_path);status.update(changed);path.write_text(json.dumps(status))
    with pytest.raises(ValueError):verify_diagnostic_checkpoint(path)


def test_formal_server_still_rejects_real_diagnostic_checkpoint(tmp_path):
    path,_=fixture(tmp_path)
    verify_diagnostic_checkpoint(path)
    with pytest.raises(ValueError):verify_training_checkpoint(path)
