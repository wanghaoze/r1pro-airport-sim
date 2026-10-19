import json
from pathlib import Path
import pytest
from r1pro_teleop.single_tray_3table.evaluation_batch import verify_zero_frame_infrastructure,summary,handoff,PROFILE


def test_zero_frame_initialization_is_infra_not_model_failure_or_video(tmp_path):
 case=tmp_path/'case';case.mkdir();r=dict(task_profile=PROFILE,checkpoint_id='actual10',scene_id='scene',split='test',frames=0,physical_episode_started=False,actual_inference_calls=0,task_completed=False,zero_frame_evidence={'native_video_possible':False},inverse_solver_calls=None,failure_code='ValueError',failure_detail='profile initialization')
 (case/'result.json').write_text(json.dumps(r));row=verify_zero_frame_infrastructure(case,'actual10','scene','test')
 assert row['videos']==[] and row['model_task_outcome']=='unavailable_no_model_execution' and row['inverse_solver_calls'] is None
 report=summary([row,dict(task_completed=False,failure_code='model_budget',videos=[])],2,'scope')
 assert report['attempted']==2 and report['covered']==1 and report['infrastructure_error_count']==1 and report['failures']=={'model_budget':1} and report['complete_task_rate'] is None
 m=tmp_path/'milestone.json';m.write_text(json.dumps(dict(schema='airport_pi05_training_milestone/1',prompt_mode=PROFILE,status='milestone_checkpoint',checkpoint_verified=True,actual_completed_updates=10)))
 p=tmp_path/'summary.json';p.write_text(json.dumps(report))
 with pytest.raises(ValueError,match='coverage'):handoff(m,'scope',p,[dict(returncode=0,active=False)],[])
 r['actual_inference_calls']=1;(case/'result.json').write_text(json.dumps(r))
 with pytest.raises(ValueError,match='zero_frame'):verify_zero_frame_infrastructure(case,'actual10','scene','test')

def test_per_action_completion_requires_verified_real_span_attempts_use_actual_events():
 from r1pro_teleop.single_tray_3table.evaluation_batch import action_evidence
 r=dict(frames=20,actual_inference_calls=3,inverse_solver_calls=0,teacher_fallback_calls=0,action_spans=[dict(action_label='pick_empty',verified=True,start_frame=0,end_frame=10,measured_endpoint_frame=9),dict(action_label='place_empty',verified=False,start_frame=10,end_frame=20,measured_endpoint_frame=19)])
 row=action_evidence(r,[dict(event='action_start',action_label='pick_empty'),dict(event='action_start',action_label='place_empty')]);row.update(task_completed=False,failure_code='place_budget')
 assert row['per_action_completed']==dict(pick_empty=True,place_empty=False,push_loaded=False)
 assert row['per_action_status']==dict(pick_empty='completed_verified',place_empty='attempted_incomplete',push_loaded='not_attempted')
 report=summary([row],1,'scope')
 assert report['action_complete_counts']=={'Pick up the tray':1,'Place the tray':0,'Flush tray to the left':0}
 assert row['actual_inference_calls']==3 and row['inverse_solver_calls']==0
 r['action_spans'][0]['end_frame']=30
 with pytest.raises(ValueError,match='actual_trace'):action_evidence(r,[])

def test_new_scope_raw2_missing_contact_peaks_is_unavailable_not_rejected_or_strict_passed(tmp_path):
 import h5py
 from r1pro_teleop.single_tray_lab.contact_summary import audit_contact_peaks
 path=tmp_path/'trace.h5'
 with h5py.File(path,'w') as f:
  f.attrs['schema']='airport_fsm_raw/2';f.attrs['metadata_json']=json.dumps({'task_profile':PROFILE})
 answer=audit_contact_peaks({'frames':3},path,raw_schema='airport_fsm_raw/2',task_profile=PROFILE)
 assert answer['coverage']=='unavailable' and answer['strict_contact_success'] is None
 with pytest.raises(ValueError,match='raw2_contact'):audit_contact_peaks({'frames':3},path)
 with pytest.raises(ValueError,match='profile_mismatch'):audit_contact_peaks({'frames':3},path,raw_schema='airport_fsm_raw/2',task_profile='old_three_tray')
