import pathlib,json
root=pathlib.Path('/home/michelle/haoze/r1pro-airport-sim/releases')
out=[]
for rel,vs in [('robust_v19_20260929',['alternate_align','alternate_feedback','baseline']),('robust_v18_20260929',['baseline'])]:
 for v in vs:
  for p in (root/rel/'runs/ablation'/v/'attempts').glob('*/a000/result.json'):
   if int(p.parents[1].name.split('_')[1]) not in [4,218,310]:continue
   es=[json.loads(x) for x in (p.parent/'events.jsonl').read_text().splitlines()];res=json.loads(p.read_text());res={k:res.get(k) for k in ['failure_code','error','frames','simulation_seconds','physics_success']}
   out.append(dict(release=rel,variant=v,scene=p.parents[1].name,result=res,events_tail=es[-14:]))
pathlib.Path('/home/michelle/haoze/r1pro-airport-sim/diagnostictools/support_forces_20260929_v1/v19_camera_events.json').write_text(json.dumps(out,indent=2))
print(json.dumps(out))

