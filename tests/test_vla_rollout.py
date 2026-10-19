import dataclasses
import json
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import pytest
from r1pro_teleop.vla import rollout
from r1pro_teleop.vla.dagger import ExpertLabel,state_digest
from r1pro_teleop.airport_fsm.contracts import Config,sha256_file
from r1pro_teleop.vla.executor import VLAOperationExecutor,ActionBounds
from r1pro_teleop.vla.policy import Pi05Policy,PolicyContract,PolicyError


def metadata():
    return dict(checkpoint_id='sha256:'+'a'*64,action_width=19,action_horizon=20,
                action_space='mobile19_absolute_v1',control_hz=20,model='pi05',
                fine_tuned=True,training_steps=10)


def save(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value),encoding='utf-8')


def source(tmp_path,split='test'):
    root=tmp_path/'source'
    directory=root/'scenes/airport_0004_123'
    spec=dict(scene_id='airport_0004_123',split=split,seed=123)
    save(directory/'scene.json',spec)
    (directory/'mobile.xml').write_text('<mujoco/>')
    save(directory/'preflight.json',dict(scene_id=spec['scene_id'],split=split,valid=True,
        scene_json_sha256=sha256_file(directory/'scene.json'),
        scene_xml_sha256=sha256_file(directory/'mobile.xml')))
    save(root/'collection.json',dict(schema='airport_fsm_collection/1',config=Config().dump()))
    save(root/'scenes/index.json',[dict(scene_id=spec['scene_id'],split=split)])
    return root,spec


def test_pure_eval_new_run_no_oracle_and_explicit_checkpoint_cfg(tmp_path):
    root,spec=source(tmp_path)
    before={str(p):p.read_bytes() for p in root.rglob('*') if p.is_file()}
    def oracle_forbidden(*a,**kw):raise AssertionError('pure evaluation must not construct oracle')
    def attempt(s,xml,cfg,directory,attempt=0,**kw):
        assert not kw and cfg.motion_backend=='pi05'
        assert directory.parent.is_dir() and not directory.exists()
        # Match Machine.__init__'s actual exclusive leaf allocation.
        directory.mkdir(parents=True,exist_ok=False)
        assert cfg.vla_checkpoint_id==metadata()['checkpoint_id']
        assert cfg.vla_action_horizon==20
        assert cfg.vla_servo_projection_enabled is False
        return dict(scene_id=s['scene_id'],split=s['split'],task_completed=False,
                    failure_code='camera_guard',inverse_dynamics_calls=0,motion_backend='pi05')
    report=rollout.run_rollouts(root,tmp_path/'new_eval',metadata(),indices=[4],
                               attempt_runner=attempt,expert_factory=oracle_forbidden)
    assert report['completed']==0 and report['attempted']==1
    assert report['pure_vla_no_inverse_dynamics_verified'] is True
    assert report['inverse_dynamics_calls']==0 and report['status']=='completed'
    assert before=={str(p):p.read_bytes() for p in root.rglob('*') if p.is_file()}
    with pytest.raises(FileExistsError):
        rollout.run_rollouts(root,tmp_path/'new_eval',metadata(),indices=[4],attempt_runner=attempt)


def test_eval_inverse_dynamics_violation_not_claimed_pure(tmp_path):
    root,spec=source(tmp_path)
    def attempt(*a,**kw):
        return dict(scene_id=spec['scene_id'],split='test',task_completed=True,
                    inverse_dynamics_calls=1,motion_backend='pi05')
    report=rollout.run_rollouts(root,tmp_path/'bad_eval',metadata(),indices=[4],attempt_runner=attempt)
    assert report['pure_vla_no_inverse_dynamics_verified'] is False
    assert report['status']=='controller_verification_failed'


def test_dagger_refuses_heldout_before_output_or_oracle_creation(tmp_path):
    root,_=source(tmp_path,split='val')
    with pytest.raises(ValueError,match='only prepared train'):
        rollout.run_rollouts(root,tmp_path/'bad_dagger',metadata(),indices=[4],collect_dagger=True)
    assert not (tmp_path/'bad_dagger').exists()


def test_changed_scene_and_output_inside_source_are_rejected(tmp_path):
    root,_=source(tmp_path)
    with pytest.raises(ValueError,match='modify the source'):
        rollout.run_rollouts(root,root/'bad_out',metadata(),indices=[4])
    (root/'scenes/airport_0004_123/mobile.xml').write_text('changed')
    with pytest.raises(ValueError,match='changed after preflight'):
        rollout.selected_sources(root,indices=[4])


@pytest.mark.parametrize('values',[{'fine_tuned':False},{'training_steps':0},
                                  {'action_width':32},{'checkpoint_id':'friendly-name'}])
