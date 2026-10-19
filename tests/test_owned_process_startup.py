"""Only the first exact identity match gets bounded startup retry."""
import json,subprocess
from types import SimpleNamespace
import pytest
from test_owned_process_exit_race import module,Process


def clock(m,monkeypatch):
    value=[0.]
    monkeypatch.setattr(m,'time',SimpleNamespace(monotonic=lambda:value[0],
        sleep=lambda dt:value.__setitem__(0,value[0]+dt),time=lambda:value[0]))
    return value


def test_empty_initial_identity_then_exact_gets_receipt_without_signaling(tmp_path,monkeypatch):
    m=module();p=Process();timer=clock(m,monkeypatch);calls=[]
    def verify(*a):
        calls.append(1)
        if len(calls)==1:raise RuntimeError('empty initial command')
    monkeypatch.setattr(m,'verify_owned_identity',verify)
    monkeypatch.setattr(m,'process_command',lambda _:None)
    receipt=m.wait_owned_startup(p,['exact'],tmp_path,tmp_path/'startup.json')
    assert receipt['identity_verified'] and receipt['attempts']==2
    assert receipt['last_transient']['observed_command'] is None
    assert receipt['elapsed_seconds']==.02 and p.signals==0
    assert json.loads((tmp_path/'startup.json').read_text())==receipt


def test_permanent_live_mismatch_times_out_without_signal(tmp_path,monkeypatch):
    m=module();p=Process();clock(m,monkeypatch)
    monkeypatch.setattr(m,'verify_owned_identity',lambda *a:(_ for _ in ()).throw(RuntimeError('wrong argv')))
    monkeypatch.setattr(m,'process_command',lambda _:['unrelated'])
    with pytest.raises(RuntimeError,match='refuse to signal unknown'):
        m.wait_owned_startup(p,['exact'],tmp_path,tmp_path/'startup.json',timeout_seconds=.04)
    receipt=json.loads((tmp_path/'startup.json').read_text())
    assert not receipt['identity_verified'] and receipt['status']=='unverified_live_identity_timeout'
    assert receipt['attempts']==3 and p.signals==0


@pytest.mark.parametrize('code',[0,7])
def test_early_exit_is_reaped_but_not_labeled_identity_success(tmp_path,monkeypatch,code):
    m=module();p=Process();p.returncode=code
    receipt=m.wait_owned_startup(p,['exact'],tmp_path,tmp_path/'startup.json')
    assert not receipt['identity_verified'] and receipt['returncode']==code
    assert receipt['status']=='owned_child_exited_before_identity' and p.signals==0


def test_after_first_match_identity_change_is_strict_not_retried(tmp_path,monkeypatch):
    m=module();p=Process();clock(m,monkeypatch);calls=[]
    def verify(*a):
        calls.append(1)
        if len(calls)>1:raise RuntimeError('live identity changed')
    monkeypatch.setattr(m,'verify_owned_identity',verify)
    monkeypatch.setattr(m,'checked_gpu_rows',lambda _:[dict(index=0,uuid=m.EXPECTED_UUID)])
    monkeypatch.setattr(m,'process_command',lambda _:['unrelated'])
    with pytest.raises(RuntimeError,match='refuse to signal unknown'):
        m.monitor_owned(p,['exact'],tmp_path,tmp_path/'gpu.json',deadline=100)
    assert len(calls)==2 and p.signals==0
    assert json.loads((tmp_path/'gpu_startup.json').read_text())['identity_verified']


def test_existing_startup_receipt_is_not_overwritten(tmp_path):
    m=module();p=Process();path=tmp_path/'startup.json';path.write_text('preserved')
    with pytest.raises(FileExistsError):m.wait_owned_startup(p,['exact'],tmp_path,path)
    assert path.read_text()=='preserved' and p.signals==0


@pytest.mark.parametrize('timeout,poll',[(6,.02),(float('nan'),.02),(0,.02),(5,0),(5,float('inf'))])
def test_handshake_budget_is_finite_and_bounded(tmp_path,timeout,poll):
    with pytest.raises(ValueError):module().wait_owned_startup(Process(),['exact'],tmp_path,timeout_seconds=timeout,poll_seconds=poll)
