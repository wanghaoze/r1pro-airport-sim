import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from r1pro_teleop.vla.three_table_training_resume import verify_external_training,training_resume_command
from r1pro_teleop.vla.training_cache import file_sha
from r1pro_teleop.vla.training_pipeline import GPU_UUIDS


def fixture(tmp_path):
 old=tmp_path/'original_training';new=tmp_path/'new_orchestration';release=tmp_path/'frozen_training';old.mkdir();new.mkdir()
 spec={'run_dir':str(old),'dataset_root':str(old/'datasets/train'),'prompt_mode':'three_table_single_tray_action3_v1','num_train_steps':100000};sp=tmp_path/'original_spec.json';sp.write_text(json.dumps(spec));hashes={str(sp):file_sha(sp)}
 files=[old/'data_cache/cache_manifest.json',old/'acceleration_spec.json']
 files += [old/'datasets'/split/name for split in ('train','val','test') for name in ('airport_training_manifest.json','whole_action_source_manifest.jsonl')]
 files += [release/name for name in ('scripts/train_pi05_accelerated.py','r1pro_teleop/vla/training_accelerated.py','r1pro_teleop/vla/training.py')]
 for path in files:path.parent.mkdir(parents=True,exist_ok=True);path.write_text('{}');hashes[str(path)]=file_sha(path)
 mile=old/'milestone_000010.json';mile.write_text(json.dumps(dict(actual_completed_updates=10,checkpoint_step=9,checkpoint_verified=True,spec=spec)))
 exitfile=old/'train_to_000010.exit.json';exitfile.write_text(json.dumps(dict(returncode=0,trainer_exited=True,argv=['python',str(release/'scripts/train_pi05_accelerated.py'),'--spec',str(sp),'--stop-after','10'],actual_own_gpu_rows=[[f'100,{u},5000' for u in GPU_UUIDS]])))
 options=dict(external_training_run=str(old),run_dir=str(new),training_release=str(release),release=str(tmp_path/'new_evaluator'),spec=str(sp),initial_milestone=str(mile),initial_train_exit=str(exitfile),initial_milestone_sha256=file_sha(mile),initial_train_exit_sha256=file_sha(exitfile),initial_checkpoint_id='sha256:actual-model10',external_input_sha256=hashes,vla_python='python',parent_status='original_initializer.json')
 return options


def test_resume_keeps_original_spec_optimizer_code_and_new_evaluation_directory(tmp_path):
 from r1pro_teleop.vla.three_table_single_tray_pipeline import evaluation_command
 options=fixture(tmp_path);before={p:Path(p).read_bytes() for p in options['external_input_sha256']};spec,receipt=verify_external_training(options)
 command=training_resume_command(options,100)
 assert command[1]==str(Path(options['training_release'])/'scripts/train_pi05_accelerated.py') and '--resume' in command
 assert command[command.index('--spec')+1]==options['spec'] and spec['run_dir']==options['external_training_run']
 assert receipt['new_optimizer_initialized'] is False
 protocol=tmp_path/'protocol.json';protocol.write_text('{}');driver=Path(options['release'])/'scripts/evaluate_three_table_single_tray_pi05_batch.py';driver.parent.mkdir(parents=True);driver.write_text('# mocked CLI')
 options.update(evaluation_protocol=str(protocol),sim_python='sim')
 destination=Path(options['run_dir'])/'evaluations/step_000010';argv=evaluation_command(options,options['initial_milestone'],destination)
 assert argv[argv.index('--out')+1]==str(destination) and argv[argv.index('--milestone')+1]==options['initial_milestone']
 assert all(Path(p).read_bytes()==contents for p,contents in before.items())
 with pytest.raises(ValueError,match='not_retrained'):training_resume_command(options,10)


