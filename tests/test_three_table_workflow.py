import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from r1pro_teleop.single_tray_3table import workflow as w
from r1pro_teleop.vla.data_three_table_single_tray import PROFILE,RULE_REVISION


def fixture(tmp_path,complete=True):
    root=tmp_path/'overnight';root.mkdir();(root/'bootstrap_status.json').write_text('retained bootstrap')
    scene=tmp_path/'scene.json';scene.write_text(json.dumps(dict(task_profile=PROFILE,task_rule_revision=RULE_REVISION)))
    result=tmp_path/'diagnostic_result.json';result.write_text(json.dumps(dict(schema='airport_three_table_full_motion_candidate/1',task_completed=complete,empty_pick_completed=True,empty_place_completed=True,loaded_continuation=dict(push_loaded_completed=complete,actual_handover_verified=complete),recorded_frames=123)))
    training=tmp_path/'train_options.json';training.write_text(json.dumps(dict(campaign=str(root/'campaign_v1'),release=str(tmp_path),run_dir=str(root/'training'))))
    options=dict(schema=w.SCHEMA,workflow_dir=str(root),release=str(tmp_path),sim_python='sim-python',vla_python='vla-python',selection='selection',inventory='inventory',parent_manifest='manifest',split_registry='registry',campaign_dir=str(root/'campaign_v1'),config='cfg',push_reference_scene='ref',training_options=str(training),demo_candidates=[dict(scene=str(scene),result=str(result),cwd=str(tmp_path))])
    path=tmp_path/'workflow_options.json';path.write_text(json.dumps(options))
    return options,path,scene,result,root


def stop(_):raise RuntimeError('stop_test_loop')


def test_healthy_demo_pid_never_accepts_early_result_or_duplicates(tmp_path):
    o,_,_,_,_=fixture(tmp_path);job=dict(o['demo_candidates'][0],pid=123,argv=['python','demo.py'])
    identity=dict(pid=123,argv=job['argv'],cwd=job['cwd'],start_ticks='77')
    proof=w.demo_gate(job,probe=lambda pid:identity)
    assert proof['status']=='running' and not proof['task_completed']
    with pytest.raises(ValueError,match='identity_changed'):
        w.demo_gate(job,probe=lambda pid:dict(identity,argv=['unrelated']))


@pytest.mark.parametrize('change',['old_scope','failed_push','missing_handover','partial_empty','changed_scene'])
def test_partial_old_scope_or_mutated_demo_cannot_unlock_collection(tmp_path,change):
    o,_,scene,result,_=fixture(tmp_path);job=o['demo_candidates'][0]
    r=json.loads(result.read_text())
    if change=='old_scope':scene.write_text(json.dumps(dict(task_profile='single_tray_action3_v1',task_rule_revision=RULE_REVISION)))
    elif change=='failed_push':r['loaded_continuation']['push_loaded_completed']=False
    elif change=='missing_handover':r['loaded_continuation']['actual_handover_verified']=False
    elif change=='partial_empty':r['empty_pick_completed']=False
    else:job['scene_sha256']='a'*64
    result.write_text(json.dumps(r))
    if change in ('old_scope','changed_scene'):
        with pytest.raises(ValueError):w.demo_gate(job)
    else:assert not w.demo_gate(job)['task_completed']


def test_options_bind_campaign_release_and_only_explicit_bounded_recipes(tmp_path):
    o,_,_,_,_=fixture(tmp_path);w.validate_options(o)
    o['campaign_dir']=str(tmp_path/'outside')
    with pytest.raises(ValueError,match='inside_workflow'):w.validate_options(o)
    o['campaign_dir']=str(Path(o['workflow_dir'])/'campaign_v1');o['demo_candidates']*=4
    with pytest.raises(ValueError,match='bounded'):w.validate_options(o)


