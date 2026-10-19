import importlib.util,json
from pathlib import Path
import pytest
from r1pro_teleop.vla.training_pipeline import GPU_UUIDS
from r1pro_teleop.vla.training_cache import file_sha
spec=importlib.util.spec_from_file_location('data_version2_watcher',Path(__file__).parents[1]/'scripts/watch_three_table_data_version2.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

def fixture(tmp_path):
 cp=tmp_path/'checkpoints/9';(cp/'params').mkdir(parents=True);(cp/'train_state').mkdir();norm=cp/'norm.json';norm.write_text('{}');mile=tmp_path/'milestone_000010.json'
 mile.write_text(json.dumps(dict(schema='airport_pi05_training_milestone/1',prompt_mode='three_table_single_tray_action3_v1',checkpoint_verified=True,actual_completed_updates=10,checkpoint_step=9,checkpoint=str(cp),normalization=str(norm),norm_sha256=file_sha(norm))))
 (tmp_path/'train_to_000010.exit.json').write_text(json.dumps(dict(pid=123,returncode=0,trainer_exited=True,actual_own_gpu_rows=[[f'123, {u}, 5000' for u in GPU_UUIDS]])))
 folder=tmp_path/'evaluations/step_000010';folder.mkdir(parents=True);(folder/'model_gpu_receipt.json').write_text(json.dumps(dict(checkpoint_id='sha256:actual',rows=[dict(pid=321,gpu_uuid=GPU_UUIDS[1])])))
 return mile

def test_gate_requires_real_model_on_gpu1_and_reaped_dual_gpu_trainer(tmp_path,monkeypatch):
 mile=fixture(tmp_path);monkeypatch.setattr(module.subprocess,'check_output',lambda *a,**k:f'321, {GPU_UUIDS[1]}')
 old=Path.read_bytes
 def read(path):return ('python\0serve_pi05_airport.py\0--training-status\0'+str(mile)+'\0').encode() if path.name=='cmdline' and path.parent.name=='321' else old(path)
 monkeypatch.setattr(Path,'read_bytes',read);assert module.evaluation10_gate(tmp_path)['verified']
 monkeypatch.setattr(module.subprocess,'check_output',lambda *a,**k:f'321, {GPU_UUIDS[0]}');assert module.evaluation10_gate(tmp_path) is None

def test_metadata_saved_does_not_substitute_exit_or_weights(tmp_path,monkeypatch):
 fixture(tmp_path);(tmp_path/'train_to_000010.exit.json').write_text('{"returncode":1}')
 assert module.evaluation10_gate(tmp_path) is None
 (tmp_path/'checkpoints/9/train_state').rmdir()
 with pytest.raises(ValueError,match='checkpoint10_files'):module.evaluation10_gate(tmp_path)

def test_failed_main_allows_independent_data_only_with_actual_headroom(tmp_path,monkeypatch):
 (tmp_path/'pipeline_status.json').write_text(json.dumps({'stage':'failed_preserving_sources_and_checkpoints'}))
 def output(argv,**kwargs):return '' if '--query-compute-apps=pid,gpu_uuid' in argv else f'{GPU_UUIDS[0]}, 8000\n{GPU_UUIDS[1]}, 90000'
 monkeypatch.setattr(module.subprocess,'check_output',output)
 assert module.terminal_failure_gate(tmp_path)['trigger']=='main_pipeline_terminal_failure_gpu_available'
 monkeypatch.setattr(module,'reject_live_owned_children',lambda _:(_ for _ in ()).throw(ValueError('healthy child')))
 assert module.terminal_failure_gate(tmp_path) is None


def test_data_child_fault_budget_persists_no_second_trainer(tmp_path,monkeypatch):
 import r1pro_teleop.vla.three_table_recovery as recovery
 monkeypatch.setattr(recovery.time,'sleep',lambda _:None)
 run=tmp_path/'data';run.mkdir();options={'run_dir':str(run),'release':str(tmp_path),'vla_python':'python'};calls=[]
 def bad(argv,*args,**kwargs):calls.append(argv);raise RuntimeError('owned_child_failed:17')
 monkeypatch.setattr(module,'run_owned',bad)
 for _ in range(2):
  with pytest.raises(RuntimeError):module.execute_data_child(options,tmp_path/'options.json',tmp_path/'watch',{'verified':True})
 assert len(calls)==3 and all('--data-only' in a and all('train_pi05' not in v for v in a) for a in calls)


@pytest.mark.parametrize('stage',['preflight_contract_failed_preserving_sources_and_checkpoints','waiting_missing_qualified_media_split'])
def test_closed_data_or_preflight_block_can_release_independent_data_version2(tmp_path,monkeypatch,stage):
 (tmp_path/'pipeline_status.json').write_text(json.dumps({'stage':stage,'source_campaign_closed':True}))
 monkeypatch.setattr(module.subprocess,'check_output',lambda argv,**kwargs:'' if '--query-compute-apps=pid,gpu_uuid' in argv else f'{GPU_UUIDS[0]}, 8000')
 assert module.terminal_failure_gate(tmp_path)['verified']
 if stage=='waiting_missing_qualified_media_split':
  (tmp_path/'pipeline_status.json').write_text(json.dumps({'stage':stage,'source_campaign_closed':False}))
  assert module.terminal_failure_gate(tmp_path) is None
