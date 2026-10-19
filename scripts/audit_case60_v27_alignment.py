import pathlib,json,h5py,numpy as np
B=pathlib.Path('/home/michelle/haoze/r1pro-airport-sim/releases');D=B.parent/'diagnostictools/support_forces_20260929_v1/v27_case60_shortcut_fresh'
roots={'v4':B/'coverage_v4_20260928/runs/firstpass','v27':D};out={};hs={}
for n,root in roots.items():
 a=next((root/'attempts').glob('airport_0060_*'))/'a000';hs[n]=h5py.File(a/'trace.h5');es=[json.loads(s) for s in (a/'events.jsonl').read_text().splitlines()];out[n]={'events':es,'keys':list(hs[n])}
for n in roots:
 h=hs[n];out[n]['phase_segments']=[]
 for key in ['phase','fsm_state']:
  ar=h[key][:];idx=np.r_[0,np.flatnonzero(ar[1:]!=ar[:-1])+1];out[n][key+'_segments']=[{'frame':int(i),'value':str(ar[i])} for i in idx]
metrics={}
for key in ['action','qpos','qvel','tray_pose']:
 a=hs['v4'][key][:821];b=hs['v27'][key][:821];diff=abs(a-b).reshape(len(a),-1).max(1)
 metrics[key]={'first_over':{str(t):(int(np.flatnonzero(diff>t)[0]) if (diff>t).any() else None) for t in [1e-7,1e-6,1e-5,1e-4,.001,.01]},'windows':[{'start':s,'end':e,'max':float(diff[s:e].max())} for s,e in [(0,377),(377,428),(428,541),(541,591),(591,785),(785,820)]]}
out['metrics']=metrics
(D/'detailed_alignment.json').write_text(json.dumps(out,indent=2));print(json.dumps(metrics));
for n in roots:
 print(n,'PHASE',json.dumps(out[n]['phase_segments']))
 print(n,'EVENTS',json.dumps([e for e in out[n]['events'] if 780<=e['frame']<=880]))
