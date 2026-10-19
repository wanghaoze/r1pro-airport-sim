import json
from pathlib import Path
from types import SimpleNamespace
import time
import numpy as np
import pytest
from r1pro_teleop.airport_fsm import physical_preview as pp
from r1pro_teleop.airport_fsm.contracts import Config, Fault


@pytest.fixture
def machine(tmp_path):
    import mujoco
    from r1pro_teleop.airport_mobile import make_mobile_scene
    from r1pro_teleop.airport_fsm.runtime import Runtime
    from r1pro_teleop.airport_fsm.machine import Machine
    base=Path('resources/scenes');scope=base/'server_v7' if (base/'server_v7').exists() else base/'formal'
    scene=sorted(scope.rglob('scene.json'))[0]
    spec=json.loads(scene.read_text());source=scene.parent/spec.get('scene_file','scene.xml')
    model=mujoco.MjModel.from_xml_path(str(source))
    if mujoco.mj_name2id(model,mujoco.mjtObj.mjOBJ_JOINT,'agent_base_x')<0:
        xml=tmp_path/'mobile.xml';make_mobile_scene(source,xml)
    else:xml=source
    r=Runtime(spec,xml,Config(),render=False);m=Machine(r,tmp_path/'live')
    yield m
    m.log.close();r.close()


def test_independent_model_data_context_and_exact_physical_continuation(machine,tmp_path):
    source=machine;r=source.r
    r.retained_support_missing_since=12.345
    r.grasp_rel={'left':np.eye(4),'right':np.eye(4)}
    r.primitive_lift_xy_shift_m=.023
    source.pending_grasp_contact={'tray':1,'values':np.array([1.,2.])}
    r.m.geom_friction[0,0]+=.001 # effective model changes must be copied exactly
    fingerprint=pp.context_digest(source)
    probe=pp.clone_machine(source,tmp_path/'probe')
    try:
        p=probe.r
        assert p.m is not r.m and p.d is not r.d and p.shadow is not r.shadow
        assert p.sim.ik_data is not r.sim.ik_data and p.evidence.sim is p.sim
        assert p.wall_start==r.wall_start and p.retained_support_missing_since==12.345
        assert p.grasp_rel['left'] is not r.grasp_rel['left']
        assert p.m.geom_friction[0,0]==r.m.geom_friction[0,0]
        p.m.geom_friction[0,0]+=.01
        assert p.m.geom_friction[0,0]!=r.m.geom_friction[0,0]
        p.m.geom_friction[0,0]=r.m.geom_friction[0,0]
        p.tick();r.tick()
        np.testing.assert_array_equal(pp._integration(p),pp._integration(r))
        np.testing.assert_array_equal(p.d.ctrl,r.d.ctrl)
        p.sim.target[0]+=.5;p.grasp_rel['left'][0,0]=2
        probe.pending_grasp_contact['values'][0]=9
        assert source.pending_grasp_contact['values'][0]==1
        assert r.grasp_rel['left'][0,0]==1
        assert p.sim.target[0]!=r.sim.target[0]
        assert bool(probe.log.file.attrs['physical_preview'])
        assert not bool(probe.log.file.attrs['actual_episode_success_eligible'])
    finally:probe.log.close();probe.r.close()


def test_candidate_changes_only_declared_controls():
    with pytest.raises(ValueError):pp.PushCandidate('unsafe',(('primitive_seconds',4),)).config(Config())
    with pytest.raises(ValueError):pp.PushCandidate('duplicate',(('push_yaw_feedback_enabled',True),('push_yaw_feedback_enabled',False))).config(Config())
    with pytest.raises(ValueError):pp.PushCandidate('../escape').config(Config())
    assert pp.default_candidates()[0]==pp.PushCandidate('original')


