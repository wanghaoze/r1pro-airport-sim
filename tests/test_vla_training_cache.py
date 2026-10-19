import json
import numpy as np
import pytest
from r1pro_teleop.vla.training_cache import flatten,unflatten,balanced_schedule,CachedDataset,file_sha,SCHEMA

def test_nested_cache_roundtrip_preserves_uint8_and_float32():
 sample={'images':{'base':np.arange(24,dtype=np.uint8).reshape(2,4,3)},'state':np.ones(19,np.float32),'tokenized_prompt':np.arange(3,dtype=np.int32)}
 restored=unflatten(flatten(sample))
 assert restored['images']['base'].dtype==np.uint8
 np.testing.assert_array_equal(restored['state'],sample['state'])
 with pytest.raises(ValueError):flatten({'prompt':'unknown'})

def test_schedule_resume_is_exact_and_classes_balanced_despite_source_skew():
 labels=np.concatenate([np.zeros(1000,np.int32),np.arange(1,8,dtype=np.int32)])
 schedule=balanced_schedule(labels,8,10000,42)
 np.testing.assert_array_equal(schedule,balanced_schedule(labels,8,10000,42))
 assert schedule[10:].shape==(9990,8)
 counts=np.bincount(labels[schedule.ravel()],minlength=8)
 assert np.all(np.abs(counts/80000-1/8)<.005)
 with pytest.raises(ValueError):balanced_schedule(np.arange(7),8,10,42)

def test_cache_memmap_reads_independent_arrays_and_rejects_mutation(tmp_path):
 path=tmp_path/'leaf.npy';np.save(path,np.ones((2,19),np.float32))
 manifest={'schema':SCHEMA,'status':'complete','split':'train','frames':2,'leaves':[{'path':'leaf.npy','keys':['state'],'sha256':file_sha(path),'shape':[2,19],'dtype':'float32'}]}
 (tmp_path/'cache_manifest.json').write_text(json.dumps(manifest))
 cached=CachedDataset(tmp_path);sample=cached[0];sample['state'][0]=8
 assert cached[0]['state'][0]==1
 with pytest.raises(IndexError):cached[2]
 cached.leaves.clear()
 import gc;gc.collect()
 np.save(path,np.zeros((2,19),np.float32))
 with pytest.raises(ValueError,match='resource_changed'):CachedDataset(tmp_path)


def test_cache_rejects_holdout_and_changed_training_spec(tmp_path):
 from types import SimpleNamespace
 from r1pro_teleop.vla.training_cache import validate_cache_source,validate_cache_spec
 path=tmp_path/'source.jsonl';path.write_bytes(b'original')
 spec=SimpleNamespace(prompt_mode='task_complete_action8_v1',dataset_repo_id='airport/train',action_horizon=20,batch_size=8,num_train_steps=100000,seed=42,dataset_root=str(tmp_path))
 manifest=dict(split='val',episodes=[],repo_id='airport/train',prompt_mode=spec.prompt_mode,source_manifest=str(path),source_manifest_sha256=file_sha(path),all_parquet_values_verified={'verified':True})
 with pytest.raises(ValueError,match='holdout'):validate_cache_source(spec,manifest,diagnostic_fixture=True)
 manifest['split']='train';validate_cache_source(spec,manifest,diagnostic_fixture=True)
 path.write_bytes(b'changed')
 with pytest.raises(ValueError,match='manifest_changed'):validate_cache_source(spec,manifest,diagnostic_fixture=True)
 cache=dict(prompt_mode=spec.prompt_mode,repo_id=spec.dataset_repo_id,action_horizon=20,batch_size=8,total_steps=100000,seed=42,dataset_root=str(tmp_path))
 validate_cache_spec(spec,cache);cache['seed']=7
 with pytest.raises(ValueError,match='seed'):validate_cache_spec(spec,cache)

def test_model_staging_float64_cast_matches_official_jax_fp32_input():
 values=np.array([.123456789123],np.float64)
 assert flatten({'state':values},model_float32=True)[('state',)].dtype==np.float32
 np.testing.assert_array_equal(flatten({'state':values},model_float32=True)[('state',)],values.astype(np.float32))
