"""V29 migration binds artifacts and original closed source; no process launch."""
import importlib.util
import json
from pathlib import Path

import pytest


def helper():
    path=Path(__file__).resolve().parents[1]/'runs/three_table_reference_20261006/deploy_artifact_reuse_v29.py'
    spec=importlib.util.spec_from_file_location('v29_deploy_contract',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def put(path,value):
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value))


def test_native_bindings_derive_actual_exit_argv_without_render_or_copy(tmp_path,monkeypatch):
    m=helper();monkeypatch.setattr(m,'OLD',tmp_path)
    for split in ('train','val','test'):
        folder=tmp_path/'training_batch_v1/native'/split/'actual_scene'
        put(folder/'manifest.json',{'verified':True})
        put(tmp_path/f'training_batch_v1/render_{split}_0.exit.json',
            dict(returncode=0,trainer_exited=True,argv=['python','renderer','--output',str(folder)]))
    rows=m.reusable_native_stages()
    assert len(rows)==3
    assert rows['native_val_0']['folder'].endswith('val/actual_scene') or rows['native_val_0']['folder'].endswith('val\\actual_scene')
    assert rows['native_train_0']['exit_receipt_sha256']==m.sha(rows['native_train_0']['exit_receipt'])
    put(tmp_path/'training_batch_v1/render_test_0.exit.json',dict(returncode=17,trainer_exited=True,argv=[]))
    with pytest.raises(ValueError,match='exit0_required'):m.reusable_native_stages()


def test_adoption_keeps_original_v27_identity_and_rejects_live_source(tmp_path,monkeypatch):
    m=helper();monkeypatch.setattr(m,'OLD',tmp_path/'v28')
    old27=tmp_path/'v27';prior=old27/'workflow_options.json';plan=old27/'campaign_v2/plan.json'
    put(prior,{'release':'v27'});put(plan,{'selected':6})
    binding=dict(pid=1677763,argv=['python','v27/coordinator'],cwd='v27',start_ticks='birth',
        prior_workflow_options=str(prior),prior_workflow_options_sha256=m.sha(prior),
        source_plan=str(plan),source_plan_sha256=m.sha(plan),selection_sha256='selection')
    put(m.OLD/'workflow_options.json',dict(adopt_children={'source_campaign_v2':binding},
        continuation={'campaign_dir':str(plan.parent)}))
    put(m.OLD/'workflow_status.json',{'children':{'source_campaign_v2':binding}})
    put(plan.parent/'status.json',dict(completed=6,selected=6,results=[{'actual':True}]*6))
    monkeypatch.setattr(m,'identity',lambda pid:None)
    assert m.adopted_source()==binding
    assert m.adopted_source()['prior_workflow_options']==str(prior)
    monkeypatch.setattr(m,'identity',lambda pid:{'pid':pid})
    with pytest.raises(ValueError,match='must_be_closed'):m.adopted_source()


def test_v29_has_one_supervised_data2_launcher_and_no_dataset_manifest_copy():
    text=Path(helper().__file__).read_text()
    assert "options['data_version2_watcher']=" in text
    assert "options['continuation'].pop('dataset_only_options',None)" in text
    assert "data_only=True,data_version='v2'" in text
    assert 'supervised_unique_data2_watcher_support_not_in_frozen_release' in text
    assert 'datasets_reexported_from_verified_native=True' in text


def test_closed_durable_waiter_identity_is_verified_through_inner_command(tmp_path,monkeypatch):
    m=helper();monkeypatch.setattr(m,'OLD',tmp_path/'old');monkeypatch.setattr(m,'PRIOR_RELEASE',tmp_path/'release')
    inner=[m.VLA,str(m.PRIOR_RELEASE/'scripts/supervise_three_table_single_tray_training.py'),
        '--options',str(m.OLD/'training_options.json')]
    path=m.OLD/'training_waiter_command_attempt_00.json'
    put(path,dict(schema='airport_three_table_owned_command/1',argv=inner,cwd=str(m.PRIOR_RELEASE),
        output=str(m.OLD/'training_waiter_owned_attempt_00')))
    waiter=dict(pid=2051504,start_ticks='123456',cwd=str(m.PRIOR_RELEASE),
        argv=[m.VLA,str(m.PRIOR_RELEASE/'scripts/run_three_table_owned_command.py'),'--options',str(path)])
    guardian=dict(pid=1689440,start_ticks='123506602',cwd=str(m.PRIOR_RELEASE),
        argv=[m.SIM,str(m.PRIOR_RELEASE/'scripts/guard_three_table_workflow.py')])
    supervisor=dict(pid=2053889,start_ticks='234567',cwd=str(m.PRIOR_RELEASE),
        argv=[m.SIM,str(m.PRIOR_RELEASE/'scripts/supervise_three_table_workflow.py')])
    put(m.OLD/'migration_receipt.json',{'new_guardian':guardian})
    put(m.OLD/'guardian/guardian_status.json',{'supervisor':supervisor})
    put(m.OLD/'workflow_status.json',{'children':{'training_waiter':waiter}})
    monkeypatch.setattr(m,'identity',lambda pid:None)
    jobs=m.expected_old_jobs()
    assert jobs[-1]['pid']==2051504 and jobs[-1]['start_ticks']=='123456'
    assert m.stop_exact(jobs[-1])['signaled'] is False
    put(path,dict(schema='airport_three_table_owned_command/1',argv=['python','unknown.py'],
        cwd=str(m.PRIOR_RELEASE),output=str(m.OLD/'training_waiter_owned_attempt_00')))
    with pytest.raises(ValueError,match='inner_command_unreviewed'):m.expected_old_jobs()
