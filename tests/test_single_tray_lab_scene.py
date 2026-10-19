from pathlib import Path
import xml.etree.ElementTree as ET
import numpy as np
import pytest
from r1pro_teleop.single_tray_lab.scene import generate_scene, LabSceneConfig, passenger_load, TEMPLATE

def test_table_collision_geometry_inertia_friction_are_preserved(tmp_path):
    result=generate_scene(tmp_path/'scene',LabSceneConfig(payloads=('laptop',),cloth_enabled=False))
    old=ET.parse(TEMPLATE).getroot().find("worldbody/body[@name='table']")
    new=ET.parse(result['xml']).getroot().find("worldbody/body[@name='table']")
    assert ET.tostring(old)==ET.tostring(new)
    root=ET.parse(result['xml']).getroot()
    assert len(root.findall("worldbody/body[@name='tray']"))==1
    assert len(root.findall("worldbody/body[@name='tray']/geom[@group='3']"))==17
    assert result['table']['top_z']==.8
    assert result['tray']['goal_position'][1]==pytest.approx(.295)
    assert result['frame']['robot_left']==[0,1,0]
    assert result['training_actions']==['pick_empty','place_empty','push_loaded']

def test_passenger_transition_preserves_robot_tray_control_and_time_and_records_all_changes(tmp_path):
    import mujoco
    from r1pro_teleop.core import Simulation
    scene=generate_scene(tmp_path/'scene',LabSceneConfig())
    sim=Simulation(scene['xml'],render=False)
    sim.step()
    before=sim.data.qpos.copy();velocity=sim.data.qvel.copy();control=sim.data.ctrl.copy();stamp=sim.data.time
    journal=passenger_load(sim,scene)
    qmask=np.ones(sim.model.nq,dtype=bool);qmask[journal['qpos_indices']]=False
    vmask=np.ones(sim.model.nv,dtype=bool);vmask[journal['qvel_indices']]=False
    assert np.array_equal(before[qmask],sim.data.qpos[qmask])
    assert np.array_equal(velocity[vmask],sim.data.qvel[vmask])
    assert np.array_equal(control,sim.data.ctrl) and sim.data.time==stamp
    assert journal['robot_tray_time_control_unchanged'] and not journal['training_eligible']
    assert journal['payload_mass_kg']==pytest.approx(2.05)
    assert sim.model.nflex==1
    assert scene['physics_options']['integrator']=='discrete'
    assert len(journal['model_visual_changes'])>0
    for _ in range(10):sim.step()
    assert np.isfinite(sim.data.qpos).all()
    assert not np.array_equal(journal['qpos_after'],sim.data.qpos[journal['qpos_indices']])

def test_unsupported_table_change_and_missing_payload_identity_fail_before_transition(tmp_path):
    from r1pro_teleop.core import Simulation
    with pytest.raises(ValueError,match='original_table_height'):LabSceneConfig(table_top=.75).validate()
    scene=generate_scene(tmp_path/'scene',LabSceneConfig(payloads=('laptop',),cloth_enabled=False))
    sim=Simulation(scene['xml'],render=False);before=sim.data.qpos.copy()
    scene['payloads'][0]['joint']='unknown'
    with pytest.raises(ValueError,match='model_identity_missing'):passenger_load(sim,scene)
    assert np.array_equal(before,sim.data.qpos)
def test_actual_passenger_layout_settles_without_initial_coat_backpack_overlap(tmp_path):
    from r1pro_teleop.single_tray_lab.scene import generate_scene,LabSceneConfig
    from r1pro_teleop.single_tray_lab.control import SingleTrayController
    from r1pro_teleop.single_tray_lab.control import ControlProfile
    from dataclasses import replace
    from r1pro_teleop.single_tray_lab.scene import passenger_load
    scene=generate_scene(tmp_path/'passenger_layout',LabSceneConfig(robot_x=.15,robot_y=-.24))
    profile=replace(ControlProfile.from_scene(scene),soft_payload_penetration_m=.01)
    controller=SingleTrayController(scene['xml'],profile,passenger_loader=lambda sim:passenger_load(sim,scene))
    try:
        controller.tick()
        controller.passenger_load()  # All 1,000 real physics substeps use guards.
        observed=controller.observation()
        assert observed['payload_loaded'] and observed['payload_mass_kg']>1.8
        assert observed['hard_max_penetration']<=controller.p.max_penetration_m
        assert observed['soft_payload_max_penetration']<=controller.p.soft_payload_penetration_m
        assert observed['payload_floor_contacts']==0 and controller._on_table(observed)
    finally:controller.close()

def test_gain_tuning_preserves_motor_joint_and_arm_effort_limits(tmp_path):
    import mujoco
    scene=generate_scene(tmp_path/'motor_budget',LabSceneConfig(gripper_kp=10000,arm_kp=1000))
    model=mujoco.MjModel.from_xml_path(scene['xml'])
    for side in ('left','right'):
        assert model.actuator_forcerange[model.actuator(side+'_gripper_target').id]==pytest.approx([-40,40])
        for finger in (1,2):
            assert model.jnt_actfrcrange[model.joint(f'{side}_gripper_finger_joint{finger}').id]==pytest.approx([-100,100])
        assert model.actuator_forcerange[model.actuator(side+'_arm_joint1_target').id]==pytest.approx([-55,55])
        assert model.actuator_forcerange[model.actuator(side+'_arm_joint7_target').id]==pytest.approx([-18,18])
        for joint in range(1,8):
            actuator=model.actuator(f'{side}_arm_joint{joint}_target').id
            assert model.actuator_gainprm[actuator,0]==1000
            assert model.actuator_biasprm[actuator,2]==-25


def test_explicit_friction_solver_profile_keeps_materials_geometry_and_effort(tmp_path):
    import mujoco
    first=generate_scene(tmp_path/'original_solver',LabSceneConfig(arm_kp=1000,gripper_kp=10000))
    second=generate_scene(tmp_path/'friction_solver',LabSceneConfig(arm_kp=1000,gripper_kp=10000,friction_impratio=100))
    a=mujoco.MjModel.from_xml_path(first['xml']);b=mujoco.MjModel.from_xml_path(second['xml'])
    assert a.opt.impratio==10 and b.opt.impratio==100
    assert a.opt.noslip_iterations==b.opt.noslip_iterations==0
    assert a.opt.cone==b.opt.cone==mujoco.mjtCone.mjCONE_ELLIPTIC
    assert second['numerical_friction_solver_change_explicit'] and not first['numerical_friction_solver_change_explicit']
    for key in ('geom_friction','pair_friction','geom_size','geom_solref','geom_solimp',
                'body_mass','body_inertia','actuator_gainprm','actuator_forcerange'):
        assert np.array_equal(getattr(a,key),getattr(b,key)),key
    with pytest.raises(ValueError,match='discrete_flex_does_not_support_noslip'):
        LabSceneConfig(noslip_iterations=2).validate()

