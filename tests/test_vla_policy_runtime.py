from types import SimpleNamespace
import numpy as np
import pytest
from r1pro_teleop.vla.policy import Pi05Policy, PolicyContract, PolicyError, padded_state
from r1pro_teleop.vla.executor import ActionBounds, VLAOperationExecutor


class Client:
    def __init__(self, actions=None):
        self.calls = []
        self.actions = np.zeros((4, 32), np.float32) if actions is None else actions
    def infer(self, observation):
        self.calls.append(observation)
        return {'actions': self.actions.copy()}


def fixture(actions=None, **kwargs):
    client = Client(actions)
    policy = Pi05Policy(client, PolicyContract('test-checkpoint', action_horizon=4, action_width=32))
    sim = SimpleNamespace(target=np.zeros(16), base_target=np.zeros(3),
        state=lambda: np.arange(16, dtype=np.float32)/100,
        base_joint_state=lambda: np.array([.1, .2, .3]),
        image=lambda name: np.zeros((8, 12, 3), dtype=np.uint8))
    runtime = SimpleNamespace(cfg=SimpleNamespace(fps=20), sim=sim, steps=0, time=0.)
    def forbidden(*args, **kw):
        raise AssertionError('solver/teacher must never be called')
    for name in ('solve_pair', 'joints', 'cartesian', 'navigate', '_inverse_ratio', 'teacher'):
        setattr(runtime, name, forbidden)
    def tick():
        runtime.steps += 1
        runtime.time += .05
    runtime.tick = tick
    executor = VLAOperationExecutor(runtime, policy, ActionBounds(-np.ones(19), np.ones(19)),
                                   execute_steps=2, max_operation_steps=5, **kwargs)
    return client, runtime, executor


def test_recurrent_chunks_stop_at_completed_and_match_20hz():
    actions = np.tile(np.arange(32, dtype=np.float32)/100, (4, 1))
    records = []
    client, runtime, executor = fixture(actions, on_chunk=records.append)
    op = SimpleNamespace(tray=2, slot=1)
    assert executor.execute_operation(op, 'Move tray to slot 1.', lambda r, op: r.steps == 3)
    assert runtime.steps == 3
    assert runtime.time == pytest.approx(.15)
    assert len(client.calls) == 2
    assert [r['step'] for r in records] == [0, 2]
    np.testing.assert_array_equal(runtime.sim.target, actions[0, :16])
    np.testing.assert_array_equal(runtime.sim.base_target, actions[0, 16:19])
    obs = client.calls[0]
    assert set(obs) == {'state', 'prompt', 'image/head_left', 'image/left_wrist', 'image/right_wrist'}
    assert obs['state'].shape == (19,)
    np.testing.assert_allclose(obs['state'][16:19], [.1, .2, .3])
    assert runtime.allowed_tray == 2 and runtime.target_slot == 1


@pytest.mark.parametrize('actions', [np.zeros((4, 19)), np.zeros((1, 4, 32)),
                                   np.full((4, 32), np.nan), np.full((4, 32), np.inf)])
def test_invalid_chunk_stops_before_motion(actions):
    _, runtime, executor = fixture(actions)
    with pytest.raises(PolicyError, match='invalid_action_chunk'):
        executor.execute_operation(SimpleNamespace(tray=0, slot=0), 'Place.', lambda *_: False)
    assert runtime.steps == 0


def test_late_out_of_range_action_rejects_entire_chunk_before_motion():
    actions = np.zeros((4, 32), np.float32)
    actions[-1, 0] = 2
    _, runtime, executor = fixture(actions)
    with pytest.raises(PolicyError, match='outside_joint_limits'):
        executor.execute_operation(SimpleNamespace(tray=0, slot=0), 'Place.', lambda *_: False)
    assert runtime.steps == 0


def test_guard_failure_propagates_without_teacher_or_more_inferences():
    client, runtime, executor = fixture()
    def guarded_tick():
        raise RuntimeError('camera guard')
    runtime.tick = guarded_tick
    with pytest.raises(RuntimeError, match='camera guard'):
        executor.execute_operation(SimpleNamespace(tray=0, slot=0), 'Place.', lambda *_: False)
    assert len(client.calls) == 1


def test_inference_failure_never_falls_back():
    client, runtime, executor = fixture()
    def unavailable(_):
        raise ConnectionError('model server unavailable')
    client.infer = unavailable
    with pytest.raises(PolicyError, match='inference_failed'):
        executor.execute_operation(SimpleNamespace(tray=0, slot=0), 'Place.', lambda *_: False)
    assert runtime.steps == 0


def test_budget_exhaustion_is_failure_not_completion():
    client, runtime, executor = fixture()
    with pytest.raises(PolicyError, match='step_budget_exhausted'):
        executor.execute_operation(SimpleNamespace(tray=0, slot=0), 'Place.', lambda *_: False)
    assert runtime.steps == 5 and len(client.calls) == 3


