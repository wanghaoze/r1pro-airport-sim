import json
from pathlib import Path
import numpy as np
import pytest
from r1pro_teleop.airport_fsm import placement_reachability as p
from r1pro_teleop.airport_fsm.contracts import Config, Fault


def test_candidate_order_bound_and_rotation_covariance():
    a=list(p.placement_candidates([1,2,0]))
    b=list(p.placement_candidates([-2,1,np.pi/2]))
    assert len(a)==9 and len(set(tuple(x) for x in a))==9
    np.testing.assert_array_equal(a[0],[1,2,0])
    for x,y in zip(a,b):np.testing.assert_allclose(y[:2],[-x[1],x[0]])


def test_screen_bounded_rejections_never_qualify(monkeypatch):
    monkeypatch.setattr(p,'loaded_planning_copy',lambda r:object())
    def fail(*args):raise Fault('primitive_path_infeasible',{'available_s':1.95})
    monkeypatch.setattr(p,'qualify_placement',fail)
    out=p.screen_placement(None,[0,0,0],[0,0,0],0,[0,0,0],max_candidates=3)
    assert out.examined==3 and not out.qualified and len(out.rejected)==3
    assert all(x['reason']=='primitive_path_infeasible' for x in out.rejected)
    with pytest.raises(ValueError):p.screen_placement(None,None,None,0,None,max_candidates=19)


def test_screen_stops_at_first_qualified_without_evaluating_extra(monkeypatch):
    monkeypatch.setattr(p,'loaded_planning_copy',lambda r:object())
    monkeypatch.setattr(p,'qualify_placement',lambda *args:{'base':args[-1]})
    out=p.screen_placement(None,[0,0,0],[0,0,0],0,[0,0,0])
    assert out.examined==1 and len(out.qualified)==1 and not out.rejected


@pytest.fixture
def runtime(tmp_path):
    import mujoco
    from r1pro_teleop.airport_fsm.runtime import Runtime
    from r1pro_teleop.airport_mobile import make_mobile_scene
    base=Path('resources/scenes');scope=base/'server_v7' if (base/'server_v7').exists() else base/'formal'
    scenes=sorted(scope.rglob('scene.json'))
    scene=next((x for x in scenes if x.parent.name.startswith('airport_0004_')),scenes[0])
    spec=json.loads(scene.read_text());source=scene.parent/spec.get('scene_file','scene.xml')
    m=mujoco.MjModel.from_xml_path(str(source))
    if mujoco.mj_name2id(m,mujoco.mjtObj.mjOBJ_JOINT,'agent_base_x')<0:
        xml=tmp_path/'mobile.xml';make_mobile_scene(source,xml)
    else:xml=source
    r=Runtime(spec,xml,Config(fixed_primitives=True),render=False)
    yield r
    r.close()


def test_loaded_clone_and_private_rigid_transport_never_mutate_live(runtime):
    r=runtime;r.allowed_tray=0;r.remember_grasp(0)
    before=np.empty(r.integration_size);r.mj.mj_getState(r.m,r.d,before,r.integration_spec)
    target=r.sim.target.copy();relations={k:v.copy() for k,v in r.grasp_rel.items()}
    q=p.loaded_planning_copy(r)
    assert q.d is not r.d and q.sim is not r.sim and q.evidence.sim is q.sim
    assert all(getattr(q,x) is not getattr(r,x) for x in ('shadow','inverse'))
    base=r.sim.base_state().astype(float);base[:2]+=[.05,-.03]
    payload=r.d.body(r.g.ids[0]).xpos.copy()
    p._project(q,base=base)
    np.testing.assert_allclose(q.d.body(q.g.ids[0]).xpos,payload+[.05,-.03,0],atol=2e-7)
    after=np.empty(r.integration_size);r.mj.mj_getState(r.m,r.d,after,r.integration_spec)
    np.testing.assert_array_equal(before,after);np.testing.assert_array_equal(target,r.sim.target)
    for k in relations:np.testing.assert_array_equal(relations[k],r.grasp_rel[k])
    q.grasp_rel['left'][0,0]+=1
    np.testing.assert_array_equal(relations['left'],r.grasp_rel['left'])
    for fn in (q.tick,q.sim.step,q.sim.apply_target):
        with pytest.raises(RuntimeError,match='cannot execute'):fn()


def test_empty_or_retained_state_is_rejected(runtime):
    with pytest.raises(Fault,match='requires_bilateral'):p.loaded_planning_copy(runtime)
    runtime.remember_grasp(0);runtime.retained_contact=(0,'left')
    with pytest.raises(Fault,match='requires_bilateral'):p.loaded_planning_copy(runtime)

@pytest.mark.parametrize('preserve_enabled',[False,True])
def test_qualification_reserves_release_and_support_inside_three_seconds(runtime,monkeypatch,preserve_enabled):
    r=runtime;r.allowed_tray=0;r.remember_grasp(0);q=p.loaded_planning_copy(r)
    # Use the observed tray/table geometry; only path-solving is replaced to
    # test budget accounting without claiming this initial pose is a real grasp.
    from dataclasses import replace
    q.cfg=replace(q.cfg,placement_preserve_command_grasp_enabled=preserve_enabled)
    rebuilt=[];original_reference=p.continue_loaded_reference
    def reference(probe):
        rebuilt.append(probe.phase);original_reference(probe)
    monkeypatch.setattr(p,'continue_loaded_reference',reference)
    staged=q.observation()['tray_pose'][0,:3].copy()
    monkeypatch.setattr(q,'collision',lambda *a,**kw:None)
    monkeypatch.setattr(q,'camera_guard',lambda *a,**kw:True)
    monkeypatch.setattr(p,'object_points',lambda runtime,*args:np.stack([runtime.sim.target.copy()]*2))
    calls=[]
    class Path:
        def evaluate(self,*a):return q.sim.target.copy(),None,None,None
    def fake_plan(runtime,points,*,available,**kw):
        calls.append(available)
        return Path(),[20,19,39][len(calls)-1]
    monkeypatch.setattr(p,'plan',fake_plan)
    out=p.qualify_placement(q,staged,staged,0,q.sim.base_state())
    assert calls==pytest.approx([q.cfg.primitive_seconds-q.cfg.primitive_settle_s,2.7,1.95])
    assert out['descent_frames']+out['release_frames']+out['support_reserve_frames']==60
    assert out['certifies_contact_or_route'] is False
    assert rebuilt==['transport','descend']


