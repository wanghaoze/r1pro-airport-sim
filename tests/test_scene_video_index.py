import importlib.util
import json
from pathlib import Path
import pytest

_path=Path(__file__).resolve().parents[1]/'runs/failure_videos/update_scene_video_index.py'
_spec=importlib.util.spec_from_file_location('scene_video_index_under_test',_path)
index=importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(index)


def save(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value),encoding='utf-8')


def fixture(root,completed=True):
    collection=root/'releases/test/runs/new/collection'
    attempt=collection/'attempts/scene_1/a000'
    attempt.mkdir(parents=True)
    trace=attempt/'trace.h5';trace.write_bytes(b'actual trace')
    save(attempt/'result.json',dict(scene_id='scene_1',split='train',task_completed=completed,
                                  physics_success=True,failure_code=None if completed else 'placement_failed'))
    save(collection/'scenes/scene_1/scene.json',dict(scene_id='scene_1',split='train',
                                                  difficulty='complex',front_count=2))
    directory=root/'runs/vla/native/scene_1/a000'
    directory.mkdir(parents=True)
    references=[]
    for camera in ('head_left','head_right','left_wrist','right_wrist'):
        video=directory/(camera+'.mp4');video.write_bytes(b'video')
        references.append(dict(trace=str(trace),trace_sha256='b'*64,path=str(video),camera=camera,sha256='a'*64,
                               frames=40,source_start_frame=0,video_start_frame=0,native=True))
    manifest=dict(schema='airport_vla_native_replay/1',status='complete',scene_id='scene_1',
                  split='train',attempt='a000',trace=str(trace),trace_sha256='b'*64,frames=40,fps=20,
                  references=references,task_completed=True)
    path=directory/'manifest.json';save(path,manifest)
    return path,manifest,attempt


def test_native_four_cameras_classified_from_source_with_no_false_missing_heads(tmp_path):
    fixture(tmp_path)
    rows=index.scan_server(tmp_path)['rows']
    assert len(rows)==4 and all(r['server_video'] for r in rows)
    assert {r['outcome'] for r in rows}=={'成功'}
    assert {r['difficulty'] for r in rows}=={'complex'}
    assert {r['front_count'] for r in rows}=={'2'}
    assert {r['scene_id'] for r in rows}=={'scene_1'}


def complete_task_native_fixture(root):
    path,manifest,attempt=fixture(root)
    scene=attempt.parents[2]/'scenes/scene_1'
    (scene/'mobile.xml').write_text('<mujoco/>')
    manifest.update(schema='airport_complete_task_native_replay/1',
        source_result=str(attempt/'result.json'),source_result_sha256=index.file_digest(attempt/'result.json'),
        trace_sha256=index.file_digest(attempt/'trace.h5'),
        source_scene_json_sha256=index.file_digest(scene/'scene.json'),
        scene_xml_sha256=index.file_digest(scene/'mobile.xml'),initial_restore_count=1,
        per_frame_state_reset=False,IK_calls=0,source_hashes_before_after_verified=True,
        prefix_errors=dict(qpos=0.,qvel=0.,time=0.),terminal_errors=dict(qpos=0.,qvel=0.,time=0.))
    for entry in manifest['references']:entry['trace_sha256']=manifest['trace_sha256']
    save(path,manifest)
    return path,manifest,attempt


def test_complete_task_native_schema_uses_actual_source_and_six_replay_checks(tmp_path):
    complete_task_native_fixture(tmp_path)
    actual=[r for r in index.scan_server(tmp_path)['rows'] if r['server_video']]
    assert len(actual)==4 and {r['outcome'] for r in actual}=={'成功'}


@pytest.mark.parametrize('category,key,value',[('prefix_errors','qvel',1.),('terminal_errors','time',float('nan'))])
def test_complete_task_bad_replay_stays_unknown(tmp_path,category,key,value):
    path,manifest,_=complete_task_native_fixture(tmp_path)
    manifest[category][key]=value;save(path,manifest)
    rows=index.scan_server(tmp_path)['rows']
    assert {r['outcome'] for r in rows if r['server_video']}=={'未知'}


def test_complete_task_changed_source_stays_unknown(tmp_path):
    _,_,attempt=complete_task_native_fixture(tmp_path)
    (attempt/'trace.h5').write_bytes(b'changed source')
    assert {r['outcome'] for r in index.scan_server(tmp_path)['rows'] if r['server_video']}=={'未知'}


