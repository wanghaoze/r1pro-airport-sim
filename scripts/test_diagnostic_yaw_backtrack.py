"""Bounded retry semantics for the private candidate, without physical tuning."""
from pathlib import Path
import runpy
import sys
import numpy as np
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from diagnostic_yaw_backtrack import execute_backtracking
fixture_runtime=runpy.run_path(str(Path(__file__).resolve().parents[1]/'tests/test_yaw_feedback.py'))['fixture_runtime']

@pytest.mark.parametrize('second_pass',[True,False])
def test_exactly_one_smaller_retry_after_normal_rejection(second_pass):
    m,path,op,_,events,commands,*_=fixture_runtime()
    calls=[]
    def normal(candidate):
        calls.append(candidate)
        return None if len(calls)==2 and second_pass else {'reason':'supported_normal_reference_excursion'}
    execute_backtracking(m,(path,55),op,'right',np.array([0,0,.8]),np.eye(3),np.eye(4),None,normal)
    attempts=[e for e in events if e['event']=='diagnostic_yaw_backtrack_attempt']
    assert len(attempts)==2 and [e['scale'] for e in attempts]==[1.,.75]
    np.testing.assert_allclose([e['command_yaw_correction_deg'] for e in attempts],[-1.5,-1.125])
    assert m.r.steps==55 and attempts[-1]['accepted']==second_pass
    if not second_pass:np.testing.assert_array_equal(commands,[path.evaluate(i/55,2.75)[0] for i in range(1,56)])

def test_other_rejection_does_not_start_amplitude_search():
    m,path,op,normal,events,commands,*_=fixture_runtime(reject='path')
    execute_backtracking(m,(path,55),op,'right',np.array([0,0,.8]),np.eye(3),np.eye(4),None,normal)
    assert len([e for e in events if e['event']=='diagnostic_yaw_backtrack_attempt'])==1
    np.testing.assert_array_equal(commands,[path.evaluate(i/55,2.75)[0] for i in range(1,56)])

@pytest.mark.parametrize('lower',[True,False])
def test_normal_endpoint_trial_only_after_lower_band_rejection(lower):
    m,path,op,_,events,commands,_,_,goals=fixture_runtime()
    calls=[]
    def normal(candidate):
        calls.append(candidate)
        if len(calls)>1:return None
        return dict(reason='supported_normal_reference_excursion',command_z_m=.7 if lower else .9,allowed_z_m=[.8,.85])
    execute_backtracking(m,(path,55),op,'right',np.array([0,0,.8]),np.eye(3),np.eye(4),None,normal,normal_endpoint_lift_m=.00005)
    attempts=[e for e in events if e['event']=='diagnostic_yaw_backtrack_attempt']
    assert len(attempts)==(2 if lower else 1)
    assert m.r.steps==55
    if lower:
        assert goals[1]['right'][0][2]-goals[0]['right'][0][2]==pytest.approx(.00005)
        np.testing.assert_array_equal(goals[1]['right'][0][:2],goals[0]['right'][0][:2])
        np.testing.assert_array_equal(goals[1]['right'][1],goals[0]['right'][1])
        assert attempts[1]['scale']==1. and attempts[1]['accepted']
