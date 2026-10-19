import numpy as np
import pytest
from r1pro_teleop.vla.real_sim_data import map_real,resample_indices,split_for,mixed_schedule,mse_groups


def columns():
    out={}
    for domain in ['observation.state','action']:
        out[domain+'.left_arm']=np.ones((3,7));out[domain+'.right_arm']=np.ones((3,7))*2
        out[domain+'.left_gripper']=np.array([80.,40.,0.]);out[domain+'.right_gripper']=np.array([60.,20.,0.])
    out['observation.state.chassis']=np.array([[2.,3.,.1],[2.,3.,.1],[2.,3.,.1]])
    out['action.chassis.velocities']=np.zeros((3,6));return out


def test_units_and_stationary_base_contract():
    state,action=map_real(columns(),'mm')
    assert state.shape==action.shape==(3,19)
    np.testing.assert_allclose(action[:,7],[.08,.04,0])
    np.testing.assert_allclose(state[:,15],[.06,.02,0])
    assert np.all(action[:,16:]==0) and np.all(state[:,16:]==0)
    with pytest.raises(ValueError):map_real(columns(),'unknown')
    c=columns();c['action.chassis.velocities'][0,0]=.1
    with pytest.raises(ValueError):map_real(c,'mm')
    measured=columns();measured['observation.state.left_gripper'][0]=102.7
    state,_=map_real(measured,'mm')
    assert state[0,7]==pytest.approx(.1027)


def test_resampling_and_recording_split_deterministic():
    ix=resample_indices(np.arange(31)/30)
    assert len(ix)==21 and ix[0]==0 and ix[-1]==30
    assert split_for('same-recording')==split_for('same-recording')
    with pytest.raises(ValueError):resample_indices([0,0,1])


def test_ten_percent_is_actual_draw_fraction_not_frame_fraction():
    domains,indices=mixed_schedule(np.array([0,0,1,1]),np.array([0,1,2]),steps=100,batch=8)
    assert domains.shape==(100,8) and np.count_nonzero(domains)==80
    assert indices[domains==0].max()<4 and indices[domains==1].max()<3
    again=mixed_schedule(np.array([0,0,1,1]),np.array([0,1,2]),steps=100,batch=8)
    np.testing.assert_array_equal(domains,again[0]);np.testing.assert_array_equal(indices,again[1])


def test_mse_units_and_base_and_tail_exclusion():
    target=np.zeros((2,19));prediction=target.copy();prediction[:,0]=1;prediction[:,7]=.002;prediction[:,16:]=100;prediction[1,:16]=99
    m=mse_groups(prediction,target,valid=[True,False])
    assert m['arm_mse_rad2']==pytest.approx(1/14)
    assert m['gripper_mse_mm2']==pytest.approx(2)
    assert m['base_excluded'] is True
