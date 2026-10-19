import json
from pathlib import Path
import pytest
from r1pro_teleop.single_tray_3table import guardian as g


def fixture(tmp_path):
    workflow=tmp_path/'workflow.json';root=tmp_path/'run';root.mkdir()
    workflow.write_text(json.dumps(dict(workflow_dir=str(root))))
    identity=dict(pid=123,argv=['python','supervise_three_table_workflow.py','--options',str(workflow)],cwd=str(tmp_path),start_ticks='42')
    options=dict(schema='airport_three_table_workflow_guardian/1',guardian_dir=str(tmp_path/'guardian'),workflow_options=str(workflow),workflow_options_sha256=g.digest(workflow),supervisor_cwd=str(tmp_path),supervisor_argv=['python','supervise_three_table_workflow.py','--options',str(workflow),'--recover'],adopt_supervisor=identity)
    return options,dict(supervisor=identity,process_faults=[]),identity,root


def test_healthy_original_parent_adopted_without_signal_or_duplicate(tmp_path):
    o,s,job,_=fixture(tmp_path);g.validate_guardian(o)
    for now in [0,10,10000]:g.guardian_step(o,s,probe=lambda pid:job,clock=lambda:now,launch=lambda *args:pytest.fail('healthy job may not duplicate'))
    assert s['stage']=='watching_verified_supervisor' and s['process_faults']==[]


@pytest.mark.parametrize('field,value',[('start_ticks','43'),('argv',['unrelated-service']),('cwd','/unrelated')])
def test_pid_reuse_or_identity_change_blocks_without_signals(tmp_path,field,value):
    o,s,job,_=fixture(tmp_path);actual=dict(job);actual[field]=value
    with pytest.raises(ValueError,match='identity_changed'):g.guardian_step(o,s,probe=lambda pid:actual,clock=lambda:0,launch=lambda *args:pytest.fail('must not launch'))


def test_supervisor_death_restarts_exact_recover_three_times_with_backoff(tmp_path):
    o,s,_,_=fixture(tmp_path);launches=[]
    def launch(argv,cwd,n):
        launches.append((argv,cwd,n));return dict(pid=123+n,argv=argv,cwd=cwd,start_ticks=str(n))
    now=0
    for delay in [10,30,90]:
        g.guardian_step(o,s,probe=lambda pid:None,clock=lambda:now,launch=launch)
        assert s['retry_after_unix']==now+delay
        g.guardian_step(o,s,probe=lambda pid:None,clock=lambda:now+delay-1,launch=launch)
        assert len(launches)==len(s['process_faults'])-1
        now+=delay;g.guardian_step(o,s,probe=lambda pid:None,clock=lambda:now,launch=launch)
    g.guardian_step(o,s,probe=lambda pid:None,clock=lambda:1000,launch=launch)
    assert len(launches)==3 and s['stage']=='blocked_process_fault_limit'
    assert all(v[0]==o['supervisor_argv'] and '--recover' in v[0] for v in launches)


def test_cached_complete_boolean_without_actual_milestones_is_not_complete(tmp_path):
    o,s,_,root=fixture(tmp_path)
    (root/'workflow_status.json').write_text(json.dumps(dict(training_pipeline_status=dict(stage='three_table_bc_training_and_new_scope_evaluations_complete',training_complete=True,actual_completed_updates=100000))))
    g.guardian_step(o,s,probe=lambda pid:None,clock=lambda:1,launch=lambda *args:pytest.fail('backoff must precede process recovery'))
    assert not s.get('completed') and s['stage']=='process_fault_backoff'


def test_false_complete_or_mutated_options_do_not_authorize_resume(tmp_path):
    o,s,_,root=fixture(tmp_path)
    (root/'workflow_status.json').write_text(json.dumps(dict(training_pipeline_status=dict(training_complete=True,actual_completed_updates=10))))
    assert not g.completed_artifact(o)
    Path(o['workflow_options']).write_text('{}')
    with pytest.raises(ValueError,match='options_changed'):g.validate_guardian(o)

def test_known_terminal_pipeline_error_does_not_become_outer_os_retries(tmp_path):
    o,state,_,root=fixture(tmp_path)
    run=tmp_path/'actual_train';run.mkdir()
    training=tmp_path/'training_options.json';training.write_text(json.dumps(dict(run_dir=str(run))))
    workflow=Path(o['workflow_options']);workflow.write_text(json.dumps(dict(workflow_dir=str(root),training_options=str(training))))
    o['workflow_options_sha256']=g.digest(workflow)
    status=run/'pipeline_status.json';status.write_text(json.dumps(dict(stage='failed_preserving_sources_and_checkpoints',error="ValueError('actual_plan_binding_changed')")))
    for now in (0,100,1000):
        g.guardian_step(o,state,probe=lambda pid:None,clock=lambda:now,launch=lambda *a:pytest.fail('known contract failure must not restart'))
    assert state['process_faults']==[]
    assert state['stage']=='blocked_terminal_pipeline_failure_requires_new_reviewed_run'
    assert state['terminal_pipeline_failure']['status_sha256']==g.digest(status)

