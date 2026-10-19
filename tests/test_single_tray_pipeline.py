import json
from pathlib import Path
import pytest
from r1pro_teleop.vla.single_tray_pipeline import campaign_gate

def test_all_failed_campaign_stays_blocked_not_fake_training_ready(tmp_path):
 status=dict(task_profile='single_tray_action3_v1',stage='physical_candidates_complete_requires_native_replay_and_export_audit',selected=54,completed=54,results=[dict(task_completed=False,returncode=2)])
 (tmp_path/'status.json').write_text(json.dumps(status));proof=campaign_gate(tmp_path)
 assert proof['ready'] is False and proof['successful_splits']=={'train':[],'val':[],'test':[]}

def test_partial_campaign_not_published_and_legacy_scope_rejected(tmp_path):
 path=tmp_path/'status.json';path.write_text(json.dumps(dict(task_profile='single_tray_action3_v1',selected=3,completed=1,stage='physical_candidate_generation')))
 assert campaign_gate(tmp_path) is None
 path.write_text(json.dumps(dict(task_profile='task_complete_action8_v1')))
 with pytest.raises(ValueError,match='new_single'):campaign_gate(tmp_path)

def test_three_splits_require_actual_complete_result_not_only_summary_flags(tmp_path):
 results=[]
 for split in ('train','val','test'):
  folder=tmp_path/split;folder.mkdir();path=folder/'result.json';path.write_text(json.dumps(dict(task_completed=True,physics_success=True,training_eligible=True,split=split)));results.append(dict(task_completed=True,returncode=0,split=split,result=str(path)))
 (tmp_path/'status.json').write_text(json.dumps(dict(task_profile='single_tray_action3_v1',selected=3,completed=3,stage='physical_candidates_complete_requires_native_replay_and_export_audit',results=results)))
 assert campaign_gate(tmp_path)['ready'] is True
 result=tmp_path/'test/result.json';result.write_text(json.dumps(dict(task_completed=False,physics_success=False,training_eligible=False,split='test')))
 with pytest.raises(ValueError,match='actual_complete'):campaign_gate(tmp_path)

def test_milestone_waits_for_new_scope_bound_receipt_and_rejects_old_task(tmp_path):
 from r1pro_teleop.vla.single_tray_pipeline import new_evaluation_gate
 from r1pro_teleop.vla.training_cache import file_sha
 milestone=tmp_path/'milestone.json';milestone.write_text('saved real checkpoint status');receipt=tmp_path/'completion_receipt.json'
 assert new_evaluation_gate(receipt,milestone,10) is False
 value=dict(schema='airport_single_tray_evaluation_handoff/1',task_profile='single_tray_action3_v1',actual_completed_updates=10,training_status_sha256=file_sha(milestone),status='evaluation_completed_gpu_released',training_resume_allowed=True,new_single_tray_protocol_id='sha256:new-fixed-single-tray-scenes')
 receipt.write_text(json.dumps(value));assert new_evaluation_gate(receipt,milestone,10)
 value['task_profile']='task_complete_action8_v1';receipt.write_text(json.dumps(value))
 with pytest.raises(ValueError,match='evaluation_receipt'):new_evaluation_gate(receipt,milestone,10)
 value['task_profile']='single_tray_action3_v1';value['training_status_sha256']='stale';receipt.write_text(json.dumps(value))
 with pytest.raises(ValueError,match='evaluation_receipt'):new_evaluation_gate(receipt,milestone,10)

def test_actual_run_cli_metadata_uses_control_profile_and_binds_result_trace_scene():
 import copy
 from r1pro_teleop.vla.single_tray_pipeline import validate_run_metadata
 fixture=json.loads((Path(__file__).parent/'fixtures/single_tray_cli_actual_metadata_fixture.json').read_text())
 assert fixture['source_is_failed_not_training'] is True and 'profile' not in fixture['result']
 result=fixture['result'];scene=fixture['scene'];metadata=fixture['metadata'];frames=fixture['frames']
 assert validate_run_metadata(scene,result,metadata,frames)==result['control_profile']
 changed=copy.deepcopy(result);changed['control_profile']['contact_n']+=.1
 with pytest.raises(ValueError,match='control_profile_disagreement'):validate_run_metadata(scene,changed,metadata,frames)
 changed=copy.deepcopy(metadata);changed['model_action_mask'][-1]=True
 with pytest.raises(ValueError,match='fixed_base'):validate_run_metadata(scene,result,changed,frames)
 changed=copy.deepcopy(scene);changed['config']['seed']+=1
 with pytest.raises(ValueError,match='scene_identity'):validate_run_metadata(changed,result,metadata,frames)

def test_auto_evaluation_uses_only_new_batch_driver_with_explicit_gpu_and_execute(tmp_path):
 from r1pro_teleop.vla.single_tray_pipeline import evaluation_command
 from r1pro_teleop.vla.training_cache import file_sha
 release=tmp_path/'release';(release/'scripts').mkdir(parents=True);protocol=tmp_path/'protocol.json';protocol.write_text('new scope')
 options=dict(release=str(release),evaluation_protocol=str(protocol),evaluation_protocol_sha256=file_sha(protocol),vla_python='model_python',sim_python='sim_python',spec='training_spec.json')
 assert evaluation_command(options,'immutable.json','new_eval') is None
 (release/'scripts/evaluate_single_tray_pi05_batch.py').write_text('actual driver')
 command=evaluation_command(options,'immutable.json','new_eval')
 assert command[1].endswith('evaluate_single_tray_pi05_batch.py') and '--execute' in command and command[command.index('--port')+1]=='8013'
 assert command[command.index('--milestone')+1]=='immutable.json' and 'evaluate_action8' not in ' '.join(command)
 protocol.write_text('changed')
 with pytest.raises(ValueError,match='protocol_changed'):evaluation_command(options,'immutable.json','new_eval')
