import io
import json
import sys
import threading
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from http.server import HTTPServer
from pathlib import Path

import numpy as np
import pytest
msgpack = pytest.importorskip('msgpack')
pytest.importorskip('websockets.sync.server')
from websockets.sync.server import serve

from r1pro_teleop.vla.g05_protocol import (
    G05Client, G05ProtocolError, PARTS, decode, encode, parse_action, validate_shape_meta,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import studio_model_http as http
from studio_ros2_transport import model_error_message
from r1pro_teleop.real2sim.robot_action_filter import bound_actions, load_limits


def reply():
    return {'action': {k: np.arange(w, dtype=np.float32) + 1 for k, w in PARTS.items()},
            'need_obs': False}


def sample(task='Pick up the tray'):
    return dict(state=np.arange(19, dtype=np.float32) / 1000, prompt=task,
                **{'image/' + c: np.zeros((4, 5, 3), np.uint8)
                   for c in ('head_left', 'left_wrist', 'right_wrist')})


@contextmanager
def upstream(respond):
    requests = []
    connections = []
    errors = []
    def handler(ws):
        connection = len(connections)
        connections.append(connection)
        try:
            ws.send(msgpack.packb({'action_steps': 5}))
            for payload in ws:
                request = msgpack.unpackb(payload, object_hook=decode, raw=False)
                requests.append((connection, request))
                ws.send(msgpack.packb(respond(request, connection), default=encode))
        except Exception as exc:
            errors.append(exc)
    with serve(handler, '127.0.0.1', 0) as server:
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        try:
            yield dict(host='127.0.0.1', port=server.socket.getsockname()[1],
                       horizon=1, gripperUnit='percent80'), requests, connections
        finally:
            server.shutdown()
            thread.join(5)
    assert not thread.is_alive() and not errors


@pytest.mark.parametrize('unit,scale', [('percent80', 1250), ('mm', 1000), ('m', 1)])
def test_wire_mapping_units_and_task_history_reset(unit, scale, monkeypatch):
    monkeypatch.setenv('ws_proxy', 'http://127.0.0.1:1')
    monkeypatch.setenv('no_proxy', '')
    with upstream(lambda request, connection: reply()) as (config, requests, connections):
        adapter = http.Adapter(dict(family='g05', modelConfig={**config, 'gripperUnit': unit}))
        try:
            result = adapter.infer(sample(), 'a')
            adapter.infer(sample(), 'a')
            adapter.infer(sample('Place the tray'), 'a')
            adapter.infer(sample(), 'b')
            assert [r[0] for r in requests] == [0, 0, 1, 2]
            assert len(connections) == 3
            assert result.shape == (1, 19)
            np.testing.assert_array_equal(result[0, :7], np.arange(7) + 1)
            np.testing.assert_array_equal(result[0, 8:15], np.arange(7) + 1)
            np.testing.assert_allclose(result[0, [7, 15]], 1 / scale)
            np.testing.assert_array_equal(result[0, 16:], 0)
            first = requests[0][1]
            assert first['frequency'] == 20 and first['embodiment_type'] == 'galaxea_r1pro'
            assert first['images']['head_rgb'].shape == (3, 4, 5)
            assert first['images']['head_rgb'].dtype == np.uint8
            np.testing.assert_allclose(first['state']['left_gripper'], [.007 * scale])
            np.testing.assert_allclose(first['state']['right_gripper'], [.015 * scale])
        finally:
            adapter.close()


def test_missing_parts_close_connection_and_preserve_evidence_without_retry():
    def missing(request, connection):
        result = reply()
        del result['action']['left_gripper']
        del result['action']['right_gripper']
        return result
    with upstream(missing) as (config, requests, connections):
        client = G05Client(config)
        with pytest.raises(G05ProtocolError) as caught:
            client.infer({'task': 'Pick up the tray'}, 'a')
        assert caught.value.details['missing'] == ['left_gripper', 'right_gripper']
        assert not client.sessions and len(requests) == 1
        assert client.last_evidence['reply']['action']['left_arm']['values'] == list(range(1, 8))
        assert len(connections) == 1


@pytest.mark.parametrize('bad', [np.ones((7, 1)), np.ones((2, 7)), np.ones((1, 1, 7)),
                                np.full(7, np.nan), np.full(7, np.inf), ['1'] * 7,
                                [True] * 7, np.ones(7, dtype=complex)])
def test_malformed_controls_are_not_flattened_or_coerced(bad):
    result = reply();result['action']['left_arm'] = bad
    with pytest.raises(G05ProtocolError):parse_action(result)


def test_explicit_row_and_vector_have_same_single_step_contract():
    result = reply()
    expected = parse_action(result)
    result['action'] = {k: v[None] for k, v in result['action'].items()}
    for k, value in parse_action(result).items():
        np.testing.assert_array_equal(value, expected[k])


@pytest.mark.parametrize('result', [None, [], {}, {'action': []},
                                  {'error': {'code': 400, 'message': 'bad state'}}])
def test_invalid_reply_is_explicit(result):
    with pytest.raises(G05ProtocolError):parse_action(result)


def test_wire_dimensions_override_processed_dimensions_but_cannot_hide_bad_raw_shape():
    shape = {section: [dict(key=k, raw_shape=w, shape=w + 10) for k, w in PARTS.items()]
             for section in ('action', 'state')}
    validate_shape_meta(shape)
    shape['action'][0].update(raw_shape=6, shape=7)
    with pytest.raises(G05ProtocolError, match='joint_contract_mismatch'):
        validate_shape_meta(shape)
    legacy = {section: [dict(key=k, shape=w) for k, w in PARTS.items()]
              for section in ('action', 'state')}
    validate_shape_meta(legacy)
    legacy['state'].append(dict(key='left_arm', shape=7))
    with pytest.raises(G05ProtocolError):validate_shape_meta(legacy)


@pytest.mark.parametrize('override', [{'horizon': 20}, {'gripperUnit': 'unknown'}])
def test_configuration_cannot_duplicate_steps_or_guess_units(override):
    with pytest.raises(G05ProtocolError):
        G05Client({**dict(horizon=1, gripperUnit='mm'), **override})


@pytest.mark.parametrize('missing_part', [None, 'right_gripper'])
def test_real_http_to_websocket_filters_valid_output_or_preserves_missing_part_error(tmp_path, monkeypatch, missing_part):
    def missing(request, connection):
        result = reply()
        if missing_part:del result['action'][missing_part]
        return result
    class OneRequestServer(HTTPServer):
        def serve_forever(self):
            self.timeout = 5
            self.handle_request()
    with upstream(missing) as (config, requests, connections):
        (tmp_path / 'checkpoints.json').write_text(json.dumps([dict(id='test', family='g05', modelConfig=config)]))
        (tmp_path / 'request.json').write_text(json.dumps(dict(payload={})))
        monkeypatch.setattr(http, 'HTTPServer', OneRequestServer)
        monkeypatch.setattr(sys, 'argv', ['studio_model_http', '--run', str(tmp_path)])
        errors = []
        def start():
            try:http.main()
            except Exception as exc:errors.append(exc)
        thread = threading.Thread(target=start);thread.start()
        try:
            ready = tmp_path / 'model_http.ready.json';deadline = time.monotonic() + 3
            while not ready.exists():
                assert not errors and time.monotonic() < deadline
                time.sleep(.01)
            port = json.loads(ready.read_text())['port']
            payload = io.BytesIO();np.savez(payload, _room='a', **sample())
            request = urllib.request.Request(f'http://127.0.0.1:{port}/infer', data=payload.getvalue(),
                                            headers={'X-Inference-Request-Id': 'g05-test'})
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            if missing_part:
                with pytest.raises(urllib.error.HTTPError) as caught:
                    opener.open(request, timeout=5)
                assert caught.value.code == 500
                message = model_error_message(caught.value)
                assert 'g05_missing_action_parts' in message and 'right_gripper' in message
            else:
                with opener.open(request, timeout=5) as response:
                    with np.load(io.BytesIO(response.read()), allow_pickle=False) as output:
                        raw = output['raw_actions']
                        np.testing.assert_allclose(raw[0, [7, 15]], 1 / 1250)
                        np.testing.assert_array_equal(output['actions'], bound_actions(raw, load_limits(), 1))
                        assert not np.array_equal(raw, output['actions'])
        finally:
            thread.join(7)
        assert not thread.is_alive() and not errors and len(requests) == 1
    if missing_part:
        error = json.loads((tmp_path / 'model_error_events.jsonl').read_text())
        assert error['requestId'] == 'g05-test' and error['inferenceStarted']
        assert error['details']['missing'] == [missing_part]
        assert not (tmp_path / 'checkpoint_limit_events.jsonl').exists()
    else:
        assert not (tmp_path / 'model_error_events.jsonl').exists()
        assert (tmp_path / 'checkpoint_limit_events.jsonl').exists()
    event = json.loads((tmp_path / 'g05_protocol_events.jsonl').read_text())
    assert event['metadata'] == {'action_steps': 5}
    assert event['reply']['action']['left_gripper']['values'] == [1.0]


@pytest.mark.parametrize('body', [b'not json', b'[]', b'{}', b'\xff'])
def test_transport_retains_http_failure_when_body_is_unreadable(body):
    error = urllib.error.HTTPError('http://127.0.0.1/infer', 500, 'failure', {}, io.BytesIO(body))
    assert 'HTTPError' in model_error_message(error)


def test_upstream_error_preserves_code_and_message_and_discards_session():
    with upstream(lambda *_: {'error': {'code': 400, 'message': 'state mismatch'}}) as (config, requests, connections):
        client = G05Client(config)
        with pytest.raises(G05ProtocolError) as caught:
            client.infer({'task': 'Pick up the tray'}, 'a')
        assert caught.value.details['upstream_error'] == {'code': 400, 'message': 'state mismatch'}
        assert len(requests) == 1 and not client.sessions
