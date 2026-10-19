"""Read-only completed fresh case60 versus frozen historical/current baselines."""
import pathlib,json,h5py,numpy as np
D=pathlib.Path('/home/michelle/haoze/r1pro-airport-sim/diagnostictools/support_forces_20260929_v1');B=pathlib.Path('/home/michelle/haoze/r1pro-airport-sim/releases')
roots={'v4':B/'coverage_v4_20260928/runs/firstpass','v24b_baseline':B/'robust_v24b_20260929/runs/fresh_verification/baseline','v27_shortcut':D/'v27_case60_shortcut_fresh'}
report={};paths={}
for name,root in roots.items():
 attempt=next((root/'attempts').glob('airport_0060_*'))/'a000';paths[name]=attempt
 result=json.loads((attempt/'result.json').read_text());events=[json.loads(line) for line in (attempt/'events.jsonl').read_text().splitlines()]
 chosen=[e for e in events if e['event'] in ('free_space_joint_shortcut','empty_arm_shortcut_timing','direct_grasp_preflight_rejected','primitive_start','primitive_complete','primitive_failed','operation_failed','operation_selected')]
 report[name]={k:result.get(k) for k in ('physics_success','failure_code','error','frames','operations','simulation_seconds','wall_seconds','acceptance')};report[name]['events']=chosen
with h5py.File(paths['v4']/'trace.h5') as old,h5py.File(paths['v27_shortcut']/'trace.h5') as new:
 changes={}
 for key in ('action','qpos','qvel','phase','fsm_state','tray_pose'):
  change=None;n=min(len(old[key]),len(new[key]))
  for start in range(0,n,64):
   end=min(n,start+64);a=old[key][start:end];b=new[key][start:end];where=np.not_equal(a,b).reshape(end-start,-1).any(1)
   if where.any():
    index=start+int(np.flatnonzero(where)[0]);x,y=old[key][index],new[key][index];change=dict(frame=index)
    if np.issubdtype(np.asarray(x).dtype,np.number):change['max_abs_difference']=float(np.max(abs(x-y)))
    break
  changes[key]=change
 report['first_differences_vs_v4']=changes
out=D/'v27_case60_shortcut_fresh/comparison.json';out.write_text(json.dumps(report,indent=2));print(json.dumps({k:({a:b for a,b in v.items() if a!='events'} if k!='first_differences_vs_v4' else v) for k,v in report.items()}))
