from types import SimpleNamespace
import pytest
from r1pro_teleop.airport_fsm.batch import attempt_stopping_success
from scripts.control_regression import summarize_results


def test_completion_stops_after_recovered_actual_task_and_legacy_fallback():
 c=SimpleNamespace(acceptance_profile='completion_first')
 assert attempt_stopping_success(dict(task_completed=True,recovery_used=True,export_rejected=True),c,resumed=True)
 assert attempt_stopping_success(dict(physics_success=True,recovery_used=True),c)
 assert not attempt_stopping_success(dict(task_completed=False,physics_success=True),c)
 assert not attempt_stopping_success(dict(task_completed=True,diagnostic_only=True),c)


def test_strict_stopping_keeps_existing_export_resume_and_recovery_semantics():
 c=SimpleNamespace(acceptance_profile='strict')
 assert not attempt_stopping_success(dict(physics_success=True,recovery_used=True),c)
 r=dict(physics_success=True,export_rejected=True)
 assert attempt_stopping_success(r,c)
 assert not attempt_stopping_success(r,c,resumed=True)


def test_budget_closed_requires_success_or_all_three_terminal_attempts():
 rows=[dict(scene_id='a',attempt=0,task_completed=False),dict(scene_id='b',attempt=0,task_completed=True,recovery_used=True)]
 p=summarize_results(rows,['a','b'],3)
 assert p['all_400_attempted'] is False and not p['budget_closed']
 assert p['first_attempt_task_completion_rate']==.5 and p['budget_task_completion_rate'] is None
 rows.extend(dict(scene_id='a',attempt=i,task_completed=i==2) for i in (1,2))
 p=summarize_results(rows,['a','b'],3)
 assert p['budget_closed'] and p['budget_task_completion_rate']==1
 assert p['first_attempt_task_completion_rate']==.5 and p['completed_attempts']==4
 assert p['per_scene_attempts']['a']['closure_reason']=='task_completed'


@pytest.mark.parametrize('rows',[
 [dict(scene_id='a',attempt=0),dict(scene_id='a',attempt=0)],
 [dict(scene_id='a',attempt=1)], [dict(scene_id='a',attempt=3)],
 [dict(scene_id='a',attempt=True)]])
def test_duplicate_gap_and_invalid_budget_identity_rejected(rows):
 with pytest.raises(ValueError):summarize_results(rows,['a'],3)


def test_diagnostics_never_cover_or_close_and_full400_denominator_stays():
 p=summarize_results([dict(scene_id='0',task_completed=True),dict(scene_id='1',attempt=2,diagnostic_only=True)],map(str,range(400)),3)
 assert p['attempted_scenes']==1 and p['first_attempt_task_completion_rate']==1/400
 assert p['task_completion_rate']==1/400 and p['budget_task_completion_rate'] is None
 assert not p['per_scene_attempts']['1']['budget_closed']


def test_exhausted_failure_closes_without_counting_success():
 p=summarize_results([dict(scene_id='a',attempt=i,physics_success=False) for i in range(3)],['a'],3)
 assert p['budget_closed'] and p['budget_task_completion_rate']==0
 assert p['per_scene_attempts']['a']['closure_reason']=='attempt_budget_exhausted'

@pytest.mark.parametrize('resume',[False,True])
def test_batch_does_not_spawn_after_completed_recovered_task(tmp_path,monkeypatch,resume):
 import json
 from r1pro_teleop.airport_fsm import batch
 from r1pro_teleop.airport_fsm.contracts import atomic_json
 cfg=SimpleNamespace(acceptance_profile='completion_first',max_attempts_per_scene=3,successes_per_scene=1,max_attempt_wall_seconds=5)
 (tmp_path/'attempts').mkdir();atomic_json(tmp_path/'scenes/a/preflight.json',dict(valid=True))
 monkeypatch.setattr(batch,'config_for',lambda root:cfg)
 monkeypatch.setattr(batch,'assert_environment',lambda root:None)
 monkeypatch.setattr(batch,'selected_rows',lambda *args:[dict(scene_id='a',split='train')])
 monkeypatch.setattr(batch,'preflight_coverage',lambda *args,**kwargs:None)
 monkeypatch.setattr(batch,'coverage',lambda root:{})
 calls=[]
 def worker(args,*unused):
  attempt=int(args[-1]);calls.append(attempt)
  atomic_json(tmp_path/f'attempts/a/a{attempt:03d}/result.json',dict(scene_id='a',attempt=attempt,physics_success=True,task_completed=True,recovery_used=True))
  return 0
 monkeypatch.setattr(batch,'run_child',worker)
 if resume:
  worker(['0']);calls.clear()
 batch.generate(tmp_path,workers=1)
 assert calls==([] if resume else [0])
 assert not (tmp_path/'attempts/a/a001').exists()


def test_selected_closure_cost_and_strict_stopping_are_distinct():
 rows=[dict(scene_id='a',attempt=0,task_completed=True,physics_success=True,recovery_used=True,simulation_seconds=10,physical_elapsed_seconds=10.02,wall_seconds=15)]
 p=summarize_results(rows,['a','b'],3,selected_ids=['a'],acceptance_profile='strict')
 assert p['selected_budget_closed'] and not p['budget_closed']
 assert p['selected_task_completion_rate']==1 and p['task_completion_rate']==.5
 assert not p['selected_stopping_budget_closed']
 assert p['total_simulation_seconds']==10 and p['total_physical_elapsed_seconds']==10.02 and p['total_attempt_wall_seconds']==15
 assert 'subset' in p['selected_rate_qualification']
 p=summarize_results(rows,['a','b'],3,selected_ids=['a'],acceptance_profile='completion_first')
 assert p['selected_stopping_budget_closed']


def test_legacy_70_flag_waits_for_failure_budgets_to_close():
 rows=[dict(scene_id=str(i),attempt=0,physics_success=i<280) for i in range(400)]
 p=summarize_results(rows,map(str,range(400)),3)
 assert p['all_400_attempted'] and not p['target_70_percent_reached']
