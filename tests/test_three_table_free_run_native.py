"""Free-run diagnostic replay/publication contracts; no task success claims."""
import json
from pathlib import Path
from types import SimpleNamespace
import numpy as np,pytest
from r1pro_teleop.single_tray_3table import free_run_native as n


def test_scope_and_environment_event_are_explicit_nontraining_and_exact_boundary():
    n.require_free_run_metadata(dict(run_scope=n.FREE_SCOPE,training_eligible=False,task_completed=None))
    for bad in (dict(training_eligible=False),dict(run_scope=n.FREE_SCOPE,training_eligible=True),dict(run_scope=n.FREE_SCOPE,training_eligible=False,task_completed=True)):
        with pytest.raises(ValueError):n.require_free_run_metadata(bad)
    evidence=dict(schema='airport_passenger_environment_transition/1')
    row=dict(event='passenger_payload_initialized',frame=8000,environment_data=evidence)
    assert n.environment_events([row],12000)=={8000:[evidence]}
    assert n.environment_events([],4000)=={}
    with pytest.raises(ValueError,match='required'):n.environment_events([],12000)
    with pytest.raises(ValueError,match='duplicate'):n.environment_events([row,row],12000)
    with pytest.raises(ValueError,match='boundary'):n.environment_events([dict(row,frame=7999)],12000)
    with pytest.raises(ValueError,match='ambiguous'):n.environment_events([dict(row,environment_evidence=dict(schema='other'))],12000)


def test_four_camera_publication_requires_actual_headers_and_cannot_be_training(tmp_path):
    receipt=dict(schema='airport_three_table_free_run_native_replay/1',run_scope=n.FREE_SCOPE,task_completed=False,training_eligible=False,formal_evaluation=False,audit_only=False,recorded_frames=3)
    for camera in n.NATIVE_SHAPES:(tmp_path/(camera+'.mp4')).write_bytes(b'unit video fixture')
    def probe(path):
        height,width,_=n.NATIVE_SHAPES[path.stem]
        return dict(width=width,height=height,r_frame_rate='20/1',nb_read_frames='3',codec_name='h264')
    published=n.publish(tmp_path,receipt,probe=probe)
    assert len(published['videos'])==4 and published['training_eligible'] is False
    assert len((tmp_path/'VIDEO_PATHS.txt').read_text().splitlines())==4
    assert 'not formal task evaluation' in (tmp_path/'viewer.html').read_text()
    with pytest.raises(ValueError,match='nontraining'):n.publish(tmp_path,dict(receipt,task_completed=True),probe=probe)
    with pytest.raises(ValueError,match='four_native'):n.publish(tmp_path,receipt,probe=lambda p:dict(probe(p),nb_read_frames='2'))


def test_initial_model_snapshot_must_match_force_gain_and_camera_arrays():
    arrays={key:np.ones((2,2)) for key in ('actuator_forcerange','actuator_gainprm','actuator_biasprm','actuator_ctrlrange','cam_pos','cam_quat','cam_fovy','cam_ipd')}
    model=SimpleNamespace(**arrays);meta=dict(source_model_parameters={k:v.tolist() for k,v in arrays.items()})
    assert len(n.verify_model_parameters(model,meta))==8
    meta['source_model_parameters']['actuator_gainprm'][0][0]=2
    with pytest.raises(ValueError,match='model_parameter_mismatch'):n.verify_model_parameters(model,meta)


def test_free_run_flags_cannot_qualify_as_formal_source(tmp_path):
    from test_vla_data_three_table_single_tray import fixture
    from r1pro_teleop.vla.data_three_table_single_tray import source_validate
    for flag in ('run_scope','run_kind','free_run_diagnostic'):
        source,*_=fixture(tmp_path)
        source[flag]=True if flag=='free_run_diagnostic' else n.FREE_SCOPE
        with pytest.raises(ValueError,match='never_training'):source_validate(source)

