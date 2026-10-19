import copy
from pathlib import Path
from types import SimpleNamespace
import h5py
import numpy as np
import pytest
from r1pro_teleop.vla.teacher import SimulationExpert, TeacherError
from r1pro_teleop.vla.dagger import state_digest


class Config:
    def dump(self): return {"fps": 20, "simulation": True}


class MJ:
    def mj_getState(self, m, d, out, spec):
        out[:] = np.r_[d.qpos, d.qvel, d.ctrl, d.qacc_warmstart, d.time]
    def mj_setState(self, m, d, value, spec):
        d.qpos[:] = value[:2]; d.qvel[:] = value[2:4]; d.ctrl[:] = value[4:6]
        d.qacc_warmstart[:] = value[6:8]; d.time = value[8]
    def mj_forward(self, m, d): pass


class Runtime:
    def __init__(self, spec, xml, cfg):
        self.spec, self.cfg = spec, cfg
        self.m = SimpleNamespace(nq=2, nv=2, nu=2, opt=SimpleNamespace(timestep=.002), body_mass=np.array([2.]))
        self.d = SimpleNamespace(qpos=np.array([.2, .3]), qvel=np.array([.4, .5]), ctrl=np.array([.6, .7]),
                                 qacc_warmstart=np.array([.8, .9]), act=np.zeros(0), time=1.)
        self.sim = SimpleNamespace(scene=xml, target=np.zeros(16), base_target=np.zeros(3))
        self.mj = MJ(); self.integration_size = 9; self.integration_spec = 123
        self.holding = None; self.grasp_rel = None; self.retained_contact = None
        self.allowed_tray = 0; self.target_slot = 1; self.fsm_state = 'ALIGN'; self.phase = 'navigate'
        self.steps = 20; self.initial_bottom = np.array([.8, .8, .8]); self.closed = False
    def close(self): self.closed = True


class Log:
    def __init__(self, directory):
        self.directory = Path(directory); self.directory.mkdir(exist_ok=False)
        self.rows = None
    def arrays(self, include): return self.rows
    def close(self):
        path = self.directory / 'trace.h5'
        if path.exists(): return
        with h5py.File(path, 'w') as f:
            if self.rows:
                for key, value in self.rows.items(): f[key] = value


class Machine:
    def __init__(self, runtime, directory, **kwargs):
        self.r = runtime; self.log = Log(directory)
    def prepare_pick(self, tray, slot):
        qpos = self.r.d.qpos.copy(); qvel = self.r.d.qvel.copy()
        self.r.d.qpos[:] += 1
        self.log.rows = {'qpos': np.tile(qpos, (3, 1)), 'qvel': np.tile(qvel, (3, 1)),
                         'action': np.ones((3, 16)), 'base_action': np.ones((3, 3)),
                         'transition_completed': np.ones(3, bool)}
        return 0., 0.


def setup(tmp_path, factory=Runtime, machine_factory=Machine):
    xml = tmp_path / 'scene.xml'; xml.write_text('<mujoco/>')
    runtime = Runtime({'seed': 1, 'scene_id': 'scene1'}, xml, Config())
    expert = SimulationExpert(runtime, tmp_path / 'teacher', runtime_factory=factory, machine_factory=machine_factory)
    operation = SimpleNamespace(tray=0, slot=1)
    return runtime, expert, operation


def test_teacher_restores_private_state_and_preserves_live(tmp_path):
    runtime, expert, operation = setup(tmp_path)
    snapshot = expert.capture(); before = state_digest(snapshot)
    label = expert.label(operation, 'navigate_to_tray', snapshot, 2)
    assert label.actions.shape == (2, 19)
    assert label.start_state_sha256 == before
    assert state_digest(expert.capture()) == before
    assert SimulationExpert.verify_label(snapshot, label)
    label.actions[0, 0] += 1
    assert not SimulationExpert.verify_label(snapshot, label)


def test_stale_state_rejected(tmp_path):
    runtime, expert, operation = setup(tmp_path)
    snapshot = expert.capture(); runtime.d.qpos[0] += 1
    with pytest.raises(TeacherError, match='stale'):
        expert.label(operation, 'navigate_to_tray', snapshot, 2)


def test_changed_physics_rejected(tmp_path):
    def changed(spec, xml, cfg):
        runtime = Runtime(spec, xml, cfg); runtime.m.body_mass[:] = 100
        return runtime
    runtime, expert, operation = setup(tmp_path, factory=changed)
    with pytest.raises(TeacherError, match='physics_model'):
        expert.label(operation, 'navigate_to_tray', expert.capture(), 2)


