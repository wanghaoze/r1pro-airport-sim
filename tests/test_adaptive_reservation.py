import copy
import json
from types import SimpleNamespace as NS
from dataclasses import replace
import numpy as np
import pytest
from test_release_scheduler import scene7
from test_experiments import tiny_machine
from r1pro_teleop.airport_fsm import reservation_plan as rp
from r1pro_teleop.airport_fsm import scheduler as release
from r1pro_teleop.airport_fsm.geometry import Scheduler,Operation,slot_geometry_ready
from r1pro_teleop.airport_fsm.acceptance_profile import completion_criteria
from r1pro_teleop.airport_fsm.contracts import Config,Fault
from r1pro_teleop.experiments.checkpoint_tree import CheckpointTree,encode
from test_physical_preview import machine


def setup(scene7,monkeypatch):
    g,pose,_=scene7;pose=pose.copy();mapping=[0,2,1]
    pose[0]=[*g.goals[0],1,0,0,0]
    pose[2]=[.8413793639121464,-.07138170542223708,.7999952170405822,
             .025167908243928262,8.1552e-8,1.5062e-7,-.999683238028224]
    pose[1,:3]=[.85,-1.25,.8]
    c=Config(acceptance_profile='completion_first',retained_support_integer_clock_enabled=True,
        completion_adaptive_reservation_enabled=True,consistent_placement=True,fixed_primitives=True)
    s=Scheduler(g,completion_criteria(c),consistent_placement=True,require_full_footprint=False,use_actual_gap=True)
    s.mapping=mapping;events=[]
    m=NS(c=c,g=g,scheduler=s,verified_final_trays={0},r=NS(steps=2941),
        log=NS(event=lambda name,**kw:events.append((name,kw))))
    samples=[dict(tray_pose=pose.copy(),table_contact=np.full(3,4),gripper_contact_force=np.zeros((3,2))) for _ in range(21)]
    op=Operation(2,1,g.goals[1].copy(),0.)
    monkeypatch.setattr(release,'_executable_geometry',lambda *a:True)
    return m,op,samples,events


def test_default_and_validation():
    assert not Config().completion_adaptive_reservation_enabled
    for value in [1,0,None,'true']:
        with pytest.raises(ValueError):replace(Config(),completion_adaptive_reservation_enabled=value).validate()
    with pytest.raises(ValueError):replace(Config(),completion_adaptive_reservation_enabled=True).validate()
    assert Config().completion_push_free_open_enabled is False
    with pytest.raises(ValueError):replace(Config(),completion_push_free_open_enabled=True).validate()
    with pytest.raises(ValueError):replace(Config(),completion_push_free_open_enabled=1).validate()


def test_direct_buffer_capture_skips_active_reservation(scene7,monkeypatch):
    from r1pro_teleop.airport_fsm.general_buffer import capture_context
    m,op,samples,events=setup(scene7,monkeypatch)
    m.scheduler.reservation_plan=rp.propose(m,op,samples)
    m.c=replace(m.c,temporary_buffer_serviceability_enabled=True,completion_direct_buffer_enabled=True)
    temporary=Operation(1,-1,np.array([.85,-1.,.8]),0.,True)
    assert capture_context(m,temporary,samples[-1]['tray_pose']) is None
    assert events[-1][0]=='general_buffer_skipped'
    assert events[-1][1]['reason']=='active_adaptive_reservation'


def test_actual_reserved_overlap_gets_absolute_future_target(scene7,monkeypatch):
    m,op,samples,events=setup(scene7,monkeypatch);g=m.g;before=g.goals.copy();pose=samples[-1]['tray_pose']
    assert not slot_geometry_ready(g,pose,m.scheduler.mapping,2,1,completion_criteria(m.c),require_full_footprint=False,use_actual_gap=True)
    plan=rp.propose(m,op,samples);assert plan is not None
    assert plan['candidate_index']<9 and plan['pending_tray']==1
    m.scheduler.reservation_plan=plan
    assert slot_geometry_ready(g,pose,m.scheduler.mapping,2,1,completion_criteria(m.c),require_full_footprint=False,
        use_actual_gap=True,reservation_positions=rp.positions(g,m.scheduler.mapping,plan))
    selected=m.scheduler.choose(pose)
    assert selected.tray==1 and selected.slot==2
    np.testing.assert_array_equal(selected.destination,plan['destination'])
    np.testing.assert_array_equal(g.goals,before)
    assert events[-1][1]['qualification'].endswith('unproven')
    clone=copy.deepcopy(m.scheduler);clone.reservation_plan['destination'][0]+=.01
    assert clone.reservation_plan!=m.scheduler.reservation_plan


