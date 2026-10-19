"""Full-frame source audit and immutable constituent coverage for skill merges."""
import argparse
import copy
import json
from pathlib import Path
from .data import digest
from .data_lineage import audit_source_superset
from .data_skill_merge import (SCHEMA,canonical,eligible,merge_ready_records,record_sha256,
                              coverage_span_identity,coverage_binding_hash,derived_resource_inventory,
                              audit_constituent_qualifications)

AUDIT_SCHEMA='airport_vla_source_coverage_superset/1'


def audit_source_coverage(parent_dataset,child_dataset):
    # Self audits verify every real frame, XML, scene registry, mobile19 layout,
    # actual source SHA and source-quality/episode metadata without claiming IDs match.
    parent=audit_source_superset(parent_dataset,parent_dataset)
    child=audit_source_superset(child_dataset,child_dataset)
    roots=[Path(parent_dataset).resolve(),Path(child_dataset).resolve()]
    datasets=[]; identity_sets=[]; mappings=[]; scenes=[]
    quality=None
    for role,root,report in zip(('parent','child'),roots,(parent,child)):
        details=copy.deepcopy(report['datasets'][0]);details['role']=role
        training=json.loads(Path(details['training_manifest']).read_text())
        source_path=Path(details['source_manifest'])
        records={r['segment_id']:r for r in (json.loads(line) for line in source_path.read_text().splitlines())}
        bound_rows=None
        if role=='child':
            if training.get('source_manifest_schema')!=SCHEMA or training.get('lossless_concat',{}).get('every_decoded_frame_verified') is not True:
                raise ValueError('coverage_requires_verified_skill_derivative')
            if training.get('actual_skill_boundary_action_chunks',{}).get('verified') is not True:
                raise ValueError('coverage_requires_actual_official_action_chunks')
            derived=Path(training['derived_from_training_dataset'])/'airport_training_manifest.json'
            if digest(derived)!=training['derived_from_training_manifest_sha256']:
                raise ValueError('coverage_derived_training_manifest_changed')
            original=json.loads(derived.read_text());original_source=Path(original['source_manifest'])
            if digest(original_source)!=training['derived_from_source_manifest_sha256'] or digest(original_source)!=original['source_manifest_sha256']:
                raise ValueError('coverage_derived_source_manifest_changed')
            bound_rows={r['segment_id']:r for r in (json.loads(line) for line in original_source.read_text().splitlines())}
            quality=audit_constituent_qualifications(source_path,original_source)
            if not quality['all_scenes_initialize'] or not quality['all_source_lifts_qualified']:
                raise ValueError('coverage_missing_initialize_or_lift_constituents')
        identities=[]
        for episode in training['episodes']:
            row=records[episode['segment_id']]
            constituents=[row] if role=='parent' else row['constituent_phase_spans']
            if role=='child':
                if (episode.get('constituent_phase_spans')!=constituents
                        or episode.get('constituent_record_sha256')!=row['constituent_record_sha256']
                        or row['constituent_record_sha256']!=[record_sha256(s) for s in constituents]
                        or len(merge_ready_records(constituents))!=1
                        or constituents[0]['start_frame']!=row['start_frame']
                        or constituents[-1]['end_frame']!=row['end_frame']):
                    raise ValueError('coverage_constituent_partition_changed')
            for span in constituents:
                if not eligible(span):raise ValueError('coverage_ineligible_original_span')
                if role=='child' and canonical(span)!=canonical(bound_rows.get(span['segment_id'])):
                    raise ValueError('coverage_original_constituent_record_changed')
                identity=coverage_span_identity(span,episode['base_qpos_indices'],details['scenes'][span['scene_id']])
                identities.append(identity)
                if role=='child':mappings.append(dict(identity=identity,merged_segment_id=episode['segment_id'],merged_episode_index=episode['episode_index']))
        if len(identities)!=len(set(identities)):raise ValueError('coverage_duplicate_source_constituent')
        identity_sets.append(set(identities));scenes.append(details['scenes'])
        details['constituent_segments']=len(identities)
        inventory=derived_resource_inventory(root)
        details.update(derived_resource_inventory=inventory,derived_resource_inventory_sha256=record_sha256(inventory))
        datasets.append(details)
    if not identity_sets[0].issubset(identity_sets[1]):raise ValueError('coverage_parent_source_span_missing_or_changed')
    if any(scenes[1].get(sid)!=value for sid,value in scenes[0].items()):raise ValueError('coverage_parent_scene_source_changed')
    result=dict(schema=AUDIT_SCHEMA,verified=True,source_frame_values_verified=True,source_scene_xml_verified=True,
        constituent_phase_coverage_verified=True,source='simulation/program_generated',datasets=datasets,
        coverage_identity_sha256=coverage_binding_hash(identity_sets[0],mappings),
        verified_parent_segments=len(identity_sets[0]),verified_child_constituents=len(identity_sets[1]),
        added_constituents=len(identity_sets[1]-identity_sets[0]),
        comparison='all_real_parquet_frames_and_exact_immutable_constituent_source_coverage')
    result['constituent_quality_audit']=quality
    for role,report in (('parent',parent),('child',child)):
        result[role+'_training_manifest_sha256']=report['parent_training_manifest_sha256']
        result[role+'_source_manifest_sha256']=report['parent_source_manifest_sha256']
    return result


def main():
    p=argparse.ArgumentParser();p.add_argument('--parent-dataset',required=True);p.add_argument('--child-dataset',required=True);p.add_argument('--output',required=True)
    args=p.parse_args();output=Path(args.output)
    if output.exists():raise ValueError('refuse_existing_coverage_audit')
    report=audit_source_coverage(args.parent_dataset,args.child_dataset)
    output.write_text(json.dumps(report,indent=2,allow_nan=False))
    print(json.dumps({k:v for k,v in report.items() if k!='datasets'}))


if __name__=='__main__':main()
