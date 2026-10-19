import json
from types import SimpleNamespace
import numpy as np,pytest,h5py
from r1pro_teleop.single_tray_3table.observer import ObservedTrace,ThreeTableObserver,normalize_observed_trace
from r1pro_teleop.vla.data_three_table_single_tray import PROFILE,RULE_REVISION,FINAL_ORIENTATION_DEFINITION

def test_trace_proxy_preserves_legacy_values_and_prefix_alignment():
 rows=[];trace=SimpleNamespace(count=0,append=rows.append);o=SimpleNamespace(pending={'gripper_contact_force':np.array([1.,2.])},pending_frame=0)
 proxy=ObservedTrace(trace,o);row={'gripper_contact_force':np.array([[9.,8.]]),'transition_completed':False};proxy.append(row)
 np.testing.assert_array_equal(rows[0]['gripper_contact_force'],[[9,8]])
 np.testing.assert_array_equal(rows[0]['task_numeric/gripper_contact_force'],[1,2]);assert o.pending is None
 with pytest.raises(ValueError,match='missing_pre_action'):proxy.append(row)
 o.pending={};o.pending_frame=1
 with pytest.raises(ValueError,match='frame_alignment'):proxy.append(row)

def test_endpoint_requires_real_in_interval_complete_tick():
 o=ThreeTableObserver.__new__(ThreeTableObserver);o.action=('pick_empty',0);o.spans=[];o.original_trace=SimpleNamespace(count=2,file={'transition_completed':np.array([True,False])});events=[];o.r=SimpleNamespace(trace=SimpleNamespace(event=lambda *a,**k:events.append(k)))
 with pytest.raises(ValueError,match='actual_recorded'):o.complete_action(verified=True,measured_endpoint_frame=2)
 with pytest.raises(ValueError,match='transition_incomplete'):o.complete_action(verified=True,measured_endpoint_frame=1)
 o.complete_action(verified=True,measured_endpoint_frame=0);assert o.spans[0]['end_frame']==2

def test_derived_normalization_retains_original_trace_and_numeric(tmp_path):
 original=tmp_path/'old.h5';new=tmp_path/'new.h5'
 with h5py.File(original,'w') as f:
  f.attrs.update(schema='airport_fsm_raw/2',metadata_json='{}',num_frames=2);f['state']=np.zeros((2,16));f['action']=np.ones((2,16));f['gripper_contact_force']=np.ones((2,1,2))*9
  f['task_numeric/gripper_contact_force']=np.ones((2,2))*3;f['task_numeric/state19']=np.zeros((2,19));f['task_numeric/action19']=np.ones((2,19))
 before=original.read_bytes();meta=dict(task_profile=PROFILE,task_rule_revision=RULE_REVISION,final_orientation_definition=FINAL_ORIENTATION_DEFINITION)
 receipt=normalize_observed_trace(original,new,metadata=meta);assert original.read_bytes()==before and receipt['frames']==2 and receipt['training_ready'] is False
 with h5py.File(new) as f:
  assert f['gripper_contact_force'].shape==(2,2);assert f['legacy_numeric/gripper_contact_force'].shape==(2,1,2);assert f['state16'].shape==(2,16);assert json.loads(f.attrs['metadata_json'])['original_trace_sha256']==receipt['original_trace_sha256']
 with pytest.raises(FileExistsError):normalize_observed_trace(original,new,metadata=meta)

