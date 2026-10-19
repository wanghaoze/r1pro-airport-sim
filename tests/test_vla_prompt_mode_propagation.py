from pathlib import Path
import pytest
from r1pro_teleop.vla import rollout
from r1pro_teleop.airport_fsm.contracts import Config
from test_vla_rollout import source, metadata
from scripts import diagnose_pi05_skills as diagnostic


@pytest.mark.parametrize('mode',[None,'legacy','skill_only_v1','task_complete_action8_v1'])
def test_rollout_uses_verified_loaded_mode_in_actual_attempt_config(tmp_path,mode):
    root,_=source(tmp_path);data=metadata()
    if mode is not None:data['prompt_mode']=mode
    seen=[]
    def attempt(scene,xml,cfg,directory,**kwargs):
        seen.append(cfg.vla_prompt_mode)
        return dict(scene_id=scene['scene_id'],split=scene['split'],task_completed=False,
                    inverse_dynamics_calls=0,motion_backend='pi05')
    report=rollout.run_rollouts(root,tmp_path/'new',data,indices=[4],attempt_runner=attempt)
    assert seen==[mode or 'legacy']
    assert report['config']['vla_prompt_mode']==(mode or 'legacy')


@pytest.mark.parametrize('mode',[None,'legacy','skill_only_v1','task_complete_action8_v1'])
def test_diagnostic_propagates_mode_before_runtime_construction(tmp_path,monkeypatch,mode):
    from r1pro_teleop.airport_fsm import registry,runtime
    data=metadata()
    if mode is not None:data['prompt_mode']=mode
    monkeypatch.setattr(diagnostic,'source_identity',lambda _: (tmp_path/'trace',tmp_path,
        {'scene_id':'scene'},None))
    monkeypatch.setattr(registry,'config_for',lambda _:Config())
    seen=[]
    class Stop(RuntimeError):pass
    def construct(scene,xml,cfg,**kwargs):
        seen.append(cfg.vla_prompt_mode);raise Stop()
    monkeypatch.setattr(runtime,'Runtime',construct)
    with pytest.raises(Stop):diagnostic.diagnose_one({},tmp_path/'out',data,
        host='localhost',port=8765,max_steps=20)
    assert seen==[mode or 'legacy']


@pytest.mark.parametrize('mode',['wrong',None,True,[]])
def test_unknown_server_mode_rejected(mode):
    data=metadata();data['prompt_mode']=mode
    with pytest.raises(ValueError):rollout.validate_server_metadata(data)


@pytest.mark.parametrize('local,server,allowed',[(None,None,True),
    ('skill_only_v1','skill_only_v1',True),('legacy','skill_only_v1',False),
    ('skill_only_v1',None,False)])
def test_curriculum_local_verified_checkpoint_mode_matches_live(local,server,allowed):
    data=metadata();identity={key:data.get(key) for key in
        ('checkpoint_id','training_steps','checkpoint_step')}
    if local is not None:identity['prompt_mode']=local
    if server is not None:data['prompt_mode']=server
    verifier=lambda _: (None,Path('actual_checkpoint'),identity)
    if allowed:assert diagnostic.verify_curriculum_checkpoint('status',data,verifier)[1]==identity
    else:
        with pytest.raises(ValueError,match='prompt mode'):diagnostic.verify_curriculum_checkpoint('status',data,verifier)
