import importlib.util
from pathlib import Path
import os,subprocess
import pytest

@pytest.mark.parametrize('name',['transition_task_complete_sources_parallel','observe_task_complete_sources_parallel'])
def test_import_has_no_process_or_signal_side_effects(name,monkeypatch,tmp_path):
    def forbidden(*args,**kwargs):raise AssertionError('import must not signal or spawn')
    monkeypatch.setattr(os,'kill',forbidden);monkeypatch.setattr(subprocess,'Popen',forbidden)
    path=Path(__file__).resolve().parents[1]/'scripts'/f'{name}.py'
    spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    if name.startswith('transition'):
        with pytest.raises(ValueError,match='authorization_required'):
            module.run_transition(base=tmp_path,run_root=tmp_path,inventory=tmp_path/'missing',controller=tmp_path,tool=tmp_path,python='unused')
    else:
        with pytest.raises(ValueError,match='authorization_required'):
            module.run_observer(base=tmp_path,run_root=tmp_path,old_router_pid=1)
