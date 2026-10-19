import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from r1pro_teleop.airport_fsm import batch, registry
from r1pro_teleop.airport_fsm.contracts import Fault, atomic_json
from scripts import control_regression


@pytest.fixture
def collection(tmp_path,monkeypatch):
    rows=[dict(scene_id=f'airport_{i:04d}_seed',split='train' if i<301 else 'val' if i<351 else 'test',
               front_count=2,difficulty='simple',lighting='normal') for i in range(1,401)]
    (tmp_path/'scenes').mkdir();(tmp_path/'quality').mkdir();(tmp_path/'attempts').mkdir()
    atomic_json(tmp_path/'scenes/index.json',rows)
    atomic_json(tmp_path/'splits/scenes.json',{r['scene_id']:r['split'] for r in rows})
    calls=[]
    monkeypatch.setattr(batch,'environment_versions',lambda:{'mujoco':'test'})
    monkeypatch.setattr(batch,'freeze_dependencies',lambda root:None)
    def worker(args,log,timeout):
        sid=args[-1];calls.append(sid);row=next(r for r in rows if r['scene_id']==sid)
        atomic_json(Path(log).with_name('preflight.json'),dict(valid=True,scene_id=sid,split=row['split']))
        return 0
    monkeypatch.setattr(batch,'run_child',worker)
    return tmp_path,rows,calls


def test_selected_only_runs_complete_original_worker_and_reports_coverage(collection):
    root,rows,calls=collection;ids=[rows[i]['scene_id'] for i in (0,3,217)]
    result=batch.preflight(root,workers=2,scene_ids=ids)
    assert set(calls)==set(ids) and len(calls)==3
    assert result['total']==result['valid']==result['selected']==result['verified']==3
    assert result['registered']==400 and result['missing']==397
    assert not result['all_registered_verified'] and result['task_rollouts_validated']==0
    assert not (root/'scenes'/rows[1]['scene_id']).exists()
    assert len(registry.scene_rows(root))==400
    assert json.loads((root/'splits/scenes.json').read_text())[rows[-1]['scene_id']]=='test'


@pytest.mark.parametrize('ids',[[],['not_registered']])
def test_invalid_selection_rejected_before_dependencies_or_workers(collection,monkeypatch,ids):
    root,rows,calls=collection
    monkeypatch.setattr(batch,'freeze_dependencies',lambda root:pytest.fail('must validate first'))
    with pytest.raises(Fault):batch.preflight(root,scene_ids=ids)
    assert calls==[] and not (root/'quality/preflight.json').exists()


def test_expanding_slice_requires_new_preflight_and_caches_existing(collection,monkeypatch):
    root,rows,calls=collection;a,b=rows[0]['scene_id'],rows[1]['scene_id']
    batch.preflight(root,scene_ids=[a])
    monkeypatch.setattr(batch,'config_for',lambda root:SimpleNamespace())
    monkeypatch.setattr(batch,'assert_environment',lambda root:None)
    with pytest.raises(Fault,match='scene_preflight_missing'):
        batch.generate(root,scene_ids=[a,b])
    assert calls==[a] # no attempt worker can start while any selected scene lacks preflight
    report=batch.preflight(root,scene_ids=[a,b])
    assert calls==[a,b] and report['verified']==2 and report['selected_verified']==2
    report=batch.preflight(root,scene_ids=[b])
    assert calls==[a,b] and report['selected']==1 and report['verified']==2


def test_default_preflight_all400_compatible(collection):
    root,rows,calls=collection
    report=batch.preflight(root,workers=4)
    assert len(calls)==400 and report['registered']==report['total']==report['verified']==400
    assert report['all_registered_verified']


def test_cached_rejection_is_checked_but_never_verified(collection):
    root,rows,calls=collection;a,b=rows[0],rows[1]
    atomic_json(root/'scenes'/a['scene_id']/'preflight.json',{
        'scene_id':a['scene_id'],'split':a['split'],'valid':False,'failure_code':'initial_scene_settle_drift'})
    report=batch.preflight(root,scene_ids=[a['scene_id'],b['scene_id']])
    assert calls==[b['scene_id']]
    assert report['selected']==report['checked']==2
    assert report['verified']==report['selected_verified']==report['valid']==1
    assert report['rejected']==1 and report['rejection_codes']=={'initial_scene_settle_drift':1}