def test_failed_expert_is_not_label(tmp_path):
    class Failed(Machine):
        def prepare_pick(self, tray, slot):
            super().prepare_pick(tray, slot)
            raise RuntimeError('physical_guard')
    runtime, expert, operation = setup(tmp_path, machine_factory=Failed)
    before = state_digest(expert.capture())
    with pytest.raises(RuntimeError, match='physical_guard'):
        expert.label(operation, 'navigate_to_tray', expert.capture(), 2)
    assert state_digest(expert.capture()) == before
    assert 'label_rejected' in (expert.directory / 'expert_000000/teacher_metadata.json').read_text()


def test_incomplete_intervals_rejected(tmp_path):
    class Incomplete(Machine):
        def prepare_pick(self, tray, slot):
            super().prepare_pick(tray, slot)
            self.log.rows['transition_completed'][1] = False
    runtime, expert, operation = setup(tmp_path, machine_factory=Incomplete)
    with pytest.raises(TeacherError, match='incomplete'):
        expert.label(operation, 'navigate_to_tray', expert.capture(), 2)


def test_unknown_skill_rejected(tmp_path):
    runtime, expert, operation = setup(tmp_path)
    with pytest.raises(TeacherError, match='unsupported_skill'):
        expert.label(operation, 'made_up', expert.capture(), 2)


def test_grasp_replans_alignment_without_teacher_context(tmp_path):
    class Grasp(Machine):
        def prepare_pick(self, tray, slot):
            super().prepare_pick(tray, slot)
            return .123, .045
        def grasp(self, tray, face, rim_x):
            assert (face, rim_x) == (.123, .045)
    runtime, expert, operation = setup(tmp_path, machine_factory=Grasp)
    label = expert.label(operation, 'grasp_lift_tray', expert.capture(), 2)
    assert SimulationExpert.verify_label(expert.capture(), label)


def test_carry_requires_real_grasp(tmp_path):
    runtime, expert, operation = setup(tmp_path)
    with pytest.raises(TeacherError, match='measured_grasp'):
        expert.label(operation, 'carry_tray', expert.capture(), 2)


def test_initialization_uses_private_physical_teacher_joints(tmp_path):
    class Initialize(Machine):
        def __init__(self, runtime, directory, **kwargs):
            super().__init__(runtime, directory, **kwargs)
            runtime.tucked = np.zeros(16)
            def joints(target, minimum_seconds):
                assert minimum_seconds == .5
                self.prepare_pick(0, 0)
            runtime.joints = joints
    runtime, expert, operation = setup(tmp_path, machine_factory=Initialize)
    label = expert.label(operation, 'initialize_posture', expert.capture(), 2)
    assert SimulationExpert.verify_label(expert.capture(), label)


class ShortInitialize(Machine):
    def __init__(self, runtime, directory, **kwargs):
        super().__init__(runtime, directory, **kwargs)
        runtime.tucked = np.zeros(16)
        def joints(target, minimum_seconds):
            self.prepare_pick(0, 0)
            runtime.sim.target = np.asarray(target).copy()
        runtime.joints = joints
        def tick():
            row = {'qpos': runtime.d.qpos.copy(), 'qvel': runtime.d.qvel.copy(),
                   'action': runtime.sim.target.copy(), 'base_action': runtime.sim.base_target.copy(),
                   'transition_completed': True}
            for key, value in row.items():
                self.log.rows[key] = np.concatenate((self.log.rows[key], np.asarray(value)[None]), axis=0)
            runtime.d.time += .05
            runtime.d.qpos += .01
            runtime.steps += 1
        runtime.tick = tick


def test_short_initialization_records_real_terminal_physics_without_live_mutation(tmp_path):
    import json
    runtime, expert, operation = setup(tmp_path, machine_factory=ShortInitialize)
    snapshot = expert.capture(); before = state_digest(snapshot)
    label = expert.label(operation, 'initialize_posture', snapshot, 5)
    assert label.actions.shape == (5, 19)
    assert state_digest(expert.capture()) == before
    metadata = json.loads((Path(label.teacher_artifact).parent / 'teacher_metadata.json').read_text())
    assert metadata['skill_expert_frames'] == 3 and metadata['terminal_hold_frames'] == 2
    assert metadata['terminal_hold_end_sim_time'] - metadata['terminal_hold_start_sim_time'] == pytest.approx(.1)
    with h5py.File(label.teacher_artifact) as trace:
        assert not np.array_equal(trace['qpos'][3], trace['qpos'][4])
        assert trace['transition_completed'][:].all()
        np.testing.assert_array_equal(trace['action'][3:], np.zeros((2, 16)))
    assert SimulationExpert.verify_label(snapshot, label)


