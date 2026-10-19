"""Additive qualification of closed physically complete sources; no physics rerun."""
from pathlib import Path
import argparse,json,sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from r1pro_teleop.vla.data_three_table_lerobot import build_source
from r1pro_teleop.vla.training_cache import file_sha
from r1pro_teleop.vla.training_pipeline import write_atomic

def main():
 p=argparse.ArgumentParser();p.add_argument('--campaign',required=True);p.add_argument('--output',required=True);p.add_argument('--projection-cache');a=p.parse_args();out=Path(a.output);out.mkdir(parents=True,exist_ok=False)
 write_atomic(out/'status.json',dict(stage='starting_additive_source_audit',heartbeat_unix=__import__('time').time(),physics_rerun=False))
 status_path=Path(a.campaign)/'status.json';status=json.loads(status_path.read_text());rows=[];errors=[]
 for number,row in enumerate(status['results']):
  case=Path(row['result']).parent;result=json.loads(Path(row['result']).read_text())
  if result.get('task_completed') is not True or result.get('physics_success') is not True:continue
  write_atomic(out/'status.json',dict(stage='qualifying_closed_source',heartbeat_unix=__import__('time').time(),current_case=str(case),current_case_index=number,verified=len(rows),failures=errors,physics_rerun=False,actual_replay_progress=str(out/f'case_{number:04d}_table_contacts.progress.json')))
  try:
   directory=out/f'case_{number:04d}';source,plan=build_source(case,directory,repair_submitted_commands=True,contact_projection_cache=a.projection_cache);certificate=directory/'source_qualification_audit.json'
   rows.append(dict(original_case=str(case),qualification_dir=str(directory.resolve()),split=source['split'],certificate_sha256=file_sha(certificate)))
  except Exception as error:errors.append(dict(case=str(case),error=repr(error)))
  write_atomic(out/'status.json',dict(stage='qualifying_closed_sources',original_campaign_status_sha256=file_sha(status_path),verified=len(rows),failures=errors,physics_rerun=False))
 catalog=dict(schema='airport_three_table_certified_source_catalog/1',records=rows,errors=errors,original_campaign_status_sha256=file_sha(status_path),all_splits_qualified=all(any(r['split']==s for r in rows) for s in ('train','val','test')),old_artifacts_unchanged=True,physics_rerun=False)
 write_atomic(out/'catalog.json',catalog);write_atomic(out/'status.json',dict(stage='complete' if not errors else 'closed_with_qualification_failures',verified=len(rows),failures=errors,all_splits_qualified=catalog['all_splits_qualified'],physics_rerun=False));print(json.dumps(catalog));return 0 if catalog['all_splits_qualified'] else 2
if __name__=='__main__':raise SystemExit(main())
