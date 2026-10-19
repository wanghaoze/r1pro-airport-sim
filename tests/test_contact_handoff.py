from types import SimpleNamespace
import numpy as np
import pytest
from r1pro_teleop.airport_fsm.runtime import Runtime
from r1pro_teleop.airport_fsm.machine import Machine
from r1pro_teleop.airport_fsm.contracts import Config,Fault


@pytest.mark.parametrize('side,col,index',[('left',7,0),('right',15,1)])
def test_retained_contact_requires_closed_command_support_and_real_force(side,col,index):
    r=Runtime.__new__(Runtime);r.cfg=Config();r.retained_contact=(0,side)
    r.sim=SimpleNamespace(target=np.zeros(16))
    e={'table_contact':np.ones(3),'gripper_contact_force':np.ones((3,2))*2}
    r.observation=lambda:e
    r.check_retained_contact()
    e['gripper_contact_force'][0,index]=0
    with pytest.raises(Fault,match='retained_contact_lost'):r.check_retained_contact()
    e['gripper_contact_force'][0,index]=2;e['table_contact'][0]=0
    with pytest.raises(Fault,match='retained_contact_lost'):r.check_retained_contact()
    e['table_contact'][0]=1;r.sim.target[col]=.1
    with pytest.raises(Fault,match='retained_contact_lost'):r.check_retained_contact()


@pytest.mark.parametrize('side,free',[('left','right'),('right','left')])
def test_joining_arm_alone_approaches_and_closes_before_lift(side,free):
    m=Machine.__new__(Machine);m.c=Config();calls=[]
    m.pending_grasp_contact={'tray':0,'side':side,'face':0.,'rim_x':0.}
    m._poses=lambda:np.array([[0,0,.8,1,0,0,0.]])
    m.transition=lambda *a,**k:None
    m.log=SimpleNamespace(event=lambda *a,**k:None)
    def remember(tray):raise RuntimeError('lift_stage_reached')
    r=SimpleNamespace(check_retained_contact=lambda:None,
        rim_goals=lambda *a,**k:{'left':(np.zeros(3),np.eye(3)),'right':(np.ones(3),np.eye(3))},
        cartesian=lambda goals,**k:None if k.get('preview_only') else calls.append(('move',tuple(goals))),
        close_grippers_on_contact=lambda opening,**k:calls.append(('close',k['sides'])),
        observation=lambda:{'gripper_contact_force':np.ones((1,2))*2},
        wait=lambda *a:True,remember_grasp=remember,retained_contact=(0,side))
    m.r=r
    with pytest.raises(RuntimeError,match='lift_stage_reached'):m.grasp(0,0.,0.)
    assert calls==[('move',(free,)),('close',(free,))]
    assert r.retained_contact is None and m.pending_grasp_contact is None


def test_support_microbounce_is_bounded_and_never_relabels_contact():
    r=Runtime.__new__(Runtime);r.cfg=Config();r.retained_contact=(0,'left')
    r.retained_support_missing_since=None;r.trace=None;r.d=SimpleNamespace(time=1.)
    r.sim=SimpleNamespace(target=np.zeros(16))
    r.g=SimpleNamespace(support_table=lambda p:'table',tables={'table':{'dimensions_m':[1,1,.8]}})
    e={'table_contact':np.zeros(1),'gripper_contact_force':np.ones((1,2)),
       'min_z':np.array([.8001]),'tray_pose':np.array([[0,0,.8,1,0,0,0]])}
    r.observation=lambda:e
    r.check_retained_contact();assert e['table_contact'][0]==0
    r.d.time=1.2
    with pytest.raises(Fault,match='retained_contact_lost'):r.check_retained_contact()
    r.d.time=1.01;e['min_z'][0]=.804
    with pytest.raises(Fault,match='retained_contact_lost'):r.check_retained_contact()


@pytest.mark.xfail(strict=True, reason='Known gap in validated handoff release: temporary buffer geometry shortcut remains experimental')
def test_accepted_temporary_buffer_does_not_trigger_unnecessary_push():
    from test_airport_fsm_unit import spec_fixture,poses
    from r1pro_teleop.airport_fsm.geometry import Geometry,Operation
    m=Machine.__new__(Machine);m.c=Config();m.g=Geometry(spec_fixture())
    p=poses(m.g);m._poses=lambda:p
    op=Operation(0,-1,p[0,:3].copy(),m.g.goal_yaw[0],True)
    assert m._operation_geometry_ready(op)
    op.destination=op.destination+np.array([.04,0,0])
    assert not m._operation_geometry_ready(op)


def test_complete_physics_gate_prevents_an_extra_scheduler_grasp(tmp_path):
    from dataclasses import replace
    from test_airport_fsm_unit import MockRuntime,FlowMachine
    r=MockRuntime(tmp_path,carry=True);r.cfg=replace(Config(),consistent_placement=True)
    m=FlowMachine(r,tmp_path/'raw');original=m.scheduler.choose;calls=[]
    def choose(pose):
        calls.append(1)
        if len(calls)>1:raise AssertionError('Completed task must not be scheduled again')
        return original(pose)
    m.scheduler.choose=choose
    report=m.run();result=m.finish(True,report)
    assert result['physics_success'] and m.operations==1 and len(calls)==1
