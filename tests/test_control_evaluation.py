import pytest
from scripts.control_regression import summarize_results


def test_unique_clean_scene_coverage_excludes_recovery_and_diagnostics():
    source=[str(i) for i in range(400)]
    rows=[dict(scene_id='0',physics_success=True,attempt=a) for a in (0,1)]+[
        dict(scene_id='1',physics_success=True,recovery_used=True),
        dict(scene_id='2',physics_success=True,diagnostic_only=True)]
    report=summarize_results(rows,source,6)
    assert report['completed_attempts']==3 and report['clean_complete_attempts']==2
    assert report['clean_complete_successes']==1 and report['attempted_scenes']==2
    assert report['full_source_success_rate']==1/400
    assert not report['target_70_percent_reached'] and report['attempt_budget']==6


def test_target_requires_complete_400_source_even_with_280_successes():
    source=[str(i) for i in range(400)]
    rows=[dict(scene_id=str(i),physics_success=True) for i in range(280)]
    assert not summarize_results(rows,source,1)['target_70_percent_reached']
    rows += [dict(scene_id=str(i),physics_success=False) for i in range(280,400)]
    assert summarize_results(rows,source,1)['target_70_percent_reached']


def test_unregistered_scene_rejected_and_empty_run_not_success():
    with pytest.raises(ValueError,match='registered'):
        summarize_results([dict(scene_id='other')],['known'],1)
    report=summarize_results([],['known'],1)
    assert report['attempted_scene_success_rate'] is None
    assert not report['target_70_percent_reached']
