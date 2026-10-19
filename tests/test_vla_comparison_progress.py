import importlib.util
import json
from pathlib import Path

import pytest

spec=importlib.util.spec_from_file_location('comparison_progress',Path(__file__).parents[1]/'scripts/watch_vla_comparison.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


def test_eta_only_when_active_and_measured():
    assert module.progress(250,1000,2,True)==dict(done=250,total=1000,percent=25,eta_seconds=1500)
    assert module.progress(250,1000,2,False)['eta_seconds'] is None
    assert module.progress(0,1000,None,True)['eta_seconds'] is None
    with pytest.raises(ValueError):module.progress(1001,1000)


def test_warmup_not_misreported_as_action_updates(tmp_path):
    (tmp_path/'affordvla').mkdir();(tmp_path/'pi05').mkdir()
    (tmp_path/'affordvla/training_status.json').write_text(json.dumps(dict(training_stage=1,stage_updates=250,stage='training',seconds_per_update_ema=2)))
    (tmp_path/'pi05/training_status.json').write_text(json.dumps(dict(updates=10000)))
    (tmp_path/'pipeline_status.json').write_text(json.dumps(dict(stage='failed_preserving_checkpoints_and_evidence',error='real error')))
    s=module.snapshot(tmp_path)
    assert s['pi05']['percent']==100
    assert s['afford_mask_warmup']['percent']==25
    assert s['afford_action_bc']['done']==0
    assert s['afford_mask_warmup']['eta_seconds'] is None
    assert s['combined_training']['done']==10250


def test_action_stage_keeps_warmup_separate(tmp_path):
    (tmp_path/'affordvla').mkdir()
    (tmp_path/'affordvla/training_status.json').write_text(json.dumps(dict(training_stage=2,stage_updates=500,stage='training')))
    s=module.snapshot(tmp_path)
    assert s['afford_mask_warmup']['done']==1000
    assert s['afford_action_bc']['percent']==5


def test_evaluator_reads_actual_two_hand_force_field():
    import ast
    source=Path(__file__).parents[1]/'scripts/compare_pickup120.py'
    tree=ast.parse(source.read_text(encoding='utf-8'))
    fields={n.slice.value for n in ast.walk(tree) if isinstance(n,ast.Subscript) and isinstance(n.value,ast.Name) and n.value.id=='obs' and isinstance(n.slice,ast.Constant)}
    assert 'gripper_contact_force' in fields
    assert 'gripper_force' not in fields