def test_server_rejects_base_or_ambiguous_contract_and_closes_probe(values):
    closed=[];data=metadata();data.update(values)
    client=SimpleNamespace(get_server_metadata=lambda:data,_ws=SimpleNamespace(close=lambda:closed.append(True)))
    with pytest.raises(ValueError):
        rollout.verified_server_metadata('localhost',8000,client_factory=lambda **kw:client)
    assert closed==[True]


def observer_fixture(tmp_path,fail=False,mutate=False):
    state={'qpos':np.zeros(1),'qvel':np.zeros(1),'ctrl':np.zeros(1),'time':np.array(.5)}
    machine=SimpleNamespace(r=SimpleNamespace(spec={'scene_id':'scene','split':'train'}),
                            current_skill='push_adjust_tray',current_operation=object())
    expert=SimpleNamespace(capture=lambda:{k:v.copy() for k,v in state.items()})
    def label(op,skill,snapshot,horizon):
        assert op is machine.current_operation and skill=='push_adjust_tray'
        if mutate:state['qpos'][0]=1
        if fail:raise RuntimeError('new-state planning rejected')
        return ExpertLabel(state_digest(snapshot),np.zeros((horizon,19)),'fresh-oracle',
                           replanned_from_learner_state=True,planning_verified=True,teacher_artifact='private/trace.h5')
    expert.label=label;expert.verify_label=lambda *_:True
    collected=[]
    def collect(**kw):
        candidate=kw['expert_replan'](kw['simulator_state'],kw['observation'])
        assert candidate.start_state_sha256==state_digest(kw['simulator_state'])
        assert kw['verify_label'](kw['simulator_state'],candidate)
        collected.append(kw)
        return {'sample_dir':'private-label'}
    observer=rollout.DaggerObserver(machine,SimpleNamespace(collect_intervention=collect),expert,
                                   tmp_path/'events.jsonl',query_interval=1,max_queries=1)
    payload={'step':40,'state':np.zeros(19),'images':{'head_left':np.zeros((2,2,3),np.uint8),
             'left_wrist':np.zeros((2,2,3),np.uint8),'right_wrist':np.zeros((2,2,3),np.uint8)},
             'prompt':'Push tray.','actions':np.zeros((20,19))}
    return observer,payload,collected,state


def test_fixed_query_uses_fresh_state_after_first_chunk_and_budget_is_bounded(tmp_path):
    observer,payload,collected,state=observer_fixture(tmp_path)
    observer(payload);assert not collected
    state['qpos'][0]=.2;payload['step']=45
    observer(payload);observer(payload)
    assert observer.queries==1 and observer.accepted==1 and len(collected)==1
    assert collected[0]['simulator_state']['qpos'][0]==.2
    assert json.loads((tmp_path/'events.jsonl').read_text())['status']=='oracle_label_collected'


def test_rejected_oracle_records_no_fake_label_and_does_not_replace_actions(tmp_path):
    observer,payload,collected,state=observer_fixture(tmp_path,fail=True)
    original=payload['actions'].copy()
    observer(payload);observer(payload)
    assert observer.rejected==1 and observer.accepted==0 and not collected
    np.testing.assert_array_equal(payload['actions'],original)
    assert json.loads((tmp_path/'events.jsonl').read_text())['status']=='oracle_rejected'


def test_oracle_live_state_mutation_is_fatal_not_a_planning_rejection(tmp_path):
    observer,payload,collected,state=observer_fixture(tmp_path,mutate=True)
    observer(payload)
    with pytest.raises(RuntimeError,match='live learner'):
        observer(payload)


def test_executor_observer_cannot_mutate_live_actions_and_observes_before_tick():
    sim=SimpleNamespace(target=np.zeros(16),base_target=np.zeros(3),state=lambda:np.zeros(16),
                        base_joint_state=lambda:np.zeros(3),image=lambda _:np.zeros((2,2,3),np.uint8))
    runtime=SimpleNamespace(cfg=SimpleNamespace(fps=20),sim=sim,steps=0)
    def tick():runtime.steps+=1
    runtime.tick=tick
    policy=Pi05Policy(SimpleNamespace(infer=lambda obs:{'actions':np.zeros((2,19))}),
                       PolicyContract('test',action_horizon=2,action_width=19))
    observed=[]
    def on_decision(payload):
        assert runtime.steps==0
        observed.append(payload)
        payload['actions'][:]=.75
        payload['state'][:]=.75
    executor=VLAOperationExecutor(runtime,policy,ActionBounds(-np.ones(19),np.ones(19)),
                                   execute_steps=1,max_operation_steps=1,on_decision=on_decision)
    executor.execute_operation(SimpleNamespace(tray=0,slot=0),'Place.',lambda r,op:r.steps==1)
    assert len(observed)==1 and np.all(sim.target==0) and np.all(sim.base_target==0)


