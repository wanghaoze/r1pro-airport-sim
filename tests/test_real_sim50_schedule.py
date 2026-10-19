import importlib.util
from pathlib import Path
import numpy as np
import json
import pytest

spec=importlib.util.spec_from_file_location('mix50',Path(__file__).parents[1]/'scripts/train_pi05_real_sim50.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


def test_exact_domain_balance_task_balance_and_reproducibility():
    real=np.array([0]*7+[1]*3);sim=np.array([0]*5+[1]*4+[2]*2)
    d,i=module.schedule(real,sim,steps=100)
    assert np.all((d==0).sum(axis=1)==4) and np.all((d==1).sum(axis=1)==4)
    assert np.array_equal(i,module.schedule(real,sim,steps=100)[1])
    for domain,tasks in [(0,real),(1,sim)]:
        selected=tasks[i[d==domain]];counts=np.unique(selected,return_counts=True)[1]
        assert counts.max()-counts.min()<=1


def test_isaac_binding_does_not_accept_legacy_or_unclosed_cache(tmp_path):
    run=tmp_path/'run';run.mkdir()
    (run/'isaac_inputs.json').write_text(json.dumps(dict(engine='mujoco',physics_backend='physx')))
    with pytest.raises(ValueError,match='Native Isaac cache binding'):
        module.prepare(run)
    cache=tmp_path/'cache';cache.mkdir()
    (cache/'integrity.json').write_text('{}')
    (cache/'train').mkdir()
    (cache/'train/manifest.json').write_text(json.dumps(dict(schema='old_mujoco_cache',ready=True)))
    (run/'isaac_inputs.json').write_text(json.dumps(dict(engine='isaacsim',physics_backend='physx',cache_root=str(cache))))
    with pytest.raises(ValueError,match='All native cache splits'):
        module.prepare(run)
    assert not (run/'preparation_status.json').exists()