def test_capture_uses_live_geometry_and_does_not_mutate_physics():
 import mujoco
 xml='<mujoco><worldbody><body name="base_link"><joint name="agent_base_x" type="slide" axis="1 0 0"/><joint name="agent_base_y" type="slide" axis="0 1 0"/><joint name="agent_base_yaw" type="hinge" axis="0 0 1"/><geom size=".01" mass="1"/></body><body name="tray" pos="0 0 .85"><freejoint/><geom type="box" size=".28 .215 .05" mass="1"/></body><body name="rear"><geom type="box" size=".6 .3 .4" pos="0 0 .4"/></body><body name="front_left" pos="2 0 0"><geom type="box" size=".6 .3 .4" pos="0 0 .4"/></body><body name="front_right" pos="-2 0 0"><geom type="box" size=".6 .3 .4" pos="0 0 .4"/></body></worldbody></mujoco>'
 m=mujoco.MjModel.from_xml_string(xml);d=mujoco.MjData(m);mujoco.mj_forward(m,d);before=(d.qpos.copy(),d.qvel.copy(),d.ctrl.copy(),d.time)
 sim=SimpleNamespace(base_joint_state=lambda:d.qpos[:3].copy(),state=lambda:np.zeros(16),target=np.ones(16)*.02,base_target=np.array([.1,.2,.3]))
 o=ThreeTableObserver.__new__(ThreeTableObserver);o.r=SimpleNamespace(m=m,d=d,mj=mujoco,sim=sim);o.scene=dict(tray=dict(body='tray',size=[.56,.43,.105]),tables=[dict(table_id=name,center_world=[x,0,0],dimensions_m=[1.2,.6,.8]) for name,x in [('rear',0),('front_left',2),('front_right',-2)]]);o.origin=np.zeros(3);o.capacity=4;o.confirmed=np.zeros(2,bool);o.pending_releases={};o.stage3_requested=False;o.push_stage=0;o.manipulating=False;o.table=None;o.provider=lambda:dict(payload_loaded=False,payload_mass=0.,floor_contact=0,tray_clearance=.05,tray_goal_reached=False)
 data=o.capture();np.testing.assert_array_equal(data['robot_forward_world'],[1,0,0]);np.testing.assert_array_equal(data['robot_left_world'],[0,1,0]);np.testing.assert_array_equal(data['action19'][16:],np.array([.1,.2,.3],np.float32));assert data['tray_footprint_on_table'].tolist()==[False,False,True]
 for actual,wanted in zip((d.qpos,d.qvel,d.ctrl),before[:3]):np.testing.assert_array_equal(actual,wanted)
 assert d.time==before[3] and data['operation_manipulation']==False

def test_substep_observations_cannot_overwrite_before_interval_snapshot():
 o=ThreeTableObserver.__new__(ThreeTableObserver);o.pending=None;o.original_trace=SimpleNamespace(count=0);d=SimpleNamespace(qpos=np.array([1.]),time=0.);o.r=SimpleNamespace(d=d);o.old_observation=lambda:{'actual':d.qpos.copy()};o.capture=lambda:{'measured':d.qpos.copy()};seen=[]
 def physics_tick():
  for _ in range(3):d.qpos+=1;d.time+=.01;o.observation()
  seen.append(o.pending['measured'].copy())
 o.old_tick=physics_tick;o.tick();np.testing.assert_array_equal(seen[0],[1]);np.testing.assert_array_equal(d.qpos,[4]);assert o.pending is None

def test_proxy_rejects_poststate_masquerading_as_pre_action():
 trace=SimpleNamespace(count=0,append=lambda row:None);o=SimpleNamespace(pending={},pending_frame=0,pending_qpos=np.array([1.]),pending_time=0.)
 with pytest.raises(ValueError,match='pre_action_physics'):ObservedTrace(trace,o).append({'qpos':np.array([2.]),'sim_time':.05})

def test_real_mujoco_substep_tick_keeps_numeric_before_state():
 import mujoco
 m=mujoco.MjModel.from_xml_string('<mujoco><option gravity="0 0 0"/><worldbody><body><joint type="slide" axis="1 0 0"/><geom size=".1" mass="1"/></body></worldbody><actuator><motor joint="0"/></actuator></mujoco>'.replace('joint type','joint name="slide" type').replace('joint="0"','joint="slide"'));d=mujoco.MjData(m);d.ctrl[0]=1;mujoco.mj_forward(m,d)
 rows=[];trace=SimpleNamespace(count=0)
 def append(row):rows.append(row);trace.count+=1
 trace.append=append;o=ThreeTableObserver.__new__(ThreeTableObserver);o.pending=None;o.original_trace=trace;o.r=SimpleNamespace(d=d,sim=SimpleNamespace(nstep=25));o.old_observation=lambda:d.qpos.copy();o.capture=lambda **kw:{'joint_before':d.qpos.copy(),'tray_corners_world':np.zeros((8,3)),'table_contact_counts':np.zeros(3,np.int32)};o.old_guard=lambda:None;o.guard_domain_provider=lambda:False;proxy=ObservedTrace(trace,o)
 def oldtick():
  row={'qpos':d.qpos.copy(),'sim_time':float(d.time),'transition_completed':True,'executed_substeps':25}
  for _ in range(25):mujoco.mj_step(m,d);o.observation();o.guard()
  proxy.append(row)
 o.old_tick=oldtick;o.tick();o.tick()
 assert d.qpos[0]>0;assert rows[1]['task_numeric/joint_before'][0]>rows[0]['task_numeric/joint_before'][0]
 for row in rows:np.testing.assert_array_equal(row['task_numeric/joint_before'],row['qpos'])