def test_mismatched_preflight_identity_cannot_count_as_verified(collection):
    root,rows,calls=collection;a=rows[0]
    atomic_json(root/'scenes'/a['scene_id']/'preflight.json',{
        'scene_id':'other','split':a['split'],'valid':True})
    with pytest.raises(Fault,match='preflight_scene_identity_mismatch'):
        registry.preflight_coverage(root,rows,[a['scene_id']])


@pytest.mark.parametrize('entry',['preflight','generate'])
def test_mismatched_cached_identity_rejected_before_any_worker(collection,monkeypatch,entry):
    root,rows,calls=collection;a=rows[0]
    atomic_json(root/'scenes'/a['scene_id']/'preflight.json',{
        'scene_id':'other','split':a['split'],'valid':True})
    monkeypatch.setattr(batch,'config_for',lambda root:SimpleNamespace())
    monkeypatch.setattr(batch,'assert_environment',lambda root:None)
    with pytest.raises(Fault,match='preflight_scene_identity_mismatch'):
        getattr(batch,entry)(root,scene_ids=[a['scene_id'],rows[1]['scene_id']])
    assert calls==[]


def test_coverage_consumer_keeps_unselected_unattempted(collection,monkeypatch):
    root,rows,calls=collection
    batch.preflight(root,scene_ids=[rows[0]['scene_id']])
    monkeypatch.setattr(registry,'config_for',lambda root:SimpleNamespace(successes_per_scene=1))
    report=registry.coverage(root)
    assert report['registered']==400 and report['counts']['not_attempted']==400
    assert report['preflight_coverage']['selected']==1 and report['preflight_coverage']['verified']==1
    assert not report['all_scenes_attempted_or_rejected']


def test_cli_empty_rejected_and_default_all():
    from r1pro_teleop.airport_fsm.__main__ import parser
    assert parser().parse_args(['preflight','--root','x']).scene_ids is None
    with pytest.raises(SystemExit):parser().parse_args(['preflight','--root','x','--scene-ids'])


@pytest.mark.parametrize('indices',[[],[999]])
def test_regression_selection_invalid_before_any_subprocess(monkeypatch,tmp_path,indices):
    rows=[dict(scene_id='airport_0001_seed')]
    with pytest.raises(ValueError):control_regression.select_indices(rows,indices)
    monkeypatch.setattr(control_regression,'load_sources',lambda *a:rows)
    monkeypatch.setattr(control_regression.Config,'load',lambda *a:SimpleNamespace(expected_scenes=400))
    monkeypatch.setattr(control_regression.subprocess,'run',lambda *a,**kw:pytest.fail('no subprocess allowed'))
    if indices:
        with pytest.raises(ValueError):control_regression.main(['--output',str(tmp_path/'out'),'--config','unused','--indices','999'])


@pytest.mark.parametrize('all_scenes',[False,True])
def test_regression_selects_before_prepare_and_passes_same_slice(collection,monkeypatch,all_scenes):
    root,rows,calls=collection;commands=[]
    atomic_json(root/'collection.json',{'config':{'max_attempts_per_scene':1,'primitive_seconds':3.}})
    monkeypatch.setattr(control_regression,'load_sources',lambda *a:rows)
    monkeypatch.setattr(control_regression.Config,'load',lambda *a:SimpleNamespace(expected_scenes=400))
    monkeypatch.setattr(control_regression.subprocess,'run',lambda args,**kw:commands.append(args))
    args=['--output',str(root),'--config','unused']+(['--all'] if all_scenes else ['--indices','1','4'])
    control_regression.main(args)
    assert [c[3] for c in commands]==['prepare','preflight','generate']
    for cmd in commands[1:]:
        if all_scenes:assert '--scene-ids' not in cmd
        else:assert cmd[cmd.index('--scene-ids')+1:]==[rows[0]['scene_id'],rows[3]['scene_id']]
    report=json.loads((root/'evaluation_summary.json').read_text())
    assert report['source_scene_count']==400 and report['preflight_coverage']['verified']==0
    assert report['preflight_coverage']['selected']==(400 if all_scenes else 2)
