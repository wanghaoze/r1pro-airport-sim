"""Start independent dataset v2 export during actual milestone10 model evaluation."""
from pathlib import Path
import argparse,json,os,sys,time,subprocess
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from r1pro_teleop.vla.training_pipeline import write_atomic,run_owned,unused_path,GPU_UUIDS
from r1pro_teleop.vla.training_cache import file_sha
from r1pro_teleop.vla.three_table_recovery import StageJournal,reject_live_owned_children

def evaluation10_gate(training_run):
 root=Path(training_run);milestone=root/'milestone_000010.json';exit_files=list(root.glob('train_to_000010*.exit.json'))
 if not milestone.exists() or not exit_files:return None
 m=json.loads(milestone.read_text())
 if m.get('schema')!='airport_pi05_training_milestone/1' or m.get('prompt_mode')!='three_table_single_tray_action3_v1' or m.get('checkpoint_verified') is not True or m.get('actual_completed_updates')!=10 or m.get('checkpoint_step')!=9:raise ValueError('actual_scope_milestone10_required')
 checkpoint=Path(m.get('checkpoint','/nonexistent'));norm=Path(m.get('normalization','/nonexistent'))
 if not (checkpoint/'params').is_dir() or not (checkpoint/'train_state').is_dir() or not norm.is_file() or file_sha(norm)!=m.get('norm_sha256'):raise ValueError('actual_saved_checkpoint10_files_required')
 actual_exit=[]
 for path in exit_files:
  receipt=json.loads(path.read_text());devices={row.split(',')[1].strip() for group in receipt.get('actual_own_gpu_rows',[]) for row in group}
  if receipt.get('returncode')==0 and receipt.get('trainer_exited') is True and devices==set(GPU_UUIDS):actual_exit.append(dict(path=str(path),sha256=file_sha(path),pid=receipt['pid']))
 if not actual_exit:return None
 gpu_rows=subprocess.check_output(['nvidia-smi','--query-compute-apps=pid,gpu_uuid','--format=csv,noheader'],text=True)
 active={int(x.split(',')[0]):x.split(',')[1].strip() for x in gpu_rows.splitlines() if x.strip()}
 for path in root.glob('train_to_*.startup.json'):
  old=json.loads(path.read_text());pid=old.get('pid')
  if pid in active:
   try:command=[v.decode() for v in (Path('/proc')/str(pid)/'cmdline').read_bytes().rstrip(b'\0').split(b'\0')]
   except OSError:continue
   if command==old.get('argv'):return None
 receipt=root/'evaluations/step_000010/model_gpu_receipt.json'
 if not receipt.exists():return None
 model=json.loads(receipt.read_text());proven=[]
 for row in model.get('rows',[]):
  pid=row['pid']
  if active.get(pid)!=GPU_UUIDS[1]:continue
  try:command=[v.decode() for v in (Path('/proc')/str(pid)/'cmdline').read_bytes().rstrip(b'\0').split(b'\0')]
  except OSError:continue
  if '--training-status' in command and command[command.index('--training-status')+1]==str(milestone) and any(Path(c).name=='serve_pi05_airport.py' for c in command):proven.append(dict(pid=pid,gpu_uuid=GPU_UUIDS[1],argv=command))
 if not proven:return None
 return dict(verified=True,milestone_sha256=file_sha(milestone),actual_trainer_exits=actual_exit,actual_active_gpu1_model=proven,checkpoint_id=model['checkpoint_id'],no_active_owned_trainer=True)