def test_complete_demo_then_collection_and_train_waiter_recovery_no_duplicate(tmp_path,monkeypatch):
    o,path,_,_,root=fixture(tmp_path)
    monkeypatch.setitem(sys.modules,'fcntl',SimpleNamespace(LOCK_EX=1,LOCK_NB=2,flock=lambda *a:None))
    monkeypatch.setattr(w.os,'getsid',lambda pid:777,raising=False)
    monkeypatch.setattr(w.time,'sleep',stop);monkeypatch.setattr(w,'process_identity',lambda pid:None)
    children=[]
    def popen(argv,**kw):
        children.append((argv,kw));return SimpleNamespace(pid=100+len(children),poll=lambda:None)
    monkeypatch.setattr(w.subprocess,'Popen',popen)
    with pytest.raises(RuntimeError,match='stop_test_loop'):w.supervise(path)
    assert len(children)==3 and (root/'bootstrap_status.json').read_text()=='retained bootstrap'
    assert 'render_three_table_original_trace.py' in children[0][0][1]
    assert 'supervise_three_table_single_tray_training.py' in children[1][0][1]
    assert '--execute' in children[2][0] and 'collect_three_table_campaign.py' in children[2][0][1]
    state=json.loads((root/'workflow_status.json').read_text())
    assert state['phase']=='source_and_training_pipeline' and not state['training_started']
    assert all(kw['start_new_session'] for _,kw in children)
    assert children[0][1]['env']['MUJOCO_GL']=='egl' and children[0][1]['env']['MUJOCO_EGL_DEVICE_ID']=='1'
    assert children[0][1]['env']['CUDA_VISIBLE_DEVICES'].startswith('GPU-')
    assert all(kw['env']['CUDA_VISIBLE_DEVICES']=='' for _,kw in children[1:])
    identities={j['pid']:dict(j,start_ticks='test') for j in state['children'].values()}
    monkeypatch.setattr(w,'checked_process',lambda job,*args:identities.get(job.get('pid')))
    monkeypatch.setattr(w.subprocess,'Popen',lambda *a,**kw:pytest.fail('must reattach, not duplicate'))
    with pytest.raises(RuntimeError,match='stop_test_loop'):w.supervise(path,recover=True)


def test_failed_demo_remains_alive_blocked_without_automatic_recipe_change(tmp_path,monkeypatch):
    _,path,_,_,root=fixture(tmp_path,complete=False)
    monkeypatch.setitem(sys.modules,'fcntl',SimpleNamespace(LOCK_EX=1,LOCK_NB=2,flock=lambda *a:None))
    monkeypatch.setattr(w.os,'getsid',lambda pid:777,raising=False)
    monkeypatch.setattr(w.time,'sleep',stop)
    monkeypatch.setattr(w.subprocess,'Popen',lambda *a,**kw:pytest.fail('failed demo may not auto-launch'))
    with pytest.raises(RuntimeError,match='stop_test_loop'):w.supervise(path)
    s=json.loads((root/'workflow_status.json').read_text())
    assert s['phase']=='blocked_demo_requires_reviewed_recipe' and s['training_status']=='waiting_for_data'
    assert s['children']=={} and not s['training_started']

def test_prior_closed_campaign_requires_real_exit_and_unchanged_sources(tmp_path):
    o,_,_,_,root=fixture(tmp_path)
    campaign=tmp_path/'old_campaign';campaign.mkdir()
    status=campaign/'status.json';status.write_text(json.dumps(dict(selected=3,completed=3,results=[dict(returncode=0)]*3)))
    prior=tmp_path/'prior_options.json';prior.write_text(json.dumps(dict(campaign_dir=str(campaign))))
    exitfile=tmp_path/'prior_exit.json';exitfile.write_text(json.dumps(dict(returncode=0,exited=True)))
    o['campaign_dir']=str(campaign)
    o['reusable_campaign']=dict(campaign_dir=str(campaign),status_sha256=w.digest(status),prior_workflow_options=str(prior),prior_workflow_options_sha256=w.digest(prior),process_exit_receipt=str(exitfile),process_exit_receipt_sha256=w.digest(exitfile))
    train=Path(o['training_options']);t=json.loads(train.read_text());t.update(campaign=str(campaign),certified_source_catalog=str(root/'fresh_certified_catalog.json'));train.write_text(json.dumps(t))
    w.validate_options(o)
    status.write_text(json.dumps(dict(selected=3,completed=2)))
    with pytest.raises(ValueError,match='evidence_changed'):w.validate_options(o)


def test_prior_native_reuse_hash_checks_actual_four_videos(tmp_path):
    o,_,_,result,root=fixture(tmp_path);native=tmp_path/'oldnative';native.mkdir()
    manifest=native/'manifest.json';manifest.write_text('{}')
    videos=[]
    for i in range(4):
        p=native/(str(i)+'.mp4');p.write_bytes(bytes([i]));videos.append(dict(path=str(p),sha256=w.digest(p)))
    closure=native/'video_closure.json';closure.write_text(json.dumps(dict(verified=True,demo_result_sha256=w.digest(result),source_manifest_sha256=w.digest(manifest),videos=videos)))
    o['reusable_demo_native']=dict(output=str(native),closure_sha256=w.digest(closure))
    assert w.reusable_native_proof(o,dict(result_sha256=w.digest(result)))['verified']
    Path(videos[-1]['path']).write_bytes(b'mutated')
    with pytest.raises(ValueError,match='video_changed'):w.reusable_native_proof(o,dict(result_sha256=w.digest(result)))

