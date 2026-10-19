import pytest
from r1pro_teleop.vla.training_accelerated import milestone_target

def test_milestones_use_actual_completed_updates_not_checkpoint_index():
 assert [milestone_target(n) for n in [0,10,100,1000,10000]]==[10,100,1000,10000,100000]
 assert milestone_target(100000)==100000
 with pytest.raises(ValueError):milestone_target(-1)
 with pytest.raises(ValueError):milestone_target(True)


def test_prefetch_preserves_exact_step_and_sample_index_order():
 import numpy as np
 from r1pro_teleop.vla.training_accelerated import PrefetchedCacheBatches
 schedule=np.arange(32).reshape(8,4);produced=[]
 def producer(dataset,schedule,step):produced.append(step);return schedule[step].copy()
 batches=PrefetchedCacheBatches(None,schedule,3,8,depth=2,producer=producer)
 try:
  for step in range(3,8):np.testing.assert_array_equal(batches.get(step),schedule[step])
 finally:batches.close()
 assert produced==list(range(3,8))

def test_retention_preserves_all_evaluation_milestones_not_all_periodic():
 from r1pro_teleop.vla.training_accelerated import preserve_checkpoint
 assert all(preserve_checkpoint(step) for step in [9,99,999,9999,99999])
 assert not any(preserve_checkpoint(step) for step in [1999,2999,8999])


def test_visual_freeze_scope_excludes_language_lora_and_controller_heads():
 from r1pro_teleop.vla.training_accelerated import vision_parameter_filter
 assert vision_parameter_filter(('PaliGemma','img','encoder'),None)
 assert not vision_parameter_filter(('PaliGemma','llm','lora'),None)
 assert not vision_parameter_filter(('action_in_proj','kernel'),None)
 assert not vision_parameter_filter(('other','img','encoder'),None)


def test_long_run_duration_telemetry_is_bounded_and_keeps_exact_online_mean():
 from r1pro_teleop.vla.training_accelerated import DurationTelemetry
 telemetry=DurationTelemetry();telemetry.update(25)
 for _ in range(90000):telemetry.update(2)
 result=telemetry.summary()
 assert len(result['last32_update_seconds'])==32 and result['warm_count']==90000
 assert result['warm_mean_seconds']==2 and result['first_update_including_compile_seconds']==25
 with pytest.raises(ValueError):telemetry.update(float('nan'))