def test_clone_preserves_class_defined_controller_behavior(machine,tmp_path):
    from r1pro_teleop.airport_fsm.machine import Machine
    class ExperimentalMachine(Machine):
        def verify_operation(self,operation):return self.experimental_marker
    machine.__class__=ExperimentalMachine;machine.experimental_marker='same_policy'
    probe=pp.clone_machine(machine,tmp_path/'subclass_preview')
    try:
        assert type(probe) is ExperimentalMachine
        assert probe.verify_operation(None)=='same_policy'
    finally:probe.log.close();probe.r.close()


@pytest.mark.parametrize('nested',[False,True])
def test_clone_rejects_external_checkpoint_tree_before_creating_trace(machine,tmp_path,nested):
    from r1pro_teleop.experiments.checkpoint_tree import CheckpointTree
    tree=CheckpointTree(machine,tmp_path/'external_tree')
    machine.stage_context={'tree':tree} if nested else tree
    fingerprint=pp._integration(machine.r).copy()
    with pytest.raises(ValueError,match='external controller object'):
        pp.clone_machine(machine,tmp_path/'must_not_exist')
    assert not (tmp_path/'must_not_exist').exists()
    np.testing.assert_array_equal(fingerprint,pp._integration(machine.r))
    assert not list((tmp_path/'external_tree').iterdir())


def fake_live():
    c=Config(fixed_primitives=True)
    r=SimpleNamespace(cfg=c,steps=200,d=SimpleNamespace(time=10.),wall_start=time.monotonic(),
                      retained_contact=(1,'right'),holding=None,primitive_deadline_step=None)
    m=SimpleNamespace(c=c,r=r)
    op=SimpleNamespace(tray=1,slot=1,temporary=False)
    return m,op


@pytest.mark.parametrize('change',[{'temporary':True},{'slot':-1}])
def test_only_final_placement(change):
    m,op=fake_live()
    for key,value in change.items():setattr(op,key,value)
    assert not pp.eligible_push(m,op,separation=False,retained_side='right')


def test_separation_recursion_and_active_primitive_are_ineligible():
    m,op=fake_live()
    assert pp.eligible_push(m,op,separation=False,retained_side='right')
    assert not pp.eligible_push(m,op,separation=True,retained_side='right')
    m._physical_preview_active=True
    assert not pp.eligible_push(m,op,separation=False,retained_side='right')
    del m._physical_preview_active;m.r.primitive_deadline_step=260
    assert not pp.eligible_push(m,op,separation=False,retained_side='right')


@pytest.mark.parametrize('outcomes,expected,count',[
    ([True,False,False],'original',1),
    ([False,False,True],'yaw_feedback',3),
    ([False,False,False],'original',3),
])
def test_bounded_selection_original_first_and_failure_evidence(monkeypatch,tmp_path,outcomes,expected,count):
    m,op=fake_live();calls=[]
    monkeypatch.setattr(pp,'context_digest',lambda m:'same')
    monkeypatch.setattr(pp,'_save_terminal',lambda *a:None)
    def clone(source,directory,candidate):
        outcome=outcomes[len(calls)];calls.append(candidate.name)
        r=SimpleNamespace(steps=source.r.steps,d=SimpleNamespace(time=source.r.d.time,qpos=np.zeros(1),qvel=np.zeros(1)),close=lambda:None)
        def push(operation,retained_side):
            r.steps+=2;r.d.time+=.1
            if not outcome:raise Fault('retained_contact_lost',{'force':0.})
            return False # successful return is valid even if consistent_placement=False
        return SimpleNamespace(r=r,directory=directory,push=push,log=SimpleNamespace(event=lambda *a,**kw:None,close=lambda *a:None))
    monkeypatch.setattr(pp,'clone_machine',clone)
    start=m.r.wall_start
    result=pp.choose_push_candidate(m,op,retained_side='right',directory=tmp_path/'previews')
    assert result.candidate.name==expected and len(calls)==count
    assert result.preview_verified==any(outcomes[:count])
    assert m.r.wall_start==start and m.r.steps==200 and m.r.d.time==10.
    assert len(list((tmp_path/'previews').glob('*_summary.json')))==count
    for summary in result.summaries:
        assert summary['actual_episode_success_eligible'] is False
        assert summary['physical_seconds']==pytest.approx(.1)