def _carried_runtime(base, tray_yaw):
    from types import SimpleNamespace
    pose=np.array([[1.,2.,.9,np.cos(tray_yaw/2),0,0,np.sin(tray_yaw/2)]])
    return SimpleNamespace(holding=0,grasp_rel={'left':np.eye(4)},retained_contact=None,
        sim=SimpleNamespace(base_state=lambda:np.asarray(base,float)),
        observation=lambda:{'tray_pose':pose})


def test_carried_candidates_preserve_nominal_nine_and_bound_eighteen():
    r=_carried_runtime([.2,.3,.4],1.2)
    values=list(p.carried_placement_candidates(r,[.28,.38,0],[.85,.38],goal_tray_yaw=0))
    assert len(values)==18
    np.testing.assert_array_equal(values[:9],list(p.placement_candidates([.28,.38,0])))
    assert values[9][2]==pytest.approx(-.8)
    np.testing.assert_allclose(values[9][:2],[.85-.57*np.cos(-.8),.38-.57*np.sin(-.8)])


def test_carried_short_grasp_duplicate_family_is_removed():
    r=_carried_runtime([.2,.3,0],0)
    values=list(p.carried_placement_candidates(r,[.28,.38,0],[.85,.38],goal_tray_yaw=0))
    assert len(values)==9
    np.testing.assert_array_equal(values,list(p.placement_candidates([.28,.38,0])))


def test_carried_candidates_are_rigid_rotation_translation_covariant():
    angle=.7;shift=np.array([2.,-3.]);R=np.array([[np.cos(angle),-np.sin(angle)],[np.sin(angle),np.cos(angle)]])
    base=np.array([.2,.3,.4]);nominal=np.array([.28,.38,0.]);anchor=np.array([.85,.38])
    transform=lambda b:np.r_[R@b[:2]+shift,b[2]+angle]
    a=list(p.carried_placement_candidates(_carried_runtime(base,1.2),nominal,anchor,goal_tray_yaw=.1))
    b=list(p.carried_placement_candidates(_carried_runtime(transform(base),1.2+angle),transform(nominal),R@anchor+shift,goal_tray_yaw=.1+angle))
    assert len(a)==len(b)==18
    for x,y in zip(a,b):
        np.testing.assert_allclose(y[:2],R@x[:2]+shift,atol=1e-12)
        assert p.wrap_angle(y[2]-x[2]-angle)==pytest.approx(0)


def test_screen_default_nine_and_explicit_eighteen(monkeypatch):
    monkeypatch.setattr(p,'loaded_planning_copy',lambda r:object())
    def fail(*args):raise Fault('ik_unreachable')
    monkeypatch.setattr(p,'qualify_placement',fail)
    choices=[np.array([0.,i,0.])for i in range(30)]
    default=p.screen_placement(None,[0,0,0],[0,0,0],0,[0,0,0],candidates=choices)
    expanded=p.screen_placement(None,[0,0,0],[0,0,0],0,[0,0,0],candidates=choices,max_candidates=18)
    assert default.examined==9 and expanded.examined==18
    assert len(default.rejected)==9 and len(expanded.rejected)==18


def test_predictor_tries_original_then_single_saved_alignment_candidate(runtime,monkeypatch):
    from dataclasses import replace
    r=runtime;r.allowed_tray=0;r.remember_grasp(0);q=p.loaded_planning_copy(r)
    q.cfg=replace(q.cfg,placement_preserve_command_grasp_enabled=True,
                  placement_alignment_xy_feedforward_enabled=True)
    staged=q.observation()['tray_pose'][0,:3].copy();targets=[];rebuilt=[]
    original=p.continue_loaded_reference
    def reference(probe):
        rebuilt.append(probe.phase);original(probe)
    monkeypatch.setattr(p,'continue_loaded_reference',reference)
    monkeypatch.setattr(q,'collision',lambda *a,**kw:None)
    monkeypatch.setattr(q,'camera_guard',lambda *a,**kw:True)
    def points(probe,target,*args):
        targets.append(target.copy());return np.stack([probe.sim.target.copy()]*2)
    monkeypatch.setattr(p,'object_points',points)
    class Path:
        def evaluate(self,*args):return q.sim.target.copy(),None,None,None
    calls=[]
    def plan(probe,points,*,available,**kwargs):
        calls.append(available)
        if len(calls)==3:raise Fault('primitive_path_infeasible')
        return Path(),{1:20,2:19,4:19,5:39}[len(calls)]
    monkeypatch.setattr(p,'plan',plan)
    before=q.steps;physical=float(q.d.time)
    result=p.qualify_placement(q,staged,staged,0.,q.sim.base_state())
    assert rebuilt==['transport','descend'] and len(calls)==5
    assert calls[1:]==pytest.approx([2.7,1.95,2.7,1.95])
    assert result['descent_frames']==39 and q.steps==before and q.d.time==physical
    # A private future projection supplies no measured XY correction, even
    # with the real execution flag enabled.
    for target in targets:np.testing.assert_array_equal(target[:2],staged[:2])
