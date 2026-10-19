import pytest
from r1pro_teleop.vla.native_reference_router import merge_verified_reference_fields,decode_linux_wait_status,verify_native_replay_errors

def fixture():return dict(trace_sha256='trace',camera='head_left',path='/old/video',sha256='v',source_manifest='/old/manifest',source_manifest_sha256='m',frames=10)

def test_router_retains_original_details_without_mutating_or_reencoding():
    old=dict(fixture(),encoded_metadata={'frames':10,'width':1920},bytes=1000)
    routed=merge_verified_reference_fields([fixture()],[old])
    assert routed==[old] and 'encoded_metadata' not in fixture()
    routed[0]['encoded_metadata']['frames']=9
    assert old['encoded_metadata']['frames']==10

def test_router_rejects_source_changes_and_removal():
    old=fixture();changed=dict(old,sha256='new')
    with pytest.raises(ValueError,match='identity_changed'):merge_verified_reference_fields([changed],[old])
    with pytest.raises(ValueError,match='removed'):merge_verified_reference_fields([],[old])
    with pytest.raises(ValueError,match='duplicate'):merge_verified_reference_fields([old,old],[old])

def test_zombie_exit_status_is_real_exit_or_signal():
    assert decode_linux_wait_status(0)==0
    assert decode_linux_wait_status(256)==1
    assert decode_linux_wait_status(15)==-15
    with pytest.raises(ValueError):decode_linux_wait_status(True)

def test_replay_gate_preserves_original_velocity_and_time_limits():
    m={key:dict(qpos=1e-4,qvel=5e-4,time=1e-8) for key in ('prefix_errors','terminal_errors')}
    assert verify_native_replay_errors(m,1e-4)
    m['prefix_errors']['time']=1e-7
    with pytest.raises(ValueError,match='time'):verify_native_replay_errors(m,1e-4)
    with pytest.raises(ValueError,match='tolerance'):verify_native_replay_errors(m,True)
