"""Read-only source and frame verification for additive BC warm starts."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
from .data import base_qpos_projection
from ..airport_fsm.contracts import fingerprint

SCHEMA = 'airport_vla_source_superset/1'
QUALITY_KEYS = ('quality_class', 'source_needs_review', 'verified_lift_takeoff',
                'initial_posture_qualification', 'local_qualification', 'episode_strict_success',
                'acceptance_profile', 'strict_deviations', 'approximate_deviation_counts')


def _digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024*1024), b''): h.update(block)
    return h.hexdigest()


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def audit_source_superset(parent_dataset, child_dataset):
    """Check every actual Parquet state/action against unchanged source frames.

    No norm statistics or videos are rewritten. Official loader/encoding checks
    remain independently required; this audit binds their completed manifests.
    XML joint addresses are compiled, so world base_state cannot impersonate
    measured base origin offsets. Episode index/order may change in a superset.
    """
    import h5py
    import pyarrow.parquet as pq
    roots = [Path(parent_dataset).resolve(), Path(child_dataset).resolve()]
    report = {'schema': SCHEMA, 'verified': False, 'source_frame_values_verified': False,
              'source_scene_xml_verified': False, 'source': 'simulation/program_generated',
              'normalization_policy': 'preserve_verified_parent_train_stats',
              'comparison': 'every_episode_every_parquet_frame_against_original_h5',
              'datasets': []}
    checksums, projections, registered_scenes = {}, {}, {}
    identity_sets, scene_sets = [], []
    def digest(path):
        key = str(Path(path).resolve())
        if key not in checksums: checksums[key] = _digest(key)
        return checksums[key]
    for role, root in zip(('parent', 'child'), roots):
        manifest_path = root/'airport_training_manifest.json'
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        info = json.loads((root/'meta/info.json').read_text(encoding='utf-8'))
        if (manifest.get('split') != 'train' or manifest.get('normalization_split') != 'train_only'
                or manifest.get('environment_source') != 'simulation'
                or manifest.get('controller_source') != 'program_generated'
                or manifest.get('human_demonstration') is not False
                or manifest.get('official_loader_every_episode_first_last') is not True
                or manifest.get('training_video_encoding_verification', {}).get('verified') is not True
                or manifest.get('fps') != 20 or manifest.get('action_semantics') != 'absolute_mobile19'
                or manifest.get('state_semantics') != 'measured_joint16_plus_base_origin_offset3'
                or info.get('fps') != 20 or not manifest.get('episodes')):
            raise ValueError('source_superset_requires_completed_simulation_train_dataset')
        source_path = Path(manifest['source_manifest'])
        if digest(source_path) != manifest['source_manifest_sha256']:
            raise ValueError('source_superset_source_manifest_hash_changed')
        report[role+'_training_manifest_sha256'] = digest(manifest_path)
        report[role+'_source_manifest_sha256'] = digest(source_path)
        rows = {}
        for line in source_path.read_text(encoding='utf-8').splitlines():
            row = json.loads(line)
            if row['segment_id'] in rows: raise ValueError('source_superset_duplicate_source_segment')
            rows[row['segment_id']] = row
        tasks = {row['task_index']: row['task'] for row in
                 (json.loads(line) for line in (root/'meta/tasks.jsonl').read_text().splitlines())}
        identities, scenes, frame_count = set(), {}, 0
        indices = []
        for episode in manifest['episodes']:
            row = rows[episode['segment_id']]
            if row['split'] != 'train' or episode['split'] != 'train' or row.get('training_ready') is not True:
                raise ValueError('source_superset_non_training_episode')
            trace = Path(episode['source_trace']).resolve()
            if str(trace) != str(Path(row['trace']).resolve()) or digest(trace) != episode['source_trace_sha256'] or digest(trace) != row['trace_sha256']:
                raise ValueError('source_superset_trace_identity_changed')
            a, b = episode['source_start_frame'], episode['source_end_frame']
            if type(a) is not int or type(b) is not int or not 0 <= a < b or episode['frames'] != b-a or (a,b) != (row['start_frame'],row['end_frame']):
                raise ValueError('source_superset_interval_changed')
            for key in ('skill','phase','operation_index','language_prompt'):
                if key not in episode or episode[key] != row[key]:
                    raise ValueError('source_superset_segment_semantics_changed:'+key)
            if (episode.get('fps') != 20 or episode.get('action_semantics') != manifest['action_semantics']
                    or episode.get('state_semantics') != manifest['state_semantics']):
                raise ValueError('source_superset_mobile19_semantics_changed')
            for key in QUALITY_KEYS:
                if episode.get(key) != row.get(key):
                    raise ValueError('source_superset_quality_changed:'+key)
            xml = Path(row['collection'])/'scenes'/row['scene_id']/'mobile.xml'
            scene_json = xml.with_name('scene.json')
            scene = json.loads(scene_json.read_text())
            collection = json.loads((Path(row['collection'])/'collection.json').read_text())
            index_path = Path(row['collection'])/'scenes/index.json'
            if str(index_path) not in registered_scenes:
                registered_scenes[str(index_path)]={s['scene_id']:s for s in json.loads(index_path.read_text())}
            registered = registered_scenes[str(index_path)][row['scene_id']]
            if (collection['fingerprint'] != row['collection_fingerprint']
                    or registered['source_json_sha256'] != row['scene_source_sha256']
                    or registered['split'] != 'train' or scene['split'] != 'train'):
                raise ValueError('source_superset_collection_or_scene_identity_changed')
            columns = base_qpos_projection(row, cache=projections)
            if episode['base_qpos_indices'] != columns:
                raise ValueError('source_superset_base_joint_order_changed')
            with h5py.File(trace,'r') as f:
                meta = json.loads(f.attrs['metadata_json'])
                if (digest(xml) != meta['scene_xml_sha256'] or meta['scene_id'] != row['scene_id']
                        or meta['split'] != 'train' or fingerprint(meta['scene']) != fingerprint(scene)):
                    raise ValueError('source_superset_scene_xml_identity_changed')
                if b > len(f['state']) or not np.all(f['transition_completed'][a:b]):
                    raise ValueError('source_superset_incomplete_source_intervals')
                state = np.concatenate((f['state'][a:b],f['qpos'][a:b][:,columns]),axis=1).astype(np.float32)
                action = np.concatenate((f['action'][a:b],f['base_action'][a:b]),axis=1).astype(np.float32)
            index = episode['episode_index'];indices.append(index)
            chunk = index//info.get('chunks_size',1000)
            parquet = root/info['data_path'].format(episode_chunk=chunk,episode_index=index)
            table = pq.read_table(parquet,columns=['observation.state','action','timestamp','task_index','episode_index','frame_index'])
            actual_state = np.asarray(table['observation.state'].to_pylist(),dtype=np.float32)
            actual_action = np.asarray(table['action'].to_pylist(),dtype=np.float32)
            if (state.shape != (b-a,19) or action.shape != (b-a,19) or not np.isfinite(state).all()
                    or not np.isfinite(action).all() or not np.array_equal(state,actual_state)
                    or not np.array_equal(action,actual_action)):
                raise ValueError('source_superset_actual_frame_values_changed')
            if (not np.allclose(table['timestamp'].to_numpy(),np.arange(b-a)/20,rtol=0,atol=1e-5)
                    or not np.array_equal(table['frame_index'].to_numpy(),np.arange(b-a))
                    or not np.all(table['episode_index'].to_numpy()==index)
                    or any(tasks[t]!=episode['language_prompt'] for t in table['task_index'].to_pylist())):
                raise ValueError('source_superset_actual_time_or_language_changed')
            identity = _canonical(dict(scene_id=row['scene_id'],source_trace_sha256=digest(trace),
                source_scene_xml_sha256=digest(xml),source_segment_id=row['source_segment_id'],
                source_scene_json_sha256=digest(scene_json),collection_fingerprint=row['collection_fingerprint'],
                source_interval=[a,b],skill=row['skill'],phase=row['phase'],operation_index=row['operation_index'],
                language_prompt=row['language_prompt'],base_qpos_indices=columns,
                fps=20,state_semantics=episode['state_semantics'],action_semantics=episode['action_semantics'],
                quality={key:row.get(key) for key in QUALITY_KEYS}))
            if identity in identities: raise ValueError('source_superset_duplicate_training_identity')
            identities.add(identity);frame_count += b-a
            source_identity = dict(trace=str(trace),trace_sha256=digest(trace),scene_xml=str(xml),
                                   scene_xml_sha256=digest(xml),scene_json_sha256=digest(scene_json),
                                   collection_fingerprint=row['collection_fingerprint'])
            if row['scene_id'] in scenes and scenes[row['scene_id']] != source_identity:
                raise ValueError('source_superset_multiple_sources_for_scene')
            scenes[row['scene_id']] = source_identity
        if sorted(indices)!=list(range(len(indices))) or frame_count != info['total_frames'] or info['total_episodes'] != len(indices):
            raise ValueError('source_superset_dataset_counts_changed')
        identity_sets.append(identities);scene_sets.append(scenes)
        report['datasets'].append(dict(role=role,dataset=str(root),repo_id=manifest['repo_id'],
            training_manifest=str(manifest_path),source_manifest=str(source_path),episodes=len(identities),
            frames=frame_count,scene_count=len(scenes),scenes=scenes,
            segment_identity_sha256=hashlib.sha256('\n'.join(sorted(identities)).encode()).hexdigest()))
    if not identity_sets[0].issubset(identity_sets[1]):
        raise ValueError('source_superset_parent_segments_missing_or_changed')
    if any(scene_sets[1].get(sid)!=identity for sid,identity in scene_sets[0].items()):
        raise ValueError('source_superset_parent_scene_source_changed')
    report.update(verified=True,source_frame_values_verified=True,source_scene_xml_verified=True,
                  verified_parent_segments=len(identity_sets[0]),verified_child_segments=len(identity_sets[1]),
                  added_segments=len(identity_sets[1]-identity_sets[0]),
                  added_scene_ids=sorted(set(scene_sets[1])-set(scene_sets[0])))
    return report


def main(argv=None):
    p=argparse.ArgumentParser();p.add_argument('--parent-dataset',required=True);p.add_argument('--child-dataset',required=True);p.add_argument('--output',required=True)
    args=p.parse_args(argv)
    report=audit_source_superset(args.parent_dataset,args.child_dataset)
    output=Path(args.output)
    if output.exists():raise ValueError('source_superset_audit_output_already_exists')
    output.write_text(json.dumps(report,indent=2,allow_nan=False),encoding='utf-8')
    print(json.dumps({key:value for key,value in report.items() if key!='datasets'}))


if __name__=='__main__':main()
