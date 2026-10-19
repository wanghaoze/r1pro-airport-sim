from pathlib import Path
from types import SimpleNamespace
import pytest
from r1pro_teleop.vla import rollout


def test_pure_escape_gate_rejects_before_any_source_or_server_io(tmp_path):
    with pytest.raises(ValueError,match='requires DAgger'):
        rollout.run_rollouts('absent',tmp_path/'out',{},private_oracle_contact_escape=True)
    assert not (tmp_path/'out').exists()


def test_pure_cli_escape_gate_rejects_before_metadata_probe(monkeypatch):
    from scripts import evaluate_pi05_airport as cli
    monkeypatch.setattr(cli,'verified_server_metadata',lambda *a,**kw:pytest.fail('Must reject before server probe'))
    with pytest.raises(SystemExit) as e:
        cli.main(['--collection','absent','--output','unused','--indices','4','--private-oracle-contact-escape'])
    assert e.value.code==2


def test_isolated_pure_cli_and_function_reject_escape(monkeypatch):
    from scripts import diagnose_pi05_skills as cli
    with pytest.raises(SystemExit) as e:
        cli.main(['--dataset-manifest','absent','--episode-indices','2','--output','unused','--checkpoint-id','x','--private-oracle-contact-escape'])
    assert e.value.code==2
    with pytest.raises(ValueError,match='isolated curriculum'):
        cli.diagnose_one({},'unused',{},host='localhost',port=8765,max_steps=20,private_oracle_contact_escape=True)


@pytest.mark.parametrize('enabled,tracking',[(False,False),(True,False),(True,True)])
def test_collect_explicit_factory_receives_only_requested_optin(tmp_path,monkeypatch,enabled,tracking):
    root=tmp_path/'source';root.mkdir();xml=root/'mobile.xml';xml.write_text('<mujoco/>')
    spec=dict(scene_id='s',split='train',seed=1)
    monkeypatch.setattr(rollout,'selected_sources',lambda *a,**kw:(root,[(spec,xml)]))
    from r1pro_teleop.airport_fsm.contracts import Config
    monkeypatch.setattr(rollout,'config_for',lambda p:Config())
    from r1pro_teleop.vla import dagger
    class Round:
        def __init__(self,path,*a,**kw):
            self.directory=Path(path);self.directory.mkdir();self.rows=[];self.metadata={}
    monkeypatch.setattr(dagger,'DaggerRound',Round)
    calls=[]
    def factory(runtime,directory,**kwargs):calls.append(kwargs);return SimpleNamespace()
    def runner(s,xml,cfg,directory,**kwargs):
        machine=SimpleNamespace(r=SimpleNamespace(spec=s),executor=SimpleNamespace())
        kwargs['machine_observer'](machine)
        return dict(scene_id='s',split='train',task_completed=False,inverse_dynamics_calls=0,motion_backend='pi05')
    metadata=dict(checkpoint_id='sha256:'+'a'*64,action_width=19,action_horizon=20,
        action_space='mobile19_absolute_v1',control_hz=20,model='pi05',fine_tuned=True,training_steps=10)
    report=rollout.run_rollouts(root,tmp_path/'out',metadata,collect_dagger=True,learner_checkpoint='actual',
        expert_factory=factory,attempt_runner=runner,private_oracle_contact_escape=enabled,private_oracle_measured_tracking=tracking)
    assert len(calls)==1
    assert calls[0].get('private_contact_escape',False)==enabled
    assert ('private_contact_escape' in calls[0])==enabled
    assert report['private_oracle_contact_escape']==enabled
    assert calls[0].get('private_escape_measured_tracking',False)==tracking
    assert ('private_escape_measured_tracking' in calls[0])==tracking
    assert report['private_oracle_measured_tracking']==tracking
    assert report['private_escape_qualification_mode']==('bounded_measured_tracking_after_clearance' if tracking else 'exact_yaw_global_monotonic')
