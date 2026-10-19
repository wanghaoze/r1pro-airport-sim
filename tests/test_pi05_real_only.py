import importlib.util
from pathlib import Path
import numpy as np
import pytest

spec=importlib.util.spec_from_file_location('real_only',Path(__file__).parents[1]/'scripts/run_pi05_real_only.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


def manifests():
    return {s:dict(ready=True,source_domains=['real'],episodes=[dict(domain='real',split=s,task_index=t,raw_file_name=f'{s}_{t}',parquet_sha256=f'h_{s}_{t}') for t in (0,1)]) for s in ('train','val','test')}


def test_reject_sim_and_recording_or_content_leak():
    rows=manifests();m.validate_real_splits(rows)
    rows['train']['episodes'][0]['domain']='simulation'
    with pytest.raises(ValueError,match='domain'):m.validate_real_splits(rows)
    for field in ('raw_file_name','parquet_sha256'):
        rows=manifests();rows['test']['episodes'][0][field]=rows['train']['episodes'][0][field]
        with pytest.raises(ValueError,match='leak'):m.validate_real_splits(rows)


def test_real_schedule_is_reproducible_and_uses_both_tasks():
    tasks=np.array([0,0,0,1]);a=m.real_schedule(tasks,steps=50,batch=8)
    np.testing.assert_array_equal(a,m.real_schedule(tasks,steps=50,batch=8))
    assert a.min()>=0 and a.max()<len(tasks)
    assert .3<(tasks[a]==1).mean()<.7


def test_brightness_excludes_padding_but_keeps_intermittent_darkness():
    a=np.zeros((2,4,4,3),np.uint8);a[:,1:3,1:3]=100;a[0,1,1]=0
    b=m.brightness(a)
    assert b['sampled_content_pixels']==8
    assert b['mean']==pytest.approx(87.5)
    assert b['dark_fraction']==pytest.approx(.125)
