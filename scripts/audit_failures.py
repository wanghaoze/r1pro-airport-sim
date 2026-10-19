"""Read-only failure audit. Never changes a collection or labels."""
import argparse,json,collections
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
rows=[];counts=collections.Counter();phases=collections.Counter();incomplete=[]
for d in sorted((a.root/'attempts').glob('*/a*')):
 if not d.is_dir():continue
 result=d/'result.json'
 if not result.exists():incomplete.append(str(d));continue
 r=json.loads(result.read_text());scene=d.parent.name
 last_state=None;last_failure=None;last_primitive=None;rejections=collections.Counter();malformed=0
 events=d/'events.jsonl'
 if events.exists():
  for line in events.read_text().splitlines():
   try:e=json.loads(line)
   except json.JSONDecodeError:malformed+=1;continue
   name=e.get('event')
   if name=='state_transition':last_state=e
   if name in ('operation_failed','primitive_failed'):last_failure=e
   if name=='primitive_start':last_primitive=e
   if name=='candidate_rejected':rejections[e.get('code','unknown')]+=1
 state=(last_state or {}).get('state','unknown');phase=(last_state or {}).get('phase','unknown')
 code=r.get('failure_code') or ('clean_success' if r.get('physics_success') and not r.get('recovery_used') else 'recovered_success' if r.get('physics_success') else 'unknown_failure')
 counts[code]+=1;phases[(code,state,phase)]+=1
 spec_path=a.root/'scenes'/scene/'scene.json';spec=json.loads(spec_path.read_text()) if spec_path.exists() else {}
 rows.append(dict(scene_id=scene,attempt=d.name,code=code,simulation_seconds=r.get('simulation_seconds'),wall_seconds=r.get('wall_seconds'),error=r.get('error'),difficulty=spec.get('difficulty'),front_count=spec.get('front_count'),last_state=last_state,last_failure=last_failure,last_primitive=last_primitive,candidate_rejections=dict(rejections),malformed_event_lines=malformed,trace=str(d/'trace.h5')))
report=dict(root=str(a.root),completed_attempts=len(rows),incomplete_attempt_directories=incomplete,counts=dict(counts.most_common()),failure_phases=[dict(code=k[0],state=k[1],phase=k[2],count=v) for k,v in phases.most_common()],rows=rows)
with a.output.open('x') as f:json.dump(report,f,indent=2)
print(json.dumps({k:v for k,v in report.items() if k not in ('rows','failure_phases')},indent=2))
print(json.dumps(report['failure_phases'][:15],indent=2))
