import json
import pytest
from r1pro_teleop.single_tray_3table.evaluation_batch import protocol,canonical,sha,summary,PROFILE,RULE_REVISION,FINAL_ORIENTATION_DEFINITION
from r1pro_teleop.single_tray_3table.evaluation_protocol import prepare_from_registered_scenes


def fixture(tmp_path):
    registry=tmp_path/'registry.json';registry.write_text(json.dumps({**{f'test{i}':'test' for i in range(50)},'train0':'train','val0':'val'}))
    config=tmp_path/'config.json';config.write_text('{}')
    reference=tmp_path/'reference.json';reference.write_text('{}')
    paths=[]
    for i in range(10):
        xml=tmp_path/f'{i}.xml';xml.write_text('<mujoco><worldbody><body name="tray"/></worldbody></mujoco>')
        p=tmp_path/f'{i}.json';p.write_text(json.dumps(dict(schema='airport_three_table_single_tray_scene/1',task_profile=PROFILE,
            task_rule_revision=RULE_REVISION,final_orientation_definition=FINAL_ORIENTATION_DEFINITION,
            base_mode='planar_mobile_table_front',model_action_mask=[True]*19,
            route_goal_observation_policy='fixed_registered_rear_to_front_left_route',parent_scene_id=f'test{i%2}',
            scene_id=f'variant{i}',seed=100+i,split='test',xml=str(xml),xml_sha256=sha(xml),canonical_split_registry_sha256=sha(registry))))
        paths.append(p)
    out=tmp_path/'protocol.json'
    prepare_from_registered_scenes(paths,out,runtime_config=config,push_reference_scene=reference,canonical_split_registry=registry)
    return out,paths


def rewrite(out,doc):
    doc.pop('protocol_id');doc['protocol_id']='sha256:'+canonical(doc);out.write_text(json.dumps(doc))


def test_ten_variants_of_two_canonical_test_parents(tmp_path):
    out,_=fixture(tmp_path);p=protocol(out)
    assert p['selected']==10 and p['distinct_parent_count']==2 and not p['population_complete']
    assert len(p['declared_selection'])==10
    report=summary([dict(task_completed=False,failure_code='budget') for _ in range(10)],10,p['protocol_id'],p)
    assert report['evaluation_episode_count']==10 and report['distinct_parent_count']==2


@pytest.mark.parametrize('mutation',['train','val','duplicate_seed','duplicate_scene','selection','count'])
def test_parent_leak_and_duplicate_variants_fail_closed(tmp_path,mutation):
    out,paths=fixture(tmp_path);doc=json.loads(out.read_text())
    if mutation in ('train','val','duplicate_seed','duplicate_scene'):
        s=json.loads(paths[2].read_text())
        if mutation in ('train','val'):s['parent_scene_id']=mutation+'0';doc['scenes'][2]['parent_scene_id']=s['parent_scene_id']
        elif mutation=='duplicate_seed':s['seed']=100;doc['scenes'][2]['variant_seed']=100
        else:s['scene_id']='variant0';doc['scenes'][2]['scene_id']='variant0'
        paths[2].write_text(json.dumps(s));doc['scenes'][2]['scene_json_sha256']=sha(paths[2])
    elif mutation=='selection':doc['declared_selection'][0]['variant_seed']=999
    else:doc['distinct_parent_count']=10
    rewrite(out,doc)
    with pytest.raises(ValueError):protocol(out)
