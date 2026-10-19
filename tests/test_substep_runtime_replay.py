"""Real airport physics/Trace/Replay integration without GPU image rendering.

Only the Replay Runtime constructor's render flag/model path is adapted to the
fixture. Production Replay initialization, schema checks and iteration execute.
"""
import json
from pathlib import Path
import h5py
import numpy as np
import pytest
from r1pro_teleop.airport_fsm.contracts import Config, Fault, sha256_file
from r1pro_teleop.airport_fsm.runtime import Runtime
from r1pro_teleop.airport_fsm.trace import Trace
from r1pro_teleop.airport_fsm.exporter import Replay
from r1pro_teleop.airport_fsm.substep_control import sample_path_targets
from r1pro_teleop.airport_fsm.trajectory import BlendedJointPath


@pytest.fixture
def airport(tmp_path):
    import mujoco
    from r1pro_teleop.airport_mobile import make_mobile_scene
    base=Path('resources/scenes')
    scope=base/'server_v7' if (base/'server_v7').exists() else base/'formal'
    scenes=sorted(scope.rglob('scene.json'))
    scene=next((p for p in scenes if p.parent.name.startswith('airport_0004_')),scenes[0])
    spec=json.loads(scene.read_text());source=scene.parent/spec.get('scene_file','scene.xml')
    model=mujoco.MjModel.from_xml_path(str(source))
    if mujoco.mj_name2id(model,mujoco.mjtObj.mjOBJ_JOINT,'agent_base_x')<0:
        xml=tmp_path/'mobile.xml';make_mobile_scene(source,xml)
    else:xml=source
    opened=[]
    def create(enabled=True):
        r=Runtime(spec,xml,Config(substep_control_enabled=enabled),render=False)
        opened.append(r)
        return r
    yield create,spec,xml
    for r in opened:r.close()


def state(r):
    result=np.empty(r.integration_size)
    r.mj.mj_getState(r.m,r.d,result,r.integration_spec)
    return result


def trace_for(r,tmp_path):
    r.trace=Trace(tmp_path/'attempt',{
        'config':r.cfg.dump(),'scene_xml_sha256':sha256_file(r.sim.scene),
        'limits':r.limits,'substeps_per_frame':r.sim.nstep,
        'physics_timestep_s':float(r.m.opt.timestep)})
    return r.trace


def close_trace(r):
    path=r.trace.directory/'trace.h5'
    r.trace.close({'qpos':r.d.qpos,'qvel':r.d.qvel,'time':float(r.d.time)})
    return path


def headless_replay(monkeypatch,tmp_path,r,spec,xml,path,*,diagnostic=False):
    from r1pro_teleop.airport_fsm import exporter,runtime as runtime_module
    root=tmp_path/'collection';folder=root/'scenes'/spec['scene_id']
    folder.mkdir(parents=True)
    (folder/'scene.json').write_text(json.dumps(spec))
    monkeypatch.setattr(exporter,'config_for',lambda root:r.cfg)
    original=Runtime
    # Use the identical actual XML and limits; do not fake physics or evidence.
    monkeypatch.setattr(runtime_module,'Runtime',
        lambda spec,requested_xml,cfg,render:original(spec,xml,cfg,render=False))
    replay=Replay(root,{'scene_id':spec['scene_id'],'trace':str(path)},diagnostic=diagnostic)
    replay.shapes={} # this test exercises physics replay, not a native RGB export
    return replay


def test_airport_raw2_substeps_and_constant_wait_replay_exactly(airport,tmp_path,monkeypatch):
    create,spec,xml=airport;r=create();trace_for(r,tmp_path)
    start=r.sim.target.copy();end=start.copy();end[6]+=.001
    path=BlendedJointPath([start,end],r.v,r.a,r.j,minimum_seconds=.15)
    states=[];calls=[];original_guard=r.guard
    def guard():calls.append(float(r.d.time));return original_guard()
    monkeypatch.setattr(r,'guard',guard)
    for i in range(3):
        targets=sample_path_targets(path,i,3,r.sim.nstep,r.cfg.fps)
        r.sim.target=targets[-1].copy();r.tick(substep_targets=targets);states.append(state(r))
    r.tick();states.append(state(r)) # raw2 also records constant hold intervals
    assert len(calls)==4*r.sim.nstep and r.steps==4
    filename=close_trace(r)
    with h5py.File(filename) as f:
        assert f.attrs['schema']=='airport_fsm_raw/2'
        assert f['ctrl_substeps'].dtype==np.float64
        assert f['ctrl_substeps'].shape==(4,r.sim.nstep,r.m.nu)
        np.testing.assert_array_equal(f['executed_substeps'][:],[25]*4)
        assert np.all(f['transition_completed'][:])
        np.testing.assert_array_equal(f['ctrl_substeps'][3],np.tile(f['ctrl_substeps'][3,0],(25,1)))
    with headless_replay(monkeypatch,tmp_path,r,spec,xml,filename) as replay:
        generator=iter(replay)
        for i in range(4):
            index,_=next(generator);assert index==i
            if i:np.testing.assert_array_equal(state(replay.runtime),states[i-1])
        with pytest.raises(StopIteration):next(generator)
        np.testing.assert_array_equal(state(replay.runtime),states[-1])