def test_migration_reuses_closed_sources_and_media_without_duplicate_launch(tmp_path,monkeypatch):
    o,path,_,result,root=fixture(tmp_path)
    campaign=tmp_path/'priorcampaign';campaign.mkdir()
    oldstatus=campaign/'status.json';oldstatus.write_text(json.dumps(dict(selected=3,completed=3,results=[dict(returncode=0)]*3)))
    prior=tmp_path/'prioropts.json';prior.write_text(json.dumps(dict(campaign_dir=str(campaign))))
    exitfile=tmp_path/'prior_exit.json';exitfile.write_text(json.dumps(dict(returncode=0,exited=True)))
    o.update(campaign_dir=str(campaign),reusable_campaign=dict(campaign_dir=str(campaign),status_sha256=w.digest(oldstatus),prior_workflow_options=str(prior),prior_workflow_options_sha256=w.digest(prior),process_exit_receipt=str(exitfile),process_exit_receipt_sha256=w.digest(exitfile)))
    training=Path(o['training_options']);t=json.loads(training.read_text());t.update(campaign=str(campaign),certified_source_catalog=str(root/'not_yet_ready_catalog.json'));training.write_text(json.dumps(t))
    path.write_text(json.dumps(o))
    monkeypatch.setitem(sys.modules,'fcntl',SimpleNamespace(LOCK_EX=1,LOCK_NB=2,flock=lambda *a:None))
    monkeypatch.setattr(w.os,'getsid',lambda pid:777,raising=False)
    monkeypatch.setattr(w,'reusable_native_proof',lambda *a:dict(verified=True,diagnostic_media_only=True))
    monkeypatch.setattr(w,'process_identity',lambda pid:None)
    monkeypatch.setattr(w.time,'sleep',stop)
    launched=[]
    def popen(argv,**kwargs):
        launched.append(argv);return SimpleNamespace(pid=123,poll=lambda:None)
    monkeypatch.setattr(w.subprocess,'Popen',popen)
    with pytest.raises(RuntimeError,match='stop_test_loop'):w.supervise(path)
    assert len(launched)==1 and 'supervise_three_table_single_tray_training.py' in launched[0][1]
    state=json.loads((root/'workflow_status.json').read_text())
    assert state['reusable_campaign_proof']['status_sha256']==w.digest(oldstatus)
    assert state['demo_native_proof']['diagnostic_media_only'] and not state['training_started']

def test_native_faults_retry_only_three_new_outputs_and_preserve_healthy_children(tmp_path,monkeypatch):
    o,path,_,_,root=fixture(tmp_path)
    monkeypatch.setitem(sys.modules,'fcntl',SimpleNamespace(LOCK_EX=1,LOCK_NB=2,flock=lambda *a:None))
    monkeypatch.setattr(w.os,'getsid',lambda pid:777,raising=False)
    clock=[0];loops=[0];identities={};launches=[]
    def now():clock[0]+=100;return clock[0]
    monkeypatch.setattr(w.time,'time',now)
    monkeypatch.setattr(w,'process_identity',lambda pid:identities.get(pid))
    def popen(argv,**kw):
        pid=100+len(launches);launches.append(argv)
        identities[pid]=dict(pid=pid,argv=argv,cwd=str(Path(kw['cwd']).resolve()),start_ticks=str(pid))
        native='render_three_table_original_trace.py' in argv[1]
        return SimpleNamespace(pid=pid,poll=lambda:2 if native else None)
    monkeypatch.setattr(w.subprocess,'Popen',popen)
    monkeypatch.setattr(w,'publish_demo_native',lambda *a:(_ for _ in ()).throw(ValueError('actual_encoder_process_failed')))
    def sleep(_):
        loops[0]+=1
        if loops[0]>=9:raise RuntimeError('stop_test_loop')
    monkeypatch.setattr(w.time,'sleep',sleep)
    with pytest.raises(RuntimeError,match='stop_test_loop'):w.supervise(path)
    natives=[a for a in launches if 'render_three_table_original_trace.py' in a[1]]
    assert len(natives)==4
    assert len({a[a.index('--output')+1] for a in natives})==4
    assert len(launches)==6  # Original waiter and source are not repeated.
    state=json.loads((root/'workflow_status.json').read_text())
    assert len(state['process_faults']['demo_native'])==3
    assert state['blocked_process_faults']['demo_native']=='three_process_attempts_exhausted'
    assert not state['training_started']

