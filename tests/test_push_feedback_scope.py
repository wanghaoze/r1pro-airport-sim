from types import SimpleNamespace
import numpy as np
import pytest
from r1pro_teleop.airport_fsm.contracts import Config
from r1pro_teleop.airport_fsm.geometry import Operation
from r1pro_teleop.airport_fsm import primitives, yaw_feedback


@pytest.mark.parametrize('scope,separation,slot,temporary,enabled,expected', [
    ('all',True,-1,True,True,True),
    ('all',False,-1,True,True,True),
    ('all',False,1,False,True,True),
    ('placement',True,1,False,True,False),
    ('placement',True,-1,True,True,False),
    ('placement',False,-1,True,True,False),
    ('placement',False,1,True,True,False),
    ('placement',False,-1,False,True,False),
    ('placement',False,1,False,True,True),
    ('placement',False,1,False,False,False),
])
def test_explicit_operation_scope_dispatches_unchanged_reference_and_validation(
        monkeypatch,scope,separation,slot,temporary,enabled,expected):
    cfg=Config(fixed_primitives=True,push_yaw_feedback_enabled=enabled,push_yaw_feedback_scope=scope)
    # Deliberately misleading phase: policy must use operation/separation only.
    runtime=SimpleNamespace(cfg=cfg,phase='separation' if not separation else 'place',
        sim=SimpleNamespace(target=np.zeros(16)))
    shadow_calls=[]
    def shadow(target):
        shadow_calls.append(target)
        return SimpleNamespace(site=lambda name:SimpleNamespace(xpos=np.array([0.,0.,.9])))
    runtime._shadow=shadow
    events=[];calls=[];normal_calls=[]
    machine=SimpleNamespace(r=runtime,c=cfg,log=SimpleNamespace(event=lambda name,**kw:events.append((name,kw))))
    operation=Operation(0,slot,np.array([.85,.38,.8]),0.,temporary)
    planned=(object(),55);position=np.zeros(3);rotation=np.eye(3);relation=np.eye(4);free_goal=object()
    rejection={'reason':'supported_normal_path'}
    def normal(*args):normal_calls.append(args);return rejection
    monkeypatch.setattr(primitives,'supported_normal_path_rejection',normal)
    monkeypatch.setattr(primitives,'execute',lambda r,p:calls.append(('original',r,p)) or 'original')
    def feedback(*args):
        assert args[:8]==(machine,planned,operation,'right',position,rotation,relation,free_goal)
        path=object();assert args[8](path) is rejection
        assert normal_calls[0]==(runtime,path,'right',.9,.895)
        calls.append(('feedback',));return 'feedback'
    monkeypatch.setattr(yaw_feedback,'execute_feedback',feedback)
    result=primitives._execute_push_reference(machine,planned,operation,'right',position,
        rotation,relation,free_goal,.895,separation=separation)
    assert result==('feedback' if expected else 'original')
    assert len(calls)==1 and bool(shadow_calls)==expected
    if not expected:assert calls[0][1] is runtime and calls[0][2] is planned
    if enabled:
        assert events[0][1]['enabled']==expected and events[0][1]['separation']==separation


def test_scope_default_compatible_and_validated():
    assert Config().push_yaw_feedback_scope=='all'
    Config(push_yaw_feedback_scope='placement').validate()
    for value in ('separation','PLACE','',None,True,3):
        with pytest.raises(ValueError,match='must be all or placement'):
            Config(push_yaw_feedback_scope=value).validate()
