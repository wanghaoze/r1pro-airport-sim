"""V30 resumes saved optimizer while preserving the healthy V29 data watcher."""
import importlib.util,json
from pathlib import Path
import pytest


def helper():
    path=Path(__file__).resolve().parents[1]/'runs/three_table_reference_20261006/deploy_eval_resume_v30.py'
    spec=importlib.util.spec_from_file_location('v30_deploy_contract',path)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


def put(path,value):
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value))


def test_external_resume_keeps_original_spec_release_and_saved_artifacts(tmp_path,monkeypatch):
    m=helper();monkeypatch.setattr(m,'OLD',tmp_path/'v29');monkeypatch.setattr(m,'NEW',tmp_path/'v30')
    monkeypatch.setattr(m,'PRIOR_RELEASE',tmp_path/'release29');monkeypatch.setattr(m,'RELEASE',tmp_path/'release30')
    run=m.OLD/'training_batch_v1';spec=m.OLD/'training_spec.json'
    put(spec,{'run_dir':str(run),'dataset_root':str(run/'datasets/train'),'num_train_steps':100000})
    put(m.OLD/'training_options.json',{'run_dir':str(run),'spec':str(spec),'evaluation_protocol':'oldprotocol','parent_status':'parent'})
    put(run/'milestone_000010.json',{'actual_completed_updates':10,'checkpoint_step':9})
    put(run/'train_to_000010.exit.json',{'returncode':0,'trainer_exited':True})
    for path in [run/'data_cache/cache_manifest.json',run/'acceleration_spec.json']:
        put(path,{'actual_saved':True})
    for split in ('train','val','test'):
        for name in ('airport_training_manifest.json','whole_action_source_manifest.jsonl'):put(run/'datasets'/split/name,{'source':split})
    for name in ('scripts/train_pi05_accelerated.py','r1pro_teleop/vla/training_accelerated.py','r1pro_teleop/vla/training.py'):
        path=m.PRIOR_RELEASE/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('original_training_math')
    row=m.external_training_options(tmp_path/'core.json')
    assert row['spec']==str(spec) and row['training_release']==str(m.PRIOR_RELEASE)
    assert row['external_training_run']==str(run) and row['run_dir']==str(m.NEW/'training_batch_v1')
    assert row['evaluation_protocol']=='oldprotocol' and len(row['external_input_sha256'])==12
    assert not m.NEW.exists() and json.loads(spec.read_text())['num_train_steps']==100000


def test_watcher_adoption_preserves_wrapper_birth_and_inner_command(tmp_path,monkeypatch):
    m=helper();monkeypatch.setattr(m,'OLD',tmp_path/'v29')
    command=m.OLD/'source_v2_dataset_watcher_command_attempt_00.json';put(command,{'argv':['oldwatcher']})
    job=dict(pid=2078731,start_ticks='123834332',argv=['oldwrapper'],cwd='oldrelease',
        command_options=str(command),actual_command_argv=['oldwatcher'])
    put(m.OLD/'workflow_options.json',{'data_version2_watcher':{'watch_dir':'oldwatchdir'}})
    put(m.OLD/'workflow_status.json',{'children':{'source_v2_dataset_watcher':job}})
    monkeypatch.setattr(m,'exact',lambda value,**kw:value)
    adopted=m.adopted_watcher()
    assert adopted['argv']==job['argv'] and adopted['actual_command_argv']==['oldwatcher']
    assert adopted['command_options_sha256']==m.sha(command)
    job['start_ticks']='reused_birth';put(m.OLD/'workflow_status.json',{'children':{'source_v2_dataset_watcher':job}})
    with pytest.raises(ValueError,match='wrapper_birth_required'):m.adopted_watcher()


def test_helper_never_signals_data2_and_requires_actual_cpu_fixture_before_launch():
    text=Path(helper().__file__).read_text()
    assert "data_version2_watcher=dict(previous['data_version2_watcher'])" in text
    assert "core=core_tests();prepare_options(args.certified_source_catalog,core,freeze);cpu_recovery_fixture()" in text
    assert "allowed={watcher['pid']}|descendants({watcher['pid']})" in text
    assert "jobs=[j for j in latest if j['name']!='guardian']" in text
    assert 'new_optimizer_initialized' not in text
