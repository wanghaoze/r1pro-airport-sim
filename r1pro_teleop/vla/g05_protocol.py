"""Strict G0.5 single-step WebSocket contract; never synthesize missing controls."""
import inspect

import numpy as np


PARTS = {'left_arm': 7, 'left_gripper': 1, 'right_arm': 7, 'right_gripper': 1}


class G05ProtocolError(ValueError):
    def __init__(self, code, **details):
        self.details = {'code': code, **details}
        super().__init__(code + ': ' + str(details))


def validate_shape_meta(shape):
    """Wire dimensions are raw_shape; shape may describe transformed features."""
    for section in ('action', 'state'):
        entries = shape[section]
        parts = {p['key']: p.get('raw_shape', p.get('shape')) for p in entries}
        if len(entries) != len(PARTS) or parts != PARTS:
            raise G05ProtocolError('g05_checkpoint_joint_contract_mismatch',
                                   section=section, actual=parts)


def encode(value):
    if isinstance(value, np.ndarray):
        return {b'__ndarray__': True, b'data': value.tobytes(),
                b'dtype': value.dtype.str, b'shape': value.shape}
    if isinstance(value, np.generic):
        return value.item()
    raise TypeError(type(value).__name__)


def decode(value):
    if b'__ndarray__' in value:
        dtype = np.dtype(value[b'dtype'])
        if dtype.hasobject:
            raise G05ProtocolError('g05_object_dtype_rejected')
        return np.frombuffer(value[b'data'], dtype=dtype).reshape(value[b'shape'])
    return value


def evidence(value):
    """JSON-safe action evidence, including invalid values, without image payloads."""
    if isinstance(value, dict):
        return {str(k): evidence(v) for k, v in value.items()}
    if isinstance(value, np.ndarray):
        return {'shape': list(value.shape), 'dtype': str(value.dtype),
                'values': evidence(value.tolist()) if value.size <= 1024 else None}
    if isinstance(value, (list, tuple)):
        return [evidence(v) for v in value]
    if isinstance(value, np.generic):
        return evidence(value.item())
    if isinstance(value, float) and not np.isfinite(value):
        return str(value)
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    return repr(value)


def parse_action(reply):
    if not isinstance(reply, dict):
        raise G05ProtocolError('g05_invalid_reply', reply_type=type(reply).__name__)
    if 'error' in reply:
        raise G05ProtocolError('g05_upstream_error', upstream_error=evidence(reply['error']))
    actions = reply.get('action')
    if not isinstance(actions, dict):
        raise G05ProtocolError('g05_missing_action_object')
    missing = sorted(set(PARTS) - set(actions))
    if missing:
        raise G05ProtocolError('g05_missing_action_parts', missing=missing,
                               available=sorted(map(str, actions)))
    result = {}
    for key, width in PARTS.items():
        a = np.asarray(actions[key])
        # The MEM server returns one step, not an action chunk. Never flatten
        # a transposed tensor or duplicate that step to fill a longer horizon.
        if a.shape not in ((width,), (1, width)):
            raise G05ProtocolError('g05_action_shape_mismatch', part=key,
                                   expected=[width], actual=list(a.shape))
        if a.dtype.kind not in 'fiu' or not np.isfinite(a).all():
            raise G05ProtocolError('g05_nonfinite_or_nonnumeric_action', part=key)
        result[key] = a.reshape(1, width)
    return result


class G05Client:
    """One connection/history per room and task; errors discard it, without retry."""
    def __init__(self, config):
        if config.get('horizon') != 1:
            raise G05ProtocolError('g05_single_step_horizon_required')
        if config.get('gripperUnit') not in ('percent80', 'mm', 'm'):
            raise G05ProtocolError('g05_unknown_gripper_unit')
        self.config = config
        self.sessions = {}
        self.last_evidence = None

    def discard(self, room):
        session = self.sessions.pop(room, None)
        if session is not None:
            try:
                session['ws'].close()
            except Exception:
                pass  # Preserve the original inference failure.

    def close(self):
        for room in list(self.sessions):
            self.discard(room)

    def infer(self, request, room):
        import msgpack
        from websockets.sync.client import connect

        task = request['task']
        self.last_evidence = {'room': room, 'task': task}
        try:
            if room in self.sessions and self.sessions[room]['task'] != task:
                # Reconnect resets both cached actions and MEM history even on
                # older servers that do not implement the __reset__ message.
                self.discard(room)
            if room not in self.sessions:
                options = dict(max_size=32 * 1024 * 1024, open_timeout=15, close_timeout=5)
                # websockets 15 added automatic environment proxies. This
                # private model connection must remain direct; older clients
                # don't expose that option and don't use automatic proxies.
                if 'proxy' in inspect.signature(connect).parameters:
                    options['proxy'] = None
                ws = connect(f"ws://{self.config['host']}:{self.config['port']}", **options)
                self.sessions[room] = {'ws': ws, 'task': task}
                metadata = msgpack.unpackb(ws.recv(timeout=20), object_hook=decode, raw=False)
                if not isinstance(metadata, dict) or 'error' in metadata:
                    raise G05ProtocolError('g05_invalid_handshake', metadata=evidence(metadata))
                self.sessions[room]['metadata'] = metadata
            session = self.sessions[room]
            self.last_evidence['metadata'] = evidence(session['metadata'])
            session['ws'].send(msgpack.packb(request, default=encode))
            reply = msgpack.unpackb(session['ws'].recv(timeout=120), object_hook=decode, raw=False)
            # Preserve returned controls before parsing or unit conversion.
            self.last_evidence['reply'] = evidence(
                {k: reply[k] for k in ('action', 'need_obs', 'error') if k in reply}
                if isinstance(reply, dict) else reply)
            return parse_action(reply)
        except Exception:
            self.discard(room)
            raise