def test_external_recipe_and_actual_exit_cannot_be_silently_rebound(tmp_path):
 options=fixture(tmp_path);path=Path(options['training_release'])/'r1pro_teleop/vla/training_accelerated.py';path.write_text('changed math')
 with pytest.raises(ValueError,match='input_changed'):verify_external_training(options)
 options['external_input_sha256'][str(path)]=file_sha(path);exitfile=Path(options['initial_train_exit']);row=json.loads(exitfile.read_text());row['actual_own_gpu_rows']=[[f'100,{GPU_UUIDS[0]},5000']];exitfile.write_text(json.dumps(row));options['initial_train_exit_sha256']=file_sha(exitfile)
 with pytest.raises(ValueError,match='dual_gpu'):verify_external_training(options)

def test_external_orchestration_routes_all_evals_new_and_resumes_original_optimizer(tmp_path,monkeypatch):
 import sys
 import r1pro_teleop.vla.three_table_training_resume as m
 options=fixture(tmp_path);options.update(core_report=str(tmp_path/'core.json'),evaluation_protocol=str(tmp_path/'protocol.json'),sim_python='sim')
 Path(options['core_report']).write_text('{"returncode":0}');Path(options['evaluation_protocol']).write_text('{}')
 release=Path(options['release']);driver=release/'scripts/evaluate_three_table_single_tray_pi05_batch.py';driver.parent.mkdir(parents=True);driver.write_text('# CPU fixture only')
 old=Path(options['external_training_run']);(old/'source_records.jsonl').write_text('');old_eval=old/'evaluations/step_000010';old_eval.mkdir(parents=True);(old_eval/'failure.json').write_text('original failure immutable')
 initial_spec=Path(options['spec']).read_bytes();commands=[]
 monkeypatch.setitem(sys.modules,'fcntl',SimpleNamespace(flock=lambda *a:None,LOCK_EX=1,LOCK_NB=2))
 monkeypatch.setattr(m,'cache_proof',lambda *a:{'verified':True});monkeypatch.setattr(m,'dataset_proof',lambda *a,**k:{'verified':True});monkeypatch.setattr(m,'training_resources',lambda **k:{'ready':True})
 monkeypatch.setattr(m,'milestone_proof',lambda p,*a:{'verified':True,'actual_checkpoint_id':options['initial_checkpoint_id']})
 def child(argv,cwd,env,log,**kwargs):
  commands.append((argv,str(cwd)))
  receipt=dict(returncode=0,trainer_exited=True,argv=argv,pid=999,actual_own_gpu_rows=[[f'999,{u},5000' for u in GPU_UUIDS]])
  if '--resume' in argv:
   n=int(argv[argv.index('--stop-after')+1]);(old/f'milestone_{n:06d}.json').write_text(json.dumps(dict(actual_completed_updates=n,checkpoint_step=n-1,schema='airport_pi05_training_milestone/1',prompt_mode='three_table_single_tray_action3_v1',checkpoint_verified=True)))
  else:
   dest=Path(argv[argv.index('--out')+1]);dest.mkdir(parents=True);mile=Path(argv[argv.index('--milestone')+1]);n=json.loads(mile.read_text())['actual_completed_updates'];(dest/'completion_receipt.json').write_text(json.dumps(dict(schema='airport_three_table_single_tray_evaluation_handoff/1',task_profile='three_table_single_tray_action3_v1',actual_completed_updates=n,training_status_sha256=file_sha(mile),status='evaluation_completed_gpu_released',training_resume_allowed=True,new_three_table_single_tray_protocol_id='cpu-fixture')))
  Path(log).with_suffix('.exit.json').write_text(json.dumps(receipt));return receipt
 monkeypatch.setattr(m,'run_owned',child);m.supervise_external_resume(options)
 trains=[argv for argv,_ in commands if '--resume' in argv];evals=[argv for argv,_ in commands if '--out' in argv]
 assert [int(a[a.index('--stop-after')+1]) for a in trains]==[100,1000,10000,100000]
 assert len(evals)==5 and all(Path(a[a.index('--out')+1]).is_relative_to(Path(options['run_dir'])) for a in evals)
 assert all(Path(a[1]).parent.parent==Path(options['training_release']) for a in trains)
 assert Path(options['spec']).read_bytes()==initial_spec and (old_eval/'failure.json').read_text()=='original failure immutable'
 assert json.loads((Path(options['run_dir'])/'pipeline_status.json').read_text())['training_complete'] is True