def test_missing_checkpoint_and_nonfinite_state_are_rejected():
    with pytest.raises(PolicyError, match='checkpoint_required'):
        PolicyContract('')
    with pytest.raises(PolicyError, match='invalid_mobile19_state'):
        padded_state(np.full(19, np.nan))


def test_missing_camera_and_empty_prompt_stop_inference():
    client = Client()
    policy = Pi05Policy(client, PolicyContract('test-checkpoint', action_horizon=4))
    with pytest.raises(PolicyError, match='missing_camera'):
        policy.infer({}, np.zeros(19), 'Place.')
    with pytest.raises(PolicyError, match='task_prompt_required'):
        policy.infer({}, np.zeros(19), '')
    assert client.calls == []


def test_non_20hz_runtime_rejected():
    client, runtime, executor = fixture()
    runtime.cfg.fps = 10
    with pytest.raises(PolicyError, match='sampling_mismatch'):
        VLAOperationExecutor(runtime, executor.policy, executor.bounds)


def test_runtime_bounds_use_sum_of_finger_ranges_and_reject_unbounded_base():
    ranges = np.tile([-2., 2.], (21, 1))
    ranges[14:18] = [0., .04]
    model = SimpleNamespace(jnt_limited=np.ones(21, dtype=bool), jnt_range=ranges)
    runtime = SimpleNamespace(m=model, jids=np.arange(14), base_joints=[18, 19, 20],
                              sim=SimpleNamespace(fingers={'left': [14, 15], 'right': [16, 17]}))
    bounds = ActionBounds.from_runtime(runtime)
    assert bounds.lower[7] == 0 and bounds.upper[7] == .08
    assert bounds.upper[15] == .08
    model.jnt_limited[18] = False
    with pytest.raises(PolicyError, match='explicit_bounds'):
        ActionBounds.from_runtime(runtime)


def test_explicit_19_width_accepts_19_and_rejects_32():
    client = Client(np.zeros((4, 19), np.float32))
    policy = Pi05Policy(client, PolicyContract('test-checkpoint', action_horizon=4, action_width=19))
    images = {name: np.zeros((8, 12, 3), np.uint8) for name in policy.contract.camera_names}
    assert policy.infer(images, np.zeros(19), 'Place.').shape == (4, 19)
    client.actions = np.zeros((4, 32), np.float32)
    with pytest.raises(PolicyError, match='invalid_action_chunk'):
        policy.infer(images, np.zeros(19), 'Place.')


def test_websocket_metadata_must_match_loaded_checkpoint_and_action_contract(monkeypatch):
    import sys
    metadata = {'checkpoint_id': 'loaded-checkpoint', 'action_width': 19, 'action_horizon': 50,
                'action_space': 'mobile19_absolute_v1', 'control_hz': 20, 'model': 'pi05'}
    class Websocket:
        def __init__(self, host, port):
            assert host == 'localhost' and port == 8000
        def get_server_metadata(self):
            return metadata
    monkeypatch.setitem(sys.modules, 'openpi_client.websocket_client_policy',
                        SimpleNamespace(WebsocketClientPolicy=Websocket))
    contract = PolicyContract('loaded-checkpoint')
    assert Pi05Policy.from_websocket('localhost', 8000, contract).contract == contract
    metadata['control_hz'] = 10
    with pytest.raises(PolicyError, match='action_contract_mismatch'):
        Pi05Policy.from_websocket('localhost', 8000, contract)
    metadata['checkpoint_id'] = 'other-checkpoint'
    with pytest.raises(PolicyError, match='identity_mismatch'):
        Pi05Policy.from_websocket('localhost', 8000, contract)


def test_policy_render_bound_and_shape_are_logged_without_changing_controls(monkeypatch):
    decisions=[];chunks=[];seen=[]
    client,runtime,executor=fixture(on_decision=decisions.append,on_chunk=chunks.append)
    runtime.cfg.vla_model_render_max_dim=320
    def render(sim,camera,bound):
        seen.append((camera,bound))
        return np.zeros((256,320,3) if camera=='head_left' else (180,320,3),np.uint8)
    monkeypatch.setattr('r1pro_teleop.vla.executor.render_model_observation',render)
    executor.execute_operation(SimpleNamespace(tray=0,slot=0),'Move.',lambda r,op:r.steps==1)
    assert runtime.steps==1
    assert all(bound==320 for _,bound in seen) and len(seen)==3
    expected={'max_dim':320,'profile':'policy_same_aspect','rgb_shapes':{'head_left':[256,320,3],'left_wrist':[180,320,3],'right_wrist':[180,320,3]}}
    assert decisions[0]['observation_render']==expected
    assert chunks[0]['observation_render']==expected
    assert client.calls[0]['image/head_left'].shape==(256,320,3)
