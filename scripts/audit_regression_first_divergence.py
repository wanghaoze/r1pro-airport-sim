import pathlib,json,hashlib,collections,h5py,numpy as np
B=pathlib.Path('/home/michelle/haoze/r1pro-airport-sim/releases');O=B/'coverage_v4_20260928/runs/firstpass';N=B/'robust_v24b_20260929/runs/fresh_verification/baseline';A=B/'robust_v24b_20260929/runs/fresh_verification/additive';out=pathlib.Path('/home/michelle/haoze/r1pro-airport-sim/diagnostictools/support_forces_20260929_v1/v4_v24b_regression_audit')
def attempt(root,case):return next((root/'attempts').glob(f'airport_{case:04d}_*'))/'a000'
def convert(x):
 if isinstance(x,bytes):return x.decode()
 if isinstance(x,np.ndarray):return [convert(v) for v in x.tolist()]
 if isinstance(x,np.generic):return x.item()
 return x
result={}
for label,left,right,case in [('v4_baseline_60',O,N,60),('baseline_additive_176',N,A,176),('baseline_additive_300',N,A,300)]:
 lp,rp=attempt(left,case),attempt(right,case);info={};selected={}
 for name,p in [('left',lp),('right',rp)]:
  events=[json.loads(x) for x in (p/'events.jsonl').read_text().splitlines()]
  selected[name]=[e for e in events if e.get('event') in ('operation_selected','primitive_start','primitive_complete','primitive_failed','primitive_push_compliance_reference','primitive_push_feedforward','primitive_reference','push_yaw_feedback_suffix','reachability_screen','grasp_candidate_selected','transition','unloaded_tuck_timing')]
  (out/(label+'_'+name+'_events.json')).write_text(json.dumps(selected[name],indent=2))
 with h5py.File(lp/'trace.h5') as l,h5py.File(rp/'trace.h5') as r:
  for key in ('action','qpos','qvel','base_action','fsm_state','phase','tray_pose'):
   first=None;limit=min(len(l[key]),len(r[key]))
   for start in range(0,limit,64):
    x=l[key][start:start+64];y=r[key][start:start+64];n=min(len(x),len(y));x=x[:n];y=y[:n]
    different=np.not_equal(x,y);d=different.reshape(n,-1).any(axis=1)
    if d.any():
     index=start+int(np.flatnonzero(d)[0]);a=l[key][index];b=r[key][index]
     first=dict(frame=index,left=convert(a),right=convert(b))
     if np.issubdtype(np.asarray(a).dtype,np.number):first['max_abs_difference']=float(np.max(abs(a-b)))
     break
   info[key]=first
  firstframe=min(v['frame'] for v in info.values() if v is not None)
  info['first_divergence_context']={k:{side:convert(h[k][max(0,firstframe-1):firstframe+2]) for side,h in [('left',l),('right',r)]} for k in ('fsm_state','phase','target_tray','timestamp') if k in l and k in r}
 result[label]=info
report=json.loads((out/'audit.json').read_text());hashes=[]
for case in report['historical_success_cases']:
 entries={}
 for name,root in [('v4',O),('baseline',N),('additive',A)]:
  scene=next((root/'scenes').glob(f'airport_{case:04d}_*'))
  entries[name]={f:hashlib.sha256((scene/f).read_bytes()).hexdigest() for f in ('scene.json','mobile.xml')}
 hashes.append(dict(case=case,hashes=entries,all_equal=len({json.dumps(v,sort_keys=True) for v in entries.values()})==1))
result['scene_hashes']=hashes;(out/'first_divergence.json').write_text(json.dumps(result,indent=2))
print(json.dumps({k:{a:b for a,b in v.items() if a!='first_divergence_context'} for k,v in result.items() if k!='scene_hashes'}))
print('all_22_scene_json_xml_equal',all(x['all_equal'] for x in hashes))
