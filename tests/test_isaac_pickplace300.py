import importlib.util
from pathlib import Path
import pytest
spec=importlib.util.spec_from_file_location('production',Path(__file__).parents[1]/'scripts/supervise_isaac_pickplace300.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
def pair(source):
    return {'segments':[{'prompt':p,'ready':True,'complete_pick_place_pair':True,'split':'train','source_room':source} for p in ['Pick up the tray','Place the tray']]}
def cat(ps):return {'overview':{'path':'actual'},'overview_error':None,'frozen_batches':ps}
def test_freeze_exact_target_and_report_extras():
    root=Path('/new');chosen,total=m.select_pairs([cat([pair('/new/a'),pair('/new/b')])],1,root)
    assert len(chosen)==1 and total==2
def test_old_sources_never_count():
    with pytest.raises(ValueError,match='historical'):m.select_pairs([cat([pair('/old/a')])],300,Path('/new'))
def test_duplicates_rejected():
    with pytest.raises(ValueError,match='duplicate'):m.select_pairs([cat([pair('/new/a'),pair('/new/a')])],300,Path('/new'))
def test_partial_pair_never_accepted():
    p=pair('/new/a');p['segments'].pop()
    with pytest.raises(ValueError,match='not_complete'):m.select_pairs([cat([p])],300,Path('/new'))
def test_split_not_relabelled():
    p=pair('/new/a');p['segments'][0]['split']='test'
    with pytest.raises(ValueError,match='not_qualified'):m.select_pairs([cat([p])],300,Path('/new'))
