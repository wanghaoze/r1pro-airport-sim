import importlib.util,json,hashlib
from pathlib import Path
from types import SimpleNamespace
import numpy as np
from r1pro_teleop.vla.policy import PolicyError,PolicyContract
from r1pro_teleop.vla.data_three_table_single_tray import PROFILE,RULE_REVISION

def entrypoint():
    path=Path(__file__).resolve().parents[1]/'scripts/evaluate_three_table_single_tray_pi05.py'
    spec=importlib.util.spec_from_file_location('three_eval_evidence',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

def input_scene(tmp_path):
    xml=tmp_path/'source.xml';xml.write_text('<mujoco/>')
    return dict(scene_id='new_three_case',split='test',xml=str(xml),xml_sha256=hashlib.sha256(xml.read_bytes()).hexdigest(),
        task_rule_revision=RULE_REVISION,legacy_spec={})

def test_runtime_initialization_failure_is_zero_frame_evidence_not_verified_inverse_zero(tmp_path,monkeypatch):
    import r1pro_teleop.single_tray_3table.control as control
    def unavailable(*a,**kw):
        assert kw['render'] is True
        raise RuntimeError('actual_model_compile_failure')
    monkeypatch.setattr(control,'ThreeTableRuntime',unavailable)
    result=entrypoint().evaluate(input_scene(tmp_path),tmp_path/'evaluation',
        SimpleNamespace(contract=SimpleNamespace(checkpoint_id='sha256:actual')),cfg=object(),push_reference_scene={})
    assert result['frames']==0 and result['task_completed'] is False
    assert result['inverse_solver_calls'] is None and result['physical_episode_started'] is False
    assert result['zero_frame_evidence']['native_video_possible'] is False
    assert 'compile_failure' in result['failure_detail']
    assert json.loads((tmp_path/'evaluation/result.json').read_text())==result
    assert not (tmp_path/'evaluation/attempt/trace.h5').exists()

def test_scene_hash_failure_never_constructs_runtime(tmp_path,monkeypatch):
    import r1pro_teleop.single_tray_3table.control as control
    monkeypatch.setattr(control,'ThreeTableRuntime',lambda *a:(_ for _ in ()).throw(AssertionError('runtime forbidden')))
    scene=input_scene(tmp_path);scene['xml_sha256']='wrong'
    result=entrypoint().evaluate(scene,tmp_path/'evaluation',SimpleNamespace(contract=SimpleNamespace(checkpoint_id='id')),
        cfg=object(),push_reference_scene={})
    assert result['failure_detail']=='three_table_scene_xml_identity_changed'
    assert result['frames']==0 and result['inverse_solver_calls'] is None

def test_server_identity_failure_is_preserved_without_creating_fake_video_or_solver_proof(tmp_path):
    result=entrypoint().record_policy_startup_failure(input_scene(tmp_path),tmp_path/'evaluation','requested-id',PolicyError('mismatched_loaded_model'))
    assert result['failure_category']=='infrastructure' and result['checkpoint_identity_verified'] is False
    assert result['inverse_solver_calls'] is None and result['frames']==0
    assert not result['task_completed'] and not result['zero_frame_evidence']['native_video_possible']
    assert (tmp_path/'evaluation/scene/mobile.xml').is_file()
    assert json.loads((tmp_path/'evaluation/inference_calls.jsonl').read_text())['inference_executed'] is False

def test_inference_audit_records_real_transport_failure_without_physical_execution_claim(tmp_path):
    def failed(obs):raise RuntimeError('actual_disconnect')
    client=entrypoint().InferenceAuditClient(SimpleNamespace(infer=failed),tmp_path/'infer.jsonl',lambda:0)
    import pytest
    with pytest.raises(RuntimeError,match='actual_disconnect'):
        client.infer({'state':np.zeros(19,np.float32),'prompt':'Pick up the tray','image/head_left':np.zeros((2,2,3),np.uint8)})
    rows=[json.loads(x) for x in (tmp_path/'infer.jsonl').read_text().splitlines()]
    assert [x['event'] for x in rows]==['inference_request_started','inference_transport_failed']
    assert all(x['physical_execution_claimed'] is False for x in rows)
    assert client.count==1 and len(rows[0]['state_sha256'])==64


def test_actual_source_20mm_reference_uses_declared_bridge_contract_without_cfg_change():
    import pytest
    from r1pro_teleop.single_tray_3table.loaded_bridge import LoadedBridgeProfile
    cfg=SimpleNamespace(completion_collision_penetration_m=.02)
    source={'control_profile':{'max_penetration_m':.02}}
    p=entrypoint().source_push_reference_profile(source,cfg)
    assert isinstance(p,LoadedBridgeProfile) and p.max_penetration_m==.02
    assert p.source_collision_penetration_m==.02 and cfg.completion_collision_penetration_m==.02
    assert source=={'control_profile':{'max_penetration_m':.02}}
    with pytest.raises(ValueError,match='source_collision_contract_mismatch'):
        entrypoint().source_push_reference_profile(source,SimpleNamespace(completion_collision_penetration_m=.01))
    with pytest.raises(ValueError,match='bridge_source_collision_contract'):
        entrypoint().source_push_reference_profile({'control_profile':{'max_penetration_m':.03}},SimpleNamespace(completion_collision_penetration_m=.03))


def test_historical_reference_keeps_original_lab_contract():
    from r1pro_teleop.single_tray_lab.control import ControlProfile
    p=entrypoint().source_push_reference_profile({'control_profile':{}},SimpleNamespace(completion_collision_penetration_m=.02))
    assert type(p) is ControlProfile and p==ControlProfile().validate()

def test_actual_policy_inference_error_stops_without_teacher_or_tick_and_records_raw2_flag(tmp_path,monkeypatch):
    import r1pro_teleop.single_tray_3table.control as control
    import r1pro_teleop.single_tray_3table.learned as learned
    import r1pro_teleop.airport_fsm.trace as traces
    import r1pro_teleop.vla.executor as executor
    from r1pro_teleop.vla.executor import ActionBounds
    cfg=SimpleNamespace(fps=20,substep_control_enabled=False,vla_model_render_max_dim=0,completion_collision_penetration_m=.02,
        criteria=SimpleNamespace(contact_n=.5,lifted_m=.02),dump=lambda:{'substep_control_enabled':False})
    forbidden=[]
    def no_teacher(*a,**k):forbidden.append('called');raise AssertionError('teacher forbidden')
    sim=SimpleNamespace(base_joint_state=lambda:np.zeros(3),state=lambda:np.zeros(16),nstep=25,
        close=lambda:None,target=np.zeros(16),base_target=np.zeros(3))
    r=SimpleNamespace(limits={'fixture_actual_runtime_limits':True},cfg=cfg,sim=sim,m=SimpleNamespace(opt=SimpleNamespace(timestep=.002)),
        d=SimpleNamespace(time=0.,qpos=np.zeros(3),qvel=np.zeros(3)),integration_spec=1,id_calls=0,
        steps=0,observation=lambda:{'min_z':np.array([.8]),'table_contact':np.array([4]),'gripper_contact_force':np.zeros((1,2))},
        tick=no_teacher,solve_pair=no_teacher,joints=no_teacher,cartesian=no_teacher,navigate=no_teacher)
    def construct(*a,**kw):
        assert kw=={'render':True}
        return r
    monkeypatch.setattr(control,'ThreeTableRuntime',construct)
    class FakeTrace:
        def __init__(self,path,meta):self.meta=meta;self.file=SimpleNamespace(attrs={});self.count=0
        def event(self,*a,**k):pass
        def close(self,*a):pass
    monkeypatch.setattr(traces,'Trace',FakeTrace)
    monkeypatch.setattr(learned,'runtime_bounds',lambda r:ActionBounds(-np.ones(19),np.ones(19)))
    monkeypatch.setattr(learned,'contact_snapshot',lambda *a:dict(gripper_tray_contact_points_local=np.zeros((2,1,3)),
        gripper_tray_contact_normals_local=np.zeros((2,1,3)),gripper_tray_contact_active=np.zeros((2,1),bool),gripper_contact_force=np.zeros(2)))
    monkeypatch.setattr(learned,'opposed_contact',lambda *a:False)
    monkeypatch.setattr(executor,'render_model_observation',lambda *a:np.zeros((2,2,3),np.uint8))
    class Policy:
        contract=PolicyContract('sha256:actual',action_horizon=20,prompt_mode=PROFILE)
        def infer(self,images,state,prompt):
            assert state.shape==(19,) and prompt=='Pick up the tray'
            raise PolicyError('actual_websocket_disconnected')
    scene=input_scene(tmp_path);scene.update(tray={'size':[.56,.43,.105]},place_target={'position_world':[.85,.05,.801],'yaw_world':0})
    result=entrypoint().evaluate(scene,tmp_path/'evaluation',Policy(),cfg=cfg,push_reference_scene={'control_profile':{'max_penetration_m':.02}})
    assert 'actual_websocket_disconnected' in result['failure_detail']
    assert forbidden==[] and result['task_completed'] is False and result['frames']==0
    assert result['physical_episode_started'] is False
    assert r.trace.meta['limits']==r.limits
    assert r.trace.meta['recorded_substep_controls_without_interpolation'] is True
    assert r.record_ctrl_substeps is True and cfg.substep_control_enabled is False