def test_native_success_claim_cannot_override_actual_failed_attempt(tmp_path):
    fixture(tmp_path,completed=False)
    rows=index.scan_server(tmp_path)['rows']
    assert len(rows)==4 and {r['outcome'] for r in rows}=={'失败'}
    assert {r['failure_code'] for r in rows}=={'placement_failed'}


@pytest.mark.parametrize('change',[{'status':'rendering'},{'scene_id':'different'},
                                  {'attempt':'a001'},{'split':'test'},
                                  {'source_collection':'/outside/project'}])
def test_invalid_native_source_does_not_suppress_missing_heads(tmp_path,change):
    path,manifest,_=fixture(tmp_path)
    manifest.update(change);save(path,manifest)
    rows=index.scan_server(tmp_path)['rows']
    actual=[r for r in rows if r['server_video']]
    pending=[r for r in rows if not r['server_video']]
    assert len(actual)==4 and {r['outcome'] for r in actual}=={'未知'}
    assert {r['camera'] for r in pending}=={'head_left','head_right'}


def test_native_missing_single_head_keeps_only_that_head_pending(tmp_path):
    path,manifest,_=fixture(tmp_path)
    Path(manifest['references'][0]['path']).unlink()
    rows=index.scan_server(tmp_path)['rows']
    assert len([r for r in rows if r['server_video']])==3
    assert [r['camera'] for r in rows if not r['server_video']]==['head_left']


def test_native_reference_cannot_escape_project_or_associate_other_trace(tmp_path):
    path,manifest,_=fixture(tmp_path)
    outside=tmp_path.parent/(tmp_path.name+'_outside.mp4');outside.write_bytes(b'outside')
    manifest['references'][0]['path']=str(outside)
    manifest['references'][1]['trace']=str(tmp_path/'different/trace.h5')
    save(path,manifest)
    rows=index.scan_server(tmp_path)['rows']
    assert all(r['server_video']!=str(outside) for r in rows)
    assert {r['camera'] for r in rows if not r['server_video']}=={'head_left','head_right'}
    assert len([r for r in rows if r['outcome']=='成功' and r['server_video']])==2


def test_baseline_attempt_media_still_classifies_without_manifest(tmp_path):
    path,_,attempt=fixture(tmp_path)
    path.unlink()
    for camera in ('head_left','head_right'):(attempt/(camera+'.mp4')).write_bytes(b'head')
    rows=index.scan_server(tmp_path)['rows']
    assert len([r for r in rows if r['outcome']=='成功' and r['server_video']])==2
    assert not [r for r in rows if not r['server_video']]


def test_reference_trace_digest_mismatch_keeps_head_unknown_and_pending(tmp_path):
    path,manifest,_=fixture(tmp_path)
    manifest['references'][0]['trace_sha256']='c'*64
    save(path,manifest)
    rows=index.scan_server(tmp_path)['rows']
    assert [r['camera'] for r in rows if not r['server_video']]==['head_left']
    assert len([r for r in rows if r['server_video'] and r['outcome']=='成功'])==3


def derived_fixture(root,completed=True):
    native_path,native_manifest,attempt=fixture(root,completed=completed)
    dataset=root/'runs/vla/lerobot/airport/bootstrap'
    features={}
    for camera in ('head_left','left_wrist','right_wrist'):
        key='observation.images.'+camera
        features[key]={'dtype':'video','shape':[3,224,224]}
        for idx in range(2):
            video=dataset/'videos/chunk-000'/key/f'episode_{idx:06d}.mp4'
            video.parent.mkdir(parents=True,exist_ok=True);video.write_bytes(b'derived224')
    save(dataset/'meta/info.json',dict(total_episodes=2,chunks_size=1000,fps=20,features=features,
        video_path='videos/chunk-{episode_chunk:03d}/{video_key}/episode_{episode_index:06d}.mp4'))
    entries=[dict(episode_index=i,scene_id='scene_1',split='train',source_trace=str(attempt/'trace.h5'),
                  source_trace_sha256='b'*64,source_start_frame=i*20,source_end_frame=(i+1)*20,
                  frames=20,fps=20,episode_strict_success=True,quality_class='episode_success') for i in range(2)]
    manifest=dict(schema='airport_pi05_training/1',fps=20,episodes=entries,
                  image_derivation={'size':[224,224]},training_video_encoding_verification={'verified':True})
    path=dataset/'airport_training_manifest.json';save(path,manifest)
    return path,manifest,native_path