@pytest.mark.parametrize('bad',['off','strict','two_pending','unprotected','contact','support','moving','short_tail'])
def test_no_geometry_waiver_without_stable_released_fixed_trays(scene7,monkeypatch,bad):
    m,op,samples,events=setup(scene7,monkeypatch)
    if bad=='off':m.c=replace(m.c,completion_adaptive_reservation_enabled=False)
    if bad=='strict':m.c=replace(m.c,acceptance_profile='strict')
    if bad=='two_pending':samples[-1]['tray_pose'][0,0]+=.2
    if bad=='unprotected':m.verified_final_trays.clear()
    if bad=='contact':samples[-1]['gripper_contact_force'][2,0]=.501
    if bad=='support':samples[-1]['table_contact'][0]=0
    if bad=='moving':samples[-2]['tray_pose'][2,0]+=.002
    if bad=='short_tail':samples=samples[:-1]
    assert rp.propose(m,op,samples) is None


def test_geometry_rejection_is_bounded_and_no_plan_committed(scene7,monkeypatch):
    m,op,samples,events=setup(scene7,monkeypatch)
    monkeypatch.setattr(release,'_executable_geometry',lambda *a:False)
    assert rp.propose(m,op,samples) is None
    assert len(events[-1][1]['rejected'])==9 and m.scheduler.reservation_plan is None


def test_checkpoint_roundtrip_and_illegal_plan_rejected_before_state_write(scene7,monkeypatch,tmp_path):
    m,op,samples,_=setup(scene7,monkeypatch);plan=rp.propose(m,op,samples)
    a=tiny_machine(tmp_path,'a');b=tiny_machine(tmp_path,'b')
    for machine in [a,b]:
        machine.g=m.g;machine.r.cfg.acceptance_profile='completion_first'
        machine.r.cfg.completion_adaptive_reservation_enabled=True
        machine.scheduler.mapping=m.scheduler.mapping
        machine.r.strict_runtime_passed=True;machine.r.soft_guard_violation_count=0
        machine.r.soft_guard_violation_by_code={};machine.r.soft_guard_violation_maxima={}
        machine.r.soft_guard_last_step_by_code={};machine.r.completion_speed_since_step=None
    a.scheduler.reservation_plan=plan
    try:
        tree=CheckpointTree(a,tmp_path/'cp');tree.plan(['ready']);directory=tree.save('ready',lambda _:True)
        CheckpointTree(b,tmp_path/'restore').restore(directory)
        assert b.scheduler.reservation_plan==plan
        b.scheduler.reservation_plan['destination'][0]+=.01
        assert a.scheduler.reservation_plan==plan
        path=directory/'metadata.json';record=json.loads(path.read_text())
        malformed=copy.deepcopy(plan);malformed['destination'][0]+=.01
        record['context']['reservation_plan']=encode(malformed);path.write_text(json.dumps(record))
        fresh=tiny_machine(tmp_path,'fresh');fresh.g=m.g
        fresh.r.cfg.acceptance_profile='completion_first';fresh.r.cfg.completion_adaptive_reservation_enabled=True
        before=fresh.r.d.qpos.copy()
        try:
            with pytest.raises(ValueError,match='reservation geometry'):
                CheckpointTree(fresh,tmp_path/'badrestore').restore(directory)
            np.testing.assert_array_equal(fresh.r.d.qpos,before)
            assert not getattr(fresh,'checkpoint_restored',False)
        finally:fresh.log.close()
    finally:a.log.close();b.log.close()


def test_protected_pose_change_is_not_hidden_rearrangement(scene7,monkeypatch):
    m,op,samples,_=setup(scene7,monkeypatch)
    m.scheduler.reservation_plan=rp.propose(m,op,samples)
    pose=samples[-1]['tray_pose'].copy();pose[0,0]+=.001
    with pytest.raises(Fault,match='adaptive_reservation_protected_pose_changed'):m.scheduler.choose(pose)


def test_existing_verify_window_commits_plan_without_extra_wait(scene7,monkeypatch):
    from r1pro_teleop.airport_fsm.machine import Machine
    source,op,samples,events=setup(scene7,monkeypatch)
    m=object.__new__(Machine);m.__dict__.update(vars(source));m.transition=lambda *a,**k:None
    waits=[];warnings=[]
    m.r.record_strict_deviation=lambda *a: warnings.append(a)
    def wait(seconds,check,stable):
        waits.append(seconds)
        for x in samples:assert check(x) is False
        return False
    m.r.wait=wait
    assert m.verify_operation(op)
    assert waits==[2.] and warnings[0][0]=='adaptive_reservation_outside_strict_contract'
    assert m.scheduler.reservation_plan['pending_tray']==1


