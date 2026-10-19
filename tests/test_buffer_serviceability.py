from types import SimpleNamespace
from dataclasses import replace
import numpy as np
import pytest
from test_release_scheduler import scene7
from r1pro_teleop.airport_fsm.contracts import Config, Fault
from r1pro_teleop.airport_fsm.machine import Machine
from r1pro_teleop.airport_fsm import buffer_serviceability as service, primitives
from r1pro_teleop.airport_fsm.scheduler import release_prerequisite, rear_buffer_candidates


def setup(scene7, monkeypatch, *, qualifies=True):
    g, source, requested = scene7
    cfg = Config(fixed_primitives=True, release_preflight_enabled=True,
        temporary_buffer_serviceability_enabled=True, placement_screen_enabled=True)
    original, metadata = release_prerequisite(g, source, requested, [0,2,1], {0}, cfg)
    context = service.prerequisite_context(requested, original, source, [0,2,1], {0}, metadata, 2)
    m = object.__new__(Machine); m.g=g; m.c=cfg; m.operations=2
    m.scheduler=SimpleNamespace(mapping=[0,2,1]); m.verified_final_trays={0}
    events=[]; calls=[]; order=[]
    m.log=SimpleNamespace(event=lambda name,**kw:events.append((name,kw)))
    observed={'tray_pose':source.copy(), 'gripper_contact_force':np.full((3,2),10.)}
    # Real post-lift context, with the selected blocker no longer on its table.
    observed['tray_pose'][1,2] += .18
    m.r=SimpleNamespace(holding=1, retained_contact=None, observation=lambda:observed)
    m._poses=lambda:observed['tray_pose'].copy()
    m.transition=lambda *a,**kw:None
    monkeypatch.setattr(service,'carried_placement_candidates',lambda *a,**kw:[np.zeros(3)]*18)
    def screen(runtime, staged, final, yaw, nominal, **kwargs):
        assert runtime is m.r and kwargs['max_candidates']==18
        calls.append(final.copy())
        success=qualifies and len(calls)==3
        return SimpleNamespace(examined=18, qualified=[{'base':np.array([-.94,.78,-1.57])}] if success else [],
            rejected=[] if success else [{'reason':'ik_unreachable'}])
    monkeypatch.setattr(service,'screen_placement',screen)
    return m, original, context, events, calls, observed, order


def test_original_three_rear_candidates_preserve_geometry_and_source(scene7):
    g,pose,_=scene7; before=pose.copy()
    candidates=rear_buffer_candidates(g,pose,1)
    assert len(candidates)==3
    assert [round(x.destination[1],2) for x in candidates]==[0.,-.25,.25]
    for op in candidates:
        assert g.support_table(op.destination)=='rear'
        assert not g.blockers(pose,1,op.destination,op.yaw,.025)
    np.testing.assert_array_equal(pose,before)
    # Enlarging the tray beyond the unchanged table footprint excludes all.
    g.sizes[1,:2]=[2.,2.]
    assert rear_buffer_candidates(g,pose,1)==[]


def test_bounded_selection_copies_full_context_and_keeps_live_poses(scene7,monkeypatch):
    m,op,ctx,events,calls,obs,_=setup(scene7,monkeypatch)
    before=obs['tray_pose'].copy(); original=op.destination.copy()
    selected,proposal=service.select_buffer(m,op,ctx)
    assert len(calls)==3 and selected.destination[1]==pytest.approx(.25)
    assert selected is not op and proposal['operation'] is not selected
    np.testing.assert_array_equal(op.destination,original)
    np.testing.assert_array_equal(obs['tray_pose'],before)
    event=next(data for name,data in events if name=='temporary_buffer_serviceability_screen')
    assert event['examined']==54 and event['maximum_probes']==54
    assert event['requested']['tray']==2 and event['requested']['slot']==1
    assert ctx.requested.destination is not m.g.goals[1]
    # Even a caller after a physical recovery cannot rescreen this operation.
    assert service.select_buffer(m,selected,ctx)==(selected,None)
    assert len(calls)==3