def test_event_derivation_preserves_payload_and_legacy_actions_without_duplicate_labels(tmp_path):
 from r1pro_teleop.single_tray_3table.observer import normalize_observer_events
 original=tmp_path/'events.jsonl';new=tmp_path/'derived.jsonl';journal={'schema':'airport_passenger_environment_transition/1','qpos_indices':[19],'qpos_after':[.4]}
 rows=[{'event':'action_start','action':'push_loaded','frame':7},{'event':'action_start','action_label':'push_loaded','frame':7},{'event':'passenger_payload_initialized','frame':6,'environment_evidence':journal}];original.write_text(''.join(json.dumps(r)+'\n' for r in rows));before=original.read_bytes()
 receipt=normalize_observer_events(original,new);derived=[json.loads(x) for x in new.read_text().splitlines()];assert original.read_bytes()==before and receipt['source_unchanged']
 assert derived[0]['event']=='legacy_controller_action_start' and derived[1]['event']=='action_start' and derived[2]==rows[2]

def test_original_parent_rotated_table_front_is_short_depth_world_x():
 from pathlib import Path
 from r1pro_teleop.single_tray_3table.observer import table_front_region_violation
 from r1pro_teleop.single_tray_lab.three_table_scene import table_front
 root=Path('resources/scenes');parents=sorted(root.rglob('scene.json'));parent=next(json.loads(p.read_text()) for p in parents if len(json.loads(p.read_text()).get('tables',[]))==3)
 for t in parent['tables']:
  normal=table_front(t);center=np.asarray(t['center_world']);yaw=t.get('yaw_world',0);rotation=np.array([[np.cos(yaw),-np.sin(yaw)],[np.sin(yaw),np.cos(yaw)]])
  extent=float(np.sum(abs(rotation.T@normal[:2])*np.asarray(t['dimensions_m'])[:2]/2))
  assert not table_front_region_violation(t,center+normal*(extent+.2))
  assert table_front_region_violation(t,center+normal*(extent-.01))
  side=center+normal*(extent+.2)+np.array([0,2.,0]);assert table_front_region_violation(t,side)

def test_guard_prefix_flattening_and_original_lineage_is_exact(tmp_path):
 from r1pro_teleop.single_tray_3table.observer import normalize_observed_trace,audit_observed_lineage
 original=tmp_path/'actual.h5';derived=tmp_path/'derived.h5'
 with h5py.File(original,'w') as f:
  f.attrs.update(schema='airport_fsm_raw/2',metadata_json='{}',num_frames=2)
  for key,value in [('qpos',np.array([[1.],[2.]])),('qvel',np.zeros((2,1))),('integration_state',np.zeros((2,2))),('sim_time',np.array([0.,.05])),('ctrl_substeps',np.arange(6).reshape(2,3,1)),('executed_substeps',np.array([3,1])),('transition_completed',np.array([True,False])),('state',np.zeros((2,16))),('action',np.zeros((2,16)))]:f[key]=value
  f['task_numeric/tray_corners_world']=np.zeros((2,8,3));f['task_guard/sim_time']=np.arange(6).reshape(2,3)*.002;f['task_guard/table_contact_counts']=np.arange(18).reshape(2,3,3);f['task_guard/tray_corners_world']=np.zeros((2,3,8,3));f['task_guard/push_contact_domain']=np.ones((2,3),bool)
 meta=dict(task_profile=PROFILE,task_rule_revision=RULE_REVISION,final_orientation_definition=FINAL_ORIENTATION_DEFINITION)
 normalize_observed_trace(original,derived,metadata=meta)
 with h5py.File(derived) as f:np.testing.assert_array_equal(f['guard_frame_index'][:],[0,0,0,1]);np.testing.assert_array_equal(f['guard_sim_time'][:],[0,.002,.004,.006])
 assert audit_observed_lineage(derived)['verified']
 with h5py.File(derived,'r+') as f:f['guard_table_contact_counts'][0,0]+=1
 with pytest.raises(ValueError,match='guard_journal_lineage'):audit_observed_lineage(derived)

def test_release_command_completion_does_not_fake_measured_contact_loss():
 o=ThreeTableObserver.__new__(ThreeTableObserver);events=[];trace=SimpleNamespace(count=1222,event=lambda event,**details:events.append(dict(event=event,frame=trace.count,**details)));o.r=SimpleNamespace(trace=trace);o.original_trace=trace;o.confirmed=np.array([True,True]);o.pending_releases={};o.release_starts={'right':1200};o.stage3_requested=False;o.push_stage=2;o.confirmation_rule=dict(rule_id='actual',contact_n=.5,release_evidence_mode='existing_low_force_commanded_open',existing_open_command_m=.1)
 o.release_grasp(('right',));o.set_push_stage(3);command=np.array([.005,.1],np.float32);jaw=np.array([.02,.10102053]);o._observe_releases(np.array([11.,9.319]),jaw,command)
 assert o.confirmed.tolist()==[True,True] and o.push_stage==2 and not any(e['event']=='grasp_released' for e in events)
 trace.count=1250;o._observe_releases(np.array([11.,0.]),jaw,command)
 assert o.confirmed.tolist()==[True,False] and o.push_stage==3
 release=next(e for e in events if e['event']=='grasp_released');assert release['frame']==1250 and release['release_command_start_frame']==1200 and release['measured_contact_force_n']==0.

