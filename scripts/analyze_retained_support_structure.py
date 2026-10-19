"""Read existing private force CSVs; no simulation or collection writes."""
import csv,json,pathlib,numpy as np
root=pathlib.Path(__file__).resolve().parents[1]
evidence=root/'evidence/project_validation/support_forces_20260929/local_push'
output=[]
for name in ['local_push_case4_third_original','force_feedback/local_full_push_v11case5_force_baseline']:
 rows=list(csv.DictReader((evidence/name/'forces.csv').open()));d={k:np.array([float(r[k]) for r in rows]) for k in rows[0]};t=d['time_s']-d['time_s'][0]+.002
 windows=[]
 for lo,hi in [(0,.5),(.5,1.5),(1.5,2.7)]:
  mask=(t>lo)&(t<=hi);fn=d['table_normal_n'][mask];fg=d['gripper_vertical_n'][mask]
  windows.append(dict(start_s=lo,end_s=min(hi,float(t[-1])),samples=int(mask.sum()),support_fraction=float(np.mean(d['table_contacts'][mask]>0)),table_mean_n=float(fn.mean()),table_peak_n=float(fn.max()),gripper_vertical_mean_n=float(fg.mean()),gripper_vertical_min_n=float(fg.min()),gripper_vertical_max_n=float(fg.max()),same_step_table_gripper_correlation=float(np.corrcoef(fn,fg)[0,1]),bottom_range_m=float(np.ptp(d['bottom_z'][mask]))))
 output.append(dict(source=name,windows=windows))
(evidence/'retained_support_structure.json').write_text(json.dumps(dict(qualification='existing_exact_private_replay_evidence_not_56_case_causal_proof',positive_gripper_vertical='upward_force_on_tray',cases=output),indent=2))
