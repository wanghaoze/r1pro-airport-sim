"""Read-only legacy discovery and NEW three-tray loaded-handover assets.

Historical successful MuJoCo traces are references, never Isaac training data.
No historical push is renamed to the new loaded Flush action.
"""
import copy
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET

PROFILE = 'isaac_three_tray_loaded_action3_v1'
RULE = '20261015_three_tray_loaded_handover_left_motion3cm_v1'
PROMPTS = ('Pick up the tray', 'Place the tray', 'Flush tray to the left')


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(8 * 1024**2), b''):
            h.update(chunk)
    return h.hexdigest()


def discover(source_root):
    root = Path(source_root)
    plans = root / 'plans/all193_v4.jsonl'
    rows = [json.loads(line) for line in plans.read_text().splitlines() if line.strip()]
    registry, summaries = {}, {}
    for split in ('train', 'val', 'test'):
        path = root / f'action8_export_{split}_parallel_v2/dataset/airport_training_manifest.json'
        manifest = json.loads(path.read_text())
        if (manifest.get('dataset_ready') is not True or manifest.get('split') != split or
                manifest.get('prompt_mode') != 'task_complete_action8_v1'):
            raise ValueError('legacy_action8_export_not_closed')
        ids = manifest['complete_expected_scene_ids']
        if len(ids) != len(set(ids)) or set(ids) & set(registry):
            raise ValueError('legacy_parent_scene_split_leakage')
        registry.update({name: split for name in ids})
        summaries[split] = dict(full_sources=len(ids), old_action8_segments=len(manifest['episodes']),
            manifest=str(path), manifest_sha256=sha(path), counts=manifest['counts'])
    sources = []
    for row in rows:
        old = row['original_inventory']; scene = row['scene_id']
        if registry.get(scene) != row['split'] or old.get('split') != row['split']:
            raise ValueError('legacy_plan_and_parent_split_disagree')
        if old.get('task_completed') is not True or old.get('physics_success') is not True:
            raise ValueError('legacy_source_not_whole_task_success')
        sources.append(dict(parent_scene_id=scene, split=row['split'],
            source_engine='mujoco', intended_engine='isaacsim', source='simulation/program_generated',
            old_task_completed=True, old_strict_success=old.get('strict_success'),
            legacy_source={key: old[key] for key in ('trace', 'trace_sha256', 'result', 'result_sha256',
                'scene_xml', 'scene_xml_sha256', 'scene_json', 'scene_json_sha256', 'segments', 'segments_sha256')},
            native_training_eligible=False,
            exclusion_reason='legacy_has_no_new_loaded_handover; requires_new_native_full_task',
            old_segments_are_reference_only=True))
    if len({r['parent_scene_id'] for r in sources}) != len(sources) or set(registry) != {r['parent_scene_id'] for r in sources}:
        raise ValueError('legacy_complete_source_inventory_mismatch')
    return dict(schema='airport_three_tray_isaac_migration_inventory/1', profile=PROFILE,
        task_rule_revision=RULE, prompts=PROMPTS, legacy_root=str(root.resolve()),
        legacy_plan_sha256=sha(plans), parent_split_registry=registry, legacy_splits=summaries,
        sources=sources, qualified_new_native_sources=0, new_training_status='waiting_for_data',
        legacy_manifest_audit_only=True, all_legacy_traces_rehashed=False)


def verify_source(row):
    source = row['legacy_source']
    for key in ('trace', 'result', 'scene_xml', 'scene_json', 'segments'):
        if sha(source[key]) != source[key + '_sha256']:
            raise ValueError('legacy_source_identity_changed:' + key)
    result = json.loads(Path(source['result']).read_text())
    if result.get('task_completed') is not True:
        raise ValueError('legacy_actual_result_not_completed')
    return source