def test_official_training_episodes_associate_all_derived_videos_but_keep_native_classification(tmp_path):
    derived_fixture(tmp_path)
    rows=index.scan_server(tmp_path)['rows']
    assert len(rows)==10 and {r['outcome'] for r in rows}=={'成功'}
    training=[r for r in rows if r.get('media_type')=='training_224_derived_non_native']
    assert len(training)==6
    assert {r['episode_index'] for r in training}=={0,1}
    assert all('训练224派生（非native；source实际成功）' in r['status'] for r in training)
    assert {r['difficulty'] for r in training}=={'complex'}
    assert {r['front_count'] for r in training}=={'2'}
    assert len([r for r in rows if not r.get('media_type')])==4


def test_training_fragment_claims_cannot_override_source_task_failure(tmp_path):
    derived_fixture(tmp_path,completed=False)
    rows=index.scan_server(tmp_path)['rows']
    training=[r for r in rows if r.get('media_type')=='training_224_derived_non_native']
    assert len(training)==6 and {r['outcome'] for r in training}=={'失败'}
    assert {r['failure_code'] for r in training}=={'placement_failed'}


def test_in_progress_training_without_completed_manifest_remains_unknown(tmp_path):
    path,manifest,_=derived_fixture(tmp_path);path.unlink()
    rows=index.scan_server(tmp_path)['rows']
    assert len([r for r in rows if r['outcome']=='成功'])==4
    unknown=[r for r in rows if r['outcome']=='未知']
    assert len(unknown)==6 and all('可能渲染中' in r['status'] for r in unknown)


def test_training_224_head_fragment_does_not_hide_missing_native_head(tmp_path):
    path,manifest,native_path=derived_fixture(tmp_path)
    (native_path.parent/'head_left.mp4').unlink()
    rows=index.scan_server(tmp_path)['rows']
    assert [r['camera'] for r in rows if not r['server_video']]==['head_left']
    assert len([r for r in rows if r.get('media_type')])==6


@pytest.mark.parametrize('change',[{'scene_id':'other'},{'source_trace':'/outside/project/trace.h5'},
                                  {'source_end_frame':999},{'split':'test'}])
def test_training_source_mismatch_is_not_associated(tmp_path,change):
    path,manifest,_=derived_fixture(tmp_path)
    manifest['episodes'][0].update(change);save(path,manifest)
    rows=index.scan_server(tmp_path)['rows']
    assert len([r for r in rows if r.get('media_type')])==3
    assert len([r for r in rows if r['outcome']=='未知'])==3


def test_official_video_path_template_cannot_escape_dataset(tmp_path):
    path,manifest,_=derived_fixture(tmp_path)
    info=json.loads((path.parent/'meta/info.json').read_text())
    info['video_path']='../../escape/{video_key}/episode_{episode_index:06d}.mp4'
    save(path.parent/'meta/info.json',info)
    rows=index.scan_server(tmp_path)['rows']
    assert not [r for r in rows if r.get('media_type')]
    assert len([r for r in rows if r['outcome']=='未知'])==6


def test_historical_completed_bootstrap_loader_manifest_is_supported(tmp_path):
    path,manifest,_=derived_fixture(tmp_path)
    manifest.pop('training_video_encoding_verification')
    manifest['official_loader_every_episode_first_last']=True
    save(path,manifest)
    rows=index.scan_server(tmp_path)['rows']
    assert len([r for r in rows if r.get('media_type')])==6


def test_explicit_failed_encoding_does_not_use_legacy_loader_fallback(tmp_path):
    path,manifest,_=derived_fixture(tmp_path)
    manifest['training_video_encoding_verification']['verified']=False
    manifest['official_loader_every_episode_first_last']=True
    save(path,manifest)
    rows=index.scan_server(tmp_path)['rows']
    assert not [r for r in rows if r.get('media_type')]


