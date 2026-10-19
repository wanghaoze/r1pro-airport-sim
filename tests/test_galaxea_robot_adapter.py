import numpy as np
import pytest
from r1pro_teleop.vla.galaxea_robot_adapter import observation, command


def test_units_and_side_mapping_no_base_commands():
    s=dict(left_arm=np.arange(7),right_arm=np.arange(7)+10,left_gripper=[80],right_gripper=[20])
    obs=dict(task='Pick up the tray',state=s,images={k:np.zeros((3,4,5),np.uint8) for k in ['head_rgb','left_wrist_rgb','right_wrist_rgb']})
    result=observation(obs,lambda x,h,w:x)
    assert result['state'][7]==pytest.approx(.08)
    a=command(result['state']);assert a['left_gripper'][0]==pytest.approx(80)
    assert a['right_gripper'][0]==pytest.approx(20)
    assert np.array_equal(a['right_arm'],s['right_arm'])
    assert set(a)=={'left_arm','right_arm','left_gripper','right_gripper'}


def test_invalid_values_and_untrained_flush_rejected():
    with pytest.raises(ValueError):command(np.full(19,np.nan))
    with pytest.raises(ValueError):command(np.zeros(18))
    with pytest.raises(ValueError):observation(dict(task='Flush tray to the left'),None)


def test_user_approved_saturation_not_rescaling_and_raw_preserved():
    row=np.arange(19,dtype=np.float32);row[7]=.100462387;row[15]=-.004
    before=row.copy();raw=command(row);submitted=command(row,[0,80])
    assert raw['left_gripper'][0]==pytest.approx(100.462387,abs=.00002)
    assert submitted['left_gripper'][0]==80 and submitted['right_gripper'][0]==0
    assert np.array_equal(row,before) and np.array_equal(submitted['left_arm'],row[:7])
    row[7]=.04
    assert command(row,[0,80])['left_gripper'][0]==pytest.approx(40)
