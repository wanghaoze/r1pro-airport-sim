import importlib.util,json
from pathlib import Path
import pytest
spec=importlib.util.spec_from_file_location('native_cli_cap',Path(__file__).resolve().parents[1]/'scripts/render_task_complete_sources.py')
cli=importlib.util.module_from_spec(spec);spec.loader.exec_module(cli)

def test_per_gpu_three_then_four_cap_never_changes_case_assignment(tmp_path):
    path=tmp_path/'caps.json';slots=[0]*4+[1]*4
    path.write_text(json.dumps({'0':3,'1':3}))
    assert [i for i,g in enumerate(slots) if cli.worker_enabled(g,i,slots,path)]==[0,1,2,4,5,6]
    path.write_text(json.dumps({'0':4,'1':3}))
    assert [i for i,g in enumerate(slots) if cli.worker_enabled(g,i,slots,path)]==[0,1,2,3,4,5,6]
    assert cli.worker_enabled(0,3,slots,None)

@pytest.mark.parametrize('cap',[0,5,True,'3',None])
def test_invalid_native_cap_rejected(tmp_path,cap):
    path=tmp_path/'caps.json';path.write_text(json.dumps({'0':cap,'1':3}))
    with pytest.raises(ValueError,match='bounded_native_worker_cap'):cli.worker_enabled(0,0,[0]*4+[1]*4,path)
