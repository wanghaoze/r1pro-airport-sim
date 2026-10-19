import json
from types import SimpleNamespace
from pathlib import Path
import numpy as np,pytest
from r1pro_teleop.vla.three_table_recovery import StageJournal,process_fault,isolate_partial,training_resources,reject_live_owned_children

def test_three_process_failures_preserved_and_bounded(tmp_path,monkeypatch):
 import r1pro_teleop.vla.three_table_recovery as m
 monkeypatch.setattr(m.time,'sleep',lambda _:None);calls=[];states=[]
 def bad(pulse):calls.append(1);pulse({'pid':1,'log_bytes':32});raise RuntimeError('owned_child_failed:1')
 with pytest.raises(RuntimeError):StageJournal(tmp_path,lambda name,**fields:states.append(name)).execute('native',bad)
 assert len(calls)==3 and len(list((tmp_path/'stage_receipts/native').glob('attempt*.json')))==3
 assert 'process_fault_backoff' in states
 assert all(json.loads(p.read_text())['last_error'] for p in (tmp_path/'stage_receipts/native').glob('attempt*.json'))

def test_qualification_fault_never_retried(tmp_path):
 calls=[]
 def bad(pulse):calls.append(1);raise ValueError('source_hash_changed')
 with pytest.raises(ValueError):StageJournal(tmp_path,lambda *a,**k:None).execute('source',bad)
 assert len(calls)==1 and not process_fault(ValueError('owned_startup_identity_not_verified'))

def test_verified_artifact_reused_after_reaudit(tmp_path):
 artifact=tmp_path/'verified.json';artifact.write_text('{}');calls=[]
 (tmp_path/'render_.exit.json').write_text(json.dumps({'pid':123,'returncode':0,'trainer_exited':True}))
 (tmp_path/'native.exit.json').write_text(json.dumps({'pid':123,'returncode':0,'trainer_exited':True}))
 result=StageJournal(tmp_path,lambda *a,**k:None).execute('native',lambda _:calls.append(1),artifact=artifact,verify=lambda:{'six_errors':0,'verified':True})
 assert result is None and not calls
 with pytest.raises(ValueError):StageJournal(tmp_path,lambda *a,**k:None).execute('native',lambda _:calls.append(1),artifact=artifact,verify=lambda:(_ for _ in ()).throw(ValueError('video_changed')))

def test_partial_isolated_and_contents_preserved(tmp_path):
 p=tmp_path/'partial';p.mkdir();(p/'evidence').write_text('original');q=Path(isolate_partial(p));assert not p.exists() and (q/'evidence').read_text()=='original'

def test_small_unrelated_compute_allowed_without_signal(monkeypatch):
 import r1pro_teleop.vla.three_table_recovery as m
 from r1pro_teleop.vla.training_pipeline import GPU_UUIDS
 def output(argv,**kwargs):return '\n'.join(u+', 90000' for u in GPU_UUIDS) if 'memory.free' in argv[1] else f'1492994, {GPU_UUIDS[0]}, 1800'
 monkeypatch.setattr(m.subprocess,'check_output',output);r=training_resources();assert r['ready'] and r['actual_compute'][0]['pid']==1492994 and r['unrelated_processes_not_signaled']
 assert not training_resources(owned_compute_pids=[1492994])['ready']

def test_official_ndarray_action_mask_is_accepted():
 from r1pro_teleop.single_tray_3table.learned import ThreeTablePolicy
 from r1pro_teleop.vla.training import AirportOutputs
 from r1pro_teleop.vla.policy import PolicyContract,PolicyError
 from r1pro_teleop.vla.data_three_table_single_tray import PROFILE
 reply=AirportOutputs(prompt_mode=PROFILE)({'actions':np.zeros((20,32),np.float32)})
 client=SimpleNamespace(infer=lambda obs:reply);policy=ThreeTablePolicy(client,PolicyContract('sha256:x',action_horizon=20,action_width=19,prompt_mode=PROFILE))
 images={k:np.zeros((2,2,3),np.uint8) for k in policy.contract.camera_names}
 assert policy.infer(images,np.zeros(19),'Pick up the tray').shape==(20,19)
 reply['model_action_mask']=np.zeros(19,bool)
 with pytest.raises(PolicyError):policy.infer(images,np.zeros(19),'Pick up the tray')