def test_dagger_mode_installs_observer_and_persists_real_round_even_when_learner_fails(tmp_path):
    root,spec=source(tmp_path,split='train')
    checkpoint=tmp_path/'trained/9';(checkpoint/'params').mkdir(parents=True)
    (checkpoint/'params/test_weights').write_bytes(b'unit-test learned checkpoint')
    snapshot={'qpos':np.zeros(1),'qvel':np.zeros(1),'ctrl':np.zeros(1),'time':np.array(.5)}
    class Expert:
        def __init__(self,runtime,directory,machine):
            self.directory=Path(directory)
        def capture(self):return {key:value.copy() for key,value in snapshot.items()}
        def label(self,operation,skill,state,horizon):
            return ExpertLabel(state_digest(state),np.zeros((horizon,19)),expert_id='mock-private-physical-oracle',
                replanned_from_learner_state=True,planning_verified=True,teacher_artifact=str(self.directory/'trace.h5'))
        def verify_label(self,state,label):return label.start_state_sha256==state_digest(state)
    def attempt(s,xml,cfg,directory,attempt,machine_observer):
        machine=SimpleNamespace(r=SimpleNamespace(spec=s),executor=SimpleNamespace(on_decision=None),
                                current_skill='push_adjust_tray',current_operation=object())
        machine_observer(machine)
        payload=dict(step=40,state=np.zeros(19),actions=np.zeros((20,19)),prompt='Push tray.',
                     images={name:np.zeros((2,2,3),np.uint8) for name in ('head_left','left_wrist','right_wrist')})
        machine.executor.on_decision(payload)
        snapshot['qpos'][0]=.2;payload['step']=45
        machine.executor.on_decision(payload)
        return dict(scene_id=s['scene_id'],split=s['split'],task_completed=False,
                    failure_code='guard',inverse_dynamics_calls=0,motion_backend='pi05')
    report=rollout.run_rollouts(root,tmp_path/'dagger',metadata(),indices=[4],collect_dagger=True,
        learner_checkpoint=checkpoint,query_interval=1,attempt_runner=attempt,expert_factory=Expert)
    assert report['oracle_labels']==1 and report['completed']==0
    assert report['dagger_round']['status']=='labels_collected_not_trained'
    artifact=tmp_path/'dagger/dagger_round/intervention_000000/label.npz'
    with np.load(artifact) as label:
        assert label['physics_qpos'][0]==.2
        assert label['state'].shape==(19,) and label['expert_actions'].shape==(20,19)


def test_projection_argument_is_explicit_in_frozen_rollout_config(tmp_path):
    root,spec=source(tmp_path)
    def attempt(s,xml,cfg,directory,attempt=0,**kw):
        assert cfg.vla_servo_projection_enabled is True
        return dict(scene_id=s['scene_id'],split=s['split'],task_completed=False,
                    inverse_dynamics_calls=0,motion_backend='pi05')
    report=rollout.run_rollouts(root,tmp_path/'projected_eval',metadata(),indices=[4],
                               servo_projection=True,attempt_runner=attempt)
    assert report['config']['vla_servo_projection_enabled'] is True


@pytest.mark.parametrize('flag',[False,True])
def test_cli_projection_flag_is_passed_explicitly(monkeypatch,tmp_path,flag):
    from scripts import evaluate_pi05_airport as cli
    captured=[]
    monkeypatch.setattr(cli,'verified_server_metadata',lambda *a,**kw:metadata())
    def run(*a,**kw):captured.append(kw);return {'status':'completed'}
    monkeypatch.setattr(cli,'run_rollouts',run)
    args=['--collection',str(tmp_path/'source'),'--output',str(tmp_path/'out'),'--indices','4']
    if flag:args.append('--servo-projection')
    assert cli.main(args)==0
    assert captured[0]['servo_projection'] is flag


