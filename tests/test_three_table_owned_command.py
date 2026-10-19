import importlib.util,json,sys,subprocess
from pathlib import Path
from types import SimpleNamespace
import pytest
from r1pro_teleop.single_tray_3table import owned_command as m

def inputs(tmp_path):
    out=tmp_path/'child';options=tmp_path/'options.json'
    options.write_text(json.dumps(dict(schema='airport_three_table_owned_command/1',argv=[sys.executable,'-c','import os;print(os.environ["OMP_NUM_THREADS"]);raise SystemExit(17)'],cwd=str(tmp_path),output=str(out))))
    return out,options

def test_actual_cpu_child_exit_survives_coordinator_identity_loss(tmp_path,monkeypatch):
    monkeypatch.setitem(sys.modules,'fcntl',SimpleNamespace(LOCK_EX=1,LOCK_NB=2,flock=lambda *a:None))
    out,options=inputs(tmp_path)
    assert m.run_command_receipt(options)==17
    # Parent/wrapper can be gone; a real exit receipt still proves the code.
    state=m.command_state(out,options,probe=lambda pid:None)
    assert state['stage']=='closed' and state['returncode']==17
    assert (out/'stdout.log').read_text().strip()=='1'
    with pytest.raises(ValueError,match='fresh_required'):m.run_command_receipt(options)

def test_mutated_command_or_false_exit_cannot_be_adopted(tmp_path):
    out,options=inputs(tmp_path);out.mkdir()
    row=dict(options_sha256=m.digest(options),argv=['different'],cwd=str(tmp_path),actual_exit_observed=True,returncode=0)
    (out/'exit.json').write_text(json.dumps(row))
    with pytest.raises(ValueError,match='identity_changed'):m.command_state(out,options)

def test_living_wrapper_adoption_and_pid_reuse_fail_closed(tmp_path):
    out,options=inputs(tmp_path);out.mkdir()
    identity=dict(pid=123,argv=['python','owned_wrapper'],cwd=str(tmp_path),start_ticks='42')
    (out/'process.json').write_text(json.dumps(dict(options_sha256=m.digest(options),wrapper_identity=identity)))
    assert m.command_state(out,options,probe=lambda pid:identity)['stage']=='running_wrapper'
    with pytest.raises(ValueError,match='identity_changed'):m.command_state(out,options,probe=lambda pid:dict(identity,start_ticks='43'))

def test_dead_wrapper_without_exit_is_not_fabricated_success(tmp_path):
    out,options=inputs(tmp_path);out.mkdir()
    (out/'process.json').write_text(json.dumps(dict(options_sha256=m.digest(options),wrapper_identity=None,child_identity=None)))
    assert m.command_state(out,options,probe=lambda pid:None)['stage']=='incomplete_exit_not_observed'