def test_attempt_wall_budget_exhaustion_never_starts_preview(monkeypatch,tmp_path):
    m,op=fake_live();m.r.wall_start=time.monotonic()-m.c.max_attempt_wall_seconds-1
    monkeypatch.setattr(pp,'context_digest',lambda m:'same')
    monkeypatch.setattr(pp,'clone_machine',lambda *a:pytest.fail('must not clone'))
    with pytest.raises(Fault,match='episode_budget_exhausted'):
        pp.choose_push_candidate(m,op,retained_side='right',directory=tmp_path/'previews')


def test_exact_failed_substep_prefix_and_terminal_evidence(machine,tmp_path,monkeypatch):
    from r1pro_teleop.airport_fsm.runtime import Runtime
    probe=pp.clone_machine(machine,tmp_path/'failed_preview')
    original=Runtime.guard;start=machine.r.d.time
    def guarded(runtime):
        result=original(runtime)
        if runtime.d.time-start>=.006-1e-10:raise Fault('diagnostic_third_substep')
        return result
    monkeypatch.setattr(Runtime,'guard',guarded)
    try:
        for r in (probe.r,machine.r):
            with pytest.raises(Fault,match='diagnostic_third_substep'):r.tick()
            assert r.steps==0 and r.d.time-start==pytest.approx(.006)
        np.testing.assert_array_equal(pp._integration(probe.r),pp._integration(machine.r))
        pp._save_terminal(probe.r,probe.directory)
        with np.load(probe.directory/'terminal_state.npz') as f:
            np.testing.assert_array_equal(f['integration_state'],pp._integration(probe.r))
            assert int(f['steps'])==0 and float(f['physical_time'])==pytest.approx(start+.006)
    finally:probe.log.close();probe.r.close()


@pytest.mark.parametrize('settings',[
    {'push_physical_preview_enabled':1},
    {'push_physical_preview_max_candidates':True},
    {'push_physical_preview_max_candidates':4},
    {'push_physical_preview_enabled':True,'fixed_primitives':False},
])
def test_config_rejects_invalid_preview(settings):
    with pytest.raises(ValueError):Config(**settings).validate()


def test_default_off():
    assert Config().push_physical_preview_enabled is False
    assert Config().push_physical_preview_max_candidates==3


@pytest.mark.parametrize('fail',[False,True])
def test_actual_executes_once_with_scoped_controls_and_no_state_restore(monkeypatch,tmp_path,fail):
    m,op=fake_live();m.directory=tmp_path;events=[];calls=[]
    m.log=SimpleNamespace(event=lambda event,**kw:events.append((event,kw)))
    candidate=pp.PushCandidate('yaw_feedback',(('push_yaw_feedback_enabled',True),))
    monkeypatch.setattr(pp,'choose_push_candidate',lambda *a,**kw:pp.PushSelection(candidate,False,(),.1))
    original_c=m.c;original_wall=m.r.wall_start;fault=Fault('retained_contact_lost')
    def push(operation,retained_side):
        calls.append(operation)
        assert m._physical_preview_active and m.c.push_yaw_feedback_enabled
        assert m.r.cfg is m.c and m.r.wall_start==original_wall
        m.r.steps+=1;m.r.d.time+=.05
        if fail:raise fault
        return True
    m.push=push
    if fail:
        with pytest.raises(Fault) as exc:pp.preview_then_push(m,op,retained_side='right')
        assert exc.value is fault
    else:assert pp.preview_then_push(m,op,retained_side='right') is True
    assert len(calls)==1 and m.r.steps==201 and m.r.d.time==10.05
    assert m.c is original_c and m.r.cfg is original_c and not m._physical_preview_active
    assert events[-1][0]=='physical_push_preview_actual_result'
