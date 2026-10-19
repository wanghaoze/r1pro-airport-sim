exec(open('/home/michelle/haoze/r1pro-airport-sim/diagnostictools/support_forces_20260929_v1/audit_case60_v27_alignment.py').read().split('metrics={}')[0])
report=[]
for name,i,j in [('third_preplace',2661,2582),('third_descent_end',2691,2612),('third_push_entry',2719,2628)]:
 row={'stage':name,'frames':[i,j]}
 for k in ['action','qpos','qvel','tray_pose','table_contact','gripper_contact_force','min_z']:
  if k not in hs['v4']:continue
  a=hs['v4'][k][i];b=hs['v27'][k][j];row[k]={'old':np.asarray(a).tolist(),'new':np.asarray(b).tolist(),'maxdiff':float(np.max(abs(a-b)))}
 report.append(row)
(D/'third_stage_comparison.json').write_text(json.dumps(report,indent=2));print(json.dumps(report))
