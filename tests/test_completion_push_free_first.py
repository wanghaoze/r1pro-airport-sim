from types import SimpleNamespace

import numpy as np

from r1pro_teleop.airport_fsm.geometry import rectangle
from r1pro_teleop.airport_fsm.primitives import (
    completion_free_first_goal,completion_free_first_path_rejection)


def fixture(enabled=True):
    events=[]
    runtime=SimpleNamespace(cfg=SimpleNamespace(
        acceptance_profile='completion_first',completion_push_free_first_enabled=enabled),
        trace=SimpleNamespace(event=lambda name,**kw:events.append((name,kw))))
    machine=SimpleNamespace(r=runtime,g=SimpleNamespace(sizes=np.array([[.36,.30,.04]]),period=2*np.pi))
    operation=SimpleNamespace(tray=0,destination=np.array([.85,-.55,.8]),yaw=0.)
    pose=np.array([.85,-.40,.8,1.,0.,0.,0.])
    return machine,operation,pose,events


def test_proposal_clears_both_swept_end_footprints_without_mutating_tcp():
    machine,operation,pose,events=fixture()
    tcp=np.array([.85,-.62,.9]);before=tcp.copy()
    goal=completion_free_first_goal(machine,operation,tcp,tray_pose=pose)
    np.testing.assert_array_equal(tcp,before)
    assert goal is not None
    assert goal[1]<tcp[1] and goal[2]==tcp[2]+.1
    outward=np.array([0.,-1.])
    corners=np.vstack((rectangle(pose[:3],0.,machine.g.sizes[0]),
        rectangle(operation.destination,0.,machine.g.sizes[0])))
    assert goal[:2]@outward>=np.max(corners@outward)+.065-1e-12
    assert events[0][1]['qualification'].startswith('geometry_only')


def test_default_off_and_excessive_retreat_preserve_old_path_choice():
    machine,operation,pose,events=fixture(enabled=False)
    assert completion_free_first_goal(machine,operation,np.array([.85,-.58,.9]),tray_pose=pose) is None
    assert not events
    machine.r.cfg.completion_push_free_first_enabled=True
    operation.destination[1]=-1.0
    assert completion_free_first_goal(machine,operation,np.array([.85,-.58,.9]),tray_pose=pose) is None
    assert events[-1][1]['reason']=='retreat_exceeds_18cm_bound'


def test_free_first_branch_uses_existing_full_path_validator_before_execution():
    import inspect
    from r1pro_teleop.airport_fsm.primitives import push
    source=inspect.getsource(push)
    assert source.index('completion_free_first_goal(')<source.index('r.cartesian(goals,wrist=True,preview_only=True')
    assert source.index('free_points=r.cartesian(')<source.index('planned=plan_withdraw_path(')
    assert source.index('planned=plan_withdraw_path(')<source.index('_execute_push_reference(')
    assert 'if not free_first:' in source
    assert 'allow_shortcut=not (withdraw_free or free_first)' in source


def test_swept_path_rejects_finger_recontact_after_retained_motion():
    machine,operation,pose,_=fixture()
    class Model:
        ngeom=2
        geom_group=np.array([3,3])
        geom_bodyid=np.array([0,1])
        geom_size=np.array([[.03,.005,.02],[.03,.005,.02]])
        def body(self,index):
            return SimpleNamespace(name=f'right_gripper_finger_link{index+1}')
    machine.r.m=Model()
    class Path:
        duration=3.
        def evaluate(self,u,duration):return np.array([u]),None,None,None
    class Shadow:
        def __init__(self,u,free_y):
            self.positions={'left_tcp':np.array([.85+.02*u,-.2,.9]),
                'right_tcp':np.array([.85,free_y,.9])}
            self.geom_xpos=np.array([[.85,free_y,.9],[.85,free_y,.9]])
            self.geom_xmat=np.tile(np.eye(3).reshape(1,9),(2,1))
        def site(self,name):return SimpleNamespace(xpos=self.positions[name])
    free_tcp=np.array([.85,-.62,.9])
    machine.r._shadow=lambda q:Shadow(float(q[0]),-.69)
    rejected=completion_free_first_path_rejection(machine,Path(),operation,'right','left',pose,free_tcp)
    assert rejected['reason']=='completion_free_first_sweep_clearance'
    machine.r._shadow=lambda q:Shadow(float(q[0]),-.81)
    assert completion_free_first_path_rejection(machine,Path(),operation,'right','left',pose,free_tcp) is None
