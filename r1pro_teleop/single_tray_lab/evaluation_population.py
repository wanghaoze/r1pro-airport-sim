"""Prepare a new fixed single-tray test population; emit only after source success."""
from dataclasses import asdict, fields, replace
from pathlib import Path
import json
from .scene import LabSceneConfig, generate_scene
from .control import ControlProfile
from ..vla.data_single_tray import canonical_hash

GEOMETRY_FIELDS=frozenset(('tray_body','table_bodies','payload_bodies','payload_flexes','tray_dimensions','table_center_xy','table_half_sizes_xy','tabletop_z','empty_place_position','loaded_goal_position','front_normal','robot_left'))
WORKSPACE_Y_STRATA=(-.05,0.,.05,.10,.15)
WORKSPACE_SCOPE_ID='single_tray_fixed_front_y0_t08_workspace_v1'


def workspace_scope():
    return dict(scope_id=WORKSPACE_SCOPE_ID,description='New fixed-front workspace; robot and initial tray share Y, with 10 new test scenes per stratum.',
        robot_x_m=.15,robot_and_initial_tray_y_strata_m=list(WORKSPACE_Y_STRATA),scenes_per_stratum=10,
        reference_success_robot_y_m=0.,reference_success_tray_y_m=0.,reference_handover_left_tangent_m=.08,
        scene_generation_required=True,historical_negative_y_population_used=False)

def population(training_seeds=()):
    seeds=list(range(20261006000,20261006050))
    if set(seeds)&set(training_seeds):raise ValueError('evaluation_training_seed_overlap')
    return [dict(seed=seed,split='test',scene_id='single_tray_'+str(seed),robot_x=.15,robot_y=y,tray_y=y,
        workspace_scope_id=WORKSPACE_SCOPE_ID,stratum_index=i//10) for i,seed in enumerate(seeds) for y in [WORKSPACE_Y_STRATA[i//10]]]

def adapted_profile(scene,successful_profile):
    derived=asdict(ControlProfile.from_scene({k:v for k,v in scene.items() if k!='control_profile'}))
    known={f.name for f in fields(ControlProfile)}
    if set(successful_profile)!=known:raise ValueError('complete_success_control_profile_required')
    derived.update({k:v for k,v in successful_profile.items() if k not in GEOMETRY_FIELDS})
    ControlProfile(**derived).validate()
    return derived

def generate_protocol(success_case,output,training_seeds):
    """No source success -> no output. Uses real new scene geometry for each row."""
    import h5py
    from ..vla.single_tray_pipeline import validate_run_metadata
    from ..vla.training_cache import file_sha
    case=Path(success_case);result=json.loads((case/'result.json').read_text());scene=json.loads((case/'scene/scene.json').read_text())
    if not all(result.get(key) is True for key in ('task_completed','physics_success','training_eligible')):raise ValueError('complete_success_source_required_before_formal_protocol')
    with h5py.File(case/'attempt/trace.h5') as trace:
        profile=validate_run_metadata(scene,result,json.loads(trace.attrs['metadata_json']),int(trace.attrs['num_frames']))
        if trace.attrs.get('schema')!='airport_single_tray_raw/2' or not trace['transition_completed'][:].all():raise ValueError('complete_raw2_source_required')
    if file_sha(scene['xml'])!=scene['xml_sha256']:raise ValueError('successful_source_xml_changed')
    specs=population(training_seeds);output=Path(output)
    if output.exists():raise FileExistsError(output)
    cfg=dict(scene['config']);cfg['payloads']=tuple(cfg['payloads']);base=LabSceneConfig(**cfg);rows=[]
    if base.robot_y!=0. or base.tray_y!=0. or profile['handover_left_tangent_m']!=.08:
        raise ValueError('evaluation_reference_requires_y0_t08_success')
    output.mkdir(parents=True)
    for item in specs:
        child=output/'scenes'/item['scene_id'];new=generate_scene(child,replace(base,seed=item['seed'],split='test',robot_x=.15,robot_y=item['robot_y'],tray_y=item['tray_y']),require_blender=True)
        new['control_profile']=adapted_profile(new,profile)
        ControlProfile.from_scene(new)
        (child/'scene.json').write_text(json.dumps(new,indent=2,allow_nan=False))
        rows.append(dict(scene_json=str(child/'scene.json'),scene_json_sha256=file_sha(child/'scene.json'),scene_xml_sha256=new['xml_sha256'],scene_id=new['scene_id'],split='test',seed=item['seed'],workspace_scope_id=WORKSPACE_SCOPE_ID,stratum_index=item['stratum_index'],generated_scene_config=new['config']))
    doc=dict(schema='airport_single_tray_evaluation_protocol/1',task_profile='single_tray_action3_v1',base_mode='fixed_front',execution=dict(max_action_steps=3600,execute_steps=5,fps=20,environment_phase_excluded=True),scenes=rows,source='simulation/program_generated',source_success_case=str(case),source_result_sha256=file_sha(case/'result.json'),source_trace_sha256=file_sha(case/'attempt/trace.h5'),source_scene_sha256=file_sha(case/'scene/scene.json'),source_control_profile_sha256=canonical_hash(profile),training_seeds=sorted(training_seeds),strict_contact_report=dict(definition='task_complete_and_all_guarded_hard_le_3mm_soft_le_5mm',hard_limit_m=.003,soft_limit_m=.005,required_coverage='every_guarded_physics_substep',missing_evidence='unavailable_never_passed'),paired_strict_report='unavailable_separate_control_variant_not_defined',historical_three_tray_protocol_used=False)
    doc['workspace_scope']=workspace_scope()
    doc['source_success_config_sha256']=canonical_hash(scene['config'])
    doc['source_reference_geometry_copied']=False
    doc['new_scenes_generated']=True
    doc['protocol_id']='sha256:'+canonical_hash(doc)
    (output/'protocol.json').write_text(json.dumps(doc,indent=2,allow_nan=False));return doc


