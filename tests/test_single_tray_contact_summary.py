import json
import h5py,numpy as np,pytest
from r1pro_teleop.single_tray_lab.contact_summary import audit_contact_peaks,summarize_cases,KEYS

def fixture(tmp_path,hard=.003,soft=.005,complete=True):
 case=tmp_path/'case';(case/'attempt').mkdir(parents=True);result=dict(frames=2,guarded_substeps=50,task_completed=complete,physics_success=complete,control_profile={'max_penetration_m':.005})
 result.update(dict(zip(KEYS,(hard,soft))));(case/'result.json').write_text(json.dumps(result))
 with h5py.File(case/'attempt/trace.h5','w') as f:
  f.attrs.update(schema='airport_single_tray_raw/2',num_frames=2,guard_penetration_peaks_json=json.dumps(dict(schema='airport_single_tray_guard_penetration_peaks/1',coverage='every_guarded_physics_substep',guarded_substeps=50,**dict(zip(KEYS,(hard,soft))))))
  f['executed_substeps']=[25,25]
  for k,v in zip(KEYS,(hard,soft)):f[k]=[0.,v]
 return case,result

def test_exact_gate_and_explicit_approx_complete(tmp_path):
 case,r=fixture(tmp_path,hard=.004,soft=.008);proof=audit_contact_peaks(r,case/'attempt/trace.h5');assert proof['strict_contact_success'] is False
 report=summarize_cases([case]);assert report['complete_task_success_count']==1 and report['strict_contact_success_count']==0 and report['strict_contact_evidence_covered']==1

def test_boundary_inclusive_and_failed_task(tmp_path):
 case,r=fixture(tmp_path);assert audit_contact_peaks(r,case/'attempt/trace.h5')['strict_contact_success'] is True
 r['task_completed']=False;assert audit_contact_peaks(r,case/'attempt/trace.h5')['strict_contact_success'] is False

def test_missing_not_strict_and_result_boolean_not_trusted(tmp_path):
 case,r=fixture(tmp_path);r['strict_contact_success']=True
 with h5py.File(case/'attempt/trace.h5','r+') as f:del f.attrs['guard_penetration_peaks_json']
 assert audit_contact_peaks(r,case/'attempt/trace.h5')['strict_contact_success'] is None
 assert summarize_cases([case])['strict_contact_rate_all_cases'] is None

def test_terminal_failed_substep_peak_not_preaction_only(tmp_path):
 case,r=fixture(tmp_path,hard=.004)
 with h5py.File(case/'attempt/trace.h5','r+') as f:f[KEYS[0]][:]=[0.,.002]
 with pytest.raises(ValueError,match='invalid_cumulative_guard_peak'):audit_contact_peaks(r,case/'attempt/trace.h5')
 r[KEYS[0]]=.002
 with pytest.raises(ValueError,match='result_raw_guard_peak_mismatch'):audit_contact_peaks(r,case/'attempt/trace.h5')

def test_bad_coverage_or_nonmonotonic_rejected(tmp_path):
 case,r=fixture(tmp_path)
 with h5py.File(case/'attempt/trace.h5','r+') as f:f[KEYS[0]][:]=[.003,.002]
 with pytest.raises(ValueError,match='invalid_cumulative'):audit_contact_peaks(r,case/'attempt/trace.h5')


def test_source_validator_recomputes_bound_contact_evidence(tmp_path):
 from r1pro_teleop.vla.data_single_tray import validate_source_identity
 case,result=fixture(tmp_path);trace=case/'attempt/trace.h5';proof=audit_contact_peaks(result,trace)
 source=dict(schema='airport_single_tray_source/1',task_profile='single_tray_action3_v1',source='simulation/program_generated',tray_count=1,split='train',scene_id='new_single',fps=20,action_semantics='absolute_mobile19',state_semantics='measured_joint16_plus_base_origin_offset3',trace=str(trace),trace_sha256=proof['trace_sha256'],result=str(case/'result.json'),contact_gate_evidence=proof)
 for key in ('scene_xml_sha256','scene_json_sha256','environment_manifest_sha256','controller_sha256'):source[key]='a'*64
 validate_source_identity(source)
 source['contact_gate_evidence']={**proof,'strict_contact_success':False}
 with pytest.raises(ValueError,match='contact_gate_source_evidence_changed'):validate_source_identity(source)

