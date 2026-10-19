"""Fresh one-tray variants of the existing three-table layout; no old relabeling."""
from dataclasses import replace
from pathlib import Path
import copy,json,math,hashlib
import xml.etree.ElementTree as ET
import numpy as np
from scipy.spatial.transform import Rotation
from .scene import generate_scene,LabSceneConfig,fmt,sha,passenger_load
from ..airport_mobile import make_mobile_scene
from ..airport_fsm.geometry import rectangle,rz
from ..airport_fsm.contracts import json_default

PROFILE='three_table_single_tray_action3_v1'
RULE_REVISION='20261006_loaded_handover_left_motion3cm_v3'
TABLE_IDS=('front_left','front_right','rear')

def passenger_load_three_table(sim,scene):
    """Generate the old passenger layout in the ACTUAL horizontal tray frame.

    This is one excluded environmental transition before any next physics
    step. Only passenger state changes; the same live robot/tray are kept.
    """
    import mujoco
    model,data=sim.model,sim.data
    before_q=data.qpos.copy();before_v=data.qvel.copy()
    before_ctrl=data.ctrl.copy();stamp=float(data.time)
    tray=data.body('tray');origin=tray.xpos.copy()
    actual_yaw=float(math.atan2(tray.xmat.reshape(3,3)[1,0],tray.xmat.reshape(3,3)[0,0]))
    yaw_delta=actual_yaw-math.pi/2
    rotation=Rotation.from_euler('z',yaw_delta)
    journal=passenger_load(sim,scene)
    for item in scene['payloads']:
        if item['flex']:
            fid=int(mujoco.mj_name2id(model,mujoco.mjtObj.mjOBJ_FLEX,item['name']))
            if fid<0:raise ValueError('passenger_model_identity_missing:'+item['name'])
            adr=int(model.flex_vertadr[fid]);count=int(model.flex_vertnum[fid])
            bodies=np.unique(model.flex_vertbodyid[adr:adr+count])
            positions={int(b):data.body(int(b)).xpos.copy() for b in bodies}
            for bid in bodies:
                bid=int(bid);position=positions[bid]
                shift=origin+rotation.apply(position-origin)-position
                for jid in range(int(model.body_jntadr[bid]),int(model.body_jntadr[bid]+model.body_jntnum[bid])):
                    if model.jnt_type[jid]!=mujoco.mjtJoint.mjJNT_SLIDE:
                        raise ValueError('passenger_flex_translation_joint_required')
                    qadr=int(model.jnt_qposadr[jid])
                    data.qpos[qadr]+=float(model.jnt_axis[jid]@shift)
        else:
            jid=model.joint(item['joint']).id;qadr=int(model.jnt_qposadr[jid])
            data.qpos[qadr:qadr+3]=origin+rotation.apply(data.qpos[qadr:qadr+3]-origin)
            old=Rotation.from_quat(data.qpos[qadr+3:qadr+7][[1,2,3,0]])
            data.qpos[qadr+3:qadr+7]=(rotation*old).as_quat()[[3,0,1,2]]
    qindices=np.asarray(journal['qpos_indices'],int);vindices=np.asarray(journal['qvel_indices'],int)
    qmask=np.ones(model.nq,bool);qmask[qindices]=False
    vmask=np.ones(model.nv,bool);vmask[vindices]=False
    if not (np.array_equal(before_q[qmask],data.qpos[qmask]) and np.array_equal(before_v[vmask],data.qvel[vmask])
            and np.array_equal(before_ctrl,data.ctrl) and stamp==data.time):
        raise ValueError('passenger_load_changed_robot_tray_or_control')
    mujoco.mj_forward(model,data)
    journal.update(qpos_before=before_q[qindices].tolist(),qpos_after=data.qpos[qindices].tolist(),
        qvel_before=before_v[vindices].tolist(),qvel_after=data.qvel[vindices].tolist(),
        passenger_layout_reference_yaw_rad=math.pi/2,actual_tray_yaw_rad=actual_yaw,
        passenger_layout_rotation_rad=yaw_delta,layout_bound_to_actual_tray_horizontal_frame=True)
    return journal

def table_front(table):
    """The original aisle-facing table front, not a short-side approach."""
    return np.array([1.,0.,0.]) if table['table_id']=='rear' else np.array([-1.,0.,0.])

