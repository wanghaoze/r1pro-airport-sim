"""New single-tray contact gate; independent of historical three-tray strictness."""
from pathlib import Path
import hashlib,json
import numpy as np
KEYS=('observed_hard_penetration_peak_m','observed_soft_payload_penetration_peak_m')
LIMITS=(.003,.005)

def sha(path):
 h=hashlib.sha256()
 with Path(path).open('rb') as f:
  while c:=f.read(8*1024*1024):h.update(c)
 return h.hexdigest()

def audit_contact_peaks(result,trace,*,raw_schema='airport_single_tray_raw/2',task_profile=None):
 """Post-tick cumulative samples include the final guarded failed substep."""
 import h5py
 trace=Path(trace);answer=dict(schema='airport_single_tray_contact_gate/1',definition='task_complete_and_all_guarded_hard_le_3mm_soft_le_5mm',hard_limit_m=.003,soft_limit_m=.005,coverage='unavailable',strict_contact_success=None,trace_sha256=sha(trace))
 with h5py.File(trace,'r') as f:
  if f.attrs.get('schema')!=raw_schema:raise ValueError('single_tray_raw2_contact_evidence_required')
  if task_profile is not None and json.loads(f.attrs['metadata_json']).get('task_profile')!=task_profile:raise ValueError('contact_evidence_task_profile_mismatch')
  declared=f.attrs.get('guard_penetration_peaks_json')
  if declared is None:
   answer['unavailable_reason']='raw_terminal_every_guarded_substep_peak_evidence_missing';return answer
  doc=json.loads(declared)
  if doc.get('schema')!='airport_single_tray_guard_penetration_peaks/1' or doc.get('coverage')!='every_guarded_physics_substep':raise ValueError('guard_peak_coverage_not_complete')
  n=int(f.attrs['num_frames'])
  if n!=result.get('frames'):raise ValueError('guard_peak_source_frame_identity_changed')
  observed=[]
  for key in KEYS:
   value=doc.get(key);claimed=result.get(key)
   if isinstance(value,bool) or not isinstance(value,(int,float)) or not np.isfinite(value) or value<0:raise ValueError('invalid_terminal_guard_peak:'+key)
   if isinstance(claimed,bool) or not isinstance(claimed,(int,float)) or not np.isfinite(claimed) or float(claimed)!=float(value):raise ValueError('result_raw_guard_peak_mismatch:'+key)
   if key not in f:raise ValueError('perframe_cumulative_guard_peak_missing:'+key)
   values=np.asarray(f[key][:],float)
   if values.shape!=(n,) or not np.isfinite(values).all() or np.any(values<0) or np.any(np.diff(values)<0) or (n and values[-1]!=value):raise ValueError('invalid_cumulative_guard_peak:'+key)
   observed.append(float(value))
  steps=doc.get('guarded_substeps');per_frame=np.asarray(f['executed_substeps'][:])
  if per_frame.shape!=(n,) or not np.issubdtype(per_frame.dtype,np.integer) or np.any(per_frame<0):raise ValueError('executed_substep_evidence_invalid')
  executed=int(per_frame.sum())
  if type(steps) is not int or steps!=executed:raise ValueError('guarded_substep_coverage_incomplete')
  if type(result.get('guarded_substeps')) is not int or result['guarded_substeps']!=steps:raise ValueError('result_raw_guarded_substep_count_mismatch')
  answer.update(coverage='every_guarded_physics_substep',guarded_substeps=steps,executed_substeps=executed,trace_sha256=sha(trace),terminal_guard_evidence_sha256=hashlib.sha256(json.dumps(doc,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest(),**dict(zip(KEYS,observed)))
  complete=result.get('task_completed') is True and result.get('physics_success') is True
  answer['strict_contact_success']=bool(complete and all(v<=limit for v,limit in zip(observed,LIMITS)))
  return answer

def summarize_cases(cases):
 rows=[]
 for case in cases:
  case=Path(case);result=json.loads((case/'result.json').read_text());proof=audit_contact_peaks(result,case/'attempt/trace.h5')
  rows.append(dict(case=str(case),result_sha256=sha(case/'result.json'),task_success=result.get('task_completed') is True and result.get('physics_success') is True,declared_control_profile=result.get('control_profile'),contact_gate=proof))
 groups=[]
 for limits in sorted({(r['declared_control_profile'].get('max_penetration_m'),r['declared_control_profile'].get('soft_payload_penetration_m')) for r in rows if isinstance(r['declared_control_profile'],dict)},key=str):
  subset=[r for r in rows if isinstance(r['declared_control_profile'],dict) and (r['declared_control_profile'].get('max_penetration_m'),r['declared_control_profile'].get('soft_payload_penetration_m'))==limits]
  groups.append(dict(declared_hard_limit_m=limits[0],declared_soft_payload_limit_m=limits[1],scene_count=len(subset),complete_task_success_count=sum(r['task_success'] for r in subset),strict_contact_success_count=sum(r['contact_gate']['strict_contact_success'] is True for r in subset),strict_contact_evidence_unavailable=sum(r['contact_gate']['coverage']=='unavailable' for r in subset)))
 covered=sum(r['contact_gate']['coverage']!='unavailable' for r in rows)
 return dict(schema='airport_single_tray_contact_batch_summary/1',source='simulation/program_generated',scene_count=len(rows),complete_task_success_count=sum(r['task_success'] for r in rows),strict_contact_success_count=sum(r['contact_gate']['strict_contact_success'] is True for r in rows),strict_contact_evidence_covered=covered,strict_contact_evidence_unavailable=len(rows)-covered,strict_contact_rate_all_cases=None if covered<len(rows) else sum(r['contact_gate']['strict_contact_success'] is True for r in rows)/len(rows) if rows else None,declared_contact_profile_groups=groups,rows=rows,historical_three_tray_strict_metric_used=False,acceptance_difference_not_control_improvement=True)



