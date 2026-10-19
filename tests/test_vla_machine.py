from types import SimpleNamespace
from dataclasses import replace
import numpy as np
import pytest
from r1pro_teleop.airport_fsm.contracts import Config,State
from r1pro_teleop.airport_fsm.geometry import Operation
from r1pro_teleop.vla.machine import VLAMachine,stable_evaluation


def test_policy_failure_keeps_explicit_code_when_machine_finishes(monkeypatch,tmp_path):
    from r1pro_teleop.airport_fsm.machine import Machine
    from r1pro_teleop.airport_fsm.contracts import Fault
    from r1pro_teleop.vla.policy import PolicyError
    def finish(self,success,acceptance,error):
        assert isinstance(error,Fault) and not error.recoverable
        return {'failure_code':error.code}
    monkeypatch.setattr(Machine,'finish',finish)
    machine=VLAMachine.__new__(VLAMachine)
    machine.c=replace(Config(),motion_backend='pi05',vla_checkpoint_id='test')
    machine.directory=tmp_path
    result=machine.finish(False,error=PolicyError('vla_action_outside_joint_limits'))
    assert result['failure_code']=='vla_action_outside_joint_limits'


def test_pi05_requires_explicit_checkpoint_and_bounded_chunks():
    with pytest.raises(ValueError,match='boolean'):
        replace(Config(),vla_servo_projection_enabled=1).validate()
    with pytest.raises(ValueError,match='checkpoint'):
        replace(Config(),motion_backend='pi05').validate()
    replace(Config(),motion_backend='pi05',vla_checkpoint_id='sha256:test').validate()
    with pytest.raises(ValueError,match='chunk'):
        replace(Config(),vla_action_horizon=3,vla_execute_steps=5).validate()


def test_stability_counts_distinct_actual_intervals_not_repeated_queries():
    r=SimpleNamespace(steps=0,ready=True)
    pred=stable_evaluation(lambda r,op:r.ready,2)
    assert not pred(r,None)
    assert not pred(r,None)
    r.steps=1
    assert pred(r,None)
    r.steps=2;r.ready=False
    assert not pred(r,None)


def test_navigation_waits_for_actual_slow_base_and_declared_alternate_heading():
    m=VLAMachine.__new__(VLAMachine);m._inward_yaw=lambda point:0.
    r=SimpleNamespace(cfg=replace(Config(),alternate_rim_enabled=True),
        sim=SimpleNamespace(base_state=lambda:np.array([.5,0.,np.pi/2])),
        observation=lambda:{'tray_pose':np.array([[1.,0.,.8,1.,0.,0.,0.]])},
        d=SimpleNamespace(qvel=np.array([.2,0.,0.])),base_dofs=np.arange(3))
    op=SimpleNamespace(tray=0)
    assert not m._navigation_ready(r,op)
    r.d.qvel[:]=0.
    assert m._navigation_ready(r,op)
    r.cfg=replace(r.cfg,alternate_rim_enabled=False)
    assert not m._navigation_ready(r,op)


def test_dag_learned_motion_calls_no_teacher_or_inverse_solver():
    m=VLAMachine.__new__(VLAMachine)
    cfg=replace(Config(),motion_backend='pi05',vla_checkpoint_id='sha256:test')
    op=Operation(0,0,np.array([1.,0.,.8]),0.)
    e={'tray_pose':np.array([[1.,0.,.8,1.,0.,0.,0.]]),'min_z':np.array([.8]),
       'table_contact':np.array([1]),'gripper_contact_force':np.array([[0.,0.]])}
    r=SimpleNamespace(cfg=cfg,steps=0,id_calls=0,holding=None,grasp_rel=None,retained_contact=None)
    r.d=SimpleNamespace(qvel=np.zeros(3));r.base_dofs=np.arange(3)
    def banned(*args,**kwargs):raise AssertionError('teacher/IK/inverse motion invoked')
    for name in ['joints','cartesian','object_motion','solve_pair','drive','audit_dynamics']:
        setattr(r,name,banned)
    r.observation=lambda:e
    r.wait=lambda seconds:setattr(r,'steps',r.steps+int(seconds*20))
    r.tick=lambda:setattr(r,'steps',r.steps+1)
    r.sim=SimpleNamespace(base_state=lambda:np.array([.5,0.,0.]),state=lambda:np.array([0.]*7+[.1]+[0.]*7+[.1]))
    r.tucked=r.sim.state().copy()
    r.remember_grasp=lambda tray:setattr(r,'holding',tray)
    m.r=r;m.c=cfg;m.operations=0;m.verified_final_trays=set()
    m.g=SimpleNamespace(ids=['tray0'],spec={'slots':[{'slot_id':'slot0'}]},
        push_possible=lambda *args,**kwargs:False,period=np.pi)
    m._inward_yaw=lambda point:0.
    m._operation_geometry_ready=lambda op:True
    m.scheduler=SimpleNamespace(mapping=[0],choose=lambda pose:op)
    events=[]
    m.log=SimpleNamespace(event=lambda kind,**details:events.append((kind,details)))
    m.transition=lambda state,phase,**kw:setattr(r,'fsm_state',state)
    m._profile_final_acceptance=lambda:(True,{'reasons':[]})
    skills=[]
    def execute(operation,prompt,predicate):
        skills.append(m.current_skill)
        if m.current_skill=='grasp_lift_tray':
            e['min_z'][0]=1.;e['gripper_contact_force'][0]=[1.,1.]
        if m.current_skill=='place_release_tray':e['gripper_contact_force'][0]=[0.,0.]
        for _ in range(21):
            r.tick()
            if predicate(r,operation):return True
        raise AssertionError('predicate failed')
    m.executor=SimpleNamespace(execute_operation=execute)
    m.prepare_pick=m.grasp=m.carry_place=m.push=m.recover=banned
    assert m.run()=={'reasons':[]}
    assert skills==['initialize_posture','navigate_to_tray','grasp_lift_tray','carry_tray','place_release_tray']
    assert r.id_calls==0
    assert any(kind=='operation_selected' for kind,_ in events)
    assert r.fsm_state==State.TASK_COMPLETE