def test_main_terminal_failure_still_recovers_registered_live_or_bounded_pending_watcher(tmp_path,monkeypatch):
    o,state,_,root=fixture(tmp_path)
    training=tmp_path/'training_options.json';run=tmp_path/'main';run.mkdir()
    training.write_text(json.dumps(dict(run_dir=str(run))))
    (run/'pipeline_status.json').write_text(json.dumps(dict(stage='failed_preserving_sources_and_checkpoints',error='main_contract_failure')))
    data=tmp_path/'data2.json';data.write_text('{"data_only":true}')
    watch=tmp_path/'watch';watch.mkdir();(watch/'status.json').write_text(json.dumps(dict(stage='waiting_actual_milestone10_gpu1_evaluation')))
    workflow=Path(o['workflow_options']);workflow.write_text(json.dumps(dict(workflow_dir=str(root),training_options=str(training),data_version2_watcher=dict(options=str(data),options_sha256=g.digest(data),watch_dir=str(watch)))))
    o['workflow_options_sha256']=g.digest(workflow)
    job=dict(pid=456,start_ticks='42',argv=['owned-watcher'],cwd=str(tmp_path),exited=True)
    parent=dict(options_sha256=g.digest(workflow),children=dict(source_v2_dataset_watcher=job),process_faults={})
    status=root/'workflow_status.json';status.write_text(json.dumps(parent))
    monkeypatch.setattr(g,'checked_process',lambda candidate,*a:job if candidate['pid']==456 else None)
    g.guardian_step(o,state,probe=lambda pid:None,clock=lambda:0,launch=lambda *a:pytest.fail('backoff first'))
    assert state['stage']=='process_fault_backoff'
    assert state['supervision_scope']=='registered_data_version2_only_main_failure_sticky'
    monkeypatch.setattr(g,'checked_process',lambda *a:None)
    assert g.registered_data_watcher_needs_supervision(o)  # Recorded pending recovery, actual status present.
    parent['process_faults']['source_v2_dataset_watcher']=[{}, {}, {}];status.write_text(json.dumps(parent))
    assert not g.registered_data_watcher_needs_supervision(o)
    g.guardian_step(o,state,probe=lambda pid:None,clock=lambda:100,launch=lambda *a:pytest.fail('exhausted watcher cannot restart parent'))
    assert state['stage']=='blocked_terminal_pipeline_failure_requires_new_reviewed_run'
    parent['process_faults']={};status.write_text(json.dumps(parent));(watch/'status.json').unlink()
    assert not g.registered_data_watcher_needs_supervision(o)  # Missing status never licenses endless retries.

@pytest.mark.parametrize('stage,closed,terminal',[
    ('failed_preserving_sources_and_checkpoints',False,True),
    ('preflight_contract_failed_preserving_sources_and_checkpoints',False,True),
    ('blocked_frozen_batch_media_case',False,True),
    ('waiting_missing_qualified_media_split',True,True),
    ('waiting_missing_qualified_media_split',False,False),
    ('waiting_missing_qualified_media_split',None,False)])
def test_closed_source_media_and_preflight_terminal_stage_alignment(stage,closed,terminal):
    from r1pro_teleop.single_tray_3table.workflow import terminal_training_status
    assert terminal_training_status(dict(stage=stage,source_campaign_closed=closed)) is terminal

def test_completion_external_optimizer_milestones_use_new_eval_receipts_and_bound_inputs(tmp_path):
    from r1pro_teleop.vla.data_three_table_single_tray import PROFILE
    o,_,_,root=fixture(tmp_path)
    old=tmp_path/'B29';old.mkdir();new=tmp_path/'NEW30';new.mkdir()
    resource=old/'cache_manifest.json';resource.write_text('{"fixture":true}')
    norm=old/'norm.json';norm.write_text('{}')
    train=tmp_path/'train_options.json'
    train.write_text(json.dumps(dict(run_dir=str(new),external_training_run=str(old),training_release='immutable_V29',external_input_sha256={str(resource):g.digest(resource)})))
    Path(o['workflow_options']).write_text(json.dumps(dict(workflow_dir=str(root),training_options=str(train))))
    (new/'pipeline_status.json').write_text(json.dumps(dict(stage='three_table_bc_training_and_new_scope_evaluations_complete',training_complete=True,actual_completed_updates=100000)))
    for n in (10,100,1000,10000,100000):
        checkpoint=old/f'checkpoints/{n-1}';(checkpoint/'params').mkdir(parents=True);(checkpoint/'train_state').mkdir()
        milestone=old/f'milestone_{n:06d}.json'
        milestone.write_text(json.dumps(dict(schema='airport_pi05_training_milestone/1',prompt_mode=PROFILE,checkpoint_verified=True,actual_completed_updates=n,checkpoint_step=n-1,checkpoint=str(checkpoint),normalization=str(norm),norm_sha256=g.digest(norm))))
        evaluated=new/f'evaluations/step_{n:06d}';evaluated.mkdir(parents=True)
        case={}
        for field in ('trace','result'):
            path=evaluated/(field+'.fixture');path.write_text('unit fixture only');case[field]=str(path);case[field+'_sha256']=g.digest(path)
        case['videos']=[]
        for camera in ('head_left','head_right','left_wrist','right_wrist'):
            path=evaluated/(camera+'.fixture');path.write_text('unit fixture only');case['videos'].append(dict(camera=camera,path=str(path),sha256=g.digest(path)))
        summary=evaluated/'summary.json';summary.write_text(json.dumps(dict(protocol_id='unit-protocol',covered=1,selected=1,cases=[case])))
        (evaluated/'completion_receipt.json').write_text(json.dumps(dict(schema='airport_three_table_single_tray_evaluation_handoff/1',task_profile=PROFILE,actual_completed_updates=n,training_status_sha256=g.digest(milestone),status='evaluation_completed_gpu_released',training_resume_allowed=True,active_owned_gpu_rows=[],actual_owned_processes=[dict(returncode=0,active=False)],evaluation_summary=str(summary),evaluation_summary_sha256=g.digest(summary),new_three_table_single_tray_protocol_id='unit-protocol')))
    assert g.completed_artifact(o)
    assert not (new/'milestone_000010.json').exists()
    resource.write_text('{"mutated":true}')
    assert not g.completed_artifact(o)
