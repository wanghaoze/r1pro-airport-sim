import json
import numpy as np
import pytest

from r1pro_teleop.real2sim.policy_start_diagnostic import prepared_pick_start, validate_prepared_start, sha, policy_base_reference, initial_commands
from r1pro_teleop.real2sim.robot_action_filter import load_limits


def fixture(tmp_path):
    room=tmp_path/'room';room.mkdir()
    case=dict(seed=1,parent_scene_id='scene',parent_split='train',initial_base_world=[.3,0,0],tray_pose=[.8,0,.8,1,0,0,0])
    state=np.zeros((62,19));state[:,[3,11]]=-1.;state[:,[7,15]]=.0800001
    state[:,16:]=[.2,.1,.03]
    state[0,16:]=[.19,.11,.02]
    np.savez(room/'native_trace.npz',state=state,tray_pose=np.tile(case['tray_pose'],(62,1,1)))
    (room/'result.json').write_text(json.dumps(dict(passed=True,case=case)))
    (room/'initial_base_station.json').write_text(json.dumps(dict(original_drive_origin=[.1,-.1,.02])))
    receipt=tmp_path/'exit.json';receipt.write_text(json.dumps(dict(returncode=0,actual_child_wait=True)))
    row=dict(source_room=str(room),prompt='Pick up the tray',source_trace_sha256=sha(room/'native_trace.npz'),
        source_result_sha256=sha(room/'result.json'),source_frame_interval=[1,61],frames=60,actual_engine_exit_receipt=str(receipt))
    manifest=tmp_path/'manifest.json';manifest.write_text(json.dumps(dict(schema='parallel_pickplace_frozen_training/1',ready=True,pairs=[dict(segments=[row])])))
    return manifest,room,case


def test_frozen_pose_bounded_initialization_and_diagnostic_scope(tmp_path):
    manifest,room,case=fixture(tmp_path)
    out=prepared_pick_start(manifest,room,case,load_limits())
    state,tray,base=validate_prepared_start(out,load_limits())
    assert np.all(state[[7,15]]<=.08)
    assert np.allclose(base,[.3,0,.05])
    assert out['original_state'][7]>.08 and out['initialization_bound_delta'][7]<0
    assert not out['online_teacher'] and not out['full_task_success_eligible']
    assert out['velocity_initialization']=='zero_not_recorded_source_velocity'


@pytest.mark.parametrize('mutation',['case','trace','source','receipt'])
def test_rejects_wrong_case_mutated_source_or_unclosed_exit(tmp_path,mutation):
    manifest,room,case=fixture(tmp_path)
    if mutation=='case':case['seed']=2
    elif mutation=='trace':(room/'native_trace.npz').write_bytes(b'changed')
    elif mutation=='source':room=tmp_path/'different'
    else:(tmp_path/'exit.json').write_text(json.dumps(dict(returncode=1,actual_child_wait=True)))
    with pytest.raises(ValueError):prepared_pick_start(manifest,room,case,load_limits())


@pytest.mark.parametrize('mutation',['nan','limit','quaternion','success'])
def test_runtime_rejects_invalid_initialization(tmp_path,mutation):
    manifest,room,case=fixture(tmp_path);out=prepared_pick_start(manifest,room,case,load_limits())
    if mutation=='nan':out['state16'][0]=float('nan')
    elif mutation=='limit':out['state16'][3]=-2.0944
    elif mutation=='quaternion':out['tray_pose'][3]=2
    else:out['full_task_success_eligible']=True
    with pytest.raises(ValueError):validate_prepared_start(out,load_limits())


def test_prepared_base_input_matches_cached_source_and_retains_later_drift(tmp_path):
    manifest,room,case=fixture(tmp_path);limits=load_limits()
    start=prepared_pick_start(manifest,room,case,limits)
    with np.load(room/'native_trace.npz') as source:
        expected=source['state'][1,16:].astype(np.float32)-source['state'][0,16:].astype(np.float32)
    measured=np.r_[start['state16'],[.7,-.3,.8]]
    reference=policy_base_reference(measured,start,limits)
    np.testing.assert_allclose(measured[16:]-reference,expected,rtol=0,atol=1e-15)
    assert np.linalg.norm(expected)>0  # Regression: prepared observation was zeroed.
    later=measured.copy();later[16:]+=[.001,-.002,.003]
    np.testing.assert_allclose(later[16:]-reference,expected+[.001,-.002,.003],rtol=0,atol=1e-15)
    np.testing.assert_array_equal(policy_base_reference(measured,None,limits),measured[16:])


@pytest.mark.parametrize('mutation',['offset','nan','old_schema'])
def test_rejects_inconsistent_source_base_contract(tmp_path,mutation):
    manifest,room,case=fixture(tmp_path);limits=load_limits()
    start=prepared_pick_start(manifest,room,case,limits)
    if mutation=='offset':start['policy_initial_base_state'][0]+=.1
    elif mutation=='nan':start['source_initial_base_state'][0]=float('nan')
    else:start['schema']='prepared_pick_pose_diagnostic/1'
    with pytest.raises(ValueError):policy_base_reference(np.array(start['original_state']),start,limits)


def test_prepared_grippers_hold_measurement_without_changing_normal_initialization():
    states=np.zeros((2,19));states[:,[7,15]]=[.031,.057]
    states[:,16:]=[.2,-.3,.1];saved=states.copy()
    commands=initial_commands(states,{1})
    np.testing.assert_array_equal(commands[1],states[1])
    np.testing.assert_array_equal(commands[0,[7,15]],[.08,.08])
    np.testing.assert_array_equal(commands[:,16:],states[:,16:])
    np.testing.assert_array_equal(states,saved)
    with pytest.raises(ValueError):initial_commands(states,{2})
