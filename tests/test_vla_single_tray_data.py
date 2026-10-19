import copy
import numpy as np
import pytest
from r1pro_teleop.vla.data_single_tray import PROFILE,plan_action_segments

def fixture():
 source=dict(schema='airport_single_tray_source/1',task_profile=PROFILE,source='simulation/program_generated',tray_count=1,scene_id='new_photo_train_1',split='train',frames=14,fps=20,action_semantics='absolute_mobile19',state_semantics='measured_joint16_plus_base_origin_offset3',**{k:'a'*64 for k in ('trace_sha256','scene_xml_sha256','scene_json_sha256','environment_manifest_sha256','controller_sha256')})
 events=[]
 for label,a,b in [('pick_empty',1,4),('place_empty',4,7),('push_loaded',10,14)]:events.extend([dict(event='action_start',action_label=label,frame=a),dict(event='action_complete',action_label=label,end_frame_exclusive=b,measured_endpoint_frame=b-1,verified=True)])
 numeric=dict(payload_loaded=np.r_[np.zeros(10),np.ones(4)],payload_mass=np.r_[np.zeros(10),np.ones(4)*2],gripper_contact_force=np.zeros((14,2)),support_contact=np.ones(14),floor_contact=np.zeros(14),tray_clearance=np.zeros(14),tray_goal_reached=np.zeros(14))
 numeric['gripper_contact_force'][3]=[4,5];numeric['support_contact'][3]=0;numeric['tray_clearance'][3]=.04;numeric['tray_goal_reached'][13]=1
 return source,events,dict(task_completed=True,physics_success=True),numeric

def plan(values):return plan_action_segments(*values,contact_n=.5,lifted_m=.02)

def test_exact_three_actions_and_environment_gap_do_not_become_robot_labels():
 result=plan(fixture())
 assert [r['action_label'] for r in result['segments']]==['pick_empty','place_empty','push_loaded']
 assert result['source_frames']==14 and result['supervised_frames']==10 and result['excluded_frames']==4
 assert result['inventory']==[dict(start_frame=0,end_frame=1,training_eligible=False,reason='environment_load_or_settle_not_robot_demonstration'),dict(start_frame=7,end_frame=10,training_eligible=False,reason='environment_load_or_settle_not_robot_demonstration')]
 assert result['dataset_ready'] is False

@pytest.mark.parametrize('change,error',[
 (lambda v:v[0].update(schema='airport_whole_action_source/1'), 'legacy_relabeling'),
 (lambda v:v[0].update(tray_count=3),'single_tray_simulation'),
 (lambda v:v[3]['payload_loaded'].__setitem__(2,1),'empty_action'),
 (lambda v:v[3]['payload_mass'].__setitem__(11,0),'loaded_push'),
 (lambda v:v[3]['gripper_contact_force'].__setitem__(6,[0,12]),'bilateral_release'),
 (lambda v:v[3]['support_contact'].__setitem__(3,1),'measured_supported_lift'),
 (lambda v:v[1][1].update(measured_endpoint_frame=4),'halfopen'),
 (lambda v:v[2].update(task_completed=False),'complete_task'),
])
def test_physical_and_new_environment_provenance_fail_closed(change,error):
 values=fixture();change(values)
 with pytest.raises(ValueError,match=error):plan(values)

def test_holdout_split_is_preserved_not_silently_training():
 values=fixture();values[0]['split']='test';result=plan(values)
 assert all(r['split']=='test' for r in result['segments'])

def test_materializer_rejects_legacy_and_holdout_before_creating_any_output(tmp_path):
 from r1pro_teleop.vla.data_single_tray import materialize_action_split
 source,events,result,numeric=fixture();record=dict(source=source,plan=plan((source,events,result,numeric)),native_videos=[])
 source['schema']='legacy_action8'
 with pytest.raises(ValueError,match='legacy_relabeling'):materialize_action_split([record],tmp_path/'legacy','airport/new',split='train',dataset_class=object)
 assert not (tmp_path/'legacy').exists()
 source['schema']='airport_single_tray_source/1';source['split']='test'
 with pytest.raises(ValueError,match='split_leakage'):materialize_action_split([record],tmp_path/'leak','airport/new',split='train',dataset_class=object)
 assert not (tmp_path/'leak').exists()


def test_loaded_push_instruction_names_user_requested_left_end():
 from r1pro_teleop.vla.data_single_tray import ACTION_VOCABULARY
 assert [row['language_prompt'] for row in ACTION_VOCABULARY]==['Pick up the tray','Place the tray','Flush tray to the left']

def test_fixed_base_reader_uses_explicit_raw19_and_never_xml_joint_guesses(tmp_path):
 import h5py,json,hashlib,numpy as np
 from r1pro_teleop.vla.data_single_tray import read_fixed_base_arrays
 path=tmp_path/'trace.h5';state=np.arange(48,dtype=np.float64).reshape(3,16);action=state.astype(np.float32)/100
 with h5py.File(path,'w') as f:
  f.attrs['schema']='airport_single_tray_raw/2';f.attrs['metadata_json']=json.dumps(dict(base_mode='fixed_front',base_actuated=False,model_action_mask=[True]*16+[False]*3))
  f['state']=state;f['action']=action;f['state19']=np.c_[state,np.zeros((3,3))];f['action19']=np.c_[action,np.zeros((3,3),dtype=np.float32)]
 source=dict(trace=str(path),trace_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
 s,a,columns=read_fixed_base_arrays(source,dict(start_frame=1,end_frame=3))
 assert columns is None and s.shape==(2,19) and np.array_equal(s[:,:16],state[1:].astype(np.float32)) and np.all(a[:,16:]==0)
 with h5py.File(path,'r+') as f:f['action19'][1,16]=.1
 source['trace_sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
 with pytest.raises(ValueError,match='projection_changed'):read_fixed_base_arrays(source,dict(start_frame=1,end_frame=3))

def test_long_rim_permission_requires_actual_trace_declaration(tmp_path):
 import json,h5py
 from r1pro_teleop.vla.data_single_tray import validate_source_identity
 from r1pro_teleop.single_tray_lab.grasp_contract import long_rim_contract
 source,*_=fixture();trace=tmp_path/'trace.h5'
 with h5py.File(trace,'w') as f:f.attrs['metadata_json']=json.dumps({'allowed_long_rim_contract':long_rim_contract()})
 source.update(trace=str(trace),allowed_long_rim_contract=long_rim_contract());validate_source_identity(source)
 with h5py.File(trace,'r+') as f:f.attrs['metadata_json']='{}'
 with pytest.raises(ValueError,match='not_declared_by_actual_trace'):validate_source_identity(source)
 source['allowed_long_rim_contract']['allowed_long_rims'].append('local_x_positive')
 with pytest.raises(ValueError,match='invalid_long_rim_permission'):validate_source_identity(source)
