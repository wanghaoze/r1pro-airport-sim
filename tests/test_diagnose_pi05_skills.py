from pathlib import Path
from types import SimpleNamespace
import importlib.util,json,hashlib
import numpy as np
import pytest

def module():
    path=Path(__file__).resolve().parents[1]/'scripts/diagnose_pi05_skills.py'
    spec=importlib.util.spec_from_file_location('skill_diagnostic',path);mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod);return mod

def test_initial_snapshot_restores_integration_once_without_future_teacher_actions():
    mod=module();calls=[]
    d=SimpleNamespace(qpos=np.zeros(2),qvel=np.zeros(2),ctrl=np.zeros(1),act=np.zeros(1),qacc_warmstart=np.zeros(2),time=0.)
    def restore(m,data,state,spec):
        calls.append(state.copy());data.qpos[:]=state[:2];data.qvel[:]=state[2:4];data.ctrl[:]=state[4:5];data.act[:]=state[5:6];data.time=state[6]
    r=SimpleNamespace(integration_size=7,integration_spec=123,m=None,d=d,sim=SimpleNamespace(target=None,base_target=None),
        mj=SimpleNamespace(mj_setState=restore,mj_forward=lambda *_:None))
    snapshot=dict(integration_state=np.array([1.,2.,3.,4.,5.,6.,7.]),qpos=np.array([1.,2.]),qvel=np.array([3.,4.]),
        ctrl=np.array([5.]),act=np.array([6.]),qacc_warmstart=np.array([8.,9.]),time=7.,joint_target=np.zeros(16),base_target=np.zeros(3))
    mod.restore_initial_once(r,snapshot)
    assert len(calls)==1 and r.steps==0 and r.physics_clock_origin_time==7.
    np.testing.assert_array_equal(d.qacc_warmstart,[8.,9.]);np.testing.assert_array_equal(r.sim.target,np.zeros(16))
    # No setState can occur during subsequent commands: helper has no callback
    # or teacher execution hook, and owns no reference to learner ticks.
    assert not hasattr(r,'teacher')

@pytest.mark.parametrize('bad',['shape','finite','mismatch'])
def test_incomplete_or_unverifiable_snapshot_rejected(bad):
    mod=module();d=SimpleNamespace(qpos=np.zeros(1),qvel=np.zeros(1),ctrl=np.zeros(1),act=np.zeros(0),qacc_warmstart=np.zeros(1),time=0.)
    r=SimpleNamespace(integration_size=3,integration_spec=1,m=None,d=d,sim=SimpleNamespace(),mj=SimpleNamespace(mj_setState=lambda *_:None,mj_forward=lambda *_:None))
    value=np.zeros(3);snapshot=dict(integration_state=value,qpos=np.zeros(1),qvel=np.zeros(1),ctrl=np.zeros(1),act=np.zeros(0),qacc_warmstart=np.zeros(1),time=0.,joint_target=np.zeros(16),base_target=np.zeros(3))
    if bad=='shape':snapshot['integration_state']=np.zeros(2)
    if bad=='finite':snapshot['ctrl'][0]=np.nan
    if bad=='mismatch':snapshot['qpos'][0]=1.
    with pytest.raises(ValueError):mod.restore_initial_once(r,snapshot)

def test_source_identity_requires_actual_successful_expert_hash_and_preserves_split(tmp_path):
    mod=module();collection=tmp_path/'collection';sid='airport_0004_seed'
    trace=collection/'attempts'/sid/'a000/trace.h5';trace.parent.mkdir(parents=True);trace.write_bytes(b'recorded physics snapshot')
    (trace.parent/'result.json').write_text(json.dumps(dict(task_completed=True,controller_source='program_generated')))
    scene=collection/'scenes'/sid/'scene.json';scene.parent.mkdir(parents=True);scene.write_text(json.dumps(dict(scene_id=sid,split='train')))
    record=dict(source_trace=str(trace),source_trace_sha256=hashlib.sha256(trace.read_bytes()).hexdigest(),scene_id=sid,
        source_start_frame=40,skill='initialize_posture',split='train')
    assert mod.source_identity(record)[1]==collection
    record['split']='val'
    with pytest.raises(ValueError):mod.source_identity(record)
    record['split']='train';trace.write_bytes(b'changed')
    with pytest.raises(ValueError):mod.source_identity(record)

def test_unchanged_production_initial_guard_and_release_guard():
    mod=module();state=np.zeros(16);r=SimpleNamespace(tucked=np.zeros(16),sim=SimpleNamespace(state=lambda:state.copy()))
    machine=SimpleNamespace(r=r,_released=lambda r,op:False)
    predicate,frames=mod.skill_predicate(machine,'initialize_posture');assert frames==3 and predicate(r,None)
    state[7]=.0051;assert not predicate(r,None)
    predicate,frames=mod.skill_predicate(machine,'place_release_tray');assert frames==4 and not predicate(r,None)


def test_complete_vector_decodes_actual_activation_without_independent_act_dataset():
    mod=module()
    def data():return SimpleNamespace(qpos=np.zeros(2),qvel=np.zeros(2),ctrl=np.zeros(1),act=np.zeros(1),qacc_warmstart=np.zeros(2),time=0.)
    def set_state(m,d,state,spec):
        d.qpos[:]=state[:2];d.qvel[:]=state[2:4];d.ctrl[:]=state[4:5];d.act[:]=state[5:6];d.time=state[6]
    def get_state(m,d,state,spec):state[:]=np.concatenate((d.qpos,d.qvel,d.ctrl,d.act,[d.time]))
    r=SimpleNamespace(m=None,integration_size=7,integration_spec=123,sim=SimpleNamespace(target=np.zeros(16),base_target=np.zeros(3)),
        mj=SimpleNamespace(MjData=lambda m:data(),mj_setState=set_state,mj_getState=get_state,mj_forward=lambda *_:None))
    class Source(dict):attrs={'schema':'airport_fsm_raw/1'}
    source=Source(integration_state=np.array([[1.,2.,3.,4.,5.,6.,7.]]),qpos=np.array([[1.,2.]]),qvel=np.array([[3.,4.]]),
                  ctrl=np.array([[5.]]),qacc_warmstart=np.array([[8.,9.]]),sim_time=np.array([7.]))
    assert 'act' not in source
    snapshot=mod.decode_full_vector(r,source,dict(integration_state_spec=123),0)
    np.testing.assert_array_equal(snapshot['act'],[6.]);np.testing.assert_array_equal(snapshot['ctrl'],[5.])
    with pytest.raises(ValueError,match='spec mismatch'):
        mod.decode_full_vector(r,source,dict(integration_state_spec=124),0)


def test_isolated_skill_production_states_are_preserved():
    mod=module()
    expected=['SEARCH_TARGET','ALIGN_BASE','ADJUST_TRAY','GRASP_TRAY','TRANSPORT_TRAY','PLACE_TRAY']
    assert [mod.skill_state(skill).value for skill in mod.SKILLS]==expected
