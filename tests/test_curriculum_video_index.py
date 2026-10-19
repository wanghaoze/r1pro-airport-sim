import json,importlib.util
from pathlib import Path
import pytest,h5py
from test_scene_video_index import index,save


def curriculum_fixture(root):
    source=root/'source';sid='scene1';scene=dict(scene_id=sid,split='train',difficulty='complex',front_count=2)
    save(source/'scenes'/sid/'scene.json',scene);xml=source/'scenes'/sid/'mobile.xml';xml.write_text('physics')
    teacher=source/'attempts'/sid/'a000/trace.h5';teacher.parent.mkdir(parents=True);teacher.write_bytes(b'expert')
    snapshot=dict(source_trace=str(teacher),source_trace_sha256=index.file_digest(teacher),initial_restore_count=1,
        source_scene_sha256=index.file_digest(source/'scenes'/sid/'scene.json'))
    run=root/'curriculum';attempt=run/'episode_000002';attempt.mkdir(parents=True);trace=attempt/'trace.h5'
    result=dict(schema='airport_vla_isolated_skill_diagnostic/1',scene_id=sid,split='train',task_completed=False,
        physics_success=False,controller_source='vla_generated',checkpoint_id='sha256:model',
        purpose='diagnostic_not_full_DAG_success',collection_mode='expert_snapshot_curriculum',live_teacher_actions=False,
        inverse_dynamics_calls=0,initial_snapshot=snapshot,actual_control_steps=2,skill='grasp_lift_tray',
        skill_completed=False,failure_code='vla_operation_step_budget_exhausted')
    save(attempt/'diagnostic_result.json',result)
    report=dict(schema='airport_vla_isolated_skill_diagnostic_run/1',status='completed',task_completed=False,
        full_DAG_success_eligible=False,results=[result],checkpoint_metadata={'checkpoint_id':result['checkpoint_id']})
    save(run/'diagnostic_report.json',report)
    with h5py.File(trace,'w') as f:
        f.attrs['num_frames']=2;f.attrs['metadata_json']=json.dumps(dict(scene=scene,checkpoint_id=result['checkpoint_id'],
            diagnostic=True,full_DAG_evaluation=False,initial_snapshot=snapshot))
    directory=root/'videos'/sid/attempt.name;directory.mkdir(parents=True);refs=[]
    for camera in ('head_left','head_right'):
        video=directory/(camera+'.mp4');video.write_bytes(b'learner video')
        refs.append(dict(path=str(video),camera=camera,native=True,frames=2,trace=str(trace),
            trace_sha256=index.file_digest(trace),sha256=index.file_digest(video)))
    manifest=dict(schema='airport_vla_curriculum_native_replay/1',status='complete',purpose='inspection_not_training_export',
        collection_mode='expert_snapshot_curriculum',full_DAG_success_eligible=False,task_completed=False,
        trace=str(trace),trace_sha256=index.file_digest(trace),source_collection=str(source),
        source_result=str(attempt/'diagnostic_result.json'),source_result_sha256=index.file_digest(attempt/'diagnostic_result.json'),
        source_diagnostic_report=str(run/'diagnostic_report.json'),source_report_sha256=index.file_digest(run/'diagnostic_report.json'),
        scene_id=sid,checkpoint_id=result['checkpoint_id'],initial_snapshot=snapshot,frames=2,fps=20,references=refs,
        source_scene_json_sha256=index.file_digest(source/'scenes'/sid/'scene.json'),scene_xml_sha256=index.file_digest(xml))
    path=directory/'manifest.json';save(path,manifest)
    return path,manifest,attempt


def test_curriculum_actual_failure_classifies_both_heads_with_non_full_DAG_disclosure(tmp_path):
    curriculum_fixture(tmp_path);rows=index.scan_server(tmp_path)['rows']
    assert len(rows)==2 and {r['outcome'] for r in rows}=={'失败'}
    assert {r['difficulty'] for r in rows}=={'complex'}
    assert {r['failure_code'] for r in rows}=={'vla_operation_step_budget_exhausted'}
    assert all('curriculum隔离技能（非完整DAG评估）' in r['status'] for r in rows)


@pytest.mark.parametrize('change',['result','teacher','video','claim'])
def test_curriculum_tampering_cannot_be_associated_or_claim_full_success(tmp_path,change):
    path,m,attempt=curriculum_fixture(tmp_path)
    if change=='result':(attempt/'diagnostic_result.json').write_text('{}')
    elif change=='teacher':Path(m['initial_snapshot']['source_trace']).write_bytes(b'changed')
    elif change=='video':Path(m['references'][0]['path']).write_bytes(b'changed')
    else:m['task_completed']=True;save(path,m)
    rows=index.scan_server(tmp_path)['rows']
    if change=='video':assert sum(r['outcome']=='未知' for r in rows)==1
    else:assert {r['outcome'] for r in rows}=={'未知'}


def test_curriculum_renderer_rejects_full_DAG_claim_before_any_replay(tmp_path):
    _,m,attempt=curriculum_fixture(tmp_path)
    path=Path(__file__).resolve().parents[1]/'runs/vla_deploy_20261001/render_curriculum_learner_heads.py'
    spec=importlib.util.spec_from_file_location('curriculum_renderer_test',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    report=json.loads((attempt.parent/'diagnostic_report.json').read_text());report['full_DAG_success_eligible']=True
    save(attempt.parent/'diagnostic_report.json',report)
    def banned(*args,**kwargs):raise AssertionError('invalid provenance triggered physics')
    with pytest.raises(ValueError,match='provenance'):
        module.render_attempt(attempt,m['source_collection'],tmp_path/'render',replay_factory=banned)
