import copy
import json
from pathlib import Path
import pytest
from test_vla_data_skill_merge import row
from r1pro_teleop.vla.data import digest
from r1pro_teleop.vla.data_skill_merge import (merge_ready_records,record_sha256,derived_resource_inventory,
                                              coverage_span_identity,coverage_binding_hash)
from r1pro_teleop.vla import data_skill_coverage as coverage


def make_fixture(tmp_path,monkeypatch):
    parent=tmp_path/'parent';child=tmp_path/'child'
    parent.mkdir();child.mkdir()
    spans=[row(0,38,'initial_tuck',skill='initialize_posture',operation_index=None,
               initial_posture_qualification=dict(qualification='initial_tuck_after_physical_settle',
                                                  settle_end_frame=0,first_operation_frame=38)),
           row(38,58),row(58,78,'lift')];merged=merge_ready_records(spans)
    source=parent/'source.jsonl';source.write_text(''.join(json.dumps(s)+'\n' for s in spans))
    target=child/'source.jsonl';target.write_text(''.join(json.dumps(s)+'\n' for s in merged))
    def episodes(rows):
        return [dict(segment_id=r['segment_id'],episode_index=i,base_qpos_indices=[0,1,2],
                     constituent_phase_spans=r.get('constituent_phase_spans'),
                     constituent_record_sha256=r.get('constituent_record_sha256')) for i,r in enumerate(rows)]
    pm=dict(repo_id='p',source_manifest=str(source),source_manifest_sha256=digest(source),episodes=episodes(spans))
    (parent/'airport_training_manifest.json').write_text(json.dumps(pm))
    cm=dict(repo_id='c',source_manifest=str(target),source_manifest_sha256=digest(target),episodes=episodes(merged),
        source_manifest_schema=coverage.SCHEMA,lossless_concat={'every_decoded_frame_verified':True},
        actual_skill_boundary_action_chunks={'verified':True},derived_from_training_dataset=str(parent),
        derived_from_training_manifest_sha256=digest(parent/'airport_training_manifest.json'),
        derived_from_source_manifest_sha256=digest(source))
    (child/'airport_training_manifest.json').write_text(json.dumps(cm))
    scene=dict(trace='/trace.h5',trace_sha256='a'*64,scene_xml_sha256='e'*64,
               scene_json_sha256='f'*64,collection_fingerprint='b'*64)
    def audited(dataset,_):
        root=Path(dataset);m=json.loads((root/'airport_training_manifest.json').read_text())
        return dict(parent_training_manifest_sha256=digest(root/'airport_training_manifest.json'),
            parent_source_manifest_sha256=digest(m['source_manifest']),datasets=[dict(role='parent',
                dataset=str(root),repo_id=m['repo_id'],training_manifest=str(root/'airport_training_manifest.json'),
                source_manifest=m['source_manifest'],episodes=len(m['episodes']),frames=78,scene_count=1,
                scenes={'scene':scene},segment_identity_sha256='x')])
    monkeypatch.setattr(coverage,'audit_source_superset',audited)
    return parent,child,spans,merged,scene


def test_constituent_coverage_does_not_claim_merged_id_identity(tmp_path,monkeypatch):
    p,c,spans,merged,scene=make_fixture(tmp_path,monkeypatch)
    report=coverage.audit_source_coverage(p,c)
    assert report['verified'] and report['constituent_phase_coverage_verified']
    assert report['verified_parent_segments']==report['verified_child_constituents']==3
    assert report['datasets'][1]['episodes']==2
    identities=[coverage_span_identity(s,[0,1,2],scene) for s in spans]
    mappings=[dict(identity=coverage_span_identity(s,[0,1,2],scene),merged_segment_id=r['segment_id'],merged_episode_index=j)
              for j,r in enumerate(merged) for s in r['constituent_phase_spans']]
    assert report['coverage_identity_sha256']==coverage_binding_hash(identities,mappings)


def test_media_relocation_does_not_change_source_semantic_identity():
    s=row(0,20); changed=copy.deepcopy(s)
    changed['videos']['head_left']['path']='/new/native.mp4'
    scene=dict(trace_sha256='a'*64,scene_xml_sha256='e'*64,scene_json_sha256='f'*64)
    assert coverage_span_identity(s,[0,1,2],scene)==coverage_span_identity(changed,[0,1,2],scene)
    changed['strict_deviations']={'count':1}
    assert coverage_span_identity(s,[0,1,2],scene)!=coverage_span_identity(changed,[0,1,2],scene)


def test_changed_complete_child_record_cannot_fake_source_coverage(tmp_path,monkeypatch):
    p,c,spans,merged,scene=make_fixture(tmp_path,monkeypatch)
    merged[0]['constituent_phase_spans'][0]['source_phase']='forged'
    merged[0]['constituent_record_sha256']=[record_sha256(s) for s in merged[0]['constituent_phase_spans']]
    (c/'source.jsonl').write_text(''.join(json.dumps(s)+'\n' for s in merged))
    m=json.loads((c/'airport_training_manifest.json').read_text())
    m['episodes'][0]['constituent_phase_spans']=merged[0]['constituent_phase_spans']
    m['episodes'][0]['constituent_record_sha256']=merged[0]['constituent_record_sha256']
    (c/'airport_training_manifest.json').write_text(json.dumps(m))
    with pytest.raises(ValueError,match='original_constituent_record_changed'):
        coverage.audit_source_coverage(p,c)


def test_derived_inventory_binds_bytes_and_extra_files(tmp_path):
    (tmp_path/'data').mkdir();p=tmp_path/'data/episode.parquet';p.write_bytes(b'original')
    before=record_sha256(derived_resource_inventory(tmp_path))
    p.write_bytes(b'modified')
    assert record_sha256(derived_resource_inventory(tmp_path))!=before
    current=record_sha256(derived_resource_inventory(tmp_path))
    (tmp_path/'data/extra.parquet').write_bytes(b'added')
    assert record_sha256(derived_resource_inventory(tmp_path))!=current
