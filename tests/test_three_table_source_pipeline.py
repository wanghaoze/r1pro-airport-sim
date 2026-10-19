import json
from pathlib import Path
import numpy as np,pytest,h5py,mujoco
from r1pro_teleop.vla.data_three_table_lerobot import read_mobile_arrays
from r1pro_teleop.vla.data_three_table_single_tray import RULE_REVISION,FINAL_ORIENTATION_DEFINITION
from r1pro_teleop.vla.training_cache import file_sha
from r1pro_teleop.vla.three_table_single_tray_pipeline import campaign_gate,new_evaluation_gate
PROFILE='three_table_single_tray_action3_v1'

def test_measured_base_origin_from_compiled_joints_not_segment_start(tmp_path):
 xml=tmp_path/'mobile.xml';xml.write_text('<mujoco><worldbody><body><joint name="agent_base_x" type="slide" axis="1 0 0"/><joint name="agent_base_y" type="slide" axis="0 1 0"/><joint name="agent_base_yaw" type="hinge" axis="0 0 1"/><geom size=".1"/></body></worldbody></mujoco>')
 trace=tmp_path/'trace.h5';q=np.array([[.2,.3,.4],[.25,.32,.5],[.4,.5,.6]]);arms=np.arange(48,dtype=float).reshape(3,16);base=q-q[0];commands=np.array([[.1,.2,.3],[.4,.5,.6],[.7,.8,.9]])
 meta=dict(task_profile=PROFILE,task_rule_revision=RULE_REVISION,final_orientation_definition=FINAL_ORIENTATION_DEFINITION,base_mode='planar_mobile_table_front',base_actuated=True,model_action_mask=[True]*19,scene_xml_sha256=file_sha(xml),scene=dict(xml=str(xml)))
 with h5py.File(trace,'w') as f:
  f.attrs.update(schema='airport_three_table_single_tray_raw/2',metadata_json=json.dumps(meta));f['qpos']=q;f['state16']=arms;f['action16']=arms;f['state19']=np.c_[arms,base];f['action19']=np.c_[arms,commands];f['base_action']=commands
 source=dict(trace=str(trace),trace_sha256=file_sha(trace));state,action,columns=read_mobile_arrays(source,dict(start_frame=1,end_frame=3));np.testing.assert_array_equal(state[:,16:],base[1:].astype(np.float32));np.testing.assert_array_equal(action[:,16:],commands[1:].astype(np.float32));assert columns==[0,1,2] and state[0,16]!=0
 with h5py.File(trace,'r+') as f:f['state19'][1:,16:]=0
 source['trace_sha256']=file_sha(trace)
 with pytest.raises(ValueError,match='projection_changed'):read_mobile_arrays(source,dict(start_frame=1,end_frame=3))

def test_new_campaign_does_not_accept_old_successes(tmp_path):
 status=dict(task_profile='single_tray_action3_v1',selected=2,completed=2,stage='physical_candidates_complete',results=[]);(tmp_path/'status.json').write_text(json.dumps(status))
 with pytest.raises(ValueError):campaign_gate(tmp_path)
 status['task_profile']=PROFILE;status['results']=[dict(task_completed=False,returncode=2)];(tmp_path/'status.json').write_text(json.dumps(status));assert campaign_gate(tmp_path)['ready'] is False

def test_old_eval_handoff_never_resumes_three_table_optimizer(tmp_path):
 milestone=tmp_path/'milestone.json';milestone.write_text('new true checkpoint');receipt=tmp_path/'receipt.json';receipt.write_text(json.dumps(dict(schema='airport_single_tray_evaluation_handoff/1',task_profile='single_tray_action3_v1',actual_completed_updates=10,training_status_sha256=file_sha(milestone),status='evaluation_completed_gpu_released',training_resume_allowed=True,new_single_tray_protocol_id='old')))
 with pytest.raises(ValueError):new_evaluation_gate(receipt,milestone,10)

def test_export_requalification_loads_guard_journal_from_bound_source(tmp_path,monkeypatch):
 from r1pro_teleop.vla import data_three_table_lerobot as module
 raw=tmp_path/'guard.h5';values={key:np.arange(3) for key in module.GUARD_NUMERIC_KEYS}
 with h5py.File(raw,'w') as f:
  for key,value in values.items():f[key]=value
 source=dict(trace=str(raw),trace_sha256=file_sha(raw),table_support_acceptance_rule={'declared':True},final_yaw_tolerance_rad=.1)
 def actual_guard_check(s,e,r,n,**kw):
  for key,value in values.items():np.testing.assert_array_equal(n[key],value)
  assert n['existing_actual_field']==7;return {'verified_guard_requalification':True}
 monkeypatch.setattr(module,'plan_action_segments',actual_guard_check)
 # Generic exporter intentionally reads only ordinary NUMERIC_KEYS first.
 assert module.qualify(source,[],{},dict(existing_actual_field=7),contact_n=.5,lifted_m=.02)['verified_guard_requalification']
 with h5py.File(raw,'r+') as f:f['guard_sim_time'][0]=99
 with pytest.raises(ValueError,match='guard_journal_source_trace_changed'):module.qualify(source,[],{},dict(existing_actual_field=7),contact_n=.5,lifted_m=.02)

def test_first_ready_batch_does_not_wait_for_unfinished_campaign(tmp_path):
 root=tmp_path/'campaign';root.mkdir();rows=[]
 for split in ('train','val','test'):
  case=tmp_path/split;case.mkdir();result=case/'result.json';result.write_text(json.dumps(dict(task_completed=True,physics_success=True,training_eligible=True,split=split)))
  (case/'source_qualification_audit.json').write_text(json.dumps(dict(verified=True)));rows.append(dict(result=str(result),split=split,task_completed=True,returncode=0))
 (root/'status.json').write_text(json.dumps(dict(task_profile=PROFILE,selected=20,completed=3,stage='collecting',results=rows)))
 proof=campaign_gate(root);assert proof['ready'] and not proof['campaign_all_closed'] and all(len(c)==1 for c in proof['successful_splits'].values())
 (tmp_path/'test/source_qualification_audit.json').unlink();assert not campaign_gate(root)['ready']