def sample_pose(table,seed,*,maximum_attempts=128):
    rng=np.random.default_rng(np.random.SeedSequence([int(seed),918]))
    centre=np.asarray(table['center_world'],float);size=np.asarray(table['dimensions_m'],float)
    rejected=[]
    for attempt in range(maximum_attempts):
        yaw=float(rng.uniform(-math.pi,math.pi))
        xy=centre[:2]+rng.uniform([-.025,-.12],[.025,.12])
        corners=rectangle([*xy,.801],yaw,[.56,.43,.105])
        local=(corners-centre[:2])@rz(table['yaw_world'])[:2,:2]
        if np.any(np.abs(local)>size[:2]/2-.008):
            rejected.append(dict(attempt=attempt,reason='initial_full_footprint_outside_original_table'));continue
        return dict(position_world=[float(xy[0]),float(xy[1]),.801],yaw_world=yaw,roll=0.,pitch=0.,
            sampling_attempt=attempt,rejections=rejected,horizontal=True,
            geometric_full_table_support=True,grasp_feasibility_status='pending_private_opposed_long_rim_screen')
    raise ValueError('random_single_tray_full_footprint_sampling_exhausted')

def generate_three_table_scene(output,parent_scene,parent_manifest,seed,*,source_table='rear',target_table='front_left',canonical_split=None,split_registry=None,
        source_base_distance_m=.65,target_base_standoff_m=.25,target_tray_x=None,target_base_yaw=0.,target_yaw_offset_rad=0.):
    output=Path(output).resolve();parent_scene=Path(parent_scene).resolve();parent_manifest=Path(parent_manifest).resolve()
    parent=json.loads(parent_scene.read_text());manifest=json.loads(parent_manifest.read_text())
    entry=next(row for row in manifest['scenes'] if row['scene_id']==parent['scene_id'])
    assert (parent_manifest.parent/entry['json']).resolve()==parent_scene
    tables=copy.deepcopy(parent['tables'])
    if {t['table_id'] for t in tables}!=set(TABLE_IDS):raise ValueError('original_three_table_layout_required')
    if any(t['dimensions_m']!=[1.2,.6,.8] for t in tables):raise ValueError('original_table_dimensions_required')
    if source_table==target_table or source_table not in TABLE_IDS or target_table not in TABLE_IDS:raise ValueError('different_registered_source_target_tables_required')
    # The first task route is fixed and observable from the registered DAG.
    # Do not assign hidden random target labels to the same visual state.
    if (source_table,target_table)!=('rear','front_left'):raise ValueError('first_demo_fixed_registered_rear_to_front_left_route_required')
    if split_registry is None:raise ValueError('registered_parent_split_registry_required')
    split_registry=Path(split_registry).resolve();registered_splits=json.loads(split_registry.read_text())
    if parent['scene_id'] not in registered_splits:raise ValueError('parent_missing_from_original_split_registry')
    original_split=registered_splits[parent['scene_id']]
    if canonical_split is not None and canonical_split!=original_split:raise ValueError('random_variant_parent_split_changed')
    split={'validation':'val'}.get(original_split,original_split)
    if split not in ('train','val','test'):raise ValueError('parent_scene_split_required')
    source=next(t for t in tables if t['table_id']==source_table);target=next(t for t in tables if t['table_id']==target_table)
    # These poses seed the old planner; they are not a restricted search box
    # or a replacement for its collision-checked arrival station search.
    if not np.isfinite([source_base_distance_m,target_base_standoff_m,target_base_yaw,target_yaw_offset_rad]).all() or source_base_distance_m<=0 or target_base_standoff_m<0 or abs(target_yaw_offset_rad)>np.deg2rad(15):
        raise ValueError('invalid_front_approach_hint')
    sampled=sample_pose(source,seed);normal=table_front(source)
    initial=np.asarray(sampled['position_world']);base=initial+normal*source_base_distance_m;base[2]=0.
    base_yaw=math.pi if source_table=='rear' else 0.
    config=LabSceneConfig(seed=int(seed),split=split,robot_x=float(base[0]),robot_y=float(base[1]),
        tray_y=0.,tray_x=.85,gripper_kp=10000.,arm_kp=1000.,friction_impratio=100.,lift_clearance=.28)
    lab=generate_scene(output,config,require_blender=True)
    tree=ET.parse(lab['xml']);root=tree.getroot();world=root.find('worldbody')
    # Keep unloaded passenger props separate in their offstage parking area.
    # The old bag at Y2.75 and coat at Y2.95 overlapped by 12.5 mm including
    # the flex radius; moving only their declared initial park fixes that.
    coat=next((p for p in lab['payloads'] if p['kind']=='coat' and p['flex']),None)
    if coat is not None:
        parked=np.asarray(coat['parked_position'],float)+np.array([0.,.25,0.])
        world.find("flexcomp[@name='passenger_coat']").set('pos',fmt(parked))
        coat['parked_position']=parked.tolist()
    original=world.find("body[@name='table']");world.remove(original)
    table_source_sha=hashlib.sha256(ET.tostring(original)).hexdigest()
    for table in tables:
        body=copy.deepcopy(original);body.set('name',table['table_id'])
        body.set('pos',fmt(table['center_world']));body.set('quat',fmt(Rotation.from_euler('z',table['yaw_world']).as_quat()[[3,0,1,2]]))
        for node in body.iter():
            if node is not body and node.get('name'):node.set('name',table['table_id']+'__'+node.get('name'))
        world.append(body)
    tray=world.find("body[@name='tray']");tray.set('pos',fmt(initial));tray.set('quat',fmt(Rotation.from_euler('z',sampled['yaw_world']).as_quat()[[3,0,1,2]]))
    robot=world.find("body[@name='base_link']");robot.set('pos',fmt(base));robot.set('quat',fmt(Rotation.from_euler('z',base_yaw).as_quat()[[3,0,1,2]]))
    ET.indent(root);tree.write(lab['xml'],encoding='unicode')
    # Restore the existing navigation/tucked pose as the declared initial
    # robot state. A fresh no-keyframe home can already intersect this tray.
    # This is model generation before the first tick, never a live reset.
    import mujoco
    initial_model=mujoco.MjModel.from_xml_path(lab['xml']);initial_data=mujoco.MjData(initial_model)
    initial_joints={}
    for side in ('left','right'):
        values=(-.35,0.,0.,-1.70,0.,.9,0.)
        for i,value in enumerate(values,1):
            name=f'{side}_arm_joint{i}';jid=initial_model.joint(name).id
            initial_data.qpos[initial_model.jnt_qposadr[jid]]=value
            initial_data.ctrl[initial_model.actuator(name+'_target').id]=value
            initial_joints[name]=value
        for finger in (1,2):
            name=f'{side}_gripper_finger_joint{finger}';jid=initial_model.joint(name).id
            initial_data.qpos[initial_model.jnt_qposadr[jid]]=.05;initial_joints[name]=.05
        initial_data.ctrl[initial_model.actuator(side+'_gripper_target').id]=.1
    keyframe=ET.SubElement(root,'keyframe')
    ET.SubElement(keyframe,'key',name='teleop_home',qpos=fmt(initial_data.qpos),ctrl=fmt(initial_data.ctrl))
    ET.indent(root);tree.write(lab['xml'],encoding='unicode')
    mobile=output/'mobile.xml';make_mobile_scene(lab['xml'],mobile)
    target_normal=table_front(target);target_base=np.asarray(target['center_world'],float)+target_normal*(.3+target_base_standoff_m)
    target_base[2]=0.
    final_yaw=target_base_yaw+target_yaw_offset_rad
    target_position=np.asarray(target['center_world'],float)+np.array([0.,.05,.801])
    if target_tray_x is not None:
        if not np.isfinite(target_tray_x):raise ValueError('nonfinite_target_tray_x')
        target_position[0]=float(target_tray_x)
    target_corners=rectangle(target_position,final_yaw,[.56,.43,.105])
    target_local=(target_corners-np.asarray(target['center_world'])[:2])@rz(target['yaw_world'])[:2,:2]
    if np.any(np.abs(target_local)>np.asarray(target['dimensions_m'])[:2]/2-.008):raise ValueError('full_target_footprint_outside_original_table')
    left_hint=np.array([-math.sin(target_base_yaw),math.cos(target_base_yaw)])
    table_axes=rz(target['yaw_world'])[:2,:2]
    table_left_extent=float(np.sum(np.abs(left_hint@table_axes)*np.asarray(target['dimensions_m'])[:2]/2))
    # Legacy geometry has three goal slots; only Operation(tray=0) is executed.
    legacy=copy.deepcopy(parent);legacy.update(scene_id=f"{parent['scene_id']}__single3_{int(seed)}",seed=int(seed),split=split,
        task_profile=PROFILE,camera=copy.deepcopy(lab['camera']),tables=tables,
        trays=[dict(tray_id='tray',dimensions_m=[.56,.43,.105],support_table=source_table,support_parent=source_table,**sampled)])
    legacy['robot']=dict(base_position_world=base.tolist(),base_yaw_world=base_yaw,base_control_available=True,
        home_key=None,wrist_profile='direct_camera_front')
    legacy.update(xml_sha256=sha(mobile),xml=str(mobile),scene_file='mobile.xml',base_control_available=True,
        base_model='simulation_ideal_planar_position_servo_v1',real_base_driver_available=False)
    result=copy.deepcopy(lab);result.update(schema='airport_three_table_single_tray_scene/1',task_profile=PROFILE,
        rule_revision=RULE_REVISION,task_rule_revision=RULE_REVISION,
        final_orientation_definition='tray_long_axis_parallel_actual_horizontal_robot_forward_mod_pi',
        scene_id=legacy['scene_id'],seed=int(seed),split=split,source='simulation/program_generated',
        parent_scene_id=parent['scene_id'],parent_scene_json=str(parent_scene),parent_scene_json_sha256=sha(parent_scene),
        parent_manifest=str(parent_manifest),parent_manifest_sha256=sha(parent_manifest),parent_split=original_split,
        split_alias={'validation':'val'},canonical_split_registry=str(split_registry),
        canonical_split_registry_sha256=sha(split_registry),parent_resource_split=parent.get('split'),
        tables=tables,source_table=source_table,target_table=target_table,initial_tray_pose=sampled,
        initial_robot_pose=dict(position_world=base.tolist(),yaw_world=base_yaw),
        robot_initial_joint_pose=initial_joints,
        robot_initialization_source='old_Runtime_tucked_joint_configuration_at_episode_start',
        offstage_passenger_parking_separation_explicit=True,
        target_robot_pose=dict(position_world=target_base.tolist(),yaw_world=target_base_yaw),
        front_approach_candidates=dict(source_base_distance_m=source_base_distance_m,target_base_standoff_m=target_base_standoff_m,
            hints_only=True,fixed_target_station_override=False,joint_station_grasp_orientation_search_required=True,
            actual_robot_table_collision_check_required=True,side_access_allowed=False),
        place_target=dict(position_world=target_position.tolist(),yaw_world=final_yaw,
            long_axis_parallel_robot_forward=True,orientation_reference='actual_robot_forward',
            planned_pose_is_hint=True,forced_in_grasp_rotation=False,
            angle_tolerance_deg=15.,release_maximum_above_table_m=.02),
        loaded_push_target=dict(table_id=target_table,reference='actual_manipulation_robot_left',
            target='handover_left_motion_then_release',minimum_left_tray_motion_m=.03,
            exact_table_left_endpoint_required=False,completion_reference='actual_tray_translation_after_actual_right_release',
            table_edge_margin_m=0.,
            actual_edge_tolerance_m=.050,goal_edge_tolerance_m=.050,robot_left_hint=left_hint.tolist(),
            push_boundary_grace_revision='20261006_authorized_push_5cm_v1',
            supported_boundary_margin_m=.050,base_drift_m=.050,transient_boundary_extra_m=0.,
            transient_support_grace_s=.3,transient_lowest_corner_gap_m=.001,
            final_boundary_extra_m=0.,strict_geometry_reported_separately=True,
            edge_projection_hint_m=float(np.asarray(target['center_world'])[:2]@left_hint+table_left_extent),
            recompute_with_selected_station=True,
            footprint_within_declared_margin_and_actual_support_required=True,
            strict_full_footprint_result_reported_separately=True),
        loaded_push_control=dict(push_axis_feedback_enabled=False,
            push_axis_feedback_step_rad=math.radians(.5),push_axis_feedback_cap_rad=.10,
            material_reference='capture_command_fk_relative_actual_tray_once_per_hand',
            pause_new_leftward_lead_when_footprint_worsens=True,
            reference_only=True,acceptance_predicates_unchanged=True),
        route_goal_observation_policy='fixed_registered_rear_to_front_left_route',
        pickup_place_grasp_contract=dict(required='two_opposing_long_rims',same_long_rim_forbidden=True,short_rims_forbidden=True),
        pickup_preparation=dict(single_arm_position_or_yaw_adjustment_allowed=True,
            training_prompt='Pick up the tray',included_in_pick_window=True,
            policy_must_execute_preparation=True,implicit_teacher_fallback_allowed=False),
        per_hand_longitudinal_offsets_m=dict(left=0.,right=0.),
        base_mode='planar_mobile_table_front',base_actuated=True,model_action_mask=[True]*19,
        original_table_local_xml_sha256=table_source_sha,scene_generator_sha256=sha(Path(__file__)),
        xml=str(mobile),xml_sha256=sha(mobile),legacy_spec=legacy,
        frame=dict(base_mode='planar_mobile_table_front',side_access_allowed=False),
        sampled_initial_position_only_geometric_verified=True,physical_demo_completed=False)
    result['tray'].update(position=sampled['position_world'],yaw=sampled['yaw_world'],
        goal_position=target_position.tolist(),goal_yaw=final_yaw)
    result['passenger_layout'].update(reference_tray_yaw_rad=math.pi/2,
        orientation_binding='actual_horizontal_tray_yaw_relative_reference',environment_transition_only=True)
    result['place_target']['requested_robot_forward_angle_error_rad']=abs(float(target_yaw_offset_rad))
    (output/'scene.json').write_text(json.dumps(result,default=json_default,indent=2,allow_nan=False))
    (output/'legacy_spec.json').write_text(json.dumps(legacy,default=json_default,indent=2,allow_nan=False))
    return result
