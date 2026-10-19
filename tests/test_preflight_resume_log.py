"""Interrupted preflight can resume without deleting or overwriting old evidence."""
import json
from pathlib import Path
from test_selected_preflight import collection
from r1pro_teleop.airport_fsm import batch
from r1pro_teleop.airport_fsm.contracts import atomic_json


def test_interrupted_log_without_report_uses_new_exclusive_log(collection,monkeypatch):
    root,rows,_=collection;row=rows[0];folder=root/'scenes'/row['scene_id'];folder.mkdir()
    old=folder/'preflight.log';old.write_bytes(b'original partial worker evidence\n')
    prior=folder/'preflight_resume_123.log';prior.write_bytes(b'older retry evidence\n')
    monkeypatch.setattr(batch.time,'time_ns',lambda:456)
    logs=[]
    def worker(args,log,timeout):
        logs.append(Path(log));assert timeout==180.
        assert args[-1]==row['scene_id']
        with Path(log).open('x') as out:out.write('new worker complete\n')
        atomic_json(folder/'preflight.json',dict(scene_id=row['scene_id'],split=row['split'],valid=True))
        return 0
    monkeypatch.setattr(batch,'run_child',worker)
    result=batch.preflight(root,workers=1,scene_ids=[row['scene_id']])
    assert logs==[folder/'preflight_resume_456.log']
    assert old.read_bytes()==b'original partial worker evidence\n'
    assert prior.read_bytes()==b'older retry evidence\n'
    assert result['selected_verified']==1 and result['verified']==1 and result['registered']==400
    # Completed evidence is cached: no extra process or new resume log.
    batch.preflight(root,workers=1,scene_ids=[row['scene_id']])
    assert len(logs)==1


def test_fresh_preflight_retains_original_log_name(collection,monkeypatch):
    root,rows,_=collection;row=rows[0];logs=[]
    def worker(args,log,timeout):
        logs.append(Path(log))
        with Path(log).open('x') as f:f.write('fresh')
        atomic_json(Path(log).with_name('preflight.json'),dict(scene_id=row['scene_id'],split=row['split'],valid=True))
        return 0
    monkeypatch.setattr(batch,'run_child',worker)
    batch.preflight(root,workers=1,scene_ids=[row['scene_id']])
    assert logs==[root/'scenes'/row['scene_id']/'preflight.log']