@pytest.mark.parametrize('mutation', ['protected','mapping','index','stack','ordinary','lost_contact','retained'])
def test_context_and_grasp_gates_prevent_probes(scene7,monkeypatch,mutation):
    m,op,ctx,events,calls,obs,_=setup(scene7,monkeypatch)
    if mutation=='protected':m.verified_final_trays.add(1)
    if mutation=='mapping':m.scheduler.mapping=[2,0,1]
    if mutation=='index':m.operations+=1
    if mutation=='stack':monkeypatch.setattr(m.g,'top_available',lambda *args:False)
    if mutation=='ordinary':ctx=None
    if mutation=='lost_contact':obs['gripper_contact_force'][1,0]=.5
    if mutation=='retained':m.r.retained_contact={'tray':1}
    if mutation in ('lost_contact','retained'):
        with pytest.raises(Fault,match='temporary_buffer_grasp_context_invalid'):
            service.select_buffer(m,op,ctx)
    else:
        assert service.select_buffer(m,op,ctx)==(op,None)
    assert not calls


def test_original_requested_release_must_remain_executable(scene7,monkeypatch):
    m,op,ctx,events,calls,obs,_=setup(scene7,monkeypatch)
    monkeypatch.setattr(service,'_executable_geometry',lambda g,p,candidate,c: candidate.tray!=ctx.requested.tray)
    assert service.select_buffer(m,op,ctx)==(op,None)
    assert not calls and events[-1][1]['examined']==0
    assert all(x['reason']=='requested_release_geometry' for x in events[-1][1]['candidates'])


def test_no_qualified_buffer_preserves_original_explicit_failure_path(scene7,monkeypatch):
    m,op,ctx,events,calls,obs,_=setup(scene7,monkeypatch,qualifies=False)
    assert service.select_buffer(m,op,ctx)==(op,None)
    assert len(calls)==3 and events[-1][1]['fallback_to_original']


def test_selected_operation_drives_live_place_without_duplicate_screen_or_failure_retry(scene7,monkeypatch):
    m,op,ctx,events,calls,obs,order=setup(scene7,monkeypatch)
    selected,proposal=service.select_buffer(m,op,ctx)
    from r1pro_teleop.airport_fsm import placement_reachability
    monkeypatch.setattr(placement_reachability,'screen_placement',lambda *a,**kw:pytest.fail('duplicate screen'))
    m.r.navigate=lambda base:order.append(('navigate',base.copy()))
    m.r.remember_grasp=lambda tray:order.append(('remember',tray))
    def fail_place(machine,operation,staged):
        assert service.same_operation(operation,selected)
        np.testing.assert_array_equal(staged,selected.destination)
        order.append(('place',operation))
        raise Fault('measured_joint_overspeed')
    monkeypatch.setattr(primitives,'place',fail_place)
    with pytest.raises(Fault,match='measured_joint_overspeed'):
        m.carry_place(selected,placement_proposal=proposal)
    assert [x[0] for x in order]==['navigate','remember','place']
    assert len(calls)==3
    selected.destination[1]+=.01
    with pytest.raises(Fault,match='temporary_buffer_proposal_stale'):
        m.carry_place(selected,placement_proposal=proposal)
    assert len(order)==3


def test_configuration_opt_in_dependencies():
    assert Config().temporary_buffer_serviceability_enabled is False
    Config(fixed_primitives=True,release_preflight_enabled=True,
        temporary_buffer_serviceability_enabled=True).validate()
    for args in ({'fixed_primitives':True},{'release_preflight_enabled':True}):
        with pytest.raises(ValueError,match='requires fixed primitives and release preflight'):
            Config(temporary_buffer_serviceability_enabled=True,**args).validate()
    with pytest.raises(ValueError,match='must be boolean'):
        Config(temporary_buffer_serviceability_enabled=1).validate()


