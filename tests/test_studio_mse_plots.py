import hashlib
import json
from pathlib import Path
import numpy as np
import pytest
from scripts.studio_mse_plots import aligned_data, ORDER, write


def fixture_run(tmp_path, models=2):
    run=tmp_path/'job_fixture';run.mkdir(); rows=[]; entries=[]
    for k in range(models):
        identifier=f'cp_fixture_{k}';out=run/identifier;out.mkdir()
        truth=np.zeros((3,20,19),np.float32);pred=np.broadcast_to(np.arange(1,20,dtype=np.float32),(3,20,19)).copy()*(k+1)
        valid=np.zeros((3,20),bool);valid[:,0]=True;valid[0,1]=True
        # Padded targets intentionally have large errors and must not contribute.
        pred[~valid]=1e6
        np.savez_compressed(out/'episode_000.npz',predicted=pred,truth=truth,valid=valid)
        per=((pred.astype(float)-truth)**2)[valid].mean(0)
        rows.append(dict(id=identifier,contract={'horizon':20},byEpisode=[{'prompt':'Pick up the tray'}],perChannelMseRad2OrM2=per[:16].tolist(),truthSha256=hashlib.sha256(truth.tobytes()).hexdigest(),validMaskSha256=hashlib.sha256(valid.tobytes()).hexdigest()))
        entries.append(dict(id=identifier,updates=10000,run='real_only_pi05_20261012_v1' if k else 'real_isaac300',source='real'))
    write(run/'report.json',dict(models=rows,frames=3,validTimesteps=4,split='test',protocol={'horizon':20}))
    write(run/'checkpoints.json',entries)
    return run


def test_native_order_and_padding(tmp_path):
    report,arrays,labels=aligned_data(fixture_run(tmp_path))
    np.testing.assert_allclose(arrays[0][4][ORDER],np.array([*range(1,8),*range(9,16),8,16])**2)
    assert arrays[0][4][ORDER][14]*1e6==64e6
    assert len(labels)==2 and 'Real-only' in labels[1]


def test_source_hash_change_is_rejected(tmp_path):
    run=fixture_run(tmp_path);p=run/'report.json';r=json.loads(p.read_text());r['models'][0]['truthSha256']='x';write(p,r)
    with pytest.raises(ValueError,match='plot_source_hash_mismatch'):aligned_data(run)


def test_metric_disagreement_is_rejected(tmp_path):
    run=fixture_run(tmp_path);p=run/'report.json';r=json.loads(p.read_text());r['models'][0]['perChannelMseRad2OrM2'][0]=0;write(p,r)
    with pytest.raises(AssertionError):aligned_data(run)


def test_paired_contract_disagreement_is_rejected(tmp_path):
    run=fixture_run(tmp_path);p=run/'report.json';r=json.loads(p.read_text());r['models'][1]['contract']['horizon']=10;write(p,r)
    with pytest.raises(ValueError,match='plot_protocol_mismatch'):aligned_data(run)


def test_missing_episode_is_rejected(tmp_path):
    run=fixture_run(tmp_path);(run/'cp_fixture_0/episode_000.npz').unlink()
    with pytest.raises(ValueError,match='plot_episode_coverage'):aligned_data(run)
