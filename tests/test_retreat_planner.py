from types import SimpleNamespace
import numpy as np
import pytest
from r1pro_teleop.airport_fsm.contracts import Config,minimum_duration
from r1pro_teleop.airport_fsm.retreat_planner import tuck_minimum_seconds


def fixture():
    events=[]
    r=SimpleNamespace(holding=None,retained_contact=None,cfg=Config(),
        observation=lambda:{'gripper_contact_force':np.zeros((3,2))},
        tucked=np.ones(16)*.6,sim=SimpleNamespace(state=lambda:np.zeros(16)),
        v=np.ones(16),a=np.ones(16)*2,j=np.ones(16)*20,
        trace=SimpleNamespace(event=lambda name,**kw:events.append((name,kw))))
    return r,events


def test_opt_in_changes_only_unloaded_final_tuck_timing():
    r,events=fixture()
    assert tuck_minimum_seconds(r,1.)==.3 and not events
    result=tuck_minimum_seconds(r,.5)
    assert result==minimum_duration(r.tucked,r.v*.5,r.a*.5,r.j*.5,.3)
    assert events[0][1]['counted_in_episode']


@pytest.mark.parametrize('mode',['held','retained','measured_contact'])
def test_loaded_motion_cannot_use_free_tuck_branch(mode):
    r,events=fixture()
    if mode=='held':r.holding=0
    elif mode=='retained':r.retained_contact=(0,'left')
    else:r.observation=lambda:{'gripper_contact_force':np.ones((3,2))}
    assert tuck_minimum_seconds(r,.5)==.3 and not events


@pytest.mark.parametrize('value',[True,0,.24,1.01,float('nan'),'0.5'])
def test_invalid_tuck_scale_rejected(value):
    with pytest.raises(ValueError):Config(retreat_joint_speed_scale=value).validate()