def test_observed_replay_restores_actual_initial_force_caps_and_continuous_math(tmp_path):
 import mujoco
 from r1pro_teleop.single_tray_lab.replay import SingleTrayReplay
 from r1pro_teleop.vla.training_cache import file_sha
 xml=tmp_path/'model.xml';xml.write_text('<mujoco><option gravity="0 0 0" timestep=".002"/><worldbody><camera name="head_left"/><camera name="head_right"/><camera name="left_wrist"/><camera name="right_wrist"/><body><joint name="slide" type="slide" axis="1 0 0"/><geom size=".1" mass="1"/></body></worldbody><actuator><motor joint="slide" forcerange="-2 2"/></actuator></mujoco>')
 m=mujoco.MjModel.from_xml_path(str(xml));m.actuator_forcerange[:]=[-1,1];d=mujoco.MjData(m);d.ctrl[0]=2;mujoco.mj_forward(m,d);spec=mujoco.mjtState.mjSTATE_INTEGRATION;rows=[]
 for frame in range(3):
  integration=np.empty(mujoco.mj_stateSize(m,spec));mujoco.mj_getState(m,d,integration,spec);rows.append(dict(qpos=d.qpos.copy(),qvel=d.qvel.copy(),qacc_warmstart=d.qacc_warmstart.copy(),sim_time=float(d.time),integration_state=integration,ctrl_substeps=np.full((25,1),2.),executed_substeps=25))
  for _ in range(25):mujoco.mj_step(m,d);mujoco.mj_forward(m,d)
 snapshot=dict(schema='airport_recorded_initial_actuator_limits/1',actuator_forcerange=m.actuator_forcerange.tolist(),actuator_forcelimited=m.actuator_forcelimited.tolist(),unchanged_xml_parameter_arrays={key:getattr(m,key).tolist() for key in ('actuator_gear','actuator_gainprm','actuator_biasprm','actuator_ctrlrange','cam_pos','cam_quat','cam_fovy','cam_ipd')})
 meta=dict(task_profile=PROFILE,base_mode='planar_mobile_table_front',base_actuated=True,model_action_mask=[True]*19,scene={'schema':'airport_three_table_single_tray_scene/1','payloads':[]},source_model_parameters=snapshot,numeric_derivation='live_same_runtime_pre_action_observer',scene_xml_sha256=file_sha(xml),integration_state_spec=int(spec));raw=tmp_path/'raw.h5';events=tmp_path/'events.jsonl';events.write_text('')
 with h5py.File(raw,'w') as f:
  f.attrs.update(schema='airport_three_table_single_tray_raw/2',metadata_json=json.dumps(meta),terminal_snapshot_json=json.dumps(dict(qpos=d.qpos.tolist(),qvel=d.qvel.tolist(),time=float(d.time))))
  for key in rows[0]:f[key]=np.array([r[key] for r in rows])
 replay=SingleTrayReplay(raw,xml,events)
 try:
  for i in range(3):replay.before(i);replay.advance()
  receipt=replay.finish();assert all(v==0 for v in receipt['errors'].values()) and receipt['initial_restore_count']==1
  np.testing.assert_array_equal(replay.model.actuator_forcerange,[[-1,1]])
 finally:replay.close()

def test_existing_close_rule_records_contact_stop_not_nominal_close_gate():
 from r1pro_teleop.single_tray_3table.collect import existing_confirmation_rule
 from r1pro_teleop.airport_fsm.contracts import Config
 from r1pro_teleop.single_tray_lab.control import ControlProfile
 cfg=Config.load('resources/single_tray_three_table_v1/source_registry/v64_actual_config.json');p=ControlProfile(open_command=cfg.gripper_open_m,contact_n=cfg.criteria.contact_n)
 rule=existing_confirmation_rule(cfg,p);assert rule['stable_duration_s']==.15 and rule['release_evidence_mode']=='existing_low_force_commanded_open'
 assert rule['existing_open_command_m']==.1 and 'closed_command_max_m' not in rule and rule['nominal_close_command_is_not_a_measured_aperture_acceptance_gate']