def test_run_updates_outer_verifier_operation_after_real_grasp(scene7,monkeypatch):
    m,op,ctx,events,calls,obs,order=setup(scene7,monkeypatch)
    m.operations=1; m.c=replace(m.c,max_operations=1,consistent_placement=False)
    m.scheduler.choose=lambda poses:ctx.requested
    obs['tray_pose'][:]=ctx.source_poses
    obs['min_z']=np.full(3,.8)
    m.r.holding=None; m.r.tucked=np.zeros(16)
    m.r.wait=lambda *a,**kw:None; m.r.joints=lambda *a,**kw:None
    m.prepare_pick=lambda *a:(0.,0.)
    def grasp(tray,*args):
        order.append('grasp');m.r.holding=tray;obs['tray_pose'][tray,2]+=.18
    m.grasp=grasp
    carried=[];verified=[]
    def carry(operation,**kwargs):
        assert order==['grasp'] and kwargs['placement_proposal'] is not None
        carried.append(operation);return False
    m.carry_place=carry
    m.verify_operation=lambda operation:verified.append(operation) or True
    with pytest.raises(Fault,match='operation_budget_exhausted'):m.run()
    assert carried[0] is verified[0] and verified[0].destination[1]==pytest.approx(.25)
    assert m.operations==2 and m.verified_final_trays=={0}
    assert len(calls)==3
    revised=next(data for name,data in events if name=='operation_destination_revised')
    assert revised['operation_index']==2 and revised['requested']['tray']==2


def test_exhausted_buffer_screen_does_not_add_generic_pretransport_probes(scene7,monkeypatch):
    m,op,ctx,events,calls,obs,order=setup(scene7,monkeypatch,qualifies=False)
    service.select_buffer(m,op,ctx)
    from r1pro_teleop.airport_fsm import placement_reachability
    monkeypatch.setattr(placement_reachability,'screen_placement',lambda *a,**kw:pytest.fail('54 + extra screen'))
    m.r.navigate=lambda base:order.append('navigate')
    m.r.remember_grasp=lambda tray:order.append('remember')
    monkeypatch.setattr(primitives,'place',lambda *a:order.append('place'))
    m.carry_place(op,skip_placement_screen=ctx.screened)
    assert len(calls)==3 and order==['navigate','remember','place']


def test_arrival_uses_revised_buffer_with_one_separate_shared_budget(scene7,monkeypatch):
    m,op,ctx,events,calls,obs,order=setup(scene7,monkeypatch)
    selected,proposal=service.select_buffer(m,op,ctx)
    m.c=replace(m.c,placement_arrival_rescreen_enabled=True)
    from r1pro_teleop.airport_fsm import placement_reachability as planner
    current=np.zeros(3);m.r.steps=0;m.r.d=SimpleNamespace(time=0.);m.r.cfg=m.c
    m.r.sim=SimpleNamespace(base_state=lambda:current.copy())
    def navigate(base):
        current[:]=base;m.r.steps+=20;m.r.d.time+=1.;order.append('navigate')
    m.r.navigate=navigate;m.r.remember_grasp=lambda tray:order.append('remember')
    def candidates(runtime,nominal,anchor,**kwargs):
        np.testing.assert_array_equal(anchor,selected.destination[:2])
        return [current.copy(),current+np.array([.04,0.,0.])]
    def screen(runtime,staged,final,yaw,nominal,**kwargs):
        np.testing.assert_array_equal(final,selected.destination)
        np.testing.assert_array_equal(staged,proposal['staged'])
        alternatives=list(kwargs['candidates'])
        assert len(alternatives)==1
        np.testing.assert_allclose(alternatives[0],current+np.array([.04,0.,0.]))
        assert kwargs['max_candidates']==18
        order.append('arrival_screen')
        return SimpleNamespace(examined=1,qualified=[{'base':alternatives[0]}],rejected=[])
    monkeypatch.setattr(planner,'carried_placement_candidates',candidates)
    monkeypatch.setattr(planner,'screen_placement',screen)
    def place(*args):
        order.append('place')
        if order.count('place')==1:
            with primitives.action(m,'transport_align'):
                raise Fault('primitive_path_infeasible')
    monkeypatch.setattr(primitives,'place',place)
    m.carry_place(selected,placement_proposal=proposal)
    assert order==['navigate','remember','place','remember','arrival_screen','navigate','remember','place'] and len(calls)==3


def test_disabled_feature_does_not_consume_context_or_probe(scene7,monkeypatch):
    m,op,ctx,events,calls,obs,order=setup(scene7,monkeypatch)
    m.c=replace(m.c,temporary_buffer_serviceability_enabled=False)
    assert service.select_buffer(m,op,ctx)==(op,None)
    assert not ctx.consumed and not calls and not events