def test_model_origin_is_measured_at_right_release_not_after_extra_left_motion(monkeypatch):
 import r1pro_teleop.single_tray_3table.learned as m
 from r1pro_teleop.single_tray_lab.learned import PhysicalHandover
 p=SimpleNamespace(contact_n=.5,stable_contact_frames=3,robot_left=[0,1,0]);obs=dict(gripper_contact_force={'left':2.,'right':0.},tray_position=np.array([0.,.2,0.]),payload_floor_contacts=0,payload_mass_kg=2.,payload_total_mass_kg=2.)
 bridge=SimpleNamespace(p=p,left_motion_origin=None,left_motion_axis=None,observation=lambda:obs,_capture_actual_left_origin=lambda e:None)
 bridge.loaded_goal_reached=lambda e:bridge.left_motion_origin is not None and (e['tray_position']-bridge.left_motion_origin)[1]>=.03
 events=[];r=SimpleNamespace(cfg=SimpleNamespace(criteria=SimpleNamespace(contact_n=.5)),observation=lambda:{'gripper_contact_force':np.array([[obs['gripper_contact_force']['left'],0.]])},trace=SimpleNamespace(event=lambda *a,**k:events.append((a,k))))
 learner=m.LearnedThreeTable.__new__(m.LearnedThreeTable);learner.r=r;learner.scene={'tray':{'size':[.5,.3,.03]}};learner.action='push_loaded';learner.bridge=bridge;learner.handover=PhysicalHandover(p,[0,0,0],goal_checker=bridge.loaded_goal_reached);learner.handover.stage='right_release'
 monkeypatch.setattr(m,'contact_snapshot',lambda *a:{});monkeypatch.setattr(m,'opposed_contact',lambda *a:False)
 assert not learner.endpoint(r,None);np.testing.assert_array_equal(bridge.left_motion_origin,[0,.2,0]);assert len(events)==1
 obs['tray_position']=np.array([0,.231,0]);assert not learner.endpoint(r,None)
 obs['gripper_contact_force']['left']=0.;assert learner.endpoint(r,None)
 np.testing.assert_array_equal(bridge.left_motion_origin,[0,.2,0])

def test_submitted_command_derivation_uses_actual_xml_internal_clamp(tmp_path):
 import h5py
 from r1pro_teleop.vla.gripper_command_evidence import derive_submitted_gripper_evidence
 from r1pro_teleop.vla.training_cache import file_sha
 bodies=''.join(f'<body name="b{i}"><joint name="j{i}" type="slide" axis="1 0 0"/><geom size=".01"/></body>' for i in range(16))
 actuators=''.join(f'<position name="{("left_gripper_target" if i==7 else "right_gripper_target" if i==15 else "a"+str(i))}" joint="j{i}" ctrllimited="true" ctrlrange="{(".002 .05" if i in (7,15) else "-1 1")}"/>' for i in range(16))
 xml=tmp_path/'model.xml';xml.write_text('<mujoco><worldbody>'+bodies+'</worldbody><actuator>'+actuators+'</actuator></mujoco>');raw=tmp_path/'raw.h5';controls=np.zeros((3,25,16));controls[1:,:,7]=.0500006377696991;controls[1:,:,15]=.05
 with h5py.File(raw,'w') as f:
  f.attrs['metadata_json']=json.dumps({'config':{'substep_control_enabled':False}});f['ctrl_substeps']=controls;f['executed_substeps']=np.full(3,25);f['transition_completed']=np.ones(3,bool);f['gripper_command_openings']=np.full((3,2),.10000127544604663)
 source=dict(trace=str(raw),trace_sha256=file_sha(raw),scene_xml=str(xml),scene_xml_sha256=file_sha(xml),frames=3);before=file_sha(raw);numeric,evidence,audit=derive_submitted_gripper_evidence(source)
 np.testing.assert_array_equal(numeric['gripper_control_substeps'],controls[:,:,[7,15]])
 np.testing.assert_array_equal(numeric['gripper_effective_command_openings'],np.clip(controls[:,0,[7,15]],.002,.05)*2)
 assert before==file_sha(raw) and audit['engine_clipped_control_count']>0 and evidence['actuator_ctrllimited']==[True,True]
 with h5py.File(raw,'r+') as f:f['ctrl_substeps'][1,1,7]=.04
 source['trace_sha256']=file_sha(raw)
 with pytest.raises(ValueError,match='not_constant'):derive_submitted_gripper_evidence(source)

