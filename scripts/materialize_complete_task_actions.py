"""Export complete action windows without starting training or a GPU model."""
import argparse,json,os,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from r1pro_teleop.vla.data_task_lerobot import materialize_complete_task_split,available_native_overrides,assemble_complete_task_split

def main():
 parser=argparse.ArgumentParser()
 parser.add_argument('--plans',required=True);parser.add_argument('--label-spec',required=True)
 parser.add_argument('--destination',required=True);parser.add_argument('--repo-id',required=True)
 parser.add_argument('--native-references');parser.add_argument('--incremental',action='store_true');parser.add_argument('--poll-seconds',type=int,default=30)
 parser.add_argument('--split',required=True,choices=['train','val','test']);parser.add_argument('--max-scenes',type=int)
 args=parser.parse_args()
 if args.incremental:
  return incremental(args)
 result=materialize_complete_task_split(args.plans,args.label_spec,args.destination,args.repo_id,split=args.split,max_scenes=args.max_scenes)
 print(json.dumps(result,indent=2))
def incremental(args):
 if not args.native_references:raise ValueError('incremental_native_publication_required')
 destination=Path(args.destination);destination.mkdir(parents=True,exist_ok=False)
 cases=[json.loads(line) for line in Path(args.plans).read_text().splitlines() if line.strip()]
 cases=[case for case in cases if case['original_inventory']['split']==args.split]
 completed=[]
 def status(stage,**extra):
  payload=dict(stage=stage,split=args.split,expected_scenes=len(cases),completed_scenes=len(completed),cases=completed,dataset_ready=(stage=='complete'),training_started=False,**extra)
  tmp=destination/'status.json.tmp';tmp.write_text(json.dumps(payload,indent=2));tmp.replace(destination/'status.json')
 while len(completed)<len(cases):
  overrides=available_native_overrides(cases,json.loads(Path(args.native_references).read_text()))
  for case in cases:
   task=case['original_inventory'];sid=task['scene_id']
   if any(item['scene_id']==sid for item in completed) or sid not in overrides:continue
   status('exporting_case',active_scene=sid)
   plan_path=destination/'plans'/f'{sid}.jsonl';plan_path.parent.mkdir(exist_ok=True)
   plan_path.write_text(json.dumps(case)+'\n')
   try:
    result=materialize_complete_task_split(plan_path,args.label_spec,destination/'cases'/sid,args.repo_id+'_'+sid,split=args.split,native_overrides=overrides)
   except Exception as error:
    status('failed',active_scene=sid,error=repr(error));raise
   completed.append(dict(result,scene_id=sid))
   # Publish actual completed media paths while later scenes are still rendering.
   lines=[]
   for item in completed:lines.extend((Path(item['path'])/'COMPLETE_ACTION_VIDEO_INDEX.txt').read_text().splitlines())
   tmp=destination/'COMPLETE_ACTION_VIDEO_INDEX.txt.tmp';tmp.write_text('\n'.join(lines)+'\n');tmp.replace(destination/'COMPLETE_ACTION_VIDEO_INDEX.txt')
   status('case_completed')
  if len(completed)<len(cases):status('waiting_native_cases');time.sleep(args.poll_seconds)
 status('assembling_complete_split')
 result=assemble_complete_task_split([item['path'] for item in completed],destination/'dataset',args.repo_id,split=args.split,expected_scene_ids=[case['original_inventory']['scene_id'] for case in cases])
 status('complete',split_dataset=result)
if __name__=='__main__':main()
