"""CPU and HTTP contract evidence, not hardware or physical episode acceptance."""
import io
import json
import sys
import threading
import time
import urllib.request
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from r1pro_teleop.real2sim.robot_action_filter import (
    ARMS, bound_actions, bounds, contract_id, filter_command, load_limits, configured_limits, interpolate_commands,
)


@pytest.mark.parametrize('invalid',[0,-1,.100001,True,float('nan'),float('inf'),'0.01'])
def test_changed_limits_never_widen_envelope(invalid):
    with pytest.raises(ValueError):configured_limits({'maxStepRad':invalid})


@pytest.mark.parametrize('horizon',[1,20,40])
def test_adjusted_filter_and_all_25_interpolation_substeps(horizon):
    limits=configured_limits({'maxStepRad':.02,'maxVelocityRadS':.3})
    assert contract_id(limits)!=contract_id(load_limits())
    lo,hi=bounds(limits);model=model_for(limits)
    previous=np.r_[(lo+hi)/2,[0,0,0]]
    raw=np.random.default_rng(5).uniform(-100,100,(horizon,19))
    for target in bound_actions(raw,limits,horizon):
        applied=filter_command(target,previous,previous,model,limits,0)
        path=np.array([previous]+[interpolate_commands(previous,applied,i) for i in range(1,26)])
        assert np.all(path[:,:16]>=lo) and np.all(path[:,:16]<=hi)
        # Audit what PhysX actually consumes, including float32 quantization.
        actual=path.astype(np.float32).astype(float)
        assert np.max(np.abs(np.diff(actual[:,ARMS],axis=0)))/.002<=.3
        assert np.allclose(path[-1],applied,rtol=0,atol=1e-15)
        previous=applied


def model_for(limits):
    names = []; ranges = []
    for side in ('left', 'right'):
        for j in range(1, 8):
            name = f'{side}_arm_joint{j}'; names.append(name)
            ranges.append(limits['mechanical']['ranges'][name])
        for j in (1, 2):
            names.append(f'{side}_gripper_finger_joint{j}')
            ranges.append([0, .04])
    return SimpleNamespace(joint=lambda name: SimpleNamespace(id=names.index(name)),
                           jnt_limited=np.ones(len(names), bool), jnt_range=np.array(ranges))


@pytest.mark.parametrize('horizon', [1, 20, 40])
def test_all_channels_bound_and_raw_preserved(horizon):
    limits = load_limits(); lo, hi = bounds(limits)
    raw = np.random.default_rng(42).uniform(-100, 100, (horizon, 19)); copy = raw.copy()
    result = bound_actions(raw, limits, horizon)
    assert np.array_equal(raw, copy)
    assert np.all(result[:, :16] >= lo) and np.all(result[:, :16] <= hi)
    assert np.all(result[:, 16:] == 0)


@pytest.mark.parametrize('invalid', [np.nan, np.inf, -np.inf])
def test_nonfinite_is_rejected_before_clipping(invalid):
    raw = np.zeros((20, 19)); raw[0, 0] = invalid
    with pytest.raises(ValueError, match='invalid_action_chunk'):
        bound_actions(raw, load_limits(), 20)


def test_missing_gripper_channels_are_not_repaired():
    with pytest.raises(ValueError, match='invalid_action_chunk'):
        bound_actions(np.zeros((1, 14)), load_limits(), 1)


def test_random_sequence_respects_joint_and_rate_intersection():
    limits = load_limits(); model = model_for(limits); lo, hi = bounds(limits)
    previous = np.r_[(lo+hi)/2, [1., -2., .3]]
    rng = np.random.default_rng(2)
    for _ in range(1000):
        raw = rng.uniform(-100, 100, 19)
        applied = filter_command(raw, previous, previous, model, limits, .01)
        assert np.all(applied[:16] >= lo) and np.all(applied[:16] <= hi)
        assert np.max(np.abs(applied[ARMS]-previous[ARMS])) <= .075 + 1e-15
        assert np.array_equal(applied[16:], previous[16:])
        previous = applied


@pytest.mark.parametrize('age', [np.nan, np.inf, -.01, .501])
def test_missing_future_or_stale_feedback_fails_closed(age):
    limits = load_limits(); zero = np.zeros(19)
    with pytest.raises(ValueError, match='stale_feedback'):
        filter_command(zero, zero, zero, model_for(limits), limits, age)


def test_mechanical_intersection_and_invalid_config():
    limits = load_limits(); model = model_for(limits)
    model.jnt_range[0] = [-.1, .01]
    out = filter_command(np.ones(19), np.zeros(19), np.zeros(19), model, limits, 0)
    assert out[0] <= .01 and np.isclose(out[0], .01)
    limits['max_velocity_rad_s'] = np.nan
    with pytest.raises(ValueError, match='invalid_limits'): contract_id(limits)