def test_event_projection_retains_original_duplicate_annotations():
 from r1pro_teleop.vla.action_event_projection import project_action_events
 events=[];spans=[]
 for i,label in enumerate(['pick_empty','place_empty','push_loaded']):
  a=i*10;b=a+10;span=dict(action_label=label,start_frame=a,end_frame=b,measured_endpoint_frame=b-1,verified=True);spans.append(span)
  events.extend([dict(event='action_start',frame=a,action_label=label,task_rule_revision='actual'),dict(event='action_complete',frame=b,**span)])
 events.insert(4,dict(event='action_start',frame=20,action_label='push_loaded',phase='bridge'))
 events.append(dict(event='action_complete',frame=30,action_label='push_loaded',start_frame=20,end_frame_exclusive=30,measured_endpoint_frame=29,verified=True))
 before=json.dumps(events);projected,audit=project_action_events(events,dict(action_spans=spans));assert before==json.dumps(events) and audit['verified']
 assert len([e for e in projected if e['event']=='action_start'])==3 and all(e['end_frame_exclusive']==e['frame'] for e in projected if e['event']=='action_complete')
 events[-1]['measured_endpoint_frame']=28
 with pytest.raises(ValueError):project_action_events(events,dict(action_spans=spans))


def test_stage_retry_budget_survives_supervisor_restart(tmp_path,monkeypatch):
 import r1pro_teleop.vla.three_table_recovery as m
 monkeypatch.setattr(m.time,'sleep',lambda _:None);calls=[]
 def bad(pulse):calls.append(1);raise RuntimeError('owned_child_failed:1')
 for _ in range(2):
  with pytest.raises(RuntimeError):StageJournal(tmp_path,lambda *a,**k:None).execute('native',bad)
 assert len(calls)==3

def test_reuse_requires_actual_exit_receipt(tmp_path):
 artifact=tmp_path/'video';artifact.write_text('verified')
 with pytest.raises(ValueError,match='actual_successful_child_exit'):StageJournal(tmp_path,lambda *a,**k:None).execute('native',lambda _:None,artifact=artifact,verify=lambda:{'verified':True})

def test_legacy_checkpoint_saved_status_parent_is_actually_verified(tmp_path,monkeypatch):
 import r1pro_teleop.vla.three_table_recovery as m
 cp=tmp_path/'9999';(cp/'params').mkdir(parents=True);(cp/'train_state').mkdir();parent=tmp_path/'parent.json';parent.write_text(json.dumps({'status':'checkpoint_saved','checkpoint_verified':True,'checkpoint':str(cp)}))
 options={'parent_status':str(parent),'sim_python':'sim-env','vla_python':'vla-env','release':str(tmp_path/'release')};calls=[]
 def output(argv,**kwargs):
  calls.append(argv)
  return json.dumps({'checkpoint_id':'sha256:actually-verified'}) if '--identity-only' in argv else json.dumps({'prefix':'/nonbase/envs/vla','executable':argv[0]})
 monkeypatch.setattr(m.subprocess,'check_output',output);monkeypatch.setattr(m.shutil,'disk_usage',lambda _:SimpleNamespace(free=2*1024**4))
 receipt=m.preflight(options,tmp_path);assert receipt['actual_verified_parent_checkpoint_id']=='sha256:actually-verified' and any('--identity-only' in c for c in calls)
 (cp/'train_state').rmdir()
 with pytest.raises(ValueError):m.preflight(options,tmp_path)

