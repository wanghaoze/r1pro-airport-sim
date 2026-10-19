import json,sys
from pathlib import Path
from types import SimpleNamespace
import pytest
from r1pro_teleop.single_tray_3table import campaign_recovery as c
from r1pro_teleop.single_tray_3table.campaign import atomic_json,digest,build_plan,case_commands
from test_three_table_campaign import inputs


def config(tmp_path):
    cfg=tmp_path/'cfg.json';cfg.write_text('{}');ref=tmp_path/'ref.json';ref.write_text('{}');return cfg,ref


def test_recover_closed_real_failure_never_reruns_or_upgrades_it(tmp_path,monkeypatch):
    monkeypatch.setitem(sys.modules,'fcntl',SimpleNamespace(LOCK_EX=1,LOCK_NB=2,flock=lambda *a:None))
    plan=build_plan(*inputs(tmp_path));out=tmp_path/'campaign';out.mkdir();cfg,ref=config(tmp_path)
    atomic_json(out/'plan.json',plan)
    rows=[]
    for i,v in enumerate(plan['variants']):
        result=out/f'result{i}.json';result.write_text(json.dumps(dict(task_completed=False)))
        rows.append(dict(index=i,result=str(result),result_sha256=digest(result),task_completed=False,returncode=1))
    bindings=dict(release=str(tmp_path.resolve()),sim_python=sys.executable,config=str(cfg),config_sha256=digest(cfg),reference=str(ref),reference_sha256=digest(ref))
    atomic_json(out/'status.json',dict(execution_bindings=bindings,source_plan_sha256=digest(out/'plan.json'),results=rows))
    monkeypatch.setattr(c.subprocess,'Popen',lambda *a,**kw:pytest.fail('closed physical failure must not rerun'))
    status=c.execute_recoverable(plan,out,release=tmp_path,sim_python=sys.executable,config=cfg,reference=ref,recover=True)
    assert status['completed']==3 and status['successful']==0
    cfg.write_text('{"changed":true}')
    with pytest.raises(ValueError,match='bindings_changed'):c.execute_recoverable(plan,out,release=tmp_path,sim_python=sys.executable,config=cfg,reference=ref,recover=True)


def test_coordinator_adopts_existing_command_receipts_no_duplicate_then_keeps_failed_result(tmp_path,monkeypatch):
    monkeypatch.setitem(sys.modules,'fcntl',SimpleNamespace(LOCK_EX=1,LOCK_NB=2,flock=lambda *a:None))
    plan=build_plan(*inputs(tmp_path));plan['variants']=plan['variants'][:1];plan['selected']=1
    out=tmp_path/'campaign';out.mkdir();cfg,ref=config(tmp_path)
    # Recover between coordinator launch and merged status publication.
    atomic_json(out/'plan.json',plan)
    bindings=dict(release=str(tmp_path.resolve()),sim_python=sys.executable,config=str(cfg),config_sha256=digest(cfg),reference=str(ref),reference_sha256=digest(ref))
    atomic_json(out/'status.json',dict(execution_bindings=bindings,source_plan_sha256=digest(out/'plan.json'),results=[]))
    attempt=out/'case_0000/attempt_00';attempt.mkdir(parents=True)
    generate,collect=case_commands(plan,plan['variants'][0],attempt,tmp_path,sys.executable,cfg,ref)
    for stage,argv in [('generate',generate),('collect',collect)]:
        atomic_json(attempt/(stage+'_options.json'),dict(schema='airport_three_table_owned_command/1',argv=argv,cwd=str(tmp_path.resolve()),output=str(attempt/(stage+'_owned'))))
        atomic_json(attempt/(stage+'_wrapper.json'),dict(pid=123,argv=['owned'],cwd=str(tmp_path),start_ticks='42'))
    result=attempt/'observed_source/result.json';result.parent.mkdir();result.write_text(json.dumps(dict(task_completed=False,physics_success=False,training_eligible=False)))
    calls=[]
    def command(*args,**kw):
        calls.append(args);return dict(stage='closed',returncode=0)
    monkeypatch.setattr(c,'command_state',command)
    monkeypatch.setattr(c.subprocess,'Popen',lambda *a,**kw:pytest.fail('healthy/closed owned command must not duplicate'))
    status=c.execute_recoverable(plan,out,release=tmp_path,sim_python=sys.executable,config=cfg,reference=ref,recover=True,poll_seconds=.01)
    assert status['completed']==1 and status['successful']==0 and len(calls)==4
    assert not (out/'case_0000/attempt_01').exists()
