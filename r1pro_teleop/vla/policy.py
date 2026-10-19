"""Checkpoint-backed pi0.5 inference contract; no teacher or simulator imports.

The airport transform on the openpi server consumes ``image/<camera>``,
``state`` and ``prompt``. State/actions are *absolute position targets* in
mobile19 order: left 7 joints/opening, right 7 joints/opening, base dx/dy/dyaw
relative to the initial model origin. Normalization belongs to the checkpoint's
input/output transforms, never to the actuator client.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol
import numpy as np


class PolicyError(RuntimeError):
    """An invalid/unavailable learned policy must stop, never invoke a teacher."""


class InferenceClient(Protocol):
    def infer(self, observation: dict) -> dict: ...


@dataclass(frozen=True)
class PolicyContract:
    checkpoint_id: str
    action_horizon: int = 50
    action_width: int = 19
    fps: int = 20
    camera_names: tuple[str, ...] = ('head_left', 'left_wrist', 'right_wrist')
    prompt_mode: str = "legacy"

    def __post_init__(self):
        from .prompts import validate_prompt_mode
        try:
            validate_prompt_mode(self.prompt_mode)
        except ValueError as exc:
            raise PolicyError("vla_invalid_prompt_mode") from exc
        if not isinstance(self.checkpoint_id, str) or not self.checkpoint_id.strip():
            raise PolicyError('vla_checkpoint_required')
        if self.fps != 20 or isinstance(self.action_horizon, bool) or not isinstance(self.action_horizon, int) or self.action_horizon < 1:
            raise PolicyError('vla_invalid_sampling_contract')
        if isinstance(self.action_width, bool) or self.action_width not in (19, 32):
            raise PolicyError('vla_invalid_action_width')
        if (not self.camera_names or
                any(not isinstance(name, str) or not name for name in self.camera_names) or
                len(set(self.camera_names)) != len(self.camera_names)):
            raise PolicyError('vla_invalid_camera_contract')


def padded_state(state) -> np.ndarray:
    try:
        value = np.asarray(state, dtype=np.float32)
    except (TypeError, ValueError) as exc:
        raise PolicyError('vla_invalid_mobile19_state') from exc
    if value.shape != (19,) or not np.isfinite(value).all():
        raise PolicyError('vla_invalid_mobile19_state')
    return np.pad(value, (0, 13))


def mobile19_mask() -> np.ndarray:
    return np.arange(32) < 19


class Pi05Policy:
    def __init__(self, client: InferenceClient, contract: PolicyContract):
        self.client, self.contract = client, contract

    @classmethod
    def from_websocket(cls, host: str, port: int, contract: PolicyContract):
        # Official API: WebsocketClientPolicy(host, port).infer(obs)->{'actions':...}.
        # See Physical-Intelligence/openpi/packages/openpi-client/.../websocket_client_policy.py.
        try:
            from openpi_client.websocket_client_policy import WebsocketClientPolicy
        except ImportError as exc:
            raise PolicyError('vla_openpi_client_missing') from exc
        client = WebsocketClientPolicy(host=host, port=port)
        metadata = client.get_server_metadata()
        # The airport serving entry point must advertise the *loaded* checkpoint.
        if not isinstance(metadata, dict) or metadata.get('checkpoint_id') != contract.checkpoint_id:
            raise PolicyError('vla_checkpoint_identity_mismatch')
        if metadata.get("prompt_mode", "legacy") != contract.prompt_mode:
            raise PolicyError("vla_server_prompt_contract_mismatch")
        expected = {'action_width': contract.action_width,
                    'action_horizon': contract.action_horizon,
                    'action_space': 'mobile19_absolute_v1',
                    'control_hz': contract.fps, 'model': 'pi05'}
        if any(metadata.get(key) != value for key, value in expected.items()):
            raise PolicyError('vla_server_action_contract_mismatch')
        return cls(client, contract)

    def infer(self, images: Mapping[str, np.ndarray], state, prompt: str) -> np.ndarray:
        if not isinstance(prompt, str) or not prompt.strip():
            raise PolicyError('vla_task_prompt_required')
        from .prompts import normalize_prompt
        try:
            prompt = normalize_prompt(prompt, self.contract.prompt_mode)
        except ValueError as exc:
            raise PolicyError("vla_prompt_contract_mismatch") from exc
        # The airport input transform accepts robot coordinates (19). Its
        # official model transform performs padding to the internal 32 DOFs.
        observation = {'state': padded_state(state)[:19].copy(), 'prompt': prompt}
        for name in self.contract.camera_names:
            if name not in images:
                raise PolicyError(f'vla_missing_camera:{name}')
            image = np.asarray(images[name])
            if image.dtype != np.uint8 or image.ndim != 3 or image.shape[-1] != 3 or min(image.shape[:2]) < 1:
                raise PolicyError(f'vla_invalid_rgb:{name}')
            observation[f'image/{name}'] = image.copy()
        try:
            reply = self.client.infer(observation)
        except Exception as exc:
            raise PolicyError('vla_inference_failed') from exc
        if not isinstance(reply, dict) or 'actions' not in reply:
            raise PolicyError('vla_missing_actions')
        try:
            actions = np.asarray(reply['actions'], dtype=np.float32)
        except (ValueError, TypeError) as exc:
            raise PolicyError('vla_invalid_actions') from exc
        if actions.shape != (self.contract.action_horizon, self.contract.action_width) or not np.isfinite(actions).all():
            raise PolicyError('vla_invalid_action_chunk')
        # The 13 padded output channels are never actuated or scored as robot DOFs.
        return (actions[:, mobile19_mask()] if self.contract.action_width == 32 else actions).copy()