def _mock_data_pipeline(tmp_path,monkeypatch,failed_split=None,missing_source_split=None):
 import sys
 import r1pro_teleop.vla.three_table_single_tray_pipeline as pipeline
 import r1pro_teleop.vla.three_table_recovery as recovery
 monkeypatch.setitem(sys.modules,'fcntl',SimpleNamespace(flock=lambda *a:None,LOCK_EX=1,LOCK_NB=2))
 run=tmp_path/'data_version2';cases={};splits={s:[] for s in ('train','val','test')}
 for split in splits:
  case=tmp_path/split;cases[str(case)]=split;splits[split].append(str(case))
  for name in ('result.json','attempt/trace.h5','scene/scene.json','source_qualification_audit.json'):
   path=case/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('{}')
 spec=tmp_path/'spec.json';spec.write_text(json.dumps(dict(prompt_mode='three_table_single_tray_action3_v1',run_dir=str(run),dataset_root=str(run/'datasets/train'),dataset_repo_id='airport/three_table_single_tray_action3_train_v2',name='unused-model')))
 core=tmp_path/'core.json';core.write_text('{"returncode":0}')
 if missing_source_split:splits[missing_source_split]=[]
 monkeypatch.setattr(pipeline,'campaign_gate',lambda *a:dict(ready=all(splits.values()),selected=3,completed=3,campaign_all_closed=True,successful_splits=splits))
 monkeypatch.setattr(pipeline,'build_source',lambda case,path:({'scene_id':cases[case],'split':cases[case],'frames':10},{}))
 commands=[]
 class Journal:
  def __init__(self,*args,**kwargs):pass
  def execute(self,name,operation,**kwargs):
   commands.append(name)
   if name.startswith('native_'):
    split=name.split('_')[1]
    if split==failed_split:raise RuntimeError('ordinary_stage_process_fault_budget_exhausted:'+name)
    folder=Path(kwargs['artifact']).parent;folder.mkdir(parents=True)
    (folder/'manifest.json').write_text(json.dumps(dict(frames=10,initial_restore_count=1,errors=dict(qpos=0,qvel=0,time=0,terminal_qpos=0,terminal_qvel=0,terminal_time=0))))
    for camera in ('head_left','head_right','left_wrist','right_wrist'):(folder/(camera+'.mp4')).write_bytes(b'fixture-only-not-real-video')
   elif name.startswith('export_'):
    folder=Path(kwargs['artifact']).parent;folder.mkdir(parents=True);Path(kwargs['artifact']).write_text('{}')
   else:raise AssertionError('data_only_invoked_model_cache_or_training:'+name)
 monkeypatch.setattr(recovery,'StageJournal',Journal)
 def ffprobe(argv,**kwargs):
  head='head_' in argv[-1];return json.dumps({'streams':[{'width':1920 if head else 1280,'height':1536 if head else 720,'avg_frame_rate':'20/1','nb_frames':'10'}]})
 monkeypatch.setattr(pipeline.subprocess,'check_output',ffprobe)
 options=dict(run_dir=str(run),spec=str(spec),release=str(tmp_path/'release'),core_report=str(core),campaign=str(tmp_path/'campaign'),data_only=True,data_version='v2',sim_python='never-executed',vla_python='never-executed')
 pipeline.supervise(options);return json.loads((run/'pipeline_status.json').read_text()),commands,run

def test_native_failure_isolated_other_splits_continue_and_training_remains_blocked(tmp_path,monkeypatch):
 status,calls,run=_mock_data_pipeline(tmp_path,monkeypatch,'train')
 assert calls==['native_train_0','native_val_0','native_test_0','export_val','export_test'] and status['stage']=='waiting_missing_qualified_media_split'
 media=json.loads((run/'verified_media_selection.json').read_text());assert media['verified_split_counts']==dict(train=0,val=1,test=1) and media['failed_sources_excluded_from_training'] and len(media['failed_excluded_media_cases'])==1
 assert status['missing_qualified_media_splits']==['train'] and status['training_started'] is False
 assert len(json.loads((run/'verified_partial_source_records.json').read_text()))==2 and (run/'failed_media_cases.json').exists()

