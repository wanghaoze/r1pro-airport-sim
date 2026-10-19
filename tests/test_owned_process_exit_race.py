import importlib.util,subprocess
from pathlib import Path
import pytest


def module():
    path=Path(__file__).resolve().parents[1]/'runs/vla_deploy_20261001/bc32_post_runtime_checks.py'
    spec=importlib.util.spec_from_file_location('owned_race_guard',path);mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod);return mod


class Process:
    pid=123
    def __init__(self):self.returncode=None;self.signals=0;self.exit_on_wait=None
    def poll(self):return self.returncode
    def wait(self,timeout):
        if self.exit_on_wait is None:raise subprocess.TimeoutExpired('owned',timeout)
        self.returncode=self.exit_on_wait;return self.returncode
    def terminate(self):self.signals+=1


@pytest.mark.parametrize('exitcode',[0,1])
def test_exit_during_proc_identity_read_reaps_only_owned_child_keeps_gpu_requirement(tmp_path,monkeypatch,exitcode):
    m=module();p=Process();calls=[]
    def identity(*a):
        calls.append(1)
        if len(calls)==2:p.exit_on_wait=exitcode;raise FileNotFoundError('proc vanished on natural exit')
    monkeypatch.setattr(m,'verify_owned_identity',identity)
    monkeypatch.setattr(m,'checked_gpu_rows',lambda _: [{'index':0,'uuid':m.EXPECTED_UUID}])
    monkeypatch.setattr(m.time,'sleep',lambda _:None)
    if exitcode:
        with pytest.raises(RuntimeError,match='subprocess failed'):m.monitor_owned(p,['exact'],tmp_path,tmp_path/'receipt.json',deadline=1e30)
    else:assert m.monitor_owned(p,['exact'],tmp_path,tmp_path/'receipt.json',deadline=1e30)[0]['index']==0
    assert p.signals==0 and (tmp_path/'receipt.json').exists()


def test_live_identity_mismatch_remains_fail_closed_without_signal(tmp_path,monkeypatch):
    m=module();p=Process()
    monkeypatch.setattr(m,'verify_owned_identity',lambda *a:(_ for _ in ()).throw(RuntimeError('identity mismatch')))
    monkeypatch.setattr(m,'process_command',lambda _:['unrelated'])
    monkeypatch.setattr(m,'checked_gpu_rows',lambda _:pytest.fail('Mismatched process must not proceed'))
    with pytest.raises(RuntimeError,match='refuse to signal unknown'):
        m.monitor_owned(p,['exact'],tmp_path,tmp_path/'receipt.json',deadline=1e30)
    assert p.signals==0


def test_exit_before_any_gpu_receipt_does_not_become_success(tmp_path,monkeypatch):
    m=module();p=Process();p.exit_on_wait=0
    monkeypatch.setattr(m,'verify_owned_identity',lambda *a:(_ for _ in ()).throw(FileNotFoundError('gone')))
    with pytest.raises(RuntimeError,match='without actual physical GPU'):
        m.monitor_owned(p,['exact'],tmp_path,tmp_path/'receipt.json',deadline=1e30)
    assert p.signals==0


def test_termination_identity_read_race_reaps_natural_exit_without_signal(tmp_path,monkeypatch):
    m=module();p=Process();p.exit_on_wait=0
    monkeypatch.setattr(m,'process_command',lambda _:(_ for _ in ()).throw(FileNotFoundError('gone')))
    assert m.terminate_owned(p,['exact'],tmp_path) is False
    assert p.signals==0
