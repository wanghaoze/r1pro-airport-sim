import json
import inspect
from pathlib import Path
import pytest
from r1pro_teleop.single_tray_lab.evaluation_batch import protocol,canonical,sha,summary,handoff
from r1pro_teleop.single_tray_lab.evaluation_batch import verify_inputs,run_batch
from types import SimpleNamespace


def fixture_protocol(tmp_path):
    xml=tmp_path/'scene.xml';xml.write_text('<mujoco><worldbody><body name="tray"/></worldbody></mujoco>')
    scene=dict(schema='airport_single_tray_scene/1',source='simulation/program_generated',tray={'body':'tray'},
        frame={'base_mode':'fixed_front'},payload_loaded_initially=False,scene_id='new_scene',split='test',xml=str(xml),xml_sha256=sha(xml))
    sp=tmp_path/'scene.json';sp.write_text(json.dumps(scene))
    doc=dict(schema='airport_single_tray_evaluation_protocol/1',task_profile='single_tray_action3_v1',base_mode='fixed_front',
        execution=dict(max_action_steps=3600,execute_steps=5,fps=20,environment_phase_excluded=True),
        strict_contact_report=dict(definition='task_complete_and_all_guarded_hard_le_3mm_soft_le_5mm',hard_limit_m=.003,soft_limit_m=.005,required_coverage='every_guarded_physics_substep',missing_evidence='unavailable_never_passed'),
        scenes=[dict(scene_json=str(sp),scene_json_sha256=sha(sp),scene_xml_sha256=sha(xml),scene_id='new_scene',split='test')])
    doc['protocol_id']='sha256:'+canonical(doc);p=tmp_path/'protocol.json';p.write_text(json.dumps(doc));return p,doc,sp


def test_new_explicit_protocol_identity_and_source_mutation(tmp_path):
    p,doc,sp=fixture_protocol(tmp_path);assert protocol(p)['protocol_id']==doc['protocol_id']
    sp.write_text(sp.read_text()+' ')
    with pytest.raises(ValueError,match='source_bytes'):protocol(p)


def test_old_scope_and_duplicate_scenes_rejected(tmp_path):
    p,doc,sp=fixture_protocol(tmp_path);doc['task_profile']='task_complete_action8_v1';p.write_text(json.dumps(doc))
    with pytest.raises(ValueError):protocol(p)
    doc['task_profile']='single_tray_action3_v1';doc['scenes']*=2;doc['protocol_id']='sha256:'+canonical({k:v for k,v in doc.items() if k!='protocol_id'});p.write_text(json.dumps(doc))
    with pytest.raises(ValueError,match='duplicate'):protocol(p)


def test_old_three_tray_xml_not_accepted_by_new_json_label(tmp_path):
    p,doc,sp=fixture_protocol(tmp_path);scene=json.loads(sp.read_text());Path(scene['xml']).write_text('<mujoco><body name="tray_0"/><body name="tray_1"/><body name="tray_2"/></mujoco>')
    scene['xml_sha256']=sha(scene['xml']);sp.write_text(json.dumps(scene));doc['scenes'][0].update(scene_xml_sha256=scene['xml_sha256'],scene_json_sha256=sha(sp));doc['protocol_id']='sha256:'+canonical({k:v for k,v in doc.items() if k!='protocol_id'});p.write_text(json.dumps(doc))
    with pytest.raises(ValueError,match='one_tray'):protocol(p)


def test_zero_success_remains_zero_and_no_strict_claim():
    rows=[dict(task_completed=False,failure_code='budget',strict_success=None)]*3
    result=summary(rows,3,'new')
    assert result['complete_task_rate']==0
    assert result['strict_successes'] is None and result['strict_status']=='unavailable'
    with pytest.raises(ValueError,match='missing'):summary(rows,4,'new')


def handoff_files(tmp_path):
    m=tmp_path/'milestone.json';m.write_text(json.dumps(dict(actual_completed_updates=10,schema='airport_pi05_training_milestone/1',prompt_mode='single_tray_action3_v1',status='milestone_checkpoint',checkpoint_verified=True)))
    videos=[]
    for camera in ('head_left','head_right','left_wrist','right_wrist'):
        path=tmp_path/(camera+'.mp4');path.write_bytes(b'audited-test-fixture-bytes')
        videos.append(dict(camera=camera,path=str(path),sha256=sha(path),frames=1))
    trace=tmp_path/'trace.h5';trace.write_bytes(b'trace-fixture')
    result=tmp_path/'result.json';result.write_text('{}')
    s=tmp_path/'summary.json';s.write_text(json.dumps(dict(protocol_id='new_scope',selected=1,covered=1,cases=[dict(videos=videos,trace=str(trace),trace_sha256=sha(trace),result=str(result),result_sha256=sha(result))])))
    own=[dict(pid=100,active=False,returncode=-15)]
    return m,s,own


