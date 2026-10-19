"""One replay clock for all backends. Only initialization may set joint state."""
from typing import Protocol, Callable
import math
import numpy as np


class Backend(Protocol):
    timestep: float
    def initialize(self, positions: np.ndarray) -> None: ...
    def command(self, positions: np.ndarray) -> None: ...
    def step(self) -> None: ...
    def observe(self) -> np.ndarray: ...


def replay(trajectory, mapping, backend: Backend, *, on_sample: Callable | None = None,
           on_step: Callable | None = None):
    if tuple(trajectory.channels) != mapping.channels:
        raise ValueError("real2sim_trajectory_mapping_order_mismatch")
    dt = float(backend.timestep)
    if not math.isfinite(dt) or dt <= 0:
        raise ValueError("real2sim_invalid_physics_timestep")
    stamps = trajectory.seconds
    backend.initialize(mapping.encode(trajectory.feedback[0]))
    actual, times, command_indices = [], [], []
    cursor = 0
    last_executed_command = -1  # initial feedback, before any recorded command
    def sample(t):
        nonlocal cursor
        while cursor < len(stamps) and stamps[cursor] <= t + 1e-10:
            q = mapping.decode(backend.observe())
            actual.append(q); times.append(t)
            command_indices.append(last_executed_command)
            if on_sample:
                on_sample(cursor, t, q)
            cursor += 1
    sample(0.)
    steps = int(math.ceil(stamps[-1] / dt - 1e-10))
    for tick in range(steps):
        # Causal zero-order hold at the start of the physics interval. No lookahead.
        index = int(np.searchsorted(stamps, tick * dt + 1e-12, side="right") - 1)
        target = mapping.encode(trajectory.commands[index])
        backend.command(target)
        if on_step:
            on_step(tick, index, target)
        backend.step()
        last_executed_command = index
        sample((tick + 1) * dt)
    if cursor != len(stamps):
        raise RuntimeError("real2sim_incomplete_replay")
    actual = np.array(actual); times = np.array(times)
    # Compare feedback at actual physics sample time; never pair post-step with pre-step.
    reference = np.column_stack([np.interp(times, stamps, trajectory.feedback[:, j])
                                 for j in range(len(mapping.channels))])
    mse = np.mean((actual - reference) ** 2, axis=0)
    groups = {"arms": [i for i, n in enumerate(mapping.channels) if "arm_joint" in n],
              "grippers": [i for i, n in enumerate(mapping.channels) if "opening" in n],
              "torso": [i for i, n in enumerate(mapping.channels) if "torso" in n]}
    metrics = {name: dict(mse=float(mse[ids].mean()), unit="m2" if name == "grippers" else "rad2")
               for name, ids in groups.items() if ids}
    return dict(actual=actual, feedback_at_actual_time=reference, actual_times=times,
                source_times=stamps, source_command_indices=np.array(command_indices),
                metrics=metrics, physics_steps=steps, duration_s=steps * dt,
                max_sample_delay_s=float(np.max(times - stamps)),
                per_channel_mse=mse.tolist(), task_success=None,
                replay_completed=True, online_state_resets=0)
