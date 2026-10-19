"""The frozen renderer reads OUTPUT, not an unused OUT attribute."""
import importlib.util
from pathlib import Path
import runpy
import sys
import pytest


def test_private_native_worker_delegates_to_new_output_owner(monkeypatch):
    observed=[]
    original=importlib.util.spec_from_file_location
    class Loader:
        def create_module(self,spec):return None
        def exec_module(self,module):
            module.OUTPUT=Path('/sentinel/old/output')
            module.digest=lambda p:'hash';module.gpu=lambda:[];module.dump=lambda *a:None
            def worker(attempt):observed.append((module.OUTPUT,attempt,hasattr(module,'OUT')))
            module.worker=worker
    def spec(name,path,*args,**kwargs):
        if str(path).replace('\\','/').endswith('diagnostictools/native32_v2_pipeline.py'):
            return importlib.util.spec_from_loader(name,Loader())
        return original(name,path,*args,**kwargs)
    monkeypatch.setattr(importlib.util,'spec_from_file_location',spec)
    attempt='/home/michelle/haoze/r1pro-airport-sim/releases/robust_v64_20260930/runs/v64_approximate_400/approximate_completion/attempts/scene/a000'
    monkeypatch.setattr(sys,'argv',['native32_v4_pipeline.py','--one',attempt])
    monkeypatch.setattr(Path,'cwd',classmethod(lambda cls:Path('/home/michelle/haoze/r1pro-airport-sim/releases/vla_v13_20261001')))
    path=Path(__file__).resolve().parents[1]/'scripts/native32_expansion_pipeline.py'
    monkeypatch.setattr(Path,'resolve',lambda self,*args,**kwargs:self)
    with pytest.raises(RuntimeError,match='expected_output_missing'):
        runpy.run_path(str(path),run_name='__main__')
    assert observed==[(Path('/home/michelle/haoze/r1pro-airport-sim/runs/vla_20261001/native32_v4'),str(Path(attempt).resolve()),False)]
