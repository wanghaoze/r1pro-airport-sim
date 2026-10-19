import json
from types import SimpleNamespace
import numpy as np,pytest
from r1pro_teleop.vla.prompts import normalize_prompt
from r1pro_teleop.vla.training import AirportInputs,AirportOutputs
from r1pro_teleop.vla.training_cache import validate_cache_source,file_sha,validate_three_table_metadata
from r1pro_teleop.vla.data_single_tray import ACTION_VOCABULARY
from r1pro_teleop.vla.data_three_table_single_tray import RULE_REVISION,FINAL_ORIENTATION_DEFINITION
PROFILE='three_table_single_tray_action3_v1'

def metadata():return dict(task_profile=PROFILE,task_rule_revision=RULE_REVISION,final_orientation_definition=FINAL_ORIENTATION_DEFINITION,base_mode='planar_mobile_table_front',base_actuated=True,model_action_mask=[True]*19,route_goal_observation_policy='fixed_registered_rear_to_front_left_route')

def test_exact_texts_and_real_mobile_commands_are_preserved():
 for row in ACTION_VOCABULARY:assert normalize_prompt(row['language_prompt'],PROFILE)==row['language_prompt']
 with pytest.raises(ValueError):normalize_prompt('Place the tray.',PROFILE)
 state=np.arange(19,dtype=np.float32);actions=np.arange(20*19,dtype=np.float32).reshape(20,19)
 sample={'state':state,'actions':actions,'prompt':'Place the tray'}
 for name in ('head_left','left_wrist','right_wrist'):sample['image/'+name]=np.zeros((224,224,3),np.uint8)
 transformed=AirportInputs(PROFILE)(sample);np.testing.assert_array_equal(transformed['state'],state);np.testing.assert_array_equal(transformed['actions'],actions)
 result=AirportOutputs(PROFILE)({'actions':actions});np.testing.assert_array_equal(result['actions'],actions);np.testing.assert_array_equal(result['raw_actions'],actions);assert result['model_action_mask'].tolist()==[True]*19
 with pytest.raises(ValueError,match='Fixed-front'):AirportInputs('single_tray_action3_v1')(sample)

def test_three_table_cache_accepts_only_complete_parent_train_mobile_scope(tmp_path):
 source=tmp_path/'source.jsonl';source.write_text('verified source file');spec=SimpleNamespace(prompt_mode=PROFILE,dataset_repo_id='airport/new_three')
 m=dict(metadata(),split='train',repo_id=spec.dataset_repo_id,prompt_mode=PROFILE,source_manifest=str(source),source_manifest_sha256=file_sha(source),dataset_ready=True,all_parquet_values_verified={'verified':True},new_task_source_guard_audit={'verified':True},action_vocabulary=[dict(r,task_index=i) for i,r in enumerate(ACTION_VOCABULARY)],complete_expected_scene_ids=['v1'],episodes=[dict(scene_id='v1',parent_scene_id='original1',parent_split='train',split='train')])
 validate_cache_source(spec,m,diagnostic_fixture=True);m['episodes'][0]['parent_split']='test'
 with pytest.raises(ValueError,match='parent_train_split'):validate_cache_source(spec,m,diagnostic_fixture=True)
 m['episodes'][0]['parent_split']='train';m['model_action_mask'][18]=False
 with pytest.raises(ValueError,match='all_actuated'):validate_cache_source(spec,m,diagnostic_fixture=True)
 m['model_action_mask']=[True]*19;m['route_goal_observation_policy']='hidden_random_target'
 with pytest.raises(ValueError,match='observable_fixed_registered_route'):validate_cache_source(spec,m,diagnostic_fixture=True)

def test_serving_milestone_mobile_status_cache_and_dataset_bind(tmp_path):
 from scripts.serve_pi05_airport import _verify_milestone_data
 run=tmp_path/'run';dataset=tmp_path/'dataset';(run/'data_cache').mkdir(parents=True);dataset.mkdir();cache=run/'data_cache/cache_manifest.json';accel=run/'acceleration_spec.json';train=dataset/'airport_training_manifest.json';source=dataset/'whole_action_source_manifest.jsonl';source.write_text('actualsource');cache.write_text(json.dumps(metadata()));accel.write_text('{}')
 train.write_text(json.dumps(dict(metadata(),dataset_ready=True,split='train',prompt_mode=PROFILE,repo_id='airport/new',source_manifest_sha256=file_sha(source))))
 status=dict(metadata(),cache_manifest=str(cache),acceleration_spec=str(accel),cache_manifest_sha256=file_sha(cache),acceleration_spec_sha256=file_sha(accel),dataset_training_manifest_sha256=file_sha(train),dataset_source_manifest_sha256=file_sha(source));spec=SimpleNamespace(run_dir=str(run),dataset_root=str(dataset),dataset_repo_id='airport/new',prompt_mode=PROFILE)
 assert len(_verify_milestone_data(status,spec))==4
 status['base_mode']='fixed_front'
 with pytest.raises(ValueError,match='mobile19_all_actuated'): _verify_milestone_data(status,spec)



def test_production_cache_rechecks_parent_split_registry_bytes(tmp_path):
 from test_vla_data_three_table_single_tray import fixture
 s,*_=fixture(tmp_path,'train');source=tmp_path/'sources.jsonl';source.write_text(json.dumps({'source':s})+'\n');spec=SimpleNamespace(prompt_mode=PROFILE,dataset_repo_id='airport/new_three')
 m=dict(metadata(),split='train',repo_id=spec.dataset_repo_id,prompt_mode=PROFILE,source_manifest=str(source),source_manifest_sha256=file_sha(source),dataset_ready=True,all_parquet_values_verified={'verified':True},new_task_source_guard_audit={'verified':True},action_vocabulary=[dict(r,task_index=i) for i,r in enumerate(ACTION_VOCABULARY)],complete_expected_scene_ids=[s['scene_id']],episodes=[dict(scene_id=s['scene_id'],parent_scene_id=s['parent_scene_id'],parent_split='train',split='train')])
 validate_cache_source(spec,m)
 from pathlib import Path
 Path(s['canonical_split_registry']).write_text(json.dumps({'parent':'test'}))
 with pytest.raises(ValueError,match='parent_source_changed:canonical_split_registry'):validate_cache_source(spec,m)



def test_old_left_goal_metadata_rejected_and_both_numeric_axes_retained():
 from r1pro_teleop.vla.data_three_table_lerobot import NUMERIC_KEYS
 assert 'robot_forward_world' in NUMERIC_KEYS and 'robot_left_world' in NUMERIC_KEYS and 'gripper_grasp_confirmed' in NUMERIC_KEYS
 m=metadata();m['final_orientation_definition']='tray_long_axis_parallel_robot_left'
 with pytest.raises(ValueError,match='forward_axis_metadata'):validate_three_table_metadata(m)
 m=metadata();del m['task_rule_revision']
 with pytest.raises(ValueError,match='forward_axis_metadata'):validate_three_table_metadata(m)
