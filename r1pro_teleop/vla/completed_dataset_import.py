"""Import a closed official dataset without replaying or rewriting its media."""
import json,shutil
from collections import Counter,defaultdict
from pathlib import Path
from .training_cache import file_sha
from .training_pipeline import write_atomic
from .three_table_recovery import dataset_proof
from .data_three_table_single_tray import PROFILE,source_validate,bc_input_contract

PROMPTS=('Pick up the tray','Place the tray','Flush tray to the left')
LABELS=('pick_empty','place_empty','push_loaded')

def import_completed_dataset(options,run,*,on_progress=None):
    old=Path(options['completed_dataset_run']).resolve();run=Path(run).resolve()
    if old==run:raise ValueError('completed_dataset_import_requires_new_training_run')
    exit_path=Path(options['completed_dataset_exit_receipt']).resolve()
    if exit_path.is_relative_to(old):raise ValueError('actual_data_supervisor_exit_must_be_outside_data_run')
    if file_sha(exit_path)!=options['completed_dataset_exit_receipt_sha256']:raise ValueError('completed_data_exit_changed')
    exited=json.loads(exit_path.read_text());argv=exited.get('argv',[])
    actual=exited.get('actual_exit_observed') is True or exited.get('trainer_exited') is True
    if exited.get('returncode')!=0 or not actual or '--options' not in argv or not any(Path(v).name=='supervise_three_table_single_tray_training.py' for v in argv):
        raise ValueError('actual_successful_data_supervisor_exit_required')
    old_options_path=Path(argv[argv.index('--options')+1]);old_options=json.loads(old_options_path.read_text())
    if Path(old_options['run_dir']).resolve()!=old or old_options.get('data_only') is not True:raise ValueError('closed_data_supervisor_run_identity_changed')
    old_status_path=old/'pipeline_status.json';old_status=json.loads(old_status_path.read_text())
    if old_status.get('stage')!='data_only_exports_verified_no_training' or old_status.get('dataset_ready') is not True or old_status.get('training_started') is not False:
        raise ValueError('closed_verified_data_only_pipeline_required')
    paths=[old_status_path,old_options_path,exit_path,old/'source_records.jsonl',old/'frozen_source_selection.json',old/'verified_media_selection.json']
    selection=json.loads(paths[-2].read_text());media=json.loads(paths[-1].read_text())
    records=[json.loads(line) for line in (old/'source_records.jsonl').read_text().splitlines() if line.strip()]
    if not records or media.get('schema')!='airport_verified_three_table_media_selection/1' or media.get('missing_splits') or media.get('failed_excluded_media_cases') or media.get('records')!=records or media.get('physical_source_selection_sha256')!=file_sha(old/'frozen_source_selection.json'):
        raise ValueError('completed_verified_media_selection_changed')
    scenes=set();parents={};counts=Counter();source_bindings={}
    for record in records:
        source,plan=record['source'],record['plan'];source_validate(source);bc_input_contract(plan)
        split=source['split'];sid=source['scene_id']
        if sid in scenes or split not in ('train','val','test') or plan['source']!=source:raise ValueError('completed_source_identity_or_split_changed')
        scenes.add(sid);counts[split]+=1
        prior=parents.setdefault(source['parent_scene_id'],split)
        if prior!=split:raise ValueError('completed_parent_split_leakage')
        result=json.loads(Path(source['result']).read_text())
        if any(result.get(k) is not True for k in ('task_completed','physics_success','training_eligible')):raise ValueError('completed_source_not_physically_qualified')
        if result.get('scene_id')!=sid or result.get('split')!=split or [r['language_prompt'] for r in plan['segments']]!=list(PROMPTS):raise ValueError('completed_source_prompt_identity_changed')
        views=record.get('native_videos',[])
        if len(views)!=4 or {v['camera'] for v in views}!={'head_left','head_right','left_wrist','right_wrist'}:raise ValueError('completed_native_four_views_required')
        for key in ('trace','events','scene_xml','scene_json','result'):
            p=source[key];digest=source[key+'_sha256']
            if file_sha(p)!=digest:raise ValueError('completed_source_bytes_changed:'+key)
            source_bindings[str(Path(p).resolve())]=digest
    if set(counts)!= {'train','val','test'} or dict(counts)!=media.get('verified_split_counts') or media.get('verified_source_count')!=len(records):raise ValueError('completed_split_counts_changed')
    expected=options.get('completed_dataset_expected_counts')
    if expected is not None and expected!=dict(counts):raise ValueError('completed_expected_counts_changed')
    for split in counts:
        selected={str(Path(case).resolve()) for case in selection['successful_splits'][split]}
        actual={str(Path(r['source']['result']).parent.resolve()) for r in records if r['source']['split']==split}
        if selected!=actual:raise ValueError('completed_frozen_source_selection_changed')
    for path,digest in selection.get('frozen_file_sha256',{}).items():
        if file_sha(path)!=digest:raise ValueError('completed_frozen_source_bytes_changed')
        source_bindings[str(Path(path).resolve())]=digest
    archive_path=Path(options.get('completed_dataset_archive',old.parent/'by_action/manifest.json')).resolve()
    archive=json.loads(archive_path.read_text());paths.append(archive_path)
    if archive.get('dataset_ready') is not True:raise ValueError('completed_data_byte_hash_archive_required')
    archive_hashes={};archive_rows={}
    for row in archive['rows']:
        key=(row['split'],row['episode_index'])
        if key in archive_rows:raise ValueError('duplicate_completed_archive_episode')
        archive_rows[key]=row
        for f in row['files']:
            origin=str(Path(f['source']).resolve());digest=f['sha256']
            if origin in archive_hashes and archive_hashes[origin]!=digest:raise ValueError('conflicting_completed_file_hashes')
            archive_hashes[origin]=digest
    required_files=set();datasets={};episodes=Counter();data_hashes={}
    for split in ('train','val','test'):
        directory=old/'datasets'/split;manifest_path=directory/'airport_training_manifest.json'
        manifest=json.loads(manifest_path.read_text());paths.extend([manifest_path,Path(manifest['source_manifest']),directory/'meta/info.json'])
        datasets[split]=dataset_proof(directory,split,records,repo_id='airport/three_table_single_tray_action3_'+split+'_v1')
        info=json.loads((directory/'meta/info.json').read_text());groups=defaultdict(set)
        for ep in manifest['episodes']:
            index=ep['episode_index'];task=ep['task_index'];key=(split,index)
            if type(task) is not int or task not in (0,1,2) or ep['language_prompt']!=PROMPTS[task] or ep['action_label']!=LABELS[task] or ep.get('training_eligible') is not True:raise ValueError('completed_exact_action_vocabulary_required')
            if task in groups[ep['scene_id']]:raise ValueError('duplicate_completed_source_action')
            groups[ep['scene_id']].add(task);episodes[split]+=1
            ar=archive_rows.get(key)
            if ar is None or any(ar.get(k)!=ep.get(k) for k in ('scene_id','source_trace_sha256','language_prompt','frames','source_start_frame','source_end_frame')):raise ValueError('completed_archive_source_window_changed')
            chunk=index//info.get('chunks_size',1000)
            files=[directory/info['data_path'].format(episode_chunk=chunk,episode_index=index)]
            files.extend(directory/info['video_path'].format(episode_chunk=chunk,episode_index=index,video_key='observation.images.'+cam) for cam in ('head_left','left_wrist','right_wrist'))
            for path in files:
                resolved=str(path.resolve());digest=archive_hashes.get(resolved)
                if digest is None or file_sha(path)!=digest:raise ValueError('completed_training_data_bytes_changed:'+str(path))
                required_files.add(resolved);data_hashes[resolved]=digest
            if on_progress:on_progress(dict(split=split,verified_episodes=episodes[split],total_episodes=len(manifest['episodes']),verified_training_data_files=len(required_files)))
        if len(groups)!=counts[split] or any(tasks!={0,1,2} for tasks in groups.values()) or episodes[split]!=3*counts[split]:raise ValueError('completed_three_whole_actions_per_source_required')
    if len(archive_rows)!=sum(episodes.values()):raise ValueError('completed_archive_episode_count_changed')
    metadata_bindings={str(p.resolve()):file_sha(p) for p in paths}
    proof=dict(schema='airport_completed_three_action_dataset_import/1',verified=True,
        completed_dataset_run=str(old),original_data_exit=str(exit_path),metadata_sha256=metadata_bindings,
        source_file_sha256=source_bindings,training_data_file_sha256=data_hashes,
        verified_source_counts=dict(counts),verified_action_segment_counts=dict(episodes),datasets=datasets,
        original_media_replayed=False,original_native_ffprobe_repeated=False,
        original_data_run_modified=False,old_exit_not_copied_as_new_exit=True,
        optimizer_policy='verified_parent_weights_only_new_optimizer',training_started=False)
    target=run/'completed_dataset_import.json'
    if target.exists() and json.loads(target.read_text())!=proof:raise ValueError('immutable_completed_dataset_import_changed')
    if not target.exists():write_atomic(target,proof)
    link=run/'datasets'
    if link.exists() or link.is_symlink():
        if not link.is_symlink() or link.resolve()!=(old/'datasets').resolve():raise ValueError('new_training_dataset_link_changed')
    else:link.symlink_to(old/'datasets',target_is_directory=True)
    for name in ('source_records.jsonl','frozen_source_selection.json','verified_media_selection.json'):
        dst=run/name
        if dst.exists():
            if file_sha(dst)!=file_sha(old/name):raise ValueError('new_training_frozen_copy_changed:'+name)
        else:shutil.copy2(old/name,dst)
    return dict(proof=proof,records=records,selection=selection)
