"""Create new canonical test variants after the first verified observed source.

No old evaluation outcome is reused. Default selects three explicitly declared
canonical test parents; the remaining 47 are not reported as evaluated.
"""
import json
from pathlib import Path
from ..vla.data_three_table_single_tray import PROFILE,RULE_REVISION,FINAL_ORIENTATION_DEFINITION,source_validate
from ..single_tray_lab.three_table_scene import generate_three_table_scene
from .evaluation_batch import sha,canonical,protocol

def prepare_from_source(source,output,*,selected=3,seed_base=202610066100,max_action_steps=3600):
    source_validate(source);output=Path(output)
    if output.exists():return protocol(output)
    registry=json.loads(Path(source['canonical_split_registry']).read_text());parents=json.loads(Path(source['parent_manifest']).read_text());ids=sorted(k for k,v in registry.items() if v=='test')
    if len(ids)!=50 or selected not in (3,50):raise ValueError('explicit_canonical_test_population_required')
    winner_scene=json.loads(Path(source['scene_json']).read_text())
    import h5py
    with h5py.File(source['trace']) as f:meta=json.loads(f.attrs['metadata_json'])
    root=output.parent/'new_canonical_test_scenes';root.mkdir(parents=True,exist_ok=True);config=output.parent/'evaluation_runtime_config.json';reference=output.parent/'evaluation_push_reference_scene.json'
    cfg=meta['config'];profile=meta['loaded_bridge_profile']
    # LoadedBridgeProfile has extra task fields; ControlProfile reference admits
    # only its existing fields, while scene declarations bind the selected caps.
    from dataclasses import fields
    from ..single_tray_lab.control import ControlProfile
    keys={f.name for f in fields(ControlProfile)}
    config.write_text(json.dumps(cfg,indent=2));reference.write_text(json.dumps({'control_profile':{k:v for k,v in profile.items() if k in keys}},indent=2))
    hints=winner_scene['front_approach_candidates'];rows=[]
    for i,pid in enumerate(ids[:selected]):
        parent=next(r for r in parents['scenes'] if r['scene_id']==pid);parent_path=Path(source['parent_manifest']).parent/parent['json'];directory=root/pid
        if directory.exists():raise ValueError('fresh_protocol_scene_directory_required')
        scene=generate_three_table_scene(directory,parent_path,source['parent_manifest'],seed_base+i,split_registry=source['canonical_split_registry'],source_base_distance_m=hints['source_base_distance_m'],target_base_standoff_m=hints['target_base_standoff_m'],target_tray_x=winner_scene['place_target']['position_world'][0],target_base_yaw=winner_scene['target_robot_pose']['yaw_world'])
        docpath=directory/'scene.json';doc=json.loads(docpath.read_text())
        doc['loaded_push_target']=winner_scene['loaded_push_target'].copy()
        docpath.write_text(json.dumps(doc,indent=2));rows.append(dict(scene_id=doc['scene_id'],parent_scene_id=pid,variant_seed=doc['seed'],split='test',scene_json=str(docpath),scene_json_sha256=sha(docpath),scene_xml_sha256=doc['xml_sha256']))
    result=dict(schema='airport_three_table_single_tray_evaluation_protocol/1',task_profile=PROFILE,task_rule_revision=RULE_REVISION,final_orientation_definition=FINAL_ORIENTATION_DEFINITION,base_mode='planar_mobile_table_front',model_action_mask=[True]*19,selected=selected,canonical_parent_population_size=50,population_complete=selected==50,historical_evaluation_results_reused=False,route_goal_observation_policy='fixed_registered_rear_to_front_left_route',canonical_split_registry=source['canonical_split_registry'],canonical_split_registry_sha256=source['canonical_split_registry_sha256'],winner_source_trace_sha256=source['trace_sha256'],runtime_config=str(config),runtime_config_sha256=sha(config),push_reference_scene=str(reference),push_reference_scene_sha256=sha(reference),execution=dict(max_action_steps=max_action_steps,execute_steps=5,fps=20,environment_phase_excluded=True),scenes=rows)
    result['distinct_parent_count']=len({r['parent_scene_id'] for r in rows})
    result['declared_selection']=[{k:r[k] for k in ('scene_id','parent_scene_id','variant_seed')} for r in rows]
    result['protocol_id']='sha256:'+canonical(result);output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(result,indent=2));return protocol(output)


def prepare_from_registered_scenes(scene_paths,output,*,runtime_config,push_reference_scene,canonical_split_registry,max_action_steps=3600):
    """Bind existing held-out variants; do not generate or relabel any scene."""
    output=Path(output)
    if output.exists():raise FileExistsError('fresh_evaluation_protocol_required')
    rows=[]
    for path in scene_paths:
        path=Path(path).resolve();scene=json.loads(path.read_text())
        rows.append(dict(scene_id=scene['scene_id'],parent_scene_id=scene['parent_scene_id'],variant_seed=scene['seed'],
            split=scene['split'],scene_json=str(path),scene_json_sha256=sha(path),scene_xml_sha256=sha(scene['xml'])))
    result=dict(schema='airport_three_table_single_tray_evaluation_protocol/1',task_profile=PROFILE,
        task_rule_revision=RULE_REVISION,final_orientation_definition=FINAL_ORIENTATION_DEFINITION,
        base_mode='planar_mobile_table_front',model_action_mask=[True]*19,selected=len(rows),
        distinct_parent_count=len({r['parent_scene_id'] for r in rows}),canonical_parent_population_size=50,
        population_complete=len({r['parent_scene_id'] for r in rows})==50,historical_evaluation_results_reused=False,
        route_goal_observation_policy='fixed_registered_rear_to_front_left_route',
        canonical_split_registry=str(Path(canonical_split_registry).resolve()),canonical_split_registry_sha256=sha(canonical_split_registry),
        runtime_config=str(Path(runtime_config).resolve()),runtime_config_sha256=sha(runtime_config),
        push_reference_scene=str(Path(push_reference_scene).resolve()),push_reference_scene_sha256=sha(push_reference_scene),
        execution=dict(max_action_steps=max_action_steps,execute_steps=5,fps=20,environment_phase_excluded=True),scenes=rows,
        declared_selection=[{k:r[k] for k in ('scene_id','parent_scene_id','variant_seed')} for r in rows])
    result['protocol_id']='sha256:'+canonical(result)
    # Validate all actual source bindings before committing the new protocol.
    import tempfile,os
    output.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(dir=output.parent,suffix='.json')
    try:
        with os.fdopen(fd,'w') as f:json.dump(result,f,indent=2)
        protocol(tmp);Path(tmp).replace(output)
    finally:
        if Path(tmp).exists():Path(tmp).unlink()
    return result
