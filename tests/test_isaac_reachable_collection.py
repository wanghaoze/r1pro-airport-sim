import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
import numpy as np
import pytest


@pytest.fixture
def collector(monkeypatch):
    scripts=Path(__file__).resolve().parents[1]/'scripts'
    monkeypatch.syspath_prepend(str(scripts))
    if sys.platform=='win32':
        # Pure audits do not acquire the Linux process lock.
        monkeypatch.setitem(sys.modules,'fcntl',SimpleNamespace())
    spec=importlib.util.spec_from_file_location('reachable_collector_test',scripts/'collect_isaac_fixed_pickplace.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def test_preparation_base_motion_rejected_even_when_core_fixed(collector):
    action=np.zeros((10,19));state=np.zeros((11,19));action[1,16]=.01
    collector.verify_base_trace(action,state,4,10)
    with pytest.raises(ValueError,match='base_command_moved'):
        collector.verify_base_trace(action,state,4,10,{'fixed_command':[0,0,0]})


def test_preparation_actual_drift_retains_existing_five_cm_gate(collector):
    action=np.zeros((10,19));state=np.zeros((11,19));state[2,16]=.051
    with pytest.raises(ValueError,match='actual_base_exceeded'):
        collector.verify_base_trace(action,state,4,10,{'fixed_command':[0,0,0]})
    state[2,16]=.049
    assert collector.verify_base_trace(action,state,4,10,{'fixed_command':[0,0,0]}).max()==.049


def test_failed_candidates_keep_valid_pairs_without_claiming_complete(collector):
    status=collector.partial_terminal_summary(2,5,1)
    assert status['stage']=='partial_complete'
    assert status['complete_source_pairs']==2 and status['action_segments']==4
    assert status['failed_or_unaccepted_candidates']==3
    assert status['actual_producer_returncode']==1 and not status['all_candidates_passed']
    assert collector.partial_terminal_summary(0,5,1)['complete_source_pairs']==0
    assert collector.partial_terminal_summary(5,5,0)['stage']=='complete'