def test_adopt_external_healthy_continuation_binds_old_options_plan_and_argv(tmp_path,monkeypatch):
    from test_three_table_campaign import inputs
    o,_,_,_,root=fixture(tmp_path)
    selected,inventory,manifest,registry=inputs(tmp_path)
    selection=tmp_path/'selected.json';selection.write_text(json.dumps(selected))
    external=tmp_path/'prior_continuation';external.mkdir();planfile=external/'plan.json';planfile.write_text('{}')
    continuation=dict(selection=str(selection),selection_sha256=w.digest(selection),campaign_dir=str(external),source_workers=3)
    prior=dict(o,continuation=continuation)
    priorpath=tmp_path/'prior_workflow.json';priorpath.write_text(json.dumps(prior))
    o.update(inventory=str(inventory),parent_manifest=str(manifest),split_registry=str(registry),continuation=continuation)
    adoption=dict(pid=123,start_ticks='42',argv=w.campaign_argv(dict(prior,**continuation)),cwd=o['release'],log='retained.log',prior_workflow_options=str(priorpath),prior_workflow_options_sha256=w.digest(priorpath),source_plan=str(planfile),source_plan_sha256=w.digest(planfile),selection_sha256=w.digest(selection))
    o['adopt_children']=dict(source_campaign_v2=adoption)
    calls=[]
    monkeypatch.setattr(w,'checked_process',lambda job,*a:calls.append(job) or job)
    w.validate_options(o)
    assert calls[-1]['pid']==123
    adoption['argv']=['unrelated']
    with pytest.raises(ValueError,match='command_changed'):w.validate_options(o)
    adoption['argv']=w.campaign_argv(dict(prior,**continuation))
    planfile.write_text('{"mutated":true}')
    with pytest.raises(ValueError,match='prior_identity_changed'):w.validate_options(o)

def test_unique_dataset_watcher_is_supervised_after_main_terminal_failure(tmp_path,monkeypatch):
    o,path,_,_,root=fixture(tmp_path)
    training=json.loads(Path(o['training_options']).read_text())
    main=Path(training['run_dir']);main.mkdir()
    (main/'pipeline_status.json').write_text(json.dumps(dict(stage='failed_preserving_sources_and_checkpoints',error='known_contract_failure')))
    data=tmp_path/'data2_options.json';data.write_text(json.dumps(dict(data_only=True,data_version='v2')))
    o['data_version2_watcher']=dict(options=str(data),options_sha256=w.digest(data),training_run=str(main),watch_dir=str(root/'data2_watch'))
    path.write_text(json.dumps(o));w.validate_options(o)
    monkeypatch.setitem(sys.modules,'fcntl',SimpleNamespace(LOCK_EX=1,LOCK_NB=2,flock=lambda *a:None))
    monkeypatch.setattr(w.os,'getsid',lambda pid:777,raising=False)
    monkeypatch.setattr(w.time,'sleep',stop)
    launches=[];identities={}
    monkeypatch.setattr(w,'process_identity',lambda pid:identities.get(pid))
    def popen(argv,**kw):
        pid=100+len(launches);launches.append(argv)
        identities[pid]=dict(pid=pid,argv=argv,cwd=str(Path(kw['cwd']).resolve()),start_ticks=str(pid))
        return SimpleNamespace(pid=pid,poll=lambda:1 if 'supervise_three_table_single_tray_training.py' in argv[1] else None)
    monkeypatch.setattr(w.subprocess,'Popen',popen)
    with pytest.raises(RuntimeError,match='stop_test_loop'):w.supervise(path)
    watchers=[a for a in launches if 'watch_three_table_data_version2.py' in a[1]]
    assert len(watchers)==1 and '--watch-dir' in watchers[0]
    assert len(launches)==4
    state=json.loads((root/'workflow_status.json').read_text())
    assert state['phase']=='main_pipeline_exited_supervising_data_version2_watcher'
    assert state.get('process_faults',{}).get('training_waiter',[])==[]
    data.write_text('{"changed":true}')
    with pytest.raises(ValueError,match='watcher_options_changed'):w.dataset_watcher_argv(o)


