"""RGB recovery keeps three distinct roots: V31 orchestration, V29 training/data."""
import importlib.util,json
from pathlib import Path


def helper():
    path=Path(__file__).resolve().parents[1]/'runs/three_table_reference_20261006/deploy_model_rgb_v31.py'
    spec=importlib.util.spec_from_file_location('v31_deploy_contract',path)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


def put(path,value):
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value))


def test_v31_preserves_v29_watcher_prior_options_instead_of_rebinding_to_v30(tmp_path,monkeypatch):
    m=helper();monkeypatch.setattr(m,'OLD',tmp_path/'v30')
    prior=tmp_path/'v29/workflow_options.json';command=tmp_path/'v29/command.json'
    put(prior,{'release':'original_v29'});put(command,{'argv':['v29watcher']})
    job=dict(pid=2078731,start_ticks='123834332',argv=['v29wrapper'],cwd='v29release',
        prior_workflow_options=str(prior),prior_workflow_options_sha256=m.sha(prior),
        command_options=str(command),command_options_sha256=m.sha(command),actual_command_argv=['v29watcher'])
    put(m.OLD/'workflow_options.json',{'adopt_children':{'source_v2_dataset_watcher':job}})
    put(m.OLD/'workflow_status.json',{'children':{'source_v2_dataset_watcher':job}})
    monkeypatch.setattr(m,'exact',lambda *args,**kwargs:job)
    assert m.adopted_watcher()==job


def test_v31_optimizer_remains_v29_and_only_orchestration_changes(tmp_path,monkeypatch):
    m=helper();monkeypatch.setattr(m,'BASE',tmp_path);monkeypatch.setattr(m,'RUNS',tmp_path/'runs')
    monkeypatch.setattr(m,'OLD',tmp_path/'runs/v30');monkeypatch.setattr(m,'NEW',tmp_path/'runs/v31')
    monkeypatch.setattr(m,'RELEASE',tmp_path/'releases/v31')
    oldrun=m.RUNS/'overnight_hardened_v29_v1/training_batch_v1'
    original=tmp_path/'releases/three_table_single_tray_v29_artifact_reuse_20261006'
    spec=m.RUNS/'overnight_hardened_v29_v1/training_spec.json';put(spec,{'run_dir':str(oldrun)})
    put(m.OLD/'training_options.json',dict(run_dir=str(m.OLD/'training_batch_v1'),external_training_run=str(oldrun),training_release=str(original),spec=str(spec)))
    put(oldrun/'milestone_000010.json',{'actual_completed_updates':10,'checkpoint_step':9})
    put(oldrun/'train_to_000010.exit.json',{'returncode':0,'trainer_exited':True})
    for path in (oldrun/'data_cache/cache_manifest.json',oldrun/'acceleration_spec.json'):put(path,{})
    for split in ('train','val','test'):
        for name in ('airport_training_manifest.json','whole_action_source_manifest.jsonl'):put(oldrun/'datasets'/split/name,{})
    for name in ('scripts/train_pi05_accelerated.py','r1pro_teleop/vla/training_accelerated.py','r1pro_teleop/vla/training.py'):
        path=original/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('original_math')
    value=m.external_training_options(tmp_path/'core.json')
    assert value['external_training_run']==str(oldrun) and value['training_release']==str(original)
    assert value['run_dir']==str(m.NEW/'training_batch_v1') and value['spec']==str(spec)
    assert all('v30' not in path for path in value['external_input_sha256'])