def test_attempt_leaf_creation_belongs_to_machine_and_old_run_is_retained(tmp_path):
    root,spec=source(tmp_path)
    old=tmp_path/'old_failed_eval/attempts'/spec['scene_id']/'a000'
    old.mkdir(parents=True);evidence=old/'exception.txt';evidence.write_text('original initialization failure')
    def machine_constructor_runner(s,xml,cfg,directory,attempt=0,**kw):
        assert not directory.exists()
        directory.mkdir(parents=True,exist_ok=False)
        save(directory/'result.json',dict(scene_id=s['scene_id'],split=s['split'],task_completed=False,
            inverse_dynamics_calls=0,motion_backend='pi05',failure_code='guard'))
        return json.loads((directory/'result.json').read_text())
    result=rollout.run_rollouts(root,tmp_path/'new_eval_v2',metadata(),indices=[4],
                               attempt_runner=machine_constructor_runner)
    assert result['attempted']==1 and result['status']=='completed'
    assert evidence.read_text()=='original initialization failure'
    assert (tmp_path/'new_eval_v2/attempts'/spec['scene_id']/'a000/result.json').is_file()


def test_saturation_config_and_cli_explicitly_require_rate_limit(tmp_path,monkeypatch):
    root,spec=source(tmp_path)
    from scripts import evaluate_pi05_airport as cli
    with pytest.raises(ValueError,match='requires projection and reference rate'):
        rollout.run_rollouts(root,tmp_path/'bad',metadata(),indices=[4],actuator_saturation=True)
    def runner(s,xml,cfg,directory,**kw):
        assert cfg.vla_servo_projection_enabled and cfg.vla_reference_rate_limit_enabled
        assert cfg.vla_servo_projection_mode=='actuator_saturation'
        directory.mkdir(parents=True)
        return dict(scene_id=s['scene_id'],split=s['split'],task_completed=False,inverse_dynamics_calls=0)
    result=rollout.run_rollouts(root,tmp_path/'good',metadata(),indices=[4],actuator_saturation=True,
                               reference_rate_limit=True,attempt_runner=runner)
    assert result['config']['vla_servo_projection_mode']=='actuator_saturation'
    captured=[];monkeypatch.setattr(cli,'verified_server_metadata',lambda *a,**kw:metadata())
    monkeypatch.setattr(cli,'run_rollouts',lambda *a,**kw:captured.append(kw) or {'status':'completed'})
    args=['--collection',str(root),'--output',str(tmp_path/'cli'),'--indices','4','--actuator-saturation']
    with pytest.raises(SystemExit):cli.main(args)
    assert not captured
    assert cli.main(args+['--reference-rate-limit'])==0
    assert captured[0]['actuator_saturation'] is True and captured[0]['servo_projection'] is False
    with pytest.raises(SystemExit):cli.main(args+['--servo-projection','--reference-rate-limit'])


def test_cli_model_render_bound_is_explicit_and_native_by_default(monkeypatch,tmp_path):
    from scripts import evaluate_pi05_airport as cli
    captured=[]
    monkeypatch.setattr(cli,'verified_server_metadata',lambda *a,**kw:metadata())
    monkeypatch.setattr(cli,'run_rollouts',lambda *a,**kw:captured.append(kw) or {'status':'completed'})
    args=['--collection',str(tmp_path/'source'),'--output',str(tmp_path/'out'),'--indices','4']
    assert cli.main(args)==0
    assert captured[-1]['model_render_max_dim']==0
    assert cli.main(args+['--model-render-max-dim','320'])==0
    assert captured[-1]['model_render_max_dim']==320

def test_explicit_initial_thresholds_reach_config_and_cli_without_final_acceptance_change(tmp_path,monkeypatch):
    root,spec=source(tmp_path)
    def runner(s,xml,cfg,directory,**kw):
        assert cfg.vla_initialize_arm_tolerance_rad==.15 and cfg.vla_initialize_gripper_tolerance_m==.01
        assert cfg.criteria==Config().criteria
        directory.mkdir(parents=True)
        return dict(scene_id=s['scene_id'],split=s['split'],task_completed=False,inverse_dynamics_calls=0)
    report=rollout.run_rollouts(root,tmp_path/'phase_readiness',metadata(),indices=[4],init_arm_tolerance=.15,
        init_gripper_tolerance=.01,attempt_runner=runner)
    assert report['config']['vla_initialize_arm_tolerance_rad']==.15
    from scripts import evaluate_pi05_airport as cli
    captured=[];monkeypatch.setattr(cli,'verified_server_metadata',lambda *a,**kw:metadata())
    monkeypatch.setattr(cli,'run_rollouts',lambda *a,**kw:captured.append(kw) or {'status':'completed'})
    args=['--collection',str(root),'--output',str(tmp_path/'cli'),'--indices','4']
    cli.main(args);assert captured[-1]['init_arm_tolerance']==.06 and captured[-1]['init_gripper_tolerance']==.005
    cli.main(args+['--init-arm-tolerance','.15','--init-gripper-tolerance','.01'])
    assert captured[-1]['init_arm_tolerance']==.15 and captured[-1]['init_gripper_tolerance']==.01
