"""Import qualification fixtures are not physical episodes or trainable media."""
import json
from pathlib import Path
import pytest
from r1pro_teleop.vla import completed_dataset_import as module
from r1pro_teleop.vla.training_cache import file_sha
from r1pro_teleop.vla.three_table_recovery import training_resource_admission


def put(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(value if isinstance(value,str) else json.dumps(value));return path


@pytest.fixture
def bundle(tmp_path,monkeypatch):
    old=tmp_path/'old/data_batch';run=tmp_path/'new_training';run.mkdir()
    records=[];selection={'successful_splits':{},'frozen_file_sha256':{}};archive=[]
    for split in ('train','val','test'):
        case=tmp_path/'physical_fixture'/split;sid=split+'_scene'
        result=put(case/'result.json',dict(task_completed=True,physics_success=True,training_eligible=True,scene_id=sid,split=split))
        source=dict(split=split,scene_id=sid,parent_scene_id=split+'_parent')
        for key,filename in (('trace','trace.fixture'),('events','events.fixture'),('scene_xml','scene.xml'),('scene_json','scene.json'),('result','result.json')):
            path=result if key=='result' else put(case/filename,'fixture_only_not_physical_evidence')
            source[key]=str(path);source[key+'_sha256']=file_sha(path)
        plan={'source':source,'segments':[dict(language_prompt=p) for p in module.PROMPTS]}
        records.append(dict(source=source,plan=plan,native_videos=[dict(camera=c) for c in ('head_left','head_right','left_wrist','right_wrist')]))
        selection['successful_splits'][split]=[str(case)]
        root=old/'datasets'/split;info=dict(chunks_size=1000,data_path='data/episode_{episode_index:06d}.parquet',video_path='videos/{video_key}/episode_{episode_index:06d}.mp4')
        put(root/'meta/info.json',info);episodes=[]
        for i,(label,prompt) in enumerate(zip(module.LABELS,module.PROMPTS)):
            episode=dict(split=split,episode_index=i,task_index=i,scene_id=sid,action_label=label,language_prompt=prompt,training_eligible=True,frames=10,source_trace_sha256=source['trace_sha256'],source_start_frame=i*10,source_end_frame=(i+1)*10)
            files=[]
            data=put(root/info['data_path'].format(episode_index=i),'fixture_parquet')
            files.append(dict(source=str(data),sha256=file_sha(data)))
            for cam in ('head_left','left_wrist','right_wrist'):
                path=put(root/info['video_path'].format(episode_index=i,video_key='observation.images.'+cam),'fixture_rgb')
                files.append(dict(source=str(path),sha256=file_sha(path)))
            episodes.append(episode);archive.append(dict(episode,files=files))
        src_manifest=put(root/'whole_action_source_manifest.jsonl','fixture_source')
        put(root/'airport_training_manifest.json',dict(episodes=episodes,source_manifest=str(src_manifest)))
    put(old/'pipeline_status.json',dict(stage='data_only_exports_verified_no_training',dataset_ready=True,training_started=False))
    put(old/'source_records.jsonl',''.join(json.dumps(r)+'\n' for r in records))
    frozen=put(old/'frozen_source_selection.json',selection)
    put(old/'verified_media_selection.json',dict(schema='airport_verified_three_table_media_selection/1',records=records,verified_split_counts={s:1 for s in ('train','val','test')},verified_source_count=3,physical_source_selection_sha256=file_sha(frozen),missing_splits=[],failed_excluded_media_cases=[]))
    archive_path=put(old.parent/'by_action/manifest.json',dict(dataset_ready=True,rows=archive))
    old_options=put(old.parent/'data_options.json',dict(run_dir=str(old),data_only=True))
    exited=put(old.parent/'owned/exit.json',dict(actual_exit_observed=True,returncode=0,argv=['python','supervise_three_table_single_tray_training.py','--options',str(old_options)]))
    options=dict(completed_dataset_run=str(old),completed_dataset_exit_receipt=str(exited),completed_dataset_exit_receipt_sha256=file_sha(exited),completed_dataset_expected_counts={s:1 for s in ('train','val','test')})
    monkeypatch.setattr(module,'source_validate',lambda x:None)
    monkeypatch.setattr(module,'bc_input_contract',lambda x:None)
    monkeypatch.setattr(module,'dataset_proof',lambda *a,**k:{'verified':True})
    return old,run,options,records,archive_path


def test_import_is_byte_bound_read_only_and_reuses_existing_datasets(bundle):
    old,run,options,records,_=bundle;before={str(p):file_sha(p) for p in old.rglob('*') if p.is_file()}
    try:result=module.import_completed_dataset(options,run)
    except OSError as error:
        if getattr(error,'winerror',None)==1314:pytest.skip('Linux deployment must verify real symlink; Windows process lacks symlink privilege')
        raise
    assert result['proof']['verified_source_counts']=={s:1 for s in ('train','val','test')}
    assert len(result['proof']['training_data_file_sha256'])==36
    assert result['proof']['original_native_ffprobe_repeated'] is False
    assert result['proof']['old_exit_not_copied_as_new_exit'] is True
    assert (run/'datasets').is_symlink() and (run/'datasets').resolve()==old/'datasets'
    assert before=={str(p):file_sha(p) for p in old.rglob('*') if p.is_file()}
    assert module.import_completed_dataset(options,run)['proof']==result['proof']


def test_changed_rgb_bytes_cannot_enter_train_cache(bundle):
    old,run,options,_,_=bundle
    next((old/'datasets/train/videos').rglob('*.mp4')).write_text('different_pixels')
    with pytest.raises(ValueError,match='training_data_bytes_changed'):
        module.import_completed_dataset(options,run)
    assert not (run/'datasets').exists()


def test_wrong_or_unobserved_data_exit_cannot_import(bundle):
    _,run,options,_,_=bundle;p=Path(options['completed_dataset_exit_receipt'])
    d=json.loads(p.read_text());d['actual_exit_observed']=False;put(p,d);options['completed_dataset_exit_receipt_sha256']=file_sha(p)
    with pytest.raises(ValueError,match='successful_data_supervisor_exit'):
        module.import_completed_dataset(options,run)


def test_cross_split_parent_or_duplicate_action_rejected(bundle):
    old,run,options,records,archive=bundle
    records[1]['source']['parent_scene_id']=records[0]['source']['parent_scene_id']
    # Shared plan/source reference follows the same fixture mutation.
    put(old/'source_records.jsonl',''.join(json.dumps(r)+'\n' for r in records));m=json.loads((old/'verified_media_selection.json').read_text());m['records']=records;put(old/'verified_media_selection.json',m)
    with pytest.raises(ValueError,match='parent_split_leakage'):
        module.import_completed_dataset(options,run)


def test_resource_threshold_is_explicit_bound_and_recovery_immutable(tmp_path):
    evidence=put(tmp_path/'actual_train_exit.json',{'actual_peak_mib':54632})
    options=dict(minimum_training_free_mib=58000,training_resource_admission_evidence=dict(path=str(evidence),sha256=file_sha(evidence),prior_peak_mib=54632))
    proof=training_resource_admission(options,tmp_path)
    assert proof['minimum_training_free_mib']==58000 and proof['batch_and_acceleration_strategy_unchanged']
    assert training_resource_admission(options,tmp_path)==proof
    options['minimum_training_free_mib']=57000
    with pytest.raises(ValueError,match='immutable_training_resource_admission'):
        training_resource_admission(options,tmp_path)
    with pytest.raises(ValueError,match='requires_recorded_evidence'):
        training_resource_admission({'minimum_training_free_mib':58000},tmp_path)
