import pathlib,json
root=pathlib.Path('/home/michelle/haoze/r1pro-airport-sim/releases/robust_v21_20260929/runs/ablation/geometry')
for case in [7,218]:
 a=next((root/'attempts').glob(f'airport_{case:04d}_*/a000'));events=[json.loads(x) for x in (a/'events.jsonl').read_text().splitlines()];op=None;rim=None
 for e in events:
  if e['event']=='operation_selected':op=e
  if e['event']=='affordance_candidate':rim=e
  if e['event']=='primitive_start' and e.get('primitive') in ['place','push']:print(json.dumps(dict(case=case,operation=op,rim=rim,primitive=e)))
