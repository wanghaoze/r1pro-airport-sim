import pathlib,json,difflib
B=pathlib.Path('/home/michelle/haoze/r1pro-airport-sim/releases');O=B/'coverage_v4_20260928/runs/firstpass';N=B/'robust_v24b_20260929/runs/fresh_verification/baseline';out=pathlib.Path('/home/michelle/haoze/r1pro-airport-sim/diagnostictools/support_forces_20260929_v1/v4_v24b_regression_audit')
def flat(x,p=''):
 if isinstance(x,dict):return {k:v for key,value in x.items() for k,v in flat(value,p+'.'+key).items()}
 if isinstance(x,list):return {k:v for i,value in enumerate(x) for k,v in flat(value,p+f'[{i}]').items()}
 return {p:x}
a=next((O/'scenes').glob('airport_0060_*'));b=next((N/'scenes').glob('airport_0060_*'));x=flat(json.loads((a/'scene.json').read_text()));y=flat(json.loads((b/'scene.json').read_text()));diff={k:[x.get(k),y.get(k)] for k in x.keys()|y.keys() if x.get(k)!=y.get(k)}
xml=''.join(difflib.unified_diff((a/'mobile.xml').read_text().splitlines(True),(b/'mobile.xml').read_text().splitlines(True)))
(out/'case60_scene_difference.json').write_text(json.dumps(diff,indent=2));(out/'case60_mobile.xml.diff').write_text(xml)
print('scene_diff',json.dumps(diff));print('xml_diff',xml[:2500])
for name,root in [('old',O),('new',N)]:
 p=next((root/'attempts').glob('airport_0060_*'))/'a000/events.jsonl';events=[json.loads(line) for line in p.read_text().splitlines()]
 chosen=[]
 for e in events:
  if e['frame']<500:
   d={k:v for k,v in e.items() if k not in ('reference_bounds','rejected','qualified')}
   if 'qualified' in e:d['qualified_count']=len(e['qualified'])
   chosen.append(d)
 (out/f'case60_{name}_all_events.json').write_text(json.dumps(chosen,indent=2));print(name,json.dumps(chosen))
