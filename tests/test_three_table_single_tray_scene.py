from pathlib import Path
import json,xml.etree.ElementTree as ET
import numpy as np
import pytest
from r1pro_teleop.single_tray_lab.three_table_scene import generate_three_table_scene,sample_pose
from r1pro_teleop.single_tray_lab.scene import ROOT

REGISTRY=ROOT/'resources/single_tray_three_table_v1/source_registry'
PARENT=REGISTRY/'ordinary/airport_0004_20270920/scene.json'

def test_new_scene_preserves_three_tables_one_tray_and_registered_split(tmp_path):
    import mujoco
    scene=generate_three_table_scene(tmp_path/'scene',PARENT,REGISTRY/'parent_manifest.json',202610061615,
        split_registry=REGISTRY/'canonical_split_registry.json')
    parent=json.loads(PARENT.read_text())
    assert scene['tables']==parent['tables'] and len(scene['legacy_spec']['trays'])==1
    assert scene['split']=='train' and scene['parent_split']=='train'
    assert scene['base_actuated'] and scene['model_action_mask']==[True]*19
    model=mujoco.MjModel.from_xml_path(scene['xml'])
    for name in ('front_left','front_right','rear','tray'):assert model.body(name).id>0
    assert sum(name.startswith('tray_contact_') for name in (model.geom(i).name or '' for i in range(model.ngeom)))==17
    assert model.nflex==1
    assert scene['place_target']['yaw_world']==pytest.approx(0.)
    assert scene['place_target']['long_axis_parallel_robot_forward']
    assert 'long_axis_parallel_robot_left' not in scene['place_target']
    assert scene['front_approach_candidates']['hints_only']
    assert not scene['front_approach_candidates']['fixed_target_station_override']
    assert scene['pickup_preparation']['included_in_pick_window']
    assert scene['loaded_push_target']['edge_projection_hint_m']==pytest.approx(.6)
    assert scene['loaded_push_target']['supported_boundary_margin_m']==pytest.approx(.05)
    assert scene['loaded_push_target']['base_drift_m']==pytest.approx(.05)
    assert scene['loaded_push_target']['transient_boundary_extra_m']==0.
    assert scene['loaded_push_target']['recompute_with_selected_station']
    assert scene['initial_tray_pose']['yaw_world']!=scene['place_target']['yaw_world']
    assert scene['initial_tray_pose']['grasp_feasibility_status']=='pending_private_opposed_long_rim_screen'
    assert not scene['physical_demo_completed']

def test_random_pose_seed_replay_and_parent_split_cannot_change(tmp_path):
    table=next(t for t in json.loads(PARENT.read_text())['tables'] if t['table_id']=='rear')
    first=sample_pose(table,202610061615)
    assert sample_pose(table,202610061615)==first
    assert sample_pose(table,202610061616)!=first
    with pytest.raises(ValueError,match='split_registry_required'):
        generate_three_table_scene(tmp_path/'absent',PARENT,REGISTRY/'parent_manifest.json',11)
    with pytest.raises(ValueError,match='parent_split_changed'):
        generate_three_table_scene(tmp_path/'changed',PARENT,REGISTRY/'parent_manifest.json',11,
            canonical_split='test',split_registry=REGISTRY/'canonical_split_registry.json')
