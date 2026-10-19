import dataclasses
import hashlib
import json
from pathlib import Path
import pytest
from r1pro_teleop.vla.training import TrainingSpec, verified_bc_warmstart, copy_verified_warmstart_stats


def fixture(tmp_path):
    trace = tmp_path / 'trace.h5'; trace.write_bytes(b'original real source fixture')
    row = dict(scene_id='train4', segment_id='seg1', split='train', source_trace=str(trace),
        source_trace_sha256=hashlib.sha256(trace.read_bytes()).hexdigest(), source_start_frame=40,
        source_end_frame=78, frames=38, skill='initialize_posture', language_prompt='tuck',
        base_qpos_indices=[0,1,2], phase='initial', operation_index=None, state_semantics='measured_joint16_plus_base_origin_offset3',
        action_semantics='absolute_mobile19', fps=20)
    xml=tmp_path/'collection/scenes/train4/mobile.xml'; xml.parent.mkdir(parents=True); xml.write_text('<mujoco/>'); xml.with_name('scene.json').write_text('{}')
    source = tmp_path/'source.jsonl'; source.write_text('\n'.join(json.dumps(dict(segment_id=seg,scene_id='train4',collection=str(tmp_path/'collection'))) for seg in ['seg1','seg2']))
    manifest = dict(fps=20,action_semantics='absolute_mobile19',state_semantics='measured_joint16_plus_base_origin_offset3',source_manifest=str(source), source_manifest_sha256=hashlib.sha256(source.read_bytes()).hexdigest(), split='train', normalization_split='train_only', environment_source='simulation',
        controller_source='program_generated', human_demonstration=False,
        official_loader_every_episode_first_last=True, training_video_encoding_verification={'verified':True},
        episodes=[row])
    old = tmp_path / 'old'; new = tmp_path / 'airport/new'; old.mkdir(); new.mkdir(parents=True)
    for d,repo in ((old,'airport/old'),(new,'airport/new')): (d/'airport_training_manifest.json').write_text(json.dumps(dict(manifest,repo_id=repo)))
    manifest['repo_id']='airport/new'
    ck = tmp_path/'run/checkpoints/model/training/9'
    for d in ('params','train_state'): (ck/d).mkdir(parents=True); (ck/d/'data').write_bytes(b'weights')
    norm=ck/'assets/airport/old/norm_stats.json'; norm.parent.mkdir(parents=True); norm.write_text('{"state":{}}')
    parent=dict(status='checkpoint_saved',checkpoint_verified=True,model='pi05',fps=20,
        action_semantics='absolute_mobile19',source='simulation/program_generated',training_steps=10,
        checkpoint_step=9,checkpoint=str(ck),normalization=str(norm),spec=dict(run_dir=str(tmp_path/'run'),
        name='model',num_train_steps=10,dataset_root=str(old),dataset_repo_id='airport/old',lora=True,action_horizon=20))
    status=tmp_path/'parent.json'; status.write_text(json.dumps(parent))
    files=sorted(p for p in (ck/'params').rglob('*') if p.is_file())+[norm]
    material={'training_status_sha256':hashlib.sha256(status.read_bytes()).hexdigest(),'files':[
        {'path':p.relative_to(ck).as_posix(),'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'bytes':p.stat().st_size} for p in files]}
    identity='sha256:'+hashlib.sha256(json.dumps(material,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    spec=TrainingSpec(str(new),'airport/new','unused',str(ck/'params'),str(tmp_path/'newrun'),
        bc_warmstart_parent_status=str(status),bc_warmstart_parent_checkpoint_id=identity,
        normalization_policy='preserve_verified_parent_train_stats')
    audit=tmp_path/'lineage.json'
    report=dict(schema='airport_vla_source_superset/1',verified=True,source_frame_values_verified=True,source_scene_xml_verified=True)
    for side,d in [('parent',old),('child',new)]:
        report[side+'_training_manifest_sha256']=hashlib.sha256((d/'airport_training_manifest.json').read_bytes()).hexdigest()
        report[side+'_source_manifest_sha256']=hashlib.sha256(source.read_bytes()).hexdigest()
    report['datasets']=[dict(role=side,dataset=str(d),repo_id=repo,training_manifest=str(d/'airport_training_manifest.json'),source_manifest=str(source),scene_count=1,scenes={'train4':dict(trace=str(trace),trace_sha256=row['source_trace_sha256'],scene_xml=str(xml),scene_xml_sha256=hashlib.sha256(xml.read_bytes()).hexdigest(),scene_json_sha256=hashlib.sha256(xml.with_name('scene.json').read_bytes()).hexdigest())}) for side,d,repo in [('parent',old,'airport/old'),('child',new,'airport/new')]]
    audit.write_text(json.dumps(report))
    spec=dataclasses.replace(spec,bc_warmstart_source_audit=str(audit))
    return spec, manifest, norm


def test_bc_language_change_is_explicit_weights_only_warmstart(tmp_path):
    spec, _, _ = fixture(tmp_path)
    spec = dataclasses.replace(spec, prompt_mode='skill_only_v1')
    audit = verified_bc_warmstart(spec)
    assert audit['parent_prompt_mode'] == 'legacy'
    assert audit['prompt_mode'] == 'skill_only_v1'
    assert audit['optimizer_policy'] == 'new_optimizer_weights_only_warmstart'


def test_verified_superset_and_hash_exact_copy(tmp_path):
    spec, m, norm=fixture(tmp_path)
    extra=dict(m['episodes'][0],segment_id='seg2',source_start_frame=78,source_end_frame=116)
    m['episodes'].append(extra)
    (Path(spec.dataset_root)/'airport_training_manifest.json').write_text(json.dumps(m))
    lineage=Path(spec.bc_warmstart_source_audit); report=json.loads(lineage.read_text()); report['child_training_manifest_sha256']=hashlib.sha256((Path(spec.dataset_root)/'airport_training_manifest.json').read_bytes()).hexdigest(); lineage.write_text(json.dumps(report))
    audit=verified_bc_warmstart(spec)
    assert (audit['verified_parent_segments'],audit['verified_new_segments'])==(1,2)
    assert audit['optimizer_policy']=='new_optimizer_weights_only_warmstart'
    out=tmp_path/'assets/airport/new/norm_stats.json'; copy_verified_warmstart_stats(audit,out)
    assert out.read_bytes()==norm.read_bytes()


@pytest.mark.parametrize('change',['interval','prompt','trace','split','loader','video','duplicate'])
def test_source_level_provenance_not_scene_list(tmp_path,change):
    spec,m,norm=fixture(tmp_path)
    if change=='interval': m['episodes'][0].update(source_start_frame=41,frames=37)
    if change=='prompt': m['episodes'][0]['language_prompt']='wrong'
    if change=='trace': m['episodes'][0]['source_trace_sha256']='0'*64
    if change=='split': m['episodes'][0]['split']='test'
    if change=='loader': m['official_loader_every_episode_first_last']=False
    if change=='video': m['training_video_encoding_verification']['verified']=False
    if change=='duplicate': m['episodes'].append(dict(m['episodes'][0]))
    (Path(spec.dataset_root)/'airport_training_manifest.json').write_text(json.dumps(m))
    lineage=Path(spec.bc_warmstart_source_audit); report=json.loads(lineage.read_text()); report['child_training_manifest_sha256']=hashlib.sha256((Path(spec.dataset_root)/'airport_training_manifest.json').read_bytes()).hexdigest(); lineage.write_text(json.dumps(report))
    with pytest.raises(ValueError): verified_bc_warmstart(spec)


@pytest.mark.parametrize('change',['weights','identity','lora','horizon','norm','train_state'])
def test_parent_checkpoint_bound_to_actual_bytes_and_semantics(tmp_path,change):
    spec,m,norm=fixture(tmp_path)
    if change=='weights': (Path(spec.base_params)/'data').write_bytes(b'tamper')
    if change=='identity': spec=dataclasses.replace(spec,bc_warmstart_parent_checkpoint_id='sha256:fake')
    if change=='lora': spec=dataclasses.replace(spec,lora=False)
    if change=='horizon': spec=dataclasses.replace(spec,action_horizon=30)
    if change=='norm': norm.write_text('changed')
    if change=='train_state': (Path(spec.base_params).parent/'train_state/data').unlink()
    with pytest.raises(ValueError): verified_bc_warmstart(spec)


def test_copy_rejects_norm_changed_since_audit(tmp_path):
    spec,m,norm=fixture(tmp_path); audit=verified_bc_warmstart(spec); norm.write_text('changed')
    with pytest.raises(ValueError,match='changed'): copy_verified_warmstart_stats(audit,tmp_path/'copy.json')


@pytest.mark.parametrize('field',['verified','source_frame_values_verified','source_scene_xml_verified','child_training_manifest_sha256','parent_source_manifest_sha256'])
def test_source_audit_cannot_be_unverified_or_stale(tmp_path,field):
    spec,m,norm=fixture(tmp_path); path=Path(spec.bc_warmstart_source_audit); audit=json.loads(path.read_text())
    audit[field]=False; path.write_text(json.dumps(audit))
    with pytest.raises(ValueError): verified_bc_warmstart(spec)


@pytest.mark.parametrize('fields', [dict(aggregation_manifest='aggregate.json'),
    dict(parent_trained_status='dagger-parent.json'), dict(normalization_policy='default_train_only')])
def test_bc_and_dagger_parent_modes_cannot_be_confused(tmp_path,fields):
    from test_vla_training import make_spec
    spec=dataclasses.replace(make_spec(tmp_path),bc_warmstart_parent_status='parent.json',
        normalization_policy='preserve_verified_parent_train_stats')
    with pytest.raises(ValueError): dataclasses.replace(spec,**fields).validate()


def test_preserve_normalization_requires_explicit_parent(tmp_path):
    from test_vla_training import make_spec
    with pytest.raises(ValueError,match='requires a parent'):
        dataclasses.replace(make_spec(tmp_path),normalization_policy='preserve_verified_parent_train_stats').validate()


def test_warmstart_launch_preserves_norm_without_running_norm_estimator(tmp_path,monkeypatch):
    from types import SimpleNamespace
    from r1pro_teleop.vla import training
    spec,m,norm=fixture(tmp_path)
    spec=dataclasses.replace(spec,openpi_root=str(tmp_path/'third_party/openpi'))
    # The branch test isolates launch from dataset schema validation, tested above.
    monkeypatch.setattr(TrainingSpec,'validate',lambda self:self)
    monkeypatch.setenv('HF_LEROBOT_HOME',str(tmp_path))
    monkeypatch.setattr(training,'register_openpi_config',lambda value:SimpleNamespace(
        assets_dirs=tmp_path/'assets',name=value.name))
    def forbidden(*args): raise AssertionError('Must not recompute normalization')
    monkeypatch.setattr(training,'_load_script',forbidden)
    status=training.launch_training(spec,normalize_only=True)
    assert status['status']=='normalized_only' and status['training_steps']==0
    assert Path(status['normalization']).read_bytes()==norm.read_bytes()
    assert status['bc_warmstart']['parent_checkpoint_id']==spec.bc_warmstart_parent_checkpoint_id


@pytest.mark.parametrize('resource',['mobile.xml','scene.json'])
def test_scene_resources_changed_after_audit_rejected(tmp_path,resource):
    spec,m,norm=fixture(tmp_path)
    (tmp_path/'collection/scenes/train4'/resource).write_text('changed after audit')
    with pytest.raises(ValueError,match='changed after audit'): verified_bc_warmstart(spec)


@pytest.mark.parametrize('field,value',[('repo_id','other/repo'),('dataset','wrong'),('scenes',{})])
def test_lineage_dataset_binding_cannot_be_substituted(tmp_path,field,value):
    spec,m,norm=fixture(tmp_path); path=Path(spec.bc_warmstart_source_audit); report=json.loads(path.read_text())
    report['datasets'][1][field]=value; path.write_text(json.dumps(report))
    with pytest.raises(ValueError): verified_bc_warmstart(spec)
