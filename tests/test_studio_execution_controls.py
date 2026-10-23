import json
import sys
from pathlib import Path
from unittest.mock import patch
import pytest

ROOT=Path(__file__).resolve().parents[1]
gpu=ROOT/'apps/scene-agent/gpu'
sys.path.insert(0,str(gpu if gpu.exists() else ROOT/'gpu'))
import execution_settings as settings
import studio_backend as backend
from job_diagnostics import diagnostics

INVENTORY={'devices':[{'index':0},{'index':1}]}

@pytest.mark.parametrize('ids',[[0],[1],[0,1],[1,0]])
def test_training_selection(ids):
    assert settings.selection({'trainingGpuIds':ids},'training.create',INVENTORY)==ids

@pytest.mark.parametrize('ids',[[True],[2],[0,0],[],[{}],['1']])
def test_reject_invalid_training_selection(ids):
    with pytest.raises(ValueError):settings.selection({'trainingGpuIds':ids},'training.create',INVENTORY)

def test_different_simulation_and_inference_devices():
    assert settings.selection({'simulationGpu':1,'inferenceGpu':0},'evaluation.live',INVENTORY)==[1,0]
    with pytest.raises(ValueError):settings.selection({'simulationGpu':2},'evaluation.live',INVENTORY)

@pytest.mark.parametrize('running',[False,True])
def test_cancellation_is_owned_cooperative_marker(tmp_path,running):
    run=tmp_path/'policy_123';run.mkdir()
    backend.write(run/'request.json',{'kind':'evaluation.live'})
    backend.write(run/'status.json',{'status':'running' if running else 'waiting_gpu'})
    with patch.object(backend,'JOBS',tmp_path),patch.object(backend,'alive',return_value=running):backend.cancel(run.name)
    assert (run/'stop_requested').exists()
    assert backend.read(run/'status.json')['status']==('running' if running else 'cancelled')

def test_cancel_preserves_terminal_and_rejects_training(tmp_path):
    run=tmp_path/'policy_123';run.mkdir()
    backend.write(run/'request.json',{'kind':'evaluation.live'})
    backend.write(run/'status.json',{'status':'completed'})
    with patch.object(backend,'JOBS',tmp_path):
        backend.cancel(run.name)
        assert not (run/'stop_requested').exists()
        with pytest.raises(ValueError):backend.cancel('../escape')
        backend.write(run/'request.json',{'kind':'training.create'})
        with pytest.raises(ValueError):backend.cancel(run.name)

def test_errors_before_log_tail_and_full_traceback_are_visible(tmp_path):
    (tmp_path/'failure.json').write_text(json.dumps({'traceback':'full stack','error':'broken'}))
    (tmp_path/'native.log').write_text('ERROR first failure access_token=private\n'+'ok\n'*40000+'tail\n')
    rows=diagnostics(tmp_path)
    assert any('full stack' in r['text'] for r in rows)
    assert any('first failure' in r['text'] for r in rows)
    assert any(r.get('truncated') for r in rows)
    assert 'private' not in json.dumps(rows)