def test_direct_data_waiter_and_watcher_cannot_both_be_enabled(tmp_path):
    o,_,_,_,root=fixture(tmp_path)
    data=tmp_path/'data2_options.json';data.write_text(json.dumps(dict(data_only=True,data_version='v2')))
    o['data_version2_watcher']=dict(options=str(data),options_sha256=w.digest(data),training_run=str(root/'training'),watch_dir=str(root/'watch'))
    # Check the mutual-exclusion guard directly through a valid continuation.
    from test_three_table_campaign import inputs
    selected,inventory,manifest,registry=inputs(tmp_path)
    selection=tmp_path/'selected.json';selection.write_text(json.dumps(selected))
    campaign=root/'campaign_v2'
    data.write_text(json.dumps(dict(data_only=True,data_version='v2',campaign=str(campaign))))
    o.update(inventory=str(inventory),parent_manifest=str(manifest),split_registry=str(registry))
    o['data_version2_watcher']['options_sha256']=w.digest(data)
    o['continuation']=dict(selection=str(selection),selection_sha256=w.digest(selection),campaign_dir=str(campaign),dataset_only_options=str(data),dataset_only_options_sha256=w.digest(data))
    with pytest.raises(ValueError,match='only_one_version2'):w.validate_options(o)

def test_adopt_healthy_data_watcher_keeps_immutable_old_gate_and_command(tmp_path,monkeypatch):
    o,_,_,_,root=fixture(tmp_path)
    oldroot=tmp_path/'prior_workflow';oldroot.mkdir()
    data=oldroot/'data2.json';data.write_text(json.dumps(dict(data_only=True,data_version='v2',run_dir=str(oldroot/'data_run'))))
    oldwatch=dict(options=str(data),options_sha256=w.digest(data),training_run=str(oldroot/'training'),watch_dir=str(oldroot/'watch'))
    old=dict(o,workflow_dir=str(oldroot),data_version2_watcher=oldwatch)
    priorpath=oldroot/'workflow_options.json';priorpath.write_text(json.dumps(old))
    command=oldroot/'watcher_options.json';output=oldroot/'watcher_owned'
    actual=w.dataset_watcher_argv(old)
    command.write_text(json.dumps(dict(schema='airport_three_table_owned_command/1',argv=actual,cwd=old['release'],output=str(output))))
    wrapper=[old['vla_python'],str(Path(old['release'])/'scripts/run_three_table_owned_command.py'),'--options',str(command)]
    adopted=dict(pid=123,start_ticks='42',argv=wrapper,cwd=old['release'],log=str(oldroot/'watcher.log'),actual_command_argv=actual,command_options=str(command),command_options_sha256=w.digest(command),command_output=str(output),prior_workflow_options=str(priorpath),prior_workflow_options_sha256=w.digest(priorpath))
    o.update(data_version2_watcher=oldwatch,adopt_children=dict(source_v2_dataset_watcher=adopted))
    monkeypatch.setattr(w,'checked_process',lambda job,*a:job)
    w.validate_options(o)
    assert Path(o['data_version2_watcher']['training_run'])!=Path(json.loads(Path(o['training_options']).read_text())['run_dir'])
    adopted['actual_command_argv']=['different-worker']
    with pytest.raises(ValueError,match='prior_data_watcher_command'):w.validate_options(o)
    adopted['actual_command_argv']=actual
    command.write_text('{"mutated":true}')
    with pytest.raises(ValueError,match='watcher_binding_changed'):w.validate_options(o)
    command.write_text(json.dumps(dict(schema='airport_three_table_owned_command/1',argv=actual,cwd=old['release'],output=str(output))))
    output.mkdir();watch=Path(oldwatch['watch_dir']);watch.mkdir();run=oldroot/'data_run';run.mkdir()
    exitfile=output/'exit.json'
    exitfile.write_text(json.dumps(dict(actual_exit_observed=True,returncode=1,options_sha256=w.digest(command),wrapper_identity={k:adopted[k] for k in ('pid','start_ticks','argv','cwd')})))
    watchfile=watch/'status.json';watchfile.write_text(json.dumps(dict(stage='data_only_watch_contract_or_fault_budget_blocked')))
    pipeline=run/'pipeline_status.json';pipeline.write_text(json.dumps(dict(stage='data_only_exports_verified_no_training',dataset_ready=True,training_started=False,verified_splits=['train','val','test'],actual_sources=5)))
    evidence=dict(actual_returncode=1)
    for key,path in [('exit',exitfile),('watcher_status',watchfile),('pipeline_status',pipeline)]:evidence[key]=str(path);evidence[key+'_sha256']=w.digest(path)
    adopted['closed_data2_evidence']=evidence
    monkeypatch.setattr(w,'checked_process',lambda *a:None)
    w.validate_options(o)
    assert json.loads(exitfile.read_text())['returncode']==1
    assert json.loads(pipeline.read_text())['actual_sources']==5
    evidence['actual_returncode']=0
    with pytest.raises(ValueError,match='actual_exit_identity'):w.validate_options(o)
    evidence['actual_returncode']=1;pipeline.write_text('{"mutated":true}')
    with pytest.raises(ValueError,match='artifact_binding'):w.validate_options(o)
