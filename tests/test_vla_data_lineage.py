import json
from pathlib import Path
import numpy as np
import pytest
import h5py
pq=pytest.importorskip('pyarrow.parquet')
pa=pytest.importorskip('pyarrow')
pytest.importorskip('mujoco')
from r1pro_teleop.vla.data_lineage import audit_source_superset,_digest


def datasets(tmp_path):
    collection=tmp_path/'collection';scene_dir=collection/'scenes/s1';scene_dir.mkdir(parents=True)
    (collection/'collection.json').write_text(json.dumps({'fingerprint':'collection-hash'}))
    xml=scene_dir/'mobile.xml';xml.write_text('<mujoco><worldbody><body pos="1.2 2.3 0"><joint name="agent_base_x" type="slide" axis="1 0 0"/><joint name="agent_base_y" type="slide" axis="0 1 0"/><joint name="agent_base_yaw" type="hinge" axis="0 0 1"/><geom type="sphere" size=".1"/></body></worldbody></mujoco>')
    scene={'scene_id':'s1','split':'train','source_json_sha256':'sourcehash'}
    (scene_dir/'scene.json').write_text(json.dumps(scene))
    (scene_dir.parent/'index.json').write_text(json.dumps([scene]))
    trace=tmp_path/'trace.h5'
    states=np.arange(64,dtype=np.float32).reshape(4,16)/100
    bases=np.arange(12,dtype=np.float64).reshape(4,3)/10
    actions=states+.01;baseactions=bases+.01
    with h5py.File(trace,'w') as f:
        f.attrs['metadata_json']=json.dumps({'scene_id':'s1','split':'train','scene':scene,'scene_xml_sha256':_digest(xml)})
        for key,value in {'state':states,'qpos':bases,'action':actions,'base_action':baseactions,'base_state':bases+[1.2,2.3,0],'transition_completed':np.ones(4,bool)}.items():f[key]=value
    common=dict(split='train',training_ready=True,scene_id='s1',trace=str(trace),trace_sha256=_digest(trace),collection=str(collection),collection_fingerprint='collection-hash',scene_source_sha256='sourcehash',skill='initialize_posture',phase='initial_tuck',operation_index=None,language_prompt='Move.',quality_class='complete_task')
    roots=[]
    for label,intervals in [('parent',[(0,2)]),('child',[(2,4),(0,2)])]:
        root=tmp_path/label;(root/'meta').mkdir(parents=True);(root/'data/chunk-000').mkdir(parents=True)
        rows=[];episodes=[]
        for index,(a,b) in enumerate(intervals):
            row=dict(common,segment_id=f'segment{a}',source_segment_id=f'source{a}',start_frame=a,end_frame=b,frames=b-a)
            rows.append(row)
            episodes.append(dict(row,episode_index=index,source_trace=str(trace),source_trace_sha256=_digest(trace),source_start_frame=a,source_end_frame=b,fps=20,action_semantics='absolute_mobile19',state_semantics='measured_joint16_plus_base_origin_offset3',base_qpos_indices=[0,1,2]))
            table=pa.table({'observation.state':np.concatenate((states[a:b],bases[a:b]),axis=1).astype(np.float32).tolist(),'action':np.concatenate((actions[a:b],baseactions[a:b]),axis=1).astype(np.float32).tolist(),'timestamp':np.arange(b-a,dtype=np.float32)/20,'task_index':np.zeros(b-a,int),'episode_index':np.full(b-a,index),'frame_index':np.arange(b-a)})
            pq.write_table(table,root/f'data/chunk-000/episode_{index:06d}.parquet')
        source=root/'segments.jsonl';source.write_text('\n'.join(json.dumps(r) for r in rows))
        (root/'meta/tasks.jsonl').write_text(json.dumps({'task_index':0,'task':'Move.'}))
        (root/'meta/info.json').write_text(json.dumps({'fps':20,'total_frames':sum(b-a for a,b in intervals),'total_episodes':len(intervals),'chunks_size':1000,'data_path':'data/chunk-{episode_chunk:03d}/episode_{episode_index:06d}.parquet'}))
        (root/'airport_training_manifest.json').write_text(json.dumps(dict(repo_id=label,split='train',normalization_split='train_only',environment_source='simulation',controller_source='program_generated',human_demonstration=False,official_loader_every_episode_first_last=True,training_video_encoding_verification={'verified':True},fps=20,action_semantics='absolute_mobile19',state_semantics='measured_joint16_plus_base_origin_offset3',source_manifest=str(source),source_manifest_sha256=_digest(source),episodes=episodes)))
        roots.append(root)
    return roots


def test_actual_source_superset_all_frames_and_origin_offsets(tmp_path):
    parent,child=datasets(tmp_path)
    report=audit_source_superset(parent,child)
    assert report['verified'] and report['source_frame_values_verified'] and report['source_scene_xml_verified']
    assert report['verified_parent_segments']==1 and report['verified_child_segments']==2
    assert report['added_segments']==1
    assert report['datasets'][1]['frames']==4
    assert report['parent_training_manifest_sha256']==_digest(parent/'airport_training_manifest.json')


def test_world_base_state_cannot_replace_measured_origin_offsets(tmp_path):
    parent,child=datasets(tmp_path)
    path=child/'data/chunk-000/episode_000000.parquet';table=pq.read_table(path)
    state=np.asarray(table['observation.state'].to_pylist());state[:,16:18]+=[1.2,2.3]
    table=table.set_column(table.schema.get_field_index('observation.state'),'observation.state',pa.array(state.tolist()))
    pq.write_table(table,path)
    with pytest.raises(ValueError,match='actual_frame_values_changed'):audit_source_superset(parent,child)


@pytest.mark.parametrize('change',['phase','operation_index','trace','xml','incomplete'])
def test_changed_identity_or_unfinished_dataset_is_rejected(tmp_path,change):
    parent,child=datasets(tmp_path)
    path=child/'airport_training_manifest.json';manifest=json.loads(path.read_text())
    if change=='phase':manifest['episodes'][1]['phase']='new_phase'
    elif change=='operation_index':manifest['episodes'][1]['operation_index']=10
    elif change=='trace':Path(manifest['episodes'][0]['source_trace']).write_bytes(b'changed')
    elif change=='xml':(tmp_path/'collection/scenes/s1/mobile.xml').write_text('changed')
    elif change=='incomplete':manifest['official_loader_every_episode_first_last']=False
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError):audit_source_superset(parent,child)


def test_same_scene_without_parent_segment_is_not_a_superset(tmp_path):
    parent,child=datasets(tmp_path)
    path=child/'airport_training_manifest.json';manifest=json.loads(path.read_text());manifest['episodes']=manifest['episodes'][:1];path.write_text(json.dumps(manifest))
    info=child/'meta/info.json';data=json.loads(info.read_text());data.update(total_frames=2,total_episodes=1);info.write_text(json.dumps(data))
    with pytest.raises(ValueError,match='parent_segments_missing'):audit_source_superset(parent,child)
