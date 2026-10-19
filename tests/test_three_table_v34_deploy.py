"""RGB recovery keeps three distinct roots: V34 orchestration, V29 training/data."""
import importlib.util,json
from pathlib import Path
import pytest


def helper():
    path=Path(__file__).resolve().parents[1]/'runs/three_table_reference_20261006/deploy_eval_audit_v34.py'
    spec=importlib.util.spec_from_file_location('v34_deploy_contract',path)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


def put(path,value):
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value))


def test_v34_preserves_v29_watcher_prior_options_instead_of_rebinding_to_v30(tmp_path,monkeypatch):
    m=helper();monkeypatch.setattr(m,'OLD',tmp_path/'v31')
    prior=tmp_path/'v29/workflow_options.json';command=tmp_path/'v29/command.json'
    put(prior,{'release':'original_v29'});put(command,{'argv':['v29watcher']})
    job=dict(pid=2078731,start_ticks='123834332',argv=['v29wrapper'],cwd='v29release',
        prior_workflow_options=str(prior),prior_workflow_options_sha256=m.sha(prior),
        command_options=str(command),command_options_sha256=m.sha(command),actual_command_argv=['v29watcher'])
    put(m.OLD/'workflow_options.json',{'adopt_children':{'source_v2_dataset_watcher':job}})
    put(m.OLD/'workflow_status.json',{'children':{'source_v2_dataset_watcher':job}})
    monkeypatch.setattr(m,'exact',lambda *args,**kwargs:job)
    assert m.adopted_watcher()==job


def test_v34_optimizer_remains_v29_and_only_orchestration_changes(tmp_path,monkeypatch):
    m=helper();monkeypatch.setattr(m,'BASE',tmp_path);monkeypatch.setattr(m,'RUNS',tmp_path/'runs')
    monkeypatch.setattr(m,'OLD',tmp_path/'runs/v30');monkeypatch.setattr(m,'NEW',tmp_path/'runs/v34')
    monkeypatch.setattr(m,'RELEASE',tmp_path/'releases/v34')
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


def test_closed_failed_watcher_keeps_actual_exit1_and_never_requires_restart(tmp_path):
    m=helper();command=tmp_path/'command.json';options=tmp_path/'data_options.json';run=tmp_path/'data'
    put(command,dict(argv=['original_watcher'],cwd='original_release'))
    put(options,{'run_dir':str(run)})
    job=dict(pid=2078731,argv=['original_wrapper'],cwd='original_release',start_ticks='123834332',
        command_options=str(command),command_options_sha256=m.sha(command),command_output=str(tmp_path/'owned'),actual_command_argv=['original_watcher'])
    exitfile=tmp_path/'owned/exit.json'
    put(exitfile,dict(actual_exit_observed=True,returncode=1,pid=2078732,child_identity={'pid':2078732},
        wrapper_identity={k:job[k] for k in ('pid','argv','cwd','start_ticks')},options_sha256=m.sha(command),argv=['original_watcher'],cwd='original_release'))
    put(tmp_path/'watch/status.json',{'pid':2078732,'stage':'data_only_watch_contract_or_fault_budget_blocked'})
    put(run/'pipeline_status.json',{'stage':'failed_preserving_partial_artifacts'})
    previous={'data_version2_watcher':dict(options=str(options),options_sha256=m.sha(options),watch_dir=str(tmp_path/'watch'))}
    proof=m.closed_data2_evidence(job,previous)
    assert proof['actual_returncode']==1 and proof['watcher_restart_allowed'] is False
    assert not proof['all_six_sources_ready'] and proof['independently_verified_datasets']=={}
    assert proof['exit_sha256']==m.sha(exitfile)
    row=json.loads(exitfile.read_text());row['wrapper_identity']['start_ticks']='otherbirth';put(exitfile,row)
    with pytest.raises(ValueError,match='wrapper_birth_identity_changed'):m.closed_data2_evidence(job,previous)


def test_preclone_data_audit_never_imports_old_packages_in_parent_interpreter():
    import ast,inspect
    m=helper();body=ast.parse(inspect.getsource(m.closed_data2_evidence))
    assert not any(isinstance(node,(ast.Import,ast.ImportFrom)) for node in ast.walk(body))
    text=inspect.getsource(m.closed_data2_evidence)
    assert "subprocess.check_output([SIM,'-c',audit_code,str(PRIOR_RELEASE),str(run)]" in text
    assert "CUDA_VISIBLE_DEVICES='',JAX_PLATFORMS='cpu'" in text
    assert 'old_dataset_auditor_release_identity_mismatch' in text
    assert 'new_release_validator_import_identity_mismatch' in inspect.getsource(m.prepare_options)


def test_shared_contact_summary_backward_contract_is_in_server_core_tuple():
    import inspect
    assert 'test_single_tray_contact_summary.py' in inspect.getsource(helper().core_tests)