def test_version2_data_only_exits_after_exports_without_cache_or_second_trainer(tmp_path,monkeypatch):
 status,calls,_=_mock_data_pipeline(tmp_path,monkeypatch)
 assert calls==['native_train_0','native_val_0','native_test_0','export_train','export_val','export_test']
 assert status['stage']=='data_only_exports_verified_no_training' and status['dataset_version']=='v2'
 assert not status['training_started'] and not status['optimizer_initialized'] and not status['model_gpu_jobs_started']

def test_progress_diagnostics_do_not_infer_deadlock_or_change_timeout():
 from r1pro_teleop.vla.training_pipeline import classify_progress
 previous=dict(cpu_ticks=10,log_bytes=100,actual_completed_updates=10,completed_frames=20)
 assert classify_progress(previous,dict(previous,cpu_ticks=11),50)==('cpu_active_planning_or_compute',0.)
 assert classify_progress(previous,dict(previous,actual_completed_updates=11),50)==('training_updates',0.)
 assert classify_progress(previous,dict(previous,completed_frames=21),50)==('artifact_progress',0.)
 assert classify_progress(previous,previous,50)==('no_observed_progress',50)

def test_native_import_binds_all_source_bytes_and_old_actual_output(tmp_path,monkeypatch):
 import r1pro_teleop.vla.three_table_recovery as m
 source={'frames':2};hashes={}
 for key,field in [('trace','trace_sha256'),('events','events_sha256'),('scene_xml','scene_xml_sha256'),('scene_json','scene_json_sha256'),('result','result_sha256')]:
  p=tmp_path/(key+'.source');p.write_text(key);source[key]=str(p);source[field]=m.file_sha(p);hashes[key]=source[field]
 native=tmp_path/'native';native.mkdir();manifest=native/'manifest.json'
 manifest.write_text(json.dumps(dict(frames=2,initial_restore_count=1,errors=dict(qpos=0,qvel=0,time=0,terminal_qpos=0,terminal_qvel=0,terminal_time=0),source_sha256=hashes,source_files={k:source[k] for k in hashes})))
 for c in ('head_left','head_right','left_wrist','right_wrist'):(native/(c+'.mp4')).write_bytes(c.encode())
 def probe(argv,**kwargs):
  head='head_' in argv[-1];return json.dumps({'streams':[{'width':1920 if head else 1280,'height':1536 if head else 720,'avg_frame_rate':'20/1','nb_read_frames':'2'}]})
 monkeypatch.setattr(m.subprocess,'check_output',probe)
 old_exit=tmp_path/'old.exit.json';old_exit.write_text(json.dumps(dict(returncode=0,trainer_exited=True,argv=['python','render.py','--output',str(native)])))
 proof=m.import_native_stage(tmp_path/'new','native_train_0',native,old_exit,source)
 assert proof['new_process_spawned'] is False and proof['old_exit_not_copied_as_new_exit'] is True
 assert StageJournal(tmp_path/'new',lambda *a,**k:None).exit_proof('native_train_0',manifest)==proof
 for key in hashes:
  p=Path(source[key]);before=p.read_bytes();p.write_bytes(before+b'tampered')
  with pytest.raises(ValueError,match='native_source_identity_changed:'+key):m.native_proof(native,source)
  p.write_bytes(before)
 old_exit.write_text(json.dumps(dict(returncode=0,trainer_exited=True,argv=['python','render.py','--output',str(tmp_path/'other')])))
 with pytest.raises(ValueError,match='output_binding'):m.import_native_stage(tmp_path/'new2','native_train_0',native,old_exit,source)


def test_closed_campaign_missing_split_exports_healthy_sources_without_waiting_forever(tmp_path,monkeypatch):
 status,calls,run=_mock_data_pipeline(tmp_path,monkeypatch,missing_source_split='train')
 assert calls==['native_val_0','native_test_0','export_val','export_test']
 assert status['stage']=='waiting_missing_qualified_media_split' and status['source_campaign_closed'] is True
 assert status['verified_export_splits']==['test','val'] and status['training_started'] is False
 assert (run/'frozen_source_selection.json').exists() and (run/'verified_media_selection.json').exists()