def test_missing_video_or_live_gpu_cannot_resume(tmp_path):
    m,s,own=handoff_files(tmp_path)
    with pytest.raises(ValueError,match='gpu_release'):handoff(m,'new_scope',s,own,[dict(pid=100)])
    doc=json.loads(s.read_text());doc['cases'][0]['videos'].pop();s.write_text(json.dumps(doc))
    with pytest.raises(ValueError,match='native'):handoff(m,'new_scope',s,own,[])


def test_handoff_binds_immutable_milestone_and_scope_after_actual_exits(tmp_path):
    m,s,own=handoff_files(tmp_path);r=handoff(m,'new_scope',s,own,[])
    assert r['actual_completed_updates']==10 and r['training_status_sha256']==sha(m)
    assert r['training_resume_allowed'] is True
    own[0]['active']=True
    with pytest.raises(ValueError):handoff(m,'new_scope',s,own,[])


def test_post_audit_video_mutation_blocks_receipt(tmp_path):
    m,s,own=handoff_files(tmp_path);(tmp_path/'left_wrist.mp4').write_bytes(b'mutated')
    with pytest.raises(ValueError,match='video_changed'):handoff(m,'new_scope',s,own,[])


def saved_inputs(tmp_path):
    p,doc,sp=fixture_protocol(tmp_path);spec=dict(prompt_mode='single_tray_action3_v1',action_horizon=20)
    s=tmp_path/'spec.json';s.write_text(json.dumps(spec))
    m=tmp_path/'milestone.json';m.write_text(json.dumps(dict(spec=spec,prompt_mode=spec['prompt_mode'],schema='airport_pi05_training_milestone/1',status='milestone_checkpoint',checkpoint_verified=True,actual_completed_updates=10,training_steps=10,checkpoint_step=9,base_mode='fixed_front',base_actuated=False,model_action_mask=[True]*16+[False]*3)))
    return s,m,p


def test_prepare_does_not_touch_gpu_or_restore_model(tmp_path,monkeypatch):
    s,m,p=saved_inputs(tmp_path)
    module=inspect.getmodule(run_batch)
    monkeypatch.setattr(module,'gpu_processes',lambda:pytest.fail('prepare queried GPU'))
    run_batch(SimpleNamespace(spec=s,milestone=m,protocol=p,out=tmp_path/'out',execute=False))
    assert json.loads((tmp_path/'out/status.json').read_text())['stage']=='prepared_no_model_or_gpu_execution'
    assert not (tmp_path/'out/completion_receipt.json').exists()


def test_stale_completed_updates_or_spec_disagreement_reject(tmp_path):
    s,m,p=saved_inputs(tmp_path);verify_inputs(s,m,p)
    value=json.loads(m.read_text());value['checkpoint_step']=8;m.write_text(json.dumps(value))
    with pytest.raises(ValueError,match='update_identity'):verify_inputs(s,m,p)
    value['checkpoint_step']=9;value['spec']['action_horizon']=50;m.write_text(json.dumps(value))
    with pytest.raises(ValueError,match='spec_changed'):verify_inputs(s,m,p)

def test_contact_gate_separate_from_complete_task_rate():
 rows=[dict(task_completed=True,failure_code=None,strict_contact_success=False,strict_contact_evidence={'coverage':'every_guarded_physics_substep'}),dict(task_completed=True,failure_code=None,strict_contact_success=True,strict_contact_evidence={'coverage':'every_guarded_physics_substep'})]
 result=summary(rows,2,'new_contact_profile');assert result['complete_task_rate']==1 and result['strict_contact_rate']==.5 and result['strict_contact_successes']==1
 assert result['strict_successes'] is None and result['historical_three_tray_strict_metric_used'] is False
 rows[1]['strict_contact_evidence']={'coverage':'unavailable'};rows[1]['strict_contact_success']=None
 result=summary(rows,2,'new_contact_profile');assert result['strict_contact_rate'] is None and result['strict_contact_evidence_unavailable']==1

def test_formal_milestone_requires_contactgate_declaration(tmp_path):
 s,m,p=saved_inputs(tmp_path);value=json.loads(p.read_text());value.pop('strict_contact_report');value['protocol_id']='sha256:'+canonical({k:v for k,v in value.items() if k!='protocol_id'});p.write_text(json.dumps(value))
 with pytest.raises(ValueError,match='contact_gate_protocol_required'):verify_inputs(s,m,p)



def test_budget_mismatch_rejects_before_output_or_gpu(tmp_path):
 s,m,p=saved_inputs(tmp_path);out=tmp_path/'out'
 with pytest.raises(ValueError,match='execution_budget_protocol_mismatch'):run_batch(SimpleNamespace(spec=s,milestone=m,protocol=p,out=out,execute=False,max_action_steps=1200,execute_steps=5))
 assert not out.exists()

