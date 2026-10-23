import json
import sys
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import pytest
from r1pro_teleop.vla.request_inbox import RequestInbox


def test_sequence_waits_for_atomic_publish_and_acknowledgment(tmp_path):
    inbox=RequestInbox(tmp_path,[31,2])
    later=tmp_path/'room031_000001.request.npz';later.touch()
    first=tmp_path/'room031_000000.request.npz'
    temporary=first.with_suffix('.tmp');temporary.touch()
    other=tmp_path/'room002_000000.request.npz';other.touch()
    assert list(inbox.ready())==[(2,other)]
    temporary.replace(first)
    assert list(inbox.ready())==[(2,other),(31,first)]
    # No subscribers yet: no acknowledgment, so the same request remains ready.
    assert list(inbox.ready())==[(2,other),(31,first)]
    with pytest.raises(ValueError,match='sequence_mismatch'):inbox.acknowledge(31,later)
    inbox.acknowledge(31,first)
    assert list(inbox.ready())==[(2,other),(31,later)]
    assert first.exists() and later.exists()


@pytest.mark.parametrize('ids',[[],[True],[-1],[1,1],['1']])
def test_invalid_room_contract_rejected(ids,tmp_path):
    with pytest.raises(ValueError,match='invalid_policy_inbox_rooms'):RequestInbox(tmp_path,ids)


def test_poll_work_is_bounded_by_rooms_not_history(tmp_path,monkeypatch):
    inbox=RequestInbox(tmp_path,[0,31]);inbox.next_sequence.update({0:40000,31:80000})
    checked=[]
    def exists(path):checked.append(path.name);return False
    def no_glob(*args,**kwargs):raise AssertionError('history enumeration is forbidden')
    monkeypatch.setattr(Path,'is_file',exists)
    monkeypatch.setattr(Path,'glob',no_glob)
    assert list(inbox.ready())==[]
    assert checked==['room000_040000.request.npz','room031_080000.request.npz']


@pytest.mark.parametrize('first_fails',[False,True])
def test_real_file_service_handles_each_sequence_once_and_retains_evidence(tmp_path,monkeypatch,first_fails):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1]/'scripts'))
    import studio_vla_evaluate as service
    monkeypatch.setenv('CUDA_VISIBLE_DEVICES','')
    directory=tmp_path/'policy';directory.mkdir()
    (tmp_path/'request.json').write_text(json.dumps({'payload':{'roomIds':[31]}}))
    (tmp_path/'checkpoints.json').write_text(json.dumps([{'id':'test','receiptSha256':'test'}]))
    for seq in range(2):
        np.savez(directory/f'room031_{seq:06d}.request.npz',state=np.full(19,seq),prompt='Pick up the tray',
                 **{'image/'+c:np.zeros((4,4,3),np.uint8) for c in ('head_left','left_wrist','right_wrist')})
    (directory/'room999_000000.request.npz').touch()  # unregistered room, never read
    seen=[]
    def infer(sample):
        seen.append(int(sample['state'][0]))
        if len(seen)==2:(directory/'stop').touch()
        if first_fails and len(seen)==1:raise RuntimeError('test_model_failure')
        return {'actions':np.zeros((20,19),np.float32)}
    monkeypatch.setattr(service,'load_registered_policy',lambda _:SimpleNamespace(infer=infer))
    # Fail boundedly if a regression repeats the first request instead of advancing.
    sleeps=[]
    def sleep(_):
        sleeps.append(1)
        if len(sleeps)>3:raise AssertionError('service did not advance')
    monkeypatch.setattr(service.time,'sleep',sleep)
    service.serve(tmp_path)
    assert seen==[0,1]
    assert (directory/'room031_000001.reply.npz').exists()
    if first_fails:assert 'test_model_failure' in (directory/'room031_000000.error.json').read_text()
    else:assert (directory/'room031_000000.reply.npz').exists()
    assert len(list(directory.glob('*.request.npz')))==3
    assert json.loads((directory/'heartbeat.json').read_text())['inference_requests']==2
