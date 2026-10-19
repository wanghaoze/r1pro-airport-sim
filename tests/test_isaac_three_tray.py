"""Synthetic contract checks, never physical success or training evidence."""
import copy
import json
import xml.etree.ElementTree as ET
import numpy as np
import pytest
import importlib.util
from pathlib import Path
from r1pro_teleop.real2sim.three_tray_migration import loaded_scene_tree, discover
from r1pro_teleop.vla.isaac_dataset import PROMPTS, validate_three_tray_cycles, THREE_TRAY_PROFILE, THREE_TRAY_RULE


def test_payload_assets_do_not_replace_robot_tables_or_trays(tmp_path):
    source = tmp_path / 'old.xml'
    cameras=''.join(f'<body name="{side}_realsense_link"><geom mesh="{side}_realsense_link" group="1" contype="0" conaffinity="0" density="0"/>'
        f'<geom name="{side}_camera_collision"/></body>' for side in ['left','right'])
    source.write_text('<mujoco><option/><asset/><worldbody><body name="base_link"><geom name="gripper_shell"/>' + cameras + '</body>' +
        ''.join(f'<body name="{name}" pos="1 2 3"><geom name="{name}_geom"/></body>'
                for name in ['front_left', 'front_right', 'rear', 'tray_0', 'tray_1', 'tray_2']) +
        '</worldbody><keyframe><key qpos="0"/></keyframe></mujoco>')
    template = tmp_path / 'payload.xml'
    template.write_text('<mujoco><asset><mesh name="passenger_laptop_mesh" file="mesh.obj"/></asset><worldbody>' +
        ''.join(f'<body name="passenger_{kind}" pos="-2 2 .3"><freejoint name="passenger_{kind}_free"/>' +
                ('<geom mesh="passenger_laptop_mesh"/>' if kind == 'laptop' else '') + '</body>'
                for kind in ['laptop', 'backpack']) +
        '<flexcomp name="passenger_coat" pos="-2 3 .3" file="coat.obj"/></worldbody></mujoco>')
    before = source.read_bytes()
    root, payloads = loaded_scene_tree(source, template)
    assert source.read_bytes() == before and len(payloads) == 9
    assert len(list(root.iter('flexcomp'))) == 3
    assert root.find('keyframe') is None
    mesh = root.find("worldbody/body[@name='tray_1_passenger_laptop']/geom").get('mesh')
    assert mesh == 'tray_1_passenger_laptop_mesh'
    assert root.find("asset/mesh[@name='" + mesh + "']").get('file') == str(tmp_path / 'mesh.obj')
    assert root.find("worldbody/body[@name='base_link']/geom").get('name') == 'gripper_shell'
    assert root.find(".//geom[@name='left_camera_collision']") is not None
    assert root.find(".//geom[@mesh='left_realsense_link']") is None


def cycle_fixture():
    spans, loads, physical = [], [], []
    for i in range(3):
        for prompt, a, b in zip(PROMPTS, [0, 3, 8], [3, 6, 12]):
            spans.append(dict(prompt=prompt, tray_id=f'tray_{i}', cycle_id=i, start=i * 12 + a, end=i * 12 + b))
        loads.append(dict(frame=i * 12 + 6, cycle_id=i, tray_id=f'tray_{i}', robot_and_all_trays_unchanged=True))
        row=dict(cycle_id=i, tray_id=f'tray_{i}', actual_tray_left_displacement_m=.031)
        for key in ['opposed_long_edges_pick_place','empty_pick_place','front_region_manipulation',
                    'long_axis_parallel_robot_forward','right_actual_push','left_stable_grasp',
                    'right_release_after_left_grasp','left_motion_after_right_release',
                    'final_release','stable_table_support','all_three_payloads_on_tray']:
            row[key] = True
        physical.append(row)
    return dict(task_rule_revision=THREE_TRAY_RULE,payload_load_events=loads),dict(profile=THREE_TRAY_PROFILE,
        qualified_tray_ids=['tray_0','tray_1','tray_2'],cycles=physical),spans