def test_airport_failed_third_guard_records_prefix_and_replays_terminal(airport,tmp_path,monkeypatch):
    create,spec,xml=airport;r=create();trace_for(r,tmp_path)
    start=r.sim.target.copy();end=start.copy();end[6]+=.001
    path=BlendedJointPath([start,end],r.v,r.a,r.j,minimum_seconds=.05)
    targets=sample_path_targets(path,0,1,r.sim.nstep,r.cfg.fps)
    r.sim.target=targets[-1].copy();count=[];original_guard=r.guard
    def fail_third():
        original_guard();count.append(1)
        if len(count)==3:raise Fault('test_guard_rejection')
    monkeypatch.setattr(r,'guard',fail_third)
    with pytest.raises(Fault,match='test_guard_rejection'):r.tick(substep_targets=targets)
    terminal=state(r);filename=close_trace(r)
    assert r.steps==0 and r.d.time==pytest.approx(.006)
    with h5py.File(filename) as f:
        assert int(f['executed_substeps'][0])==3
        assert not f['transition_completed'][0]
        assert np.all(f['ctrl_substeps'][0,3:]==0.)
    with headless_replay(monkeypatch,tmp_path,r,spec,xml,filename,diagnostic=True) as replay:
        assert len(list(replay))==1
        np.testing.assert_array_equal(state(replay.runtime),terminal)


def test_airport_legacy_raw1_keeps_hold_semantics_and_replay(airport,tmp_path,monkeypatch):
    create,spec,xml=airport;r=create(False);trace_for(r,tmp_path)
    r.sim.target[6]+=.0001;r.tick();terminal=state(r);filename=close_trace(r)
    with h5py.File(filename) as f:
        assert f.attrs['schema']=='airport_fsm_raw/1'
        assert 'ctrl_substeps' not in f and 'executed_substeps' not in f
        assert 'action held' in f.attrs['observation_semantics']
    with headless_replay(monkeypatch,tmp_path,r,spec,xml,filename) as replay:
        assert len(list(replay))==1
        np.testing.assert_array_equal(state(replay.runtime),terminal)


@pytest.mark.parametrize('invalid', ['shape','endpoint','nonfinite','disabled'])
def test_substep_invalid_request_never_advances_or_records_physics(airport,tmp_path,invalid):
    create,_,_=airport;r=create(invalid!='disabled');trace_for(r,tmp_path)
    targets=np.tile(r.sim.target,(r.sim.nstep,1)).astype(np.float32)
    if invalid=='shape':targets=targets[:-1]
    elif invalid=='endpoint':targets[-1,0]+=.01
    elif invalid=='nonfinite':targets[0,0]=np.nan
    before=state(r)
    with pytest.raises(Fault,match='invalid_substep_targets|substep_endpoint_mismatch|substep_control_not_enabled'):
        r.tick(substep_targets=targets)
    np.testing.assert_array_equal(state(r),before)
    assert r.steps==0 and r.trace.count==0
    close_trace(r)

def test_old_cfg_record_only_keeps_physics_and_control_identical(airport,tmp_path,monkeypatch):
 create,spec,xml=airport;plain=create(False);recorded=create(False);recorded.record_ctrl_substeps=True;trace_for(recorded,tmp_path)
 meta=json.loads(recorded.trace.file.attrs['metadata_json']);meta['recorded_substep_controls_without_interpolation']=True;recorded.trace.file.attrs['metadata_json']=json.dumps(meta);recorded.trace.file.attrs['schema']='airport_fsm_raw/2'
 assert not plain.cfg.substep_control_enabled and not recorded.cfg.substep_control_enabled
 for _ in range(3):
  plain.tick();recorded.tick();np.testing.assert_array_equal(state(plain),state(recorded));np.testing.assert_array_equal(plain.d.ctrl,recorded.d.ctrl)
 raw=close_trace(recorded)
 with h5py.File(raw) as f:
  assert f.attrs['schema']=='airport_fsm_raw/2' and len(f['ctrl_substeps'])==3
  assert np.all(f['executed_substeps'][:]==recorded.sim.nstep)
  assert json.loads(f.attrs['metadata_json'])['config']['substep_control_enabled'] is False
  assert np.all(f['ctrl_substeps'][:]==f['ctrl_substeps'][0,0])
 replay=headless_replay(monkeypatch,tmp_path,recorded,spec,xml,raw)
 list(replay);assert replay.errors==dict(qpos=0.,qvel=0.,time=0.,terminal_qpos=0.,terminal_qvel=0.,terminal_time=0.)
