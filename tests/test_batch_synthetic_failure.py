import json
import signal
import threading
from types import SimpleNamespace
import pytest
from r1pro_teleop.airport_fsm import batch
from r1pro_teleop.airport_fsm.contracts import atomic_json

@pytest.mark.parametrize('profile',['strict','completion_first'])
@pytest.mark.parametrize('kind',['timeout','crash','interrupted'])
def test_generate_synthetic_failure_profile(tmp_path,monkeypatch,profile,kind):
 cfg=SimpleNamespace(acceptance_profile=profile,max_attempts_per_scene=1,successes_per_scene=1,max_attempt_wall_seconds=1)
 (tmp_path/'attempts').mkdir();atomic_json(tmp_path/'scenes/a/preflight.json',dict(valid=True))
 monkeypatch.setattr(batch,'config_for',lambda root:cfg)
 monkeypatch.setattr(batch,'assert_environment',lambda root:None)
 monkeypatch.setattr(batch,'selected_rows',lambda *args:[dict(scene_id='a',split='train')])
 monkeypatch.setattr(batch,'preflight_coverage',lambda *args,**kwargs:None)
 monkeypatch.setattr(batch,'coverage',lambda root:{})
 def worker(args,log,timeout):
  log.write_text('original worker evidence')
  return 124 if kind=='timeout' else 9
 monkeypatch.setattr(batch,'run_child',worker)
 if kind=='interrupted':
  d=tmp_path/'attempts/a/a000';d.mkdir(parents=True);(d/'partial.txt').write_text('retain')
 batch.generate(tmp_path,workers=1)
 p=tmp_path/'attempts/a/a000';r=json.loads((p/'result.json').read_text())
 assert r['acceptance_profile']==profile
 assert all(r[k] is False for k in ['physics_success','task_completed','strict_success','diagnostic_only'])
 assert (r['scene_id'],r['split'],r['attempt'])==('a','train',0)
 assert r['failure_code']=={'timeout':'worker_timeout','crash':'worker_crashed','interrupted':'interrupted_attempt_retained'}[kind]
 if kind=='interrupted':assert (p/'partial.txt').read_text()=='retain'
 else:assert (p.parent/'a000.log').read_text()=='original worker evidence'


def test_sigterm_cleanup_restore_reentrant_lock_and_second_signal(monkeypatch):
 previous=signal.getsignal(signal.SIGTERM);calls=[]
 def stop():
  with batch._CHILD_LOCK:
   calls.append('stop');signal.getsignal(signal.SIGTERM)(signal.SIGTERM,None)
 monkeypatch.setattr(batch,'stop_children',stop)
 with pytest.raises(SystemExit) as exc:
  with batch.generation_termination_scope():
   with batch._CHILD_LOCK:signal.getsignal(signal.SIGTERM)(signal.SIGTERM,None)
 assert exc.value.code==143 and calls==['stop']
 assert signal.getsignal(signal.SIGTERM)==previous


def test_scope_in_worker_thread_does_not_install_handler(monkeypatch):
 monkeypatch.setattr(batch.signal,'signal',lambda *args:pytest.fail('worker installed signal handler'))
 seen=[]
 def target():
  with batch.generation_termination_scope():seen.append(True)
 t=threading.Thread(target=target);t.start();t.join(2)
 assert seen==[True]


def test_child_spawn_cancel_window_stops_registered_process(tmp_path,monkeypatch):
 batch._CANCEL.clear();calls=[]
 class Child:
  pid=987654
  def poll(self):return None
  def terminate(self):calls.append('terminate')
  def wait(self,timeout=None):calls.append('wait');return -15
 p=Child()
 def spawn(*args,**kwargs):batch._CANCEL.set();return p
 monkeypatch.setattr(batch.subprocess,'Popen',spawn)
 monkeypatch.setattr(batch.os,'killpg',lambda pid,sig:calls.append('terminate'),raising=False)
 try:
  assert batch.run_child([],tmp_path/'log',1)==-15
  assert calls==['terminate','wait'] and p not in batch._CHILDREN
 finally:batch._CANCEL.clear()

@pytest.mark.skipif(__import__('os').name!='posix',reason='POSIX process-group SIGTERM integration')
def test_real_sigterm_reaps_owned_subprocess():
 import subprocess,sys,textwrap
 script=textwrap.dedent('''
 import os,signal,subprocess,sys
 from r1pro_teleop.airport_fsm import batch
 child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)'],start_new_session=True)
 batch._CHILDREN.add(child)
 previous=signal.getsignal(signal.SIGTERM)
 try:
  with batch.generation_termination_scope():
   os.kill(os.getpid(),signal.SIGTERM)
 except SystemExit as exc:
  assert exc.code==143
  assert child.wait(timeout=3)==-signal.SIGTERM
  assert signal.getsignal(signal.SIGTERM)==previous
  sys.exit(exc.code)
 finally:
  if child.poll() is None:child.kill();child.wait()
 ''')
 p=subprocess.run([sys.executable,'-c',script],capture_output=True,text=True,timeout=6)
 assert p.returncode==143,p.stderr