def loaded_scene_tree(source_xml, payload_xml, *, visual_audit=None):
    """Add passenger sets; preserve physics and authorized camera-shell removal.

    Keyframes must be rebuilt by name after adding DOFs. This function deliberately
    removes them rather than retaining an invalid qpos vector.
    """
    source_xml, payload_xml = Path(source_xml), Path(payload_xml)
    root = ET.parse(source_xml).getroot(); template = ET.parse(payload_xml).getroot()
    if list(root.iter('include')) or list(template.iter('include')):
        raise ValueError('three_tray_assets_require_expanded_xml')
    for tree, directory in ((root, source_xml.parent), (template, payload_xml.parent)):
        for element in tree.iter():
            if element.get('file'):
                element.set('file', str((directory / element.get('file')).resolve()))
    world, asset = root.find('worldbody'), root.find('asset')
    if world is None or asset is None:
        raise ValueError('three_tray_world_and_assets_required')
    names = {element.get('name') for element in world.iter('body')}
    tray_names = ('tray_0', 'tray_1', 'tray_2')
    if not set(tray_names) <= names or len([n for n in names if n and n.startswith('tray_')]) != 3:
        raise ValueError('exact_legacy_three_trays_required')
    from r1pro_teleop.single_tray_lab.camera_visuals import remove_wrist_camera_housing_visuals
    revision = remove_wrist_camera_housing_visuals(root)
    if visual_audit is not None:
        visual_audit.update(revision)
    originals = {name: ET.tostring(next(e for e in world.iter('body') if e.get('name') == name))
        for name in (*tray_names, 'base_link')}
    table_nodes = {e.get('name'): ET.tostring(e) for e in world.findall('body')
        if e.get('name') in ('front_left', 'front_right', 'rear')}
    if len(table_nodes) != 3:
        raise ValueError('legacy_three_table_layout_required')
    template_world = template.find('worldbody')
    passengers = [copy.deepcopy(next(e for e in template_world
        if e.get('name') == 'passenger_' + kind)) for kind in ('laptop', 'backpack', 'coat')]
    payload_assets = [e for e in template.find('asset') if (e.get('name') or '').startswith('passenger_')]
    payloads = []
    for index, tray in enumerate(tray_names):
        prefix = tray + '_'
        elements = [copy.deepcopy(e) for e in payload_assets + passengers]
        for element in elements:
            for child in element.iter():
                for key in ('name', 'mesh', 'material', 'texture', 'joint', 'body'):
                    value = child.get(key)
                    if value and value.startswith('passenger_'):
                        child.set(key, prefix + value)
            if element.tag in ('body', 'flexcomp'):
                position = list(map(float, element.get('pos').split())); position[1] += index * 1.2
                element.set('pos', ' '.join(map(str, position)))
                world.append(element)
                payloads.append(dict(tray_id=tray, name=element.get('name'),
                    kind=element.get('name').split('passenger_')[1], flex=element.tag == 'flexcomp',
                    parked_position=position, loaded=False))
            else:
                asset.append(element)
    for key in list(root.findall('keyframe')):
        root.remove(key)
    # Compiler compatibility is handled separately by the native import copy.
    root.find('option').set('integrator', 'discrete')
    for name, before in {**originals, **table_nodes}.items():
        after = next(e for e in world.iter('body') if e.get('name') == name)
        if ET.tostring(after) != before:
            raise ValueError('legacy_robot_table_or_tray_changed:' + name)
    return root, payloads


def build_scene(row, payload_xml, output):
    import mujoco
    import numpy as np
    source = verify_source(row)
    output = Path(output); output.mkdir(parents=True, exist_ok=False)
    visual_audit = {}
    root, payloads = loaded_scene_tree(source['scene_xml'], payload_xml, visual_audit=visual_audit)
    path = output / 'mobile.xml'; ET.ElementTree(root).write(path, encoding='utf-8', xml_declaration=True)
    old = mujoco.MjModel.from_xml_path(source['scene_xml']); new = mujoco.MjModel.from_xml_path(str(path))
    original = old.key_qpos[0] if old.nkey else old.qpos0
    q = new.qpos0.copy()
    for i in range(old.njnt):
        name = old.joint(i).name
        if not name:
            raise ValueError('three_tray_named_initialization_required')
        j = new.joint(name).id
        a = int(old.jnt_qposadr[i]); b = int(old.jnt_qposadr[i + 1]) if i + 1 < old.njnt else old.nq
        c = int(new.jnt_qposadr[j]); q[c:c + b - a] = original[a:b]
    frame = ET.SubElement(root, 'keyframe')
    ET.SubElement(frame, 'key', name='legacy_home_with_parked_passengers', qpos=' '.join(format(x, '.17g') for x in q))
    ET.ElementTree(root).write(path, encoding='utf-8', xml_declaration=True)
    checked = mujoco.MjModel.from_xml_path(str(path))
    if not np.array_equal(checked.key_qpos[0], q):
        raise ValueError('three_tray_home_keyframe_changed')
    manifest = dict(schema='airport_three_tray_loaded_scene/1', profile=PROFILE, task_rule_revision=RULE,
        parent_scene_id=row['parent_scene_id'], split=row['split'], source='simulation/program_generated',
        source_xml=source['scene_xml'], source_xml_sha256=source['scene_xml_sha256'],
        payload_template=str(Path(payload_xml).resolve()), payload_template_sha256=sha(payload_xml),
        xml=str(path.resolve()), xml_sha256=sha(path), payloads=payloads,
        visual_geometry_revision=visual_audit,
        prompts=PROMPTS, environment_only_actions=['passenger_load', 'passenger_settle'],
        task_flow='legacy_three_tray_scheduler_with_new_loaded_handover_after_empty_placement',
        initialization='source_first_keyframe_by_joint_name_plus_parked_passengers',
        native_training_eligible=False, native_validation='pending',
        preserved=['three_table_dimensions_and_poses', 'three_tray_geometry', 'robot_collision_inertia_cameras',
            'gripper_shells_and_fingers', 'robot_visuals_except_authorized_camera_housing'],
        not_inherited=['historical_push_labels', 'historical_task_success', 'historical_model_checkpoint_success'])
    (output / 'scene.json').write_text(json.dumps(manifest, indent=2))
    return manifest