def learner_fixture(root):
    import h5py
    native_path,original,source_attempt=fixture(root)
    source_collection=source_attempt.parents[2]
    xml=source_collection/'scenes/scene_1/mobile.xml';xml.write_text('<mujoco/>')
    run=root/'runs/vla/learner';attempt=run/'attempts/scene_1/a000'
    result=dict(scene_id='scene_1',split='train',attempt=0,task_completed=False,
                failure_code='vla_action_outside_joint_limits',motion_backend='pi05',
                checkpoint_id='sha256:'+'a'*64)
    save(attempt/'result.json',result)
    scene=json.loads((source_collection/'scenes/scene_1/scene.json').read_text())
    with h5py.File(attempt/'trace.h5','w') as f:
        f.attrs['metadata_json']=json.dumps(dict(scene=scene,scene_id='scene_1',split='train',
            checkpoint_id=result['checkpoint_id'],scene_xml_sha256=index.file_digest(xml)))
    save(run/'rollout_report.json',dict(schema='airport_vla_rollout/1',source_collection=str(source_collection),
        selected_scene_ids=['scene_1'],checkpoint_metadata={'checkpoint_id':result['checkpoint_id']}))
    directory=root/'runs/vla/inspection/learner/scene_1/a000';directory.mkdir(parents=True)
    references=[];trace=attempt/'trace.h5';tracehash=index.file_digest(trace)
    for camera in ('head_left','head_right'):
        path=directory/(camera+'.mp4');path.write_bytes(b'actual learner failed native')
        references.append(dict(trace=str(trace),trace_sha256=tracehash,path=str(path),camera=camera,
                               frames=2,native=True,source_start_frame=0,video_start_frame=0,sha256='a'*64))
    manifest=dict(schema='airport_vla_native_replay/1',status='complete',purpose='inspection_not_training_export',
        learner_run=str(run),source_collection=str(source_collection),source_result=str(attempt/'result.json'),
        source_result_sha256=index.file_digest(attempt/'result.json'),scene_id='scene_1',split='train',attempt='a000',
        source_scene_json_sha256=index.file_digest(source_collection/'scenes/scene_1/scene.json'),trace=str(trace),
        trace_sha256=tracehash,frames=2,fps=20,references=references,task_completed=True)
    path=directory/'manifest.json';save(path,manifest)
    return path,manifest,source_collection


def test_learner_without_scenes_uses_verified_source_category_but_learner_failure(tmp_path):
    learner_fixture(tmp_path)
    rows=index.scan_server(tmp_path)['rows']
    learner=[r for r in rows if 'inspection' in Path(r['server_video']).parts]
    assert len(learner)==2 and {r['outcome'] for r in learner}=={'失败'}
    assert {r['difficulty'] for r in learner}=={'complex'}
    assert {r['front_count'] for r in learner}=={'2'}
    assert all('仅检查' in r['status'] for r in learner)
    assert not [r for r in rows if not r['server_video'] and Path(r['server_directory']).parents[2].name=='learner']


def test_learner_source_xml_change_cannot_supply_scene_category(tmp_path):
    path,manifest,collection=learner_fixture(tmp_path)
    (collection/'scenes/scene_1/mobile.xml').write_text('changed physical source')
    rows=index.scan_server(tmp_path)['rows']
    learner=[r for r in rows if 'inspection' in Path(r['server_video']).parts]
    assert len(learner)==2 and {r['outcome'] for r in learner}=={'未知'}
    assert {r['difficulty'] for r in learner}=={'未知'}


def test_failed_tail_reconstruction_is_disclosed_without_changing_learner_outcome(tmp_path):
    path,manifest,_=learner_fixture(tmp_path)
    manifest['failed_final_interval_replay']=dict(schema='airport_raw1_failed_tail_diagnostic/1',
        executed_substeps=17,maximum_substeps=25,per_frame_qpos_reset=False,
        control_semantics='frozen_servo_reconstruction_terminal_time_grid_verified_no_terminal_ctrl_journal')
    save(path,manifest)
    rows=[r for r in index.scan_server(tmp_path)['rows'] if 'inspection' in Path(r['server_video']).parts]
    assert len(rows)==2 and {r['outcome'] for r in rows}=={'失败'}
    assert all('冻结servo重建（17/25子步；非完整ctrl日志）' in r['status'] for r in rows)
    assert all('仅检查，非训练导出' in r['status'] for r in rows)