def test_real_release_geometry_is_used(scene7,monkeypatch):
    real=release._executable_geometry
    m,op,samples,events=setup(scene7,monkeypatch)
    monkeypatch.setattr(release,'_executable_geometry',real)
    plan=rp.propose(m,op,samples)
    assert plan is not None
    assert real(m.g,samples[-1]['tray_pose'],Operation(1,2,np.array(plan['destination']),plan['yaw']),m.c)


def test_operation_tolerance_cannot_accumulate_beyond_nominal(scene7,monkeypatch):
    from r1pro_teleop.airport_fsm.machine import Machine
    from r1pro_teleop.airport_fsm import geometry
    source,oldop,samples,_=setup(scene7,monkeypatch)
    source.scheduler.reservation_plan=rp.propose(source,oldop,samples)
    plan=source.scheduler.reservation_plan
    m=object.__new__(Machine);m.__dict__.update(vars(source));m.transition=lambda *a,**k:None
    m.r.record_strict_deviation=lambda *a:None
    op=Operation(plan['pending_tray'],plan['pending_slot'],np.array(plan['destination']),plan['yaw'])
    delta=op.destination-m.g.goals[op.slot];direction=delta/np.linalg.norm(delta)
    obs=copy.deepcopy(samples[-1]);obs['tray_pose'][op.tray]=[*op.destination,1,0,0,0]
    obs['tray_pose'][op.tray,:3]+=direction*.049
    assert np.linalg.norm(obs['tray_pose'][op.tray,:3]-op.destination)<.05
    monkeypatch.setattr(geometry,'slot_geometry_ready',lambda *a,**kw:True)
    def wait(*args):
        check=args[1];check(obs);return check(obs)
    m.r.wait=wait
    assert not m.verify_operation(op)


def test_checkpoint_invalid_save_does_not_write(scene7,monkeypatch,tmp_path):
    m,op,samples,_=setup(scene7,monkeypatch);plan=rp.propose(m,op,samples)
    a=tiny_machine(tmp_path,'invalid_save');a.g=m.g;a.scheduler.mapping=m.scheduler.mapping
    a.scheduler.reservation_plan=plan
    # A strict runtime must never save a completion-only reservation.
    try:
        a.r.cfg.acceptance_profile='strict'
        tree=CheckpointTree(a,tmp_path/'bad_cp');tree.plan(['ready'])
        with pytest.raises(ValueError,match='enabled completion'):
            tree.save('ready',lambda _:True)
        assert not (tmp_path/'bad_cp'/'ready').exists()
    finally:a.log.close()


def test_physical_preview_clone_copies_reservation_without_sharing(machine,tmp_path):
    from r1pro_teleop.airport_fsm import physical_preview as pp
    s=machine.scheduler;g=machine.g;s.mapping=[0,1,2]
    pose=machine.r.observation()['tray_pose']
    plan=dict(version=1,nominal_goals_sha256=rp.goal_hash(g),mapping=s.mapping,
        pending_tray=2,pending_slot=2,destination=g.goals[2].tolist(),yaw=float(g.goal_yaw[2]),
        protected_trays=[0,1],protected_pose=pose.tolist(),source_frame=0,candidate_index=0)
    s.reservation_plan=plan
    probe=pp.clone_machine(machine,tmp_path/'reservation_clone')
    try:
        assert probe.scheduler.reservation_plan==plan
        probe.scheduler.reservation_plan['destination'][0]+=.01
        assert s.reservation_plan['destination'][0]==g.goals[2,0]
    finally:probe.log.close();probe.r.close()


@pytest.mark.parametrize('operations',[0,1])
def test_both_actual_completion_paths_clear_reservation(operations):
    from r1pro_teleop.airport_fsm.machine import Machine
    m=object.__new__(Machine);m.c=Config(consistent_placement=True)
    m.operations=operations;m.scheduler=NS(reservation_plan={'test':'accepted_plan'},choose=lambda _:None)
    events=[];ticks=[]
    m.log=NS(event=lambda name,**kw:events.append((name,kw)))
    m.r=NS(wait=lambda *a:None,observation=lambda:{'min_z':np.ones(3)},
           joints=lambda *a,**k:None,tucked=np.zeros(16),tick=lambda:ticks.append(True))
    m.transition=lambda *a,**kw:None;m._poses=lambda:None
    m._record_completion_slot_deviations=lambda *a:None
    m._profile_final_acceptance=lambda:(True,{'actual_nominal_acceptance':True})
    assert m.run()=={'actual_nominal_acceptance':True}
    assert m.scheduler.reservation_plan is None and ticks==[True]
    assert [name for name,_ in events].count('adaptive_reservation_completed')==1
