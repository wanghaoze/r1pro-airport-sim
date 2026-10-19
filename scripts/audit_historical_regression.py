"""Read-only historical baseline provenance and regression audit."""
import json,pathlib,hashlib,difflib,collections
BASE=pathlib.Path('/home/michelle/haoze/r1pro-airport-sim/releases')
old=BASE/'coverage_v4_20260928';new=BASE/'robust_v24b_20260929';roots={'v4':old/'runs/firstpass','baseline':new/'runs/fresh_verification/baseline','additive':new/'runs/fresh_verification/additive'}
out=pathlib.Path('/home/michelle/haoze/r1pro-airport-sim/diagnostictools/support_forces_20260929_v1/v4_v24b_regression_audit');out.mkdir(exist_ok=True)
def read(p):return json.loads(p.read_text())
def results(root):return {int(p.parent.parent.name.split('_')[1]):(read(p),p.parent) for p in (root/'attempts').glob('*/a000/result.json')}
r={k:results(v) for k,v in roots.items()};success=sorted(i for i,(x,_) in r['v4'].items() if x['physics_success']);collections_meta={k:read(v/'collection.json') for k,v in roots.items()}
configdiff={key:{k:meta['config'].get(key,'<absent>') for k,meta in collections_meta.items()} for key in sorted(set().union(*(x['config'] for x in collections_meta.values()))) if len({json.dumps(meta['config'].get(key,'<absent>'),sort_keys=True) for meta in collections_meta.values()})>1}
rows=[]
for i in success:
 row={'case':i}
 for name,data in r.items():
  if i not in data:row[name]={'status':'missing'};continue
  result,folder=data[i];events=[json.loads(line) for line in (folder/'events.jsonl').read_text().splitlines()]
  failure_events=[e for e in events if 'fail' in e.get('event','') or 'abort' in e.get('event','')]
  context=[e for e in events if e.get('event') in ('operation_selected','primitive_start','primitive_complete','transition','phase','push_yaw_feedback_suffix')][-8:]
  row[name]={k:result.get(k) for k in ('physics_success','failure_code','error','operations','frames','simulation_seconds','recovery_used')}
  row[name].update(failure_events=failure_events[-3:],last_context=context)
 rows.append(row)
report=dict(roots={k:str(v) for k,v in roots.items()},historical_success_cases=success,completed_counts={k:len(v) for k,v in r.items()},all_completed_success_counts={k:sum(x[0]['physics_success'] for x in v.values()) for k,v in r.items()},config_diff=configdiff,collection_provenance={k:{key:meta.get(key) for key in ('schema','fingerprint','source_manifest','source_manifest_sha256')} for k,meta in collections_meta.items()},historical_success_rows=rows)
(out/'audit.json').write_text(json.dumps(report,indent=2))
for file in ('primitives.py','runtime.py','machine.py','geometry.py','trajectory.py','contracts.py','scheduler.py'):
 a=old/'r1pro_teleop/airport_fsm'/file;b=new/'r1pro_teleop/airport_fsm'/file
 if a.exists() and b.exists():
  delta=''.join(difflib.unified_diff(a.read_text().splitlines(True),b.read_text().splitlines(True),fromfile=str(a),tofile=str(b)))
  (out/(file+'.diff')).write_text(delta)
print(json.dumps({k:v for k,v in report.items() if k not in ('historical_success_rows',)}))
for row in rows:print(json.dumps({k:({x:v.get(x) for x in ('physics_success','failure_code','simulation_seconds','error')} if isinstance(v,dict) else v) for k,v in row.items()}))
