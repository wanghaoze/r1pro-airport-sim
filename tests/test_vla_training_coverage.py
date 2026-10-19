import copy,json,hashlib
from pathlib import Path
import pytest
from test_vla_training_warmstart import fixture as legacy_fixture
from r1pro_teleop.vla.training import verified_bc_warmstart
from r1pro_teleop.vla.data_skill_merge import record_sha256,coverage_span_identity,coverage_binding_hash,derived_resource_inventory


def fixture(tmp_path):
 spec,manifest,norm=legacy_fixture(tmp_path)
 parent_status=json.loads(Path(spec.bc_warmstart_parent_status).read_text());parent_root=Path(parent_status['spec']['dataset_root'])
 parent_manifest=parent_root/'airport_training_manifest.json';parent=json.loads(parent_manifest.read_text())
 row=parent['episodes'][0];row['episode_index']=0;row['language_prompt']='将双臂收拢。'
 source_path=Path(parent['source_manifest'])
 span=dict(schema='airport_vla_segments/1',segment_id='seg1',source_segment_id='original1',scene_id='train4',
   split='train',collection=str(tmp_path/'collection'),collection_fingerprint='verified-source',
   start_frame=40,end_frame=78,frames=38,skill='initialize_posture',phase='initial',operation_index=None,
   language_prompt=row['language_prompt'],training_ready=True,supervision_eligible=True,quality_class='complete_task',
   environment_source='simulation',controller_source='program_generated',human_demonstration=False,
   source_needs_review=False,action_layout='mobile19',videos={k:dict(exists=True,verified=True,path='parent/'+k) for k in ('head_left','head_right','left_wrist','right_wrist')})
 source_path.write_text(json.dumps(span)+'\n');parent['source_manifest_sha256']=hashlib.sha256(source_path.read_bytes()).hexdigest()
 parent_manifest.write_text(json.dumps(parent))
 child=json.loads((Path(spec.dataset_root)/'airport_training_manifest.json').read_text())
 child_span=copy.deepcopy(span)
 for video in child_span['videos'].values():video['path']=video['path'].replace('parent/','relocated/')
 merged=dict(child_span,schema='airport_vla_skill_contiguous_segments/1',segment_id='merged1',phase='skill_contiguous',
   constituent_phase_spans=[child_span],constituent_record_sha256=[record_sha256(child_span)])
 child_source=tmp_path/'merged.jsonl';child_source.write_text(json.dumps(merged)+'\n')
 child.update(source_manifest=str(child_source),source_manifest_sha256=hashlib.sha256(child_source.read_bytes()).hexdigest())
 child['episodes']=[dict(row,segment_id='merged1',phase='skill_contiguous',constituent_phase_spans=[child_span],constituent_record_sha256=[record_sha256(child_span)])]
 (Path(spec.dataset_root)/'airport_training_manifest.json').write_text(json.dumps(child))
 for root in [parent_root,Path(spec.dataset_root)]:
  for scope,name in [('data','sample.parquet'),('meta','info.json'),('videos','sample.mp4')]:
   path=root/scope/name;path.parent.mkdir();path.write_bytes(b'verified immutable fixture')
 refresh(spec)
 return spec,child,parent_root


def refresh(spec):
 path=Path(spec.bc_warmstart_source_audit);audit=json.loads(path.read_text())
 audit.update(schema='airport_vla_source_coverage_superset/1',constituent_phase_coverage_verified=True)
 parent_ids=[];mappings=[]
 for dataset in audit['datasets']:
  role=dataset['role'];manifest_path=Path(dataset['training_manifest']);m=json.loads(manifest_path.read_text())
  source=Path(m['source_manifest']);dataset['source_manifest']=str(source)
  audit[role+'_training_manifest_sha256']=hashlib.sha256(manifest_path.read_bytes()).hexdigest()
  audit[role+'_source_manifest_sha256']=hashlib.sha256(source.read_bytes()).hexdigest()
  dataset['derived_resource_inventory']=derived_resource_inventory(dataset['dataset'])
  dataset['derived_resource_inventory_sha256']=record_sha256(dataset['derived_resource_inventory'])
  sources={r['segment_id']:r for r in [json.loads(line) for line in source.read_text().splitlines()]}
  for e in m['episodes']:
   spans=e['constituent_phase_spans'] if role=='child' else [sources[e['segment_id']]]
   for span in spans:
    identity=coverage_span_identity(span,e['base_qpos_indices'],dataset['scenes'][e['scene_id']])
    if role=='parent':parent_ids.append(identity)
    else:mappings.append(dict(identity=identity,merged_segment_id=e['segment_id'],merged_episode_index=e['episode_index']))
 audit['coverage_identity_sha256']=coverage_binding_hash(parent_ids,mappings);path.write_text(json.dumps(audit))


def test_nonascii_phase_coverage_allows_relocated_media_but_preserves_source(tmp_path):
 spec,m,parent=fixture(tmp_path);verified=verified_bc_warmstart(spec)
 assert verified['verified_constituent_coverage'] is True
 assert verified['verified_parent_constituents']==verified['verified_child_constituents']==1
 assert verified['source_lineage_schema']=='airport_vla_source_coverage_superset/1'


@pytest.mark.parametrize('scope',['data','meta','videos'])
def test_derived_resource_mutation_after_audit_is_rejected(tmp_path,scope):
 spec,m,parent=fixture(tmp_path);path=next((Path(spec.dataset_root)/scope).iterdir());path.write_bytes(b'tampered')
 with pytest.raises(ValueError,match='resource bytes'):verified_bc_warmstart(spec)


def test_added_derived_resource_after_audit_is_rejected(tmp_path):
 spec,m,parent=fixture(tmp_path);(Path(spec.dataset_root)/'meta/extra.json').write_text('{}')
 with pytest.raises(ValueError,match='resource set'):verified_bc_warmstart(spec)


@pytest.mark.parametrize('change',['phase','quality','interval','prompt','missing','recordhash','coveragehash'])
def test_constituent_semantic_changes_do_not_become_parent_coverage(tmp_path,change):
 spec,m,parent=fixture(tmp_path);episode=m['episodes'][0];span=episode['constituent_phase_spans'][0]
 if change=='phase':span['phase']='fake_phase'
 if change=='quality':span['source_needs_review']=True
 if change=='interval':span['start_frame']=41
 if change=='prompt':span['language_prompt']='different'
 if change=='missing':episode['constituent_phase_spans']=[]
 episode['constituent_record_sha256']=[record_sha256(s) for s in episode['constituent_phase_spans']]
 source=dict(span,schema='airport_vla_skill_contiguous_segments/1',segment_id='merged1',phase='skill_contiguous',
   constituent_phase_spans=episode['constituent_phase_spans'],constituent_record_sha256=episode['constituent_record_sha256'])
 source_path=Path(m['source_manifest']);source_path.write_text(json.dumps(source)+'\n')
 m['source_manifest_sha256']=hashlib.sha256(source_path.read_bytes()).hexdigest()
 (Path(spec.dataset_root)/'airport_training_manifest.json').write_text(json.dumps(m));refresh(spec)
 if change in ('recordhash','coveragehash'):
  if change=='recordhash':
   m['episodes'][0]['constituent_record_sha256']=['0'*64]
   (Path(spec.dataset_root)/'airport_training_manifest.json').write_text(json.dumps(m));refresh(spec)
  else:
   path=Path(spec.bc_warmstart_source_audit);audit=json.loads(path.read_text());audit['coverage_identity_sha256']='0'*64;path.write_text(json.dumps(audit))
 with pytest.raises(ValueError):verified_bc_warmstart(spec)
