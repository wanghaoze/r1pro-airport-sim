import pytest
from r1pro_teleop.vla.rollout import run_rollouts


@pytest.mark.parametrize('kwargs',[
    {},dict(collect_dagger=True),dict(private_oracle_contact_escape=True),
    dict(collect_dagger='true',private_oracle_contact_escape=True)])
def test_direct_tracking_requires_real_collection_and_escape_before_model_source_or_factory(tmp_path,kwargs):
    def banned(*a,**kw):pytest.fail('Invalid private candidate reached factory')
    with pytest.raises(ValueError,match='requires DAgger'):
        run_rollouts('missing',tmp_path/'unused',{},private_oracle_measured_tracking=True,expert_factory=banned,**kwargs)
    assert not (tmp_path/'unused').exists()


@pytest.mark.parametrize('bad',[1,'true',None])
def test_tracking_requires_bool_before_external_io(tmp_path,bad):
    with pytest.raises(ValueError,match='must be boolean'):
        run_rollouts('missing',tmp_path/'unused',{},private_oracle_measured_tracking=bad)
    from scripts.diagnose_pi05_skills import diagnose_one
    with pytest.raises(ValueError,match='must be boolean'):
        diagnose_one({},tmp_path/'unused',{},host='unused',port=8765,max_steps=20,private_oracle_measured_tracking=bad)


@pytest.mark.parametrize('escape,collect',[(False,False),(True,False),(False,True)])
def test_isolated_direct_tracking_requires_curriculum_and_escape_before_runtime(escape,collect,tmp_path):
    from scripts.diagnose_pi05_skills import diagnose_one
    with pytest.raises(ValueError,match='requires isolated curriculum'):
        diagnose_one({},tmp_path/'unused',{},host='unused',port=8765,max_steps=20,
            round_data=object() if collect else None,private_oracle_contact_escape=escape,private_oracle_measured_tracking=True)
    assert not (tmp_path/'unused').exists()


@pytest.mark.parametrize('module_name,base,collection_flag',[
    ('evaluate_pi05_airport',['--collection','missing','--output','unused','--indices','4'],'--collect-dagger'),
    ('diagnose_pi05_skills',['--dataset-manifest','missing','--output','unused','--episode-indices','2','--checkpoint-id','x'],'--collect-curriculum-dagger')])
@pytest.mark.parametrize('other',[[],['--private-oracle-contact-escape']])
def test_pure_cli_pre_rejects_before_model_connection(module_name,base,collection_flag,other,monkeypatch):
    import importlib
    cli=importlib.import_module('scripts.'+module_name)
    from r1pro_teleop.vla import rollout
    monkeypatch.setattr(rollout,'verified_server_metadata',lambda *a,**kw:pytest.fail('Invalid pure private candidate reached model'))
    if hasattr(cli,'verified_server_metadata'):monkeypatch.setattr(cli,'verified_server_metadata',rollout.verified_server_metadata)
    with pytest.raises(SystemExit) as exc:cli.main(base+other+['--private-oracle-measured-tracking'])
    assert exc.value.code==2


@pytest.mark.parametrize('escape,tracking',[(False,False),(True,False),(True,True)])
def test_isolated_factory_default_compatibility_and_explicit_tracking_metadata(tmp_path,monkeypatch,escape,tracking):
    from types import SimpleNamespace
    from r1pro_teleop.airport_fsm.contracts import Config
    from r1pro_teleop.airport_fsm.geometry import Operation
    import numpy as np,json
    from scripts import diagnose_pi05_skills as cli
    from r1pro_teleop.airport_fsm import runtime,registry
    from r1pro_teleop.vla import machine
    source=tmp_path/'teacher.h5';source.write_bytes(b'teacher source')
    scene=dict(scene_id='s',split='train',seed=1);episode=dict(skill='grasp_lift_tray',language_prompt='same prompt')
    monkeypatch.setattr(cli,'source_identity',lambda e:(source,tmp_path,scene,None))
    monkeypatch.setattr(cli,'verified_curriculum_fixture',lambda e:None)
    monkeypatch.setattr(registry,'config_for',lambda _:Config())
    r=SimpleNamespace(steps=0,id_calls=0,d=SimpleNamespace(qpos=np.zeros(1),qvel=np.zeros(1),time=0.),
        g=SimpleNamespace(ids=['tray0'],spec={'slots':[{'slot_id':'slot0'}]}),close=lambda:None)
    monkeypatch.setattr(runtime,'Runtime',lambda *a,**kw:r)
    monkeypatch.setattr(cli,'expert_snapshot',lambda *a:({'initial_restore_count':1},None))
    monkeypatch.setattr(cli,'operation_for',lambda *a:Operation(0,0,np.zeros(3),0.))
    monkeypatch.setattr(cli,'restore_contact_bookkeeping',lambda *a:None)
    monkeypatch.setattr(cli,'restore_scheduler_context',lambda *a:{})
    monkeypatch.setattr(cli,'skill_predicate',lambda *a:(lambda *a:False,2))
    from r1pro_teleop.vla import data
    monkeypatch.setattr(data,'language_prompt',lambda *a:'same prompt')
    def execute(*a,**kw):r.steps+=1;return False
    executor=SimpleNamespace(execute_operation=execute,projection_stats={},rate_limit_stats={},reference_constraint_stats=[])
    m=SimpleNamespace(executor=executor,log=SimpleNamespace(file=SimpleNamespace(attrs={'metadata_json':json.dumps({})}),
        event=lambda *a,**kw:None,close=lambda *a:None),transition=lambda *a,**kw:None)
    def constructor(r,directory,**kw):directory.mkdir();return m
    monkeypatch.setattr(machine,'VLAMachine',constructor)
    observer=SimpleNamespace(queries=0,accepted=0,rejected=0)
    monkeypatch.setattr(cli,'curriculum_observer',lambda *a,**kw:observer)
    calls=[]
    result=cli.diagnose_one(episode,tmp_path/'new',{'checkpoint_id':'model','action_horizon':20},host='unused',port=8765,max_steps=20,
        round_data=object(),expert_factory=lambda *a,**kw:calls.append(kw),
        private_oracle_contact_escape=escape,private_oracle_measured_tracking=tracking)
    assert calls==[{'machine':m,**({'private_contact_escape':True} if escape else {}),
        **({'private_escape_measured_tracking':True} if tracking else {})}]
    assert result['private_oracle_measured_tracking']==tracking and result['task_completed'] is False