def terminal_failure_gate(training_run):
 root=Path(training_run);status_path=root/'pipeline_status.json'
 if not status_path.exists():return None
 status=json.loads(status_path.read_text())
 if status.get('stage') not in ('failed_preserving_sources_and_checkpoints','preflight_contract_failed_preserving_sources_and_checkpoints','waiting_missing_qualified_media_split','blocked_frozen_batch_media_case'):return None
 if status.get('stage')=='waiting_missing_qualified_media_split' and status.get('source_campaign_closed') is not True:return None
 try:reject_live_owned_children(root)
 except ValueError:return None
 rows=subprocess.check_output(['nvidia-smi','--query-compute-apps=pid,gpu_uuid','--format=csv,noheader'],text=True)
 for row in rows.splitlines():
  if not row.strip():continue
  pid=int(row.split(',')[0])
  try:argv=[v.decode() for v in (Path('/proc')/str(pid)/'cmdline').read_bytes().rstrip(b'\0').split(b'\0')]
  except OSError:continue
  if any(Path(v).name.startswith(('train_pi05','serve_pi05','evaluate_three_table')) for v in argv):return None
 free_rows=subprocess.check_output(['nvidia-smi','--query-gpu=uuid,memory.free','--format=csv,noheader,nounits'],text=True)
 free={r.split(',')[0].strip():int(r.split(',')[1]) for r in free_rows.splitlines() if r.strip()}
 if free.get(GPU_UUIDS[0],0)<6000:return None
 return dict(verified=True,trigger='main_pipeline_terminal_failure_gpu_available',main_status_sha256=file_sha(status_path),actual_free_mib=free,no_active_owned_trainer_or_model=True,unrelated_processes_not_signaled=True)

def execute_data_child(options,path,out,gate):
 env=dict(os.environ,CUDA_VISIBLE_DEVICES='',OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1');env.pop('JAX_PLATFORMS',None)
 artifact=Path(options['run_dir'])/'pipeline_status.json'
 def verify():
  completed=json.loads(artifact.read_text())
  if completed.get('stage')!='data_only_exports_verified_no_training' or completed.get('training_started') is not False:raise ValueError('data_only_child_exited_without_verified_split_exports')
  return dict(verified=True,pipeline_status_sha256=file_sha(artifact),dataset_status=completed)
 def pulse(stage,**values):
  write_atomic(out/'status.json',dict(stage=stage,pid=os.getpid(),heartbeat_unix=time.time(),training_started=False,data_only=True,actual_gate=gate,**values))
 def operation(progress):
  argv=[options['vla_python'],str(Path(options['release'])/'scripts/supervise_three_table_single_tray_training.py'),'--options',str(path),'--data-only']
  if artifact.exists():argv.append('--recover')
  return run_owned(argv,options['release'],env,unused_path(out/'data_version2.log'),on_progress=progress)
 complete=artifact.exists() and json.loads(artifact.read_text()).get('stage')=='data_only_exports_verified_no_training'
 # A durable watcher attempt is closed only by the child exit AND actual
 # independent pipeline completion proof; ordinary faults are bounded across restarts.
 result=StageJournal(out,pulse).execute('data_version2',operation,artifact=artifact if complete else None,verify=verify)
 pulse('data_only_v2_verified_complete',optimizer_initialized=False,actual_exit=result,verification=verify())
 return result

def main():
 p=argparse.ArgumentParser();p.add_argument('--options',required=True);p.add_argument('--training-run',required=True);p.add_argument('--watch-dir',required=True);a=p.parse_args();out=Path(a.watch_dir);out.mkdir(parents=True,exist_ok=True)
 import fcntl
 lock=(out/'watcher.lock').open('a+');fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
 path=Path(a.options);digest=file_sha(path);options=json.loads(path.read_text())
 if options.get('data_only') is not True or options.get('data_version')!='v2':raise ValueError('explicit_independent_data_only_v2_options_required')
 while True:
  if file_sha(path)!=digest:raise ValueError('immutable_data_only_options_changed')
  gate=terminal_failure_gate(a.training_run) or evaluation10_gate(a.training_run)
  write_atomic(out/'status.json',dict(stage='waiting_actual_milestone10_gpu1_evaluation' if gate is None else 'milestone10_gate_verified',pid=os.getpid(),heartbeat_unix=time.time(),training_started=False,data_only=True,actual_gate=gate,options_sha256=digest))
  if gate:break
  time.sleep(15)
 try:execute_data_child(options,path,out,gate)
 except Exception as error:
  write_atomic(out/'status.json',dict(stage='data_only_watch_contract_or_fault_budget_blocked',pid=os.getpid(),heartbeat_unix=time.time(),training_started=False,data_only=True,last_error=repr(error),actual_gate=gate));raise
if __name__=='__main__':main()
