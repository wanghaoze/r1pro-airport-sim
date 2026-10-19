import numpy as np
import pytest
from r1pro_teleop.vla.parallel_pickplace_training import duration_sampling_weights,balanced_mixed_schedule,cache_estimate


def source(split='train'):
    tasks=np.repeat([0,0,1,1],[20,80,20,80])
    episodes=[dict(split=split,task_index=t,offset=o,frames=n) for t,o,n in [(0,0,20),(0,20,80),(1,100,20),(1,120,80)]]
    return tasks,episodes


def test_duration_sampling_changes_effective_training_samples_without_dropping_frames():
    tasks,episodes=source();weights,report=duration_sampling_weights(tasks,episodes)
    assert weights.min()==pytest.approx(.625/80) and weights.max()==pytest.approx(2/20)
    d,i=balanced_mixed_schedule(tasks,tasks,steps=1000,real_weights=weights,sim_weights=weights)
    ud,ui=balanced_mixed_schedule(tasks,tasks,steps=1000)
    short=lambda ix:np.mean((ix<20)|((ix>=100)&(ix<120)))
    assert short(i)>.70 and short(i)>short(ui)+.15
    assert report['episodes'][0]['source_probability_within_domain_action']>report['episodes'][1]['source_probability_within_domain_action']
    assert set(i.ravel())==set(range(len(tasks)))
    assert report['frames_trimmed']==0 and report['not_RL']
    for domain in (0,1):
        for row,indices in zip(d,i):
            selected=indices[row==domain]
            assert len(selected)==4 and sum(tasks[selected]==0)==2 and sum(tasks[selected]==1)==2


def test_validation_or_test_durations_cannot_change_weights():
    for split in ('val','test'):
        tasks,episodes=source(split)
        with pytest.raises(ValueError,match='train_only'):duration_sampling_weights(tasks,episodes)


def test_same_three_second_duration_means_no_fake_speed_reward():
    tasks=np.repeat([0,1],60)
    episodes=[dict(split='train',task_index=t,offset=t*60,frames=60) for t in (0,1)]
    weights,report=duration_sampling_weights(tasks,episodes)
    assert np.allclose(weights,np.ones(120)/60)
    assert report['median_seconds']=={0:3.,1:3.}


def test_weight_statistics_are_domain_local():
    tasks,episodes=source();w,_=duration_sampling_weights(tasks,episodes)
    other=[dict(e,frames=e['frames']*2,offset=e['offset']*2) for e in episodes]
    ow,_=duration_sampling_weights(np.repeat(tasks,2),other)
    assert np.array_equal(np.repeat(w/2,2),ow)


def test_cache_estimate_does_not_count_fourth_camera_as_model_input():
    estimate=cache_estimate(300*2*60)
    assert estimate['rgb_bytes']==16257024000
    assert estimate['checkpoint_bytes_not_included']