def test_old_push_or_tcp_motion_cannot_qualify_as_new_loaded_flush():
    m,q,s = cycle_fixture(); validate_three_tray_cycles(m,q,s)
    wrong=copy.deepcopy(q);wrong['cycles'][1]['actual_tray_left_displacement_m']=.001
    wrong['cycles'][1]['tcp_left_displacement_m']=.08
    with pytest.raises(ValueError,match='real_tray_left_motion'):
        validate_three_tray_cycles(m,wrong,s)
    wrong=copy.deepcopy(q);wrong['cycles'][2]['right_release_after_left_grasp']=False
    with pytest.raises(ValueError,match='physical_evidence'):
        validate_three_tray_cycles(m,wrong,s)
    wrong=copy.deepcopy(m);wrong['payload_load_events'][0]['frame']=8
    with pytest.raises(ValueError,match='loading_invalid'):
        validate_three_tray_cycles(wrong,q,s)
    wrong=copy.deepcopy(s);wrong[3]['prompt']='Navigate to the selected tray.'
    with pytest.raises(ValueError,match='prompt_changed'):
        validate_three_tray_cycles(m,q,wrong)


def test_repeated_cycles_have_only_three_training_task_ids(tmp_path, monkeypatch):
    import r1pro_teleop.vla.isaac_dataset as module
    m,q,spans=cycle_fixture();n=36
    trace=tmp_path/'trace.npz'
    np.savez(trace,state=np.zeros((n+1,19)),action=np.zeros((n,19)))
    sources=[dict(episode_id=split,parent_scene_id='p_'+split,split=split,frames=n,actions=spans,
        profile=THREE_TRAY_PROFILE,trace=str(trace),trace_sha256='synthetic',
        videos={c:dict(path=c) for c in module.CAMERAS}) for split in ['train','val','test']]
    monkeypatch.setattr(module,'load_frozen',lambda *args:dict(episodes=sources,profile=THREE_TRAY_PROFILE))
    manifest=tmp_path/'manifest.json';manifest.write_text('{}')
    def decode(path,indices,target):target[:]=0;return n
    module.materialize_cache(manifest,{},tmp_path/'cache',decode=decode)
    tasks=np.load(tmp_path/'cache/train/task.npy')
    assert set(tasks)=={0,1,2} and len(tasks)==30
    assert tasks.tolist()==([0]*3+[1]*3+[2]*4)*3
    assert len(json.loads((tmp_path/'cache/train/manifest.json').read_text())['episodes'])==9


def test_missing_base_drive_uses_source_gain_and_force_not_new_tuning():
    import mujoco
    spec=importlib.util.spec_from_file_location('drives',Path(__file__).resolve().parents[1]/'scripts/isaacsim_base_drives.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    model=mujoco.MjModel.from_xml_string('<mujoco><worldbody><body><joint name="agent_base_y" type="slide"/>'
        '<geom type="sphere" size=".1"/></body></worldbody><actuator><position joint="agent_base_y" '
        'kp="6000" kv="600" forcelimited="true" forcerange="-600 600"/></actuator></mujoco>')
    assert module.source_base_servo(model,'agent_base_y')==dict(stiffness=6000.,damping=600.,max_force=600.)
    model.actuator_gear[0,0]=2
    with pytest.raises(ValueError,match='unsupported_base_actuator'):
        module.source_base_servo(model,'agent_base_y')


def test_fk_diagnostic_is_invariant_to_base_translation_but_detects_finger_offset():
    import mujoco
    spec=importlib.util.spec_from_file_location('fk',Path(__file__).resolve().parents[1]/'scripts/isaacsim_kinematic_audit.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    model=mujoco.MjModel.from_xml_string('<mujoco><worldbody><body name="base_link"><body name="finger" pos=".2 0 0">'
        '<joint name="slide" type="slide" axis="1 0 0"/><geom type="sphere" size=".1"/></body></body></worldbody></mujoco>')
    poses={'base_link':(np.array([4.,5.,0.]),[1,0,0,0]),'finger':(np.array([4.3,5,0]),[1,0,0,0])}
    assert module.compare(model,{'slide':.1},poses)['max_relative_position_error_m']<1e-12
    poses['finger']=(np.array([4.4,5,0]),[1,0,0,0])
    assert module.compare(model,{'slide':.1},poses)['max_relative_position_error_m']==pytest.approx(.1)
