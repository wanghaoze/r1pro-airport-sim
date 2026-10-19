import subprocess
import json
from pathlib import Path
import pytest
from r1pro_teleop.vla.training_pipeline import source_gate,digest,EXPECTED_SPLITS,verify_owned

def ready_sources(root):
 for split,count in EXPECTED_SPLITS.items():
  folder=root/('action8_export_'+split+'_parallel_v2');(folder/'dataset').mkdir(parents=True)
  ids=[split+str(n) for n in range(count)];source=folder/'dataset/whole_action_source_manifest.jsonl';source.write_text('original')
  manifest=dict(dataset_ready=True,split=split,repo_id='airport/task_complete_action8_'+split+'_v2',prompt_mode='task_complete_action8_v1',complete_expected_scene_ids=ids,episodes=[dict(scene_id=s,split=split) for s in ids],all_parquet_values_verified={'verified':True},source_manifest=str(source),source_manifest_sha256=digest(source))
  (folder/'dataset/airport_training_manifest.json').write_text(json.dumps(manifest))
  (folder/'status.json').write_text(json.dumps(dict(stage='complete',dataset_ready=True,expected_scenes=count,completed_scenes=count)))
 native=root/'native_status.json';native.write_text(json.dumps(dict(status='complete',selected=193,completed_scene_count=193,training_ready=False)))
 refs=root/'native_references_current.json';refs.write_text(json.dumps([{}]*772))
 receipt=dict(schema='airport_native_producer_exit/1',returncode=0,source_native_verified=True,selected=193,completed_scene_count=193,reference_count=772,active_owned_renderers=[],status_path=str(native),status_sha256=digest(native),references_sha256=digest(refs))
 (root/'native_parallel_exit_receipt.json').write_text(json.dumps(receipt))

def test_requires_all_three_complete_splits_and_native_nontaining_ready_is_legal(tmp_path):
 assert source_gate(tmp_path) is None
 ready_sources(tmp_path);assert len(source_gate(tmp_path)['splits'])==3
 folder=tmp_path/'action8_export_train_parallel_v2/status.json';status=json.loads(folder.read_text());status['dataset_ready']=False;folder.write_text(json.dumps(status));assert source_gate(tmp_path) is None

def test_native_changed_after_exit_and_split_source_mutation_rejected(tmp_path):
 ready_sources(tmp_path);(tmp_path/'native_references_current.json').write_text('[]')
 with pytest.raises(ValueError,match='publisher_files_changed'):source_gate(tmp_path)

def test_holdout_leakage_rejected_even_when_count_and_loader_flags_claim_ready(tmp_path):
 ready_sources(tmp_path);path=tmp_path/'action8_export_train_parallel_v2/dataset/airport_training_manifest.json';manifest=json.loads(path.read_text());manifest['episodes'][0]['split']='test';path.write_text(json.dumps(manifest))
 with pytest.raises(ValueError,match='semantics'):source_gate(tmp_path)

def test_source_failure_is_not_silently_waited_forever(tmp_path):
 ready_sources(tmp_path);(tmp_path/'action8_export_val_parallel_v2/status.json').write_text(json.dumps({'stage':'failed'}))
 with pytest.raises(ValueError,match='source_export_failed'):source_gate(tmp_path)

def test_natural_exit_before_identity_check_requires_no_signal(tmp_path):
 class Child:
  pid=99999999
  def poll(self):return 0
 assert verify_owned(Child(),['python','script.py'],tmp_path) is False


def test_runtime_must_exist_and_have_actual_core_zero_exit(tmp_path):
 from r1pro_teleop.vla.training_pipeline import runtime_gate
 options={'runtime_release':str(tmp_path/'runtime'),'runtime_core_report':str(tmp_path/'core.json')}
 assert runtime_gate(options) is None
 (tmp_path/'runtime/scripts').mkdir(parents=True);(tmp_path/'runtime/scripts/evaluate_action8_checkpoint.py').write_text('actual')
 (tmp_path/'core.json').write_text(json.dumps({'returncode':1}))
 with pytest.raises(ValueError,match='core_not_verified'):runtime_gate(options)
 (tmp_path/'core.json').write_text(json.dumps({'returncode':0}));assert runtime_gate(options)
 options['runtime_core_report_sha256']='0'*64
 with pytest.raises(ValueError,match='report_changed'):runtime_gate(options)


def test_checkpoint_recovery_uses_latest_complete_periodic_state_not_only_milestones(tmp_path):
 from r1pro_teleop.vla.training_pipeline import latest_saved_update,unused_path
 spec={'name':'run','dataset_repo_id':'airport/train'}
 folder=tmp_path/'checkpoints/run/training'
 for step in (999,2999):
  for name in ('params','train_state','assets/airport/train'):(folder/str(step)/name).mkdir(parents=True)
  (folder/str(step)/'assets/airport/train/norm_stats.json').write_text('source')
 (folder/'3999/params').mkdir(parents=True)
 assert latest_saved_update(tmp_path,spec)==3000
 path=tmp_path/'attempt.log';path.write_text('old')
 assert unused_path(path).name=='attempt_recovery_001.log' and path.read_text()=='old'

def test_evaluation_mode_selects_fixed_dual_cli_and_rejects_unknown_gpu():
 from r1pro_teleop.vla.training_pipeline import evaluation_script,GPU_UUIDS
 assert evaluation_script({})=='evaluate_action8_checkpoint.py'
 assert evaluation_script({'evaluation_mode':'dual_static_two_gpu','gpu1_uuid':GPU_UUIDS[1]})=='evaluate_action8_checkpoint_dual.py'
 with pytest.raises(ValueError,match='gpu_identity'):evaluation_script({'evaluation_mode':'dual_static_two_gpu','gpu1_uuid':'unknown'})
 with pytest.raises(ValueError,match='unsupported'):evaluation_script({'evaluation_mode':'guess'})