@pytest.mark.parametrize('field', ['target', 'previous', 'measured'])
def test_bad_vector_never_reaches_actuator(field):
    values = {k: np.zeros(19) for k in ('target', 'previous', 'measured')}
    values[field][3] = np.nan; limits = load_limits()
    with pytest.raises(ValueError, match='invalid_vector'):
        filter_command(values['target'], values['previous'], values['measured'], model_for(limits), limits, 0)


@pytest.mark.parametrize('family,horizon', [('pi05', 20), ('g05', 1), ('groot', 20)])
def test_http_boundary_filters_every_model_family(tmp_path, monkeypatch, family, horizon):
    """Actual loopback HTTP/NPZ handler, synthetic adapter (no model weights)."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
    import studio_model_http as http
    from http.server import HTTPServer
    raw = np.full((horizon, 19), 99.)
    class FakeAdapter:
        def __init__(self, entry): self.family = family
        def infer(self, sample, room): return raw.copy()
    servers = []
    class OneRequestServer(HTTPServer):
        def serve_forever(self):
            servers.append(self)
            self.timeout = 10
            self.handle_request()
            self.server_close()
    (tmp_path/'checkpoints.json').write_text(json.dumps([{'id': 'synthetic', 'family': family, 'modelConfig': {'horizon': horizon}}]))
    (tmp_path/'request.json').write_text(json.dumps({'payload': {'actionSafetyMode': 'strict'}}))
    monkeypatch.setattr(http, 'Adapter', FakeAdapter); monkeypatch.setattr(http, 'HTTPServer', OneRequestServer)
    monkeypatch.setattr(sys, 'argv', ['studio_model_http.py', '--run', str(tmp_path)])
    errors = []
    def serve():
        try: http.main()
        except Exception as e: errors.append(e)
    thread = threading.Thread(target=serve); thread.start()
    deadline = time.monotonic()+5
    while not servers and not errors and time.monotonic() < deadline: time.sleep(.01)
    assert servers and not errors
    sample = io.BytesIO()
    np.savez(sample, _room='0', state=np.zeros(19), prompt='Pick up the tray',
             **{'image/'+c: np.zeros((2, 2, 3), np.uint8) for c in ('head_left', 'left_wrist', 'right_wrist')})
    request = urllib.request.Request(f'http://127.0.0.1:{servers[0].server_port}/infer', data=sample.getvalue())
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=5) as r:
        with np.load(io.BytesIO(r.read()), allow_pickle=False) as reply:
            assert np.array_equal(reply['raw_actions'], raw)
            assert np.array_equal(reply['actions'], bound_actions(raw, load_limits(), horizon))
    thread.join(5); assert not thread.is_alive() and not errors
    ready = json.loads((tmp_path/'model_http.ready.json').read_text())
    assert ready['actionSafetyMode'] == 'robot_limits'
    assert ready['actionFilterContract'] == contract_id(load_limits())


def test_live_receipt_reports_effective_filter_without_relabelling_history(tmp_path):
    root=Path(__file__).resolve().parents[1]
    gpu=root/'apps/scene-agent/gpu'
    sys.path.insert(0,str(gpu if gpu.exists() else root/'gpu'))
    import live_publication
    (tmp_path/'request.json').write_text(json.dumps({'payload':{'checkpointIds':['c'],'roomIds':[0],'actionSafetyMode':'strict'}}))
    assert live_publication.snapshot(tmp_path)['configuration']['actionSafetyMode']=='strict'
    (tmp_path/'execution_contract.json').write_text(json.dumps({'actionSafetyMode':'robot_limits','actionFilterContract':contract_id(load_limits()),'requestedActionSafetyMode':'strict'}))
    snap=live_publication.snapshot(tmp_path)
    assert snap['configuration']['actionSafetyMode']=='robot_limits'
    assert snap['configuration']['requestedActionSafetyMode']=='strict'


def test_float32_transport_cannot_round_a_bound_outward():
    limits=load_limits();lo,hi=bounds(limits)
    raw=np.array([np.r_[lo-1,np.zeros(3)],np.r_[hi+1,np.zeros(3)]])
    result=bound_actions(raw,limits,2).astype(np.float32).astype(float)
    assert np.all(result[:,:16]>=lo) and np.all(result[:,:16]<=hi)
    model=model_for(limits);previous=np.r_[(lo+hi)/2,np.zeros(3)]
    out=filter_command(raw[1],previous,previous,model,limits,0).astype(np.float32).astype(float)
    assert np.max(np.abs(out[ARMS]-previous[ARMS]))<=.075
