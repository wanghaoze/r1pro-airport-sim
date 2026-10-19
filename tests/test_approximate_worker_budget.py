from types import SimpleNamespace
import time

import pytest

from r1pro_teleop.airport_fsm.batch import attempt_worker_timeout
from r1pro_teleop.airport_fsm.contracts import Fault
from r1pro_teleop.airport_fsm.physical_preview import _check_attempt_budget


def test_only_opt_in_worker_can_outlive_wall_clock_limit():
    cfg = SimpleNamespace(max_attempt_wall_seconds=1.)
    assert attempt_worker_timeout(cfg) == 31.
    cfg.approximate_completion_enabled = True
    assert attempt_worker_timeout(cfg) is None


def test_preview_expired_budget_records_diagnostic_in_approximate_mode():
    records = []
    cfg = SimpleNamespace(max_episode_seconds=1., fps=20, max_attempt_wall_seconds=1.,
                          approximate_completion_enabled=False)
    runtime = SimpleNamespace(cfg=cfg, steps=100, wall_start=time.monotonic()-10,
                              record_strict_deviation=lambda *args: records.append(args))
    with pytest.raises(Fault, match='episode_budget_exhausted'):
        _check_attempt_budget(runtime)
    cfg.approximate_completion_enabled = True
    _check_attempt_budget(runtime)
    assert records[0][0] == 'episode_budget_exhausted'
    assert records[0][1]['elapsed_physics_s'] == 5.
