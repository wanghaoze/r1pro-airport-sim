import json,pytest
from scripts.supervise_verified_three_action_training import validate

def test_fresh_completed_data_only_is_not_training(tmp_path):
    p=tmp_path/'options.json';p.write_text(json.dumps(dict(data_only=True,completed_dataset_run='/old',run_dir=str(tmp_path),spec=str(tmp_path/'training_spec.json'))))
    with pytest.raises(ValueError,match='fresh_optimizer'):validate(p)

def test_old_optimizer_resume_and_foreign_spec_rejected(tmp_path):
    o=dict(data_only=False,completed_dataset_run='/old',run_dir=str(tmp_path),spec=str(tmp_path/'training_spec.json'));p=tmp_path/'options.json'
    p.write_text(json.dumps(dict(o,external_training_run='/old_optimizer')))
    with pytest.raises(ValueError,match='fresh_optimizer'):validate(p)
    p.write_text(json.dumps(dict(o,spec='/foreign/training_spec.json')))
    with pytest.raises(ValueError,match='fresh_training_spec'):validate(p)

def test_completed_frozen_data_fresh_optimizer_allowed(tmp_path):
    o=dict(data_only=False,completed_dataset_run='/old',run_dir=str(tmp_path),spec=str(tmp_path/'training_spec.json'));p=tmp_path/'options.json';p.write_text(json.dumps(o))
    assert validate(p)==o