def test_actual_mujoco_raw2_partial_and_invalid_terminal_keep_finite_prefix(tmp_path,monkeypatch):
    import mujoco as mj,h5py
    from r1pro_teleop.airport_fsm import runtime as runtime_module
    from r1pro_teleop.airport_fsm.contracts import Config,sha256_file
    case=tmp_path/'case';(case/'scene').mkdir(parents=True);(case/'attempt').mkdir()
    xml=case/'scene/mobile.xml'
    cameras=''.join('<camera name="'+name+'" pos="0 -1 1"/>' for name in n.NATIVE_SHAPES)
    xml.write_text('<mujoco><option timestep=".002" gravity="0 0 0"/><worldbody>'+cameras+'<body><joint name="slide" type="slide" axis="1 0 0"/><geom size=".1" mass="1"/></body></worldbody><actuator><motor joint="slide" ctrllimited="true" ctrlrange="-1 1"/></actuator></mujoco>')
    model=mj.MjModel.from_xml_path(str(xml));data=mj.MjData(model);mj.mj_forward(model,data)
    spec=dict(scene_id='cpu_fixture',camera=dict(streams={name:dict(width=shape[1],height=shape[0]) for name,shape in n.NATIVE_SHAPES.items()}))
    manifest=dict(schema='airport_three_table_single_tray_scene/1',task_profile='three_table_single_tray_action3_v1',scene_id=spec['scene_id'],legacy_spec=spec,xml=str(xml),payloads=[])
    (case/'scene/scene.json').write_text(json.dumps(manifest));(case/'attempt/events.jsonl').write_text('')
    cfg=Config(substep_control_enabled=False);integ=mj.mjtState.mjSTATE_INTEGRATION
    rows=[];states=[];velocities=[];times=[];warm=[];controls=np.full((3,25,1),.2,np.float64)
    for count in (25,25,7):
        s=np.empty(mj.mj_stateSize(model,integ));mj.mj_getState(model,data,s,integ);rows.append(s)
        states.append(data.qpos.copy());velocities.append(data.qvel.copy());times.append(data.time);warm.append(data.qacc_warmstart.copy())
        for _ in range(count):data.ctrl[:]=.2;mj.mj_step(model,data);mj.mj_forward(model,data)
    terminal=dict(qpos=data.qpos.tolist(),qvel=data.qvel.tolist(),time=float(data.time))
    meta=dict(run_scope=n.FREE_SCOPE,training_eligible=False,requested_stage_seconds=.5,planned_frames=30,payload_event_frame=20,scene=spec,scene_id=spec['scene_id'],scene_xml_sha256=sha256_file(xml),config=cfg.dump(),limits={},substeps_per_frame=25,physics_timestep_s=.002,recorded_substep_controls_without_interpolation=True)
    meta['source_model_parameters']={key:getattr(model,key).tolist() for key in ('actuator_forcerange','actuator_gainprm','actuator_biasprm','actuator_ctrlrange','cam_pos','cam_quat','cam_fovy','cam_ipd')}
    trace=case/'attempt/trace.h5'
    with h5py.File(trace,'w') as f:
        f.attrs.update(schema='airport_fsm_raw/2',metadata_json=json.dumps(meta),num_frames=3,terminal_snapshot_json=json.dumps(terminal))
        for key,value in dict(qpos=states,qvel=velocities,sim_time=times,qacc_warmstart=warm,integration_state=rows,ctrl_substeps=controls,executed_substeps=[25,25,7],transition_completed=[True,True,False],action=np.zeros((3,16)),base_action=np.zeros((3,3))).items():f[key]=value
    class ActualPhysicsRuntime:
        def __init__(self,spec,path,cfg,**kwargs):
            self.mj=mj;self.m=mj.MjModel.from_xml_path(str(path));self.d=mj.MjData(self.m);self.limits={};self.integration_spec=integ
            self.sim=SimpleNamespace(scene=path,nstep=25,target=np.zeros(16),base_target=np.zeros(3))
        def close(self):pass
    monkeypatch.setattr(runtime_module,'Runtime',ActualPhysicsRuntime);monkeypatch.setattr(n,'Geometry',lambda *a,**kw:object())
    replay=n.FreeRunTraceReplay(case,render=False)
    source={k:sha256_file(v) for k,v in replay.source_files.items()}
    assert len(list(replay))==3
    receipt=n.closure(replay,3,source,audit_only=True)
    assert receipt['errors']=={k:0. for k in n.ERROR_KEYS}
    assert receipt['initial_restore_count']==1 and receipt['pose_resets_during_replay']==0
    assert receipt['recorded_physics_seconds']==pytest.approx(.114) and not receipt['full_duration_recording']
    replay.close()
    with h5py.File(trace,'r+') as f:f.attrs['terminal_snapshot_json']=json.dumps(dict(invalid=True,reason='nonfinite_terminal_state'))
    replay=n.FreeRunTraceReplay(case,render=False);source={k:sha256_file(v) for k,v in replay.source_files.items()}
    assert len(list(replay))==3
    receipt=n.closure(replay,3,source,audit_only=True)
    assert receipt['recorded_prefix_video_only'] and not receipt['last_interval_replayed']
    assert receipt['terminal_checked'] is False and receipt['errors']['terminal_time'] is None
    assert receipt['errors']['qpos']==0 and receipt['errors']['qvel']==0
    assert replay.runtime.d.time==pytest.approx(.1)
    replay.close()

def test_actual_tiny_mp4_has_front_moov_and_original_h264_settings(tmp_path):
    import struct,subprocess
    pytest.importorskip('av')
    import shutil
    if not shutil.which('ffprobe'):pytest.skip('Actual ffprobe required')
    path=tmp_path/'tiny.mp4';writer=n.FreeRunNativeWriter(path,(24,32,3))
    for i in range(3):writer.write(np.full((24,32,3),i*40,np.uint8))
    writer.close();writer.close()
    blob=path.read_bytes();atoms=[];offset=0
    while offset<len(blob):
        size,kind=struct.unpack('>I4s',blob[offset:offset+8]);header=8
        if size==1:size=struct.unpack('>Q',blob[offset+8:offset+16])[0];header=16
        if size==0:size=len(blob)-offset
        assert size>=header
        atoms.append(kind.decode());offset+=size
    assert atoms.index('moov')<atoms.index('mdat')
    doc=json.loads(subprocess.check_output(['ffprobe','-v','error','-count_frames','-show_entries','stream=codec_name,width,height,r_frame_rate,nb_read_frames','-of','json',str(path)],text=True))['streams'][0]
    assert doc==dict(codec_name='h264',width=32,height=24,r_frame_rate='20/1',nb_read_frames='3')
