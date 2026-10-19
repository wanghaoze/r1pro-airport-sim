from types import SimpleNamespace
import json
import numpy as np
import pytest
from r1pro_teleop.vla.prompts import normalize_prompt,validate_prompt_mode
from r1pro_teleop.vla.data_single_tray import ACTION_VOCABULARY,PROFILE
from r1pro_teleop.vla.training_cache import balanced_schedule,validate_cache_source,file_sha

def test_exact_three_prompts_do_not_relabel_old_eight_language():
 assert validate_prompt_mode(PROFILE)==PROFILE
 for row in ACTION_VOCABULARY:assert normalize_prompt(row['language_prompt'],PROFILE)==row['language_prompt']
 for text in ('Pick up the empty tray.','Carry the tray to position 1.','Flush tray to the left.'):
  with pytest.raises(ValueError):normalize_prompt(text,PROFILE)
 with pytest.raises(ValueError):normalize_prompt('Pick up the tray','task_complete_action8_v1')

def test_new_three_schedule_is_balanced_and_old_eight_default_unchanged():
 labels=np.r_[np.zeros(1000,dtype=int),[1,2]];schedule=balanced_schedule(labels,8,1000,42,class_count=3)
 assert np.all(np.abs(np.bincount(labels[schedule.ravel()])/8000-1/3)<.025)
 np.testing.assert_array_equal(schedule,balanced_schedule(labels,8,1000,42,class_count=3))
 with pytest.raises(ValueError):balanced_schedule(labels,8,1000,42)

def test_three_cache_requires_fixed_mask_and_declared_complete_scene_population(tmp_path):
 source=tmp_path/'source.jsonl';source.write_text('source');spec=SimpleNamespace(prompt_mode=PROFILE,dataset_repo_id='airport/new')
 manifest=dict(split='train',repo_id=spec.dataset_repo_id,prompt_mode=PROFILE,source_manifest=str(source),source_manifest_sha256=file_sha(source),dataset_ready=True,all_parquet_values_verified={'verified':True},base_mode='fixed_front',base_actuated=False,model_action_mask=[True]*16+[False]*3,action_vocabulary=[dict(row,task_index=i) for i,row in enumerate(ACTION_VOCABULARY)],complete_expected_scene_ids=['new'],episodes=[dict(scene_id='new',split='train')])
 validate_cache_source(spec,manifest)
 manifest['model_action_mask'][-1]=True
 with pytest.raises(ValueError,match='fixed_base_mask'):validate_cache_source(spec,manifest)
 manifest['model_action_mask'][-1]=False;manifest['complete_expected_scene_ids'].append('missing')
 with pytest.raises(ValueError,match='declared'):validate_cache_source(spec,manifest)

def test_single_tray_output_explicit_mask_preserves_raw_and_never_masks_active_joints():
 from r1pro_teleop.vla.training import AirportOutputs
 raw=np.arange(20*32,dtype=np.float32).reshape(20,32)*.00001
 result=AirportOutputs(PROFILE)({'actions':raw})
 np.testing.assert_array_equal(result['actions'][:,:16],raw[:,:16])
 assert np.all(result['actions'][:,16:]==0)
 np.testing.assert_array_equal(result['raw_actions'],raw[:,:19])
 assert result['model_action_mask'].tolist()==[True]*16+[False]*3
 assert set(AirportOutputs()({'actions':raw}))=={'actions'}

def test_serving_three_profile_binds_status_cache_dataset_fixed_base_masks(tmp_path):
 from scripts.serve_pi05_airport import _verify_milestone_data
 from r1pro_teleop.vla.training_cache import file_sha
 run=tmp_path/'run';dataset=tmp_path/'dataset';(run/'data_cache').mkdir(parents=True);dataset.mkdir()
 cache=run/'data_cache/cache_manifest.json';accel=run/'acceleration_spec.json';train=dataset/'airport_training_manifest.json';source=dataset/'whole_action_source_manifest.jsonl';source.write_text('source')
 fixed=dict(base_mode='fixed_front',base_actuated=False,model_action_mask=[True]*16+[False]*3)
 cache.write_text(json.dumps(fixed));accel.write_text('{}')
 manifest=dict(fixed,dataset_ready=True,split='train',prompt_mode=PROFILE,repo_id='airport/new',source_manifest_sha256=file_sha(source));train.write_text(json.dumps(manifest))
 status=dict(fixed,cache_manifest=str(cache),acceleration_spec=str(accel),cache_manifest_sha256=file_sha(cache),acceleration_spec_sha256=file_sha(accel),dataset_training_manifest_sha256=file_sha(train),dataset_source_manifest_sha256=file_sha(source))
 spec=SimpleNamespace(run_dir=str(run),dataset_root=str(dataset),dataset_repo_id='airport/new',prompt_mode=PROFILE)
 assert len(_verify_milestone_data(status,spec))==4
 status['base_actuated']=True
 with pytest.raises(ValueError,match='fixed-base mask'): _verify_milestone_data(status,spec)