def test_runtime_dual_gate_requires_actual_dual_file(tmp_path):
 from r1pro_teleop.vla.training_pipeline import runtime_gate,GPU_UUIDS
 (tmp_path/'scripts').mkdir();(tmp_path/'scripts/evaluate_action8_checkpoint.py').write_text('serial')
 core=tmp_path/'core.json';core.write_text(json.dumps({'returncode':0}))
 options={'runtime_release':str(tmp_path),'runtime_core_report':str(core),'evaluation_mode':'dual_static_two_gpu','gpu1_uuid':GPU_UUIDS[1]}
 assert runtime_gate(options) is None
 (tmp_path/'scripts/evaluate_action8_checkpoint_dual.py').write_text('actual dual')
 assert runtime_gate(options)['core_report_sha256']==digest(core)

def test_startup_transient_identity_retries_then_strict_checks_remain(monkeypatch,tmp_path):
 import r1pro_teleop.vla.training_pipeline as m
 class Child:
  def poll(self):return None
 calls=[]
 def verify(*args):
  calls.append(1)
  if len(calls)<3:raise ValueError('live_owned_process_identity_changed:preexec')
  return True
 monkeypatch.setattr(m,'verify_owned',verify)
 result=m.wait_owned_startup(Child(),['python'],tmp_path,poll_seconds=0)
 assert result['verified'] and result['retry_count']==2
 monkeypatch.setattr(m,'verify_owned',lambda *args: (_ for _ in ()).throw(ValueError('live mismatch')))
 with pytest.raises(ValueError,match='live mismatch'):m.verify_owned(Child(),['python'],tmp_path)

def test_startup_permanent_mismatch_is_bounded_and_never_signaled(monkeypatch,tmp_path):
 import r1pro_teleop.vla.training_pipeline as m
 class Child:
  def poll(self):return None
 monkeypatch.setattr(m,'verify_owned',lambda *args: (_ for _ in ()).throw(ValueError('unknown live command')))
 monkeypatch.setattr(m.os,'killpg',lambda *args: pytest.fail('unknown process signaled'),raising=False)
 with pytest.raises(ValueError,match='startup_identity_not_verified'):m.wait_owned_startup(Child(),['python'],tmp_path,timeout_seconds=0)

def test_startup_natural_exit_does_not_require_identity_retry(monkeypatch,tmp_path):
 import r1pro_teleop.vla.training_pipeline as m
 class Child:
  def poll(self):return 0
 monkeypatch.setattr(m,'verify_owned',lambda *args: False)
 receipt=m.wait_owned_startup(Child(),['python'],tmp_path)
 assert receipt['verified'] is False and receipt['retry_count']==0

def test_run_owned_startup_failure_saves_pid_without_unknown_signal(monkeypatch,tmp_path):
 import r1pro_teleop.vla.training_pipeline as m
 class Child:
  pid=98765
  def poll(self):return None
 monkeypatch.setattr(m.subprocess,'Popen',lambda *args,**kw: Child())
 monkeypatch.setattr(m,'wait_owned_startup',lambda *args: (_ for _ in ()).throw(ValueError('startup_identity_not_verified')))
 monkeypatch.setattr(m.os,'killpg',lambda *args: pytest.fail('unknown process signaled'),raising=False)
 with pytest.raises(ValueError,match='startup_identity'):m.run_owned(['python'],tmp_path,{},tmp_path/'child.log')
 receipt=json.loads((tmp_path/'child.startup.json').read_text())
 assert receipt['pid']==98765 and 'error' in receipt and receipt['status']=='spawned_awaiting_identity'


@pytest.mark.parametrize('code',[0,17])
def test_empty_proc_argv_exit_race_reaps_actual_child_without_inventing_returncode(tmp_path,monkeypatch,code):
 import r1pro_teleop.vla.training_pipeline as m
 class Child:
  pid=123;returncode=None;signals=0
  def poll(self):return self.returncode
  def wait(self,timeout):assert timeout==.2;self.returncode=code;return code
 p=Child();old_read=Path.read_bytes;old_resolve=Path.resolve
 monkeypatch.setattr(Path,'read_bytes',lambda path:b'' if str(path).replace('\\','/')=='/proc/123/cmdline' else old_read(path))
 monkeypatch.setattr(Path,'resolve',lambda path,*a,**k:tmp_path if str(path).replace('\\','/')=='/proc/123/cwd' else old_resolve(path,*a,**k))
 assert m.verify_owned(p,['python','exact.py'],tmp_path) is False and p.returncode==code and p.signals==0


def test_empty_proc_argv_live_or_reused_pid_is_not_accepted_or_signaled(tmp_path,monkeypatch):
 import r1pro_teleop.vla.training_pipeline as m
 class Child:
  pid=123;signals=0
  def poll(self):return None
  def wait(self,timeout):raise subprocess.TimeoutExpired('owned',timeout)
 p=Child();old_read=Path.read_bytes;old_resolve=Path.resolve
 monkeypatch.setattr(Path,'read_bytes',lambda path:b'' if str(path).replace('\\','/')=='/proc/123/cmdline' else old_read(path))
 monkeypatch.setattr(Path,'resolve',lambda path,*a,**k:tmp_path if str(path).replace('\\','/')=='/proc/123/cwd' else old_resolve(path,*a,**k))
 with pytest.raises(ValueError,match='live_owned_process_identity_changed'):m.verify_owned(p,['python','exact.py'],tmp_path)
 assert p.signals==0