def test_terminal_hold_guard_failure_rejects_label_and_keeps_live_state(tmp_path):
    class FailHold(ShortInitialize):
        def __init__(self, runtime, directory, **kwargs):
            super().__init__(runtime, directory, **kwargs)
            advance = runtime.tick
            def tick():
                advance()
                raise RuntimeError('terminal_contact_camera_guard')
            runtime.tick = tick
    runtime, expert, operation = setup(tmp_path, machine_factory=FailHold)
    before = state_digest(expert.capture())
    with pytest.raises(RuntimeError, match='terminal_contact_camera_guard'):
        expert.label(operation, 'initialize_posture', expert.capture(), 5)
    assert state_digest(expert.capture()) == before
    assert 'label_rejected' in (expert.directory / 'expert_000000/teacher_metadata.json').read_text()


def test_terminal_hold_requires_actual_time_advance(tmp_path):
    class NoAdvance(ShortInitialize):
        def __init__(self, runtime, directory, **kwargs):
            super().__init__(runtime, directory, **kwargs)
            runtime.tick = lambda: None
    runtime, expert, operation = setup(tmp_path, machine_factory=NoAdvance)
    with pytest.raises(TeacherError, match='did_not_advance_physics'):
        expert.label(operation, 'initialize_posture', expert.capture(), 5)


def test_other_short_skills_remain_real_short_labels(tmp_path):
    runtime, expert, operation = setup(tmp_path)
    label = expert.label(operation, 'navigate_to_tray', expert.capture(), 5)
    assert label.actions.shape == (3, 19)
    assert SimulationExpert.verify_label(expert.capture(), label)


@pytest.mark.parametrize('skill',['carry_tray','place_release_tray'])
def test_declared_holding_does_not_override_actual_lost_contact(tmp_path,skill,monkeypatch):
    runtime,expert,operation=setup(tmp_path)
    runtime.holding=0;runtime.grasp_rel={'left':np.eye(4),'right':np.eye(4)}
    def observation(self):
        return dict(gripper_contact_force=np.zeros((3,2)),min_z=np.full(3,.8),support_contact=np.ones(3))
    monkeypatch.setattr(Runtime,'observation',observation,raising=False)
    monkeypatch.setattr(Config,'criteria',SimpleNamespace(lifted_m=.02),raising=False)
    before=state_digest(expert.capture())
    with pytest.raises(TeacherError,match='stale_holding'):
        expert.label(operation,skill,expert.capture(),20)
    assert state_digest(expert.capture())==before
    import json
    report=json.loads((expert.directory/'expert_000000/teacher_metadata.json').read_text())
    assert report['measured_holding_qualification']['bilateral_force_n']==[0.,0.]
    assert report['measured_holding_qualification']['verified'] is False


def test_private_escape_default_disabled_retains_original_failure(tmp_path,monkeypatch):
    runtime,expert,operation=setup(tmp_path)
    calls=[]
    def reject(*args,**kwargs):calls.append(kwargs);raise TeacherError('joint_path_collision_or_wrist')
    monkeypatch.setattr(expert,'_label_once',reject)
    with pytest.raises(TeacherError,match='joint_path_collision'):
        expert.label(operation,'grasp_lift_tray',expert.capture(),20)
    assert calls==[{}]


def test_private_escape_retry_uses_same_snapshot_and_independent_attempt(tmp_path,monkeypatch):
    runtime,expert,operation=setup(tmp_path);expert.private_contact_escape=True
    snapshot=expert.capture();calls=[]
    def attempt(op,skill,state,horizon,**kw):
        calls.append(kw)
        assert state is snapshot and state_digest(expert.capture())==state_digest(snapshot)
        if not kw:raise TeacherError('joint_path_collision_or_wrist')
        if len(calls)==2:raise TeacherError('original_physical_guard_failed')
        return 'validated-full-skill-label'
    class Adapter:
        def __init__(self,r):assert r is runtime
        def candidates(self):return [np.array([.002,0,0]),np.array([.005,0,0])]
    import r1pro_teleop.vla.contact_escape as ce
    monkeypatch.setattr(ce,'RuntimeEscapeAdapter',Adapter)
    monkeypatch.setattr(expert,'_label_once',attempt)
    assert expert.label(operation,'grasp_lift_tray',snapshot,20)=='validated-full-skill-label'
    assert len(calls)==3
