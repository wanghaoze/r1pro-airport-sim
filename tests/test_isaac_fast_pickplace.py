from types import SimpleNamespace
import numpy as np
from r1pro_teleop.real2sim.isaac_fast_pickplace import FastPickPlace, aligned_pad_rotation
from r1pro_teleop.real2sim.isaac_lab_visuals import obj_mesh
from r1pro_teleop.real2sim.isaac_command_timing import substep_commands
from r1pro_teleop.real2sim.isaac_rubber_contacts import nominal_patch_radius
from r1pro_teleop.real2sim.isaac_path_stability import path_stability
from r1pro_teleop.real2sim.isaac_diverse_pickplace import DiversePickPlace, supported_arc_goal
from scipy.spatial.transform import Rotation
import pytest


def test_preadjustment_remains_in_pick_without_new_prompt_or_trimmed_time():
    teacher=DiversePickPlace.__new__(DiversePickPlace)
    teacher.preparation_start=40;teacher.spans=[]
    teacher.o=SimpleNamespace(action=None)
    saved={}
    teacher.r=SimpleNamespace(frames=120,event=lambda *a,**kw:None,
                              write=lambda name,rows:saved.update(rows=rows))
    start=teacher.begin_timed('Pick up the tray')
    assert start==40 and teacher.core_start==120
    teacher.r.frames=180
    teacher.finish_timed('Pick up the tray',start,True)
    span=saved['rows'][0]
    assert span['frames']==140 and span['simulation_seconds']==7
    assert span['core_motion_frames']==60 and span['core_motion_seconds']==3
    assert span['includes_supported_preadjustment']
    assert teacher.begin_timed('Place the tray')==180


def test_failed_preadjustment_registry_never_moves_or_resets_live_tray():
    teacher=DiversePickPlace.__new__(DiversePickPlace)
    teacher.fixed_base_world=[.3,0,0];teacher.grasp_pitch_degrees=-30.
    teacher.contact_along_edge_offset_m=.02
    teacher.obs=lambda:dict(tray_pose=np.array([[.85,0,.8,1,0,0,0]]))
    saved={};teacher.r=SimpleNamespace(yaw=lambda q:0.,write=lambda name,rows:saved.update(registry=rows),
        boundary_footprints={'tray_0':np.array([[x,y,0] for x in (-.28,.28) for y in (-.215,.215)])},
        context=dict(yaw_world=np.pi/2,center_world=[.85,0,0],dimensions_m=[1.2,.6,.8]))
    teacher.goals=lambda *a:dict(left=(np.array([.85,.2,.875]),np.eye(3)),right=(np.array([.85,-.2,.875]),np.eye(3)))
    def fail(*a,**kw):raise ValueError('private_reachability_only')
    teacher.solve=fail
    teacher.move=lambda *a,**kw:pytest.fail('must not command an unavailable path')
    with pytest.raises(Exception,match='diverse_single_arm_preadjustment_paths_unavailable'):
        teacher.supported_preadjustment()
    assert len(saved['registry'])==18 and all(not r['path_available'] for r in saved['registry'])
    assert teacher.grasp_pitch_degrees==-30. and teacher.contact_along_edge_offset_m==.02


def test_changing_wrist_pitch_preserves_rigid_pad_contact_arc():
    center=np.array([.85,.04,.8]);target=center+[-.02,-.04,0]
    offset=np.array([0,0,.00811]);R=aligned_pad_rotation(np.deg2rad(75),'left',0.)
    p=center+[-.2,.05,.075]-R@offset
    for u in np.linspace(0,1,13):
        tcp,orientation=supported_arc_goal(center,target,(p,R),np.deg2rad(-75),u,np.deg2rad(-30),offset)
        expected=center+u*(target-center)+Rotation.from_euler('z',np.deg2rad(-75)*u).as_matrix()@(p+R@offset-center)
        np.testing.assert_allclose(tcp+orientation@offset,expected,atol=1e-12)


def test_supported_planar_arc_keeps_grasp_pitch_and_contact_height():
    center=np.array([.85,.04,.8]);offset=np.array([0,0,.00811])
    rotation=aligned_pad_rotation(np.deg2rad(75),'left',0.)
    p=center+[-.2,.05,.075]-rotation@offset
    for u in np.linspace(0,1,31):
        tcp,R=supported_arc_goal(center,center,(p,rotation),-1.3,u,0.,offset)
        assert np.isclose((tcp+R@offset)[2],.875)
        np.testing.assert_allclose(R[2,:],rotation[2,:],atol=1e-12)


def test_planar_feedback_cannot_wind_up_or_command_vertical_correction():
    from r1pro_teleop.real2sim.isaac_diverse_pickplace import bounded_planar_correction
    correction=np.zeros(3)
    for _ in range(1000):
        correction=bounded_planar_correction(correction,[-.2,-.1,.1])
        assert np.linalg.norm(correction)<=.02000000001 and correction[2]==0.
    before=np.linalg.norm(correction)
    for _ in range(50):correction=bounded_planar_correction(correction,[0,0,0])
    assert np.linalg.norm(correction)<before*.01


def test_supported_center_projects_entire_rotation_footprint_inside_existing_gate():
    from r1pro_teleop.real2sim.isaac_diverse_pickplace import supported_center_for_yaw
    from r1pro_teleop.real2sim.isaac_collision_footprint import maximum_union_overhang
    vertices=np.array([[x,y,0] for x in (-.28,.28) for y in (-.215,.215)])
    table=dict(yaw_world=np.pi/2,center_world=[.85,0,0],dimensions_m=[1.2,.6,.8])
    for yaw in np.linspace(0,np.pi/2,91):
        # A rectangular bounding proxy has an infeasible short interval near
        # 38 degrees; actual bevelled collision vertices are checked natively.
        try:center=supported_center_for_yaw([.9,.04,.8],vertices,yaw,table)
        except Exception as exc:
            assert 'footprint_unavailable' in str(exc);continue
        points=vertices@Rotation.from_euler('z',yaw).as_matrix().T+center
        assert maximum_union_overhang(points,[table])<=.0500000001


def test_supported_yaw_reference_ramps_without_accumulating_or_overshooting():
    from r1pro_teleop.real2sim.isaac_diverse_pickplace import supported_yaw_reference
    assert np.isclose(supported_yaw_reference(1.3,0.,1)[0],1.29)
    assert np.isclose(supported_yaw_reference(1.3,0.,1000)[0],1.18)
    assert np.isclose(supported_yaw_reference(.04,0.,1000)[0],0.)
    next_angle,error=supported_yaw_reference(-np.pi+.01,np.pi-.01,100)
    assert np.isclose(error,-.02) and np.isclose(next_angle,-np.pi-.01)


def test_supported_center_does_not_fight_long_table_axis_motion():
    from r1pro_teleop.real2sim.isaac_diverse_pickplace import compliant_long_axis_center
    table=dict(yaw_world=np.pi/2,center_world=[.85,0,0],dimensions_m=[1.2,.6,.8])
    target=np.array([.85,.04,.8]);actual=np.array([.87,.1,.81])
    np.testing.assert_allclose(compliant_long_axis_center(target,actual,table),[.85,.1,.8])


def test_pad_normal_has_no_along_rim_component_at_random_yaws():
    for yaw in (-.48,0.,.48,3.14):
        along=np.array([np.cos(yaw),np.sin(yaw),0.])
        for side in ('left','right'):
            for pitch in (-30.,0.,20.):
                rotation=aligned_pad_rotation(yaw,side,pitch)
                assert abs(along@rotation[:,1])<1e-12
                np.testing.assert_allclose(rotation.T@rotation,np.eye(3),atol=1e-12)
                assert np.isclose(np.linalg.det(rotation),1.)


def test_reference_velocity_limit_keeps_raw_diagnostics_grippers_and_base():
    events=[];teacher=FastPickPlace.__new__(FastPickPlace)
    teacher.r=SimpleNamespace(command=np.zeros(19),event=lambda name,**data:events.append((name,data)))
    target=np.linspace(-2.,2.,19);target[[7,15]]=[.08,.04];original=target.copy()
    teacher.send_timed_target(target);arms=np.r_[0:7,8:15]
    assert np.max(abs(teacher.r.command[arms]))/.05<=1.5+1e-12
    np.testing.assert_array_equal(teacher.r.command[[7,15,16,17,18]],target[[7,15,16,17,18]])
    np.testing.assert_array_equal(target,original)
    np.testing.assert_array_equal(events[0][1]['raw_ik_target'],original)
    np.testing.assert_array_equal(events[0][1]['submitted_mobile19'],teacher.r.command)
    # One shared progress factor preserves the requested bilateral direction.
    active=arms[abs(target[arms])>1e-10]
    np.testing.assert_allclose(teacher.r.command[active]/target[active],.075/abs(target[arms]).max())


def test_native_substep_interpolation_records_real_last_target_without_overshoot():
    a=np.linspace(-.3,.3,19);b=a+.075;commands=substep_commands(a,b)
    assert commands.shape==(25,19)
    np.testing.assert_allclose(commands[-1],b)
    np.testing.assert_allclose(np.diff(np.vstack([a,commands]),axis=0),.003,atol=1e-12)
    assert np.all(commands>=a) and np.all(commands<=b+1e-12)
    np.testing.assert_allclose(substep_commands(b,b),np.repeat(b[None],25,axis=0))


def test_obj_negative_indices_keep_face_winding(tmp_path):
    p=tmp_path/'face.obj';p.write_text('v 0 0 0\nv 1 0 0\nv 0 1 0\nf -3 -2 -1\n')
    vertices,counts,indices=obj_mesh(p)
    assert counts==[3] and indices==[0,1,2]
    assert np.cross(vertices[1]-vertices[0],vertices[2]-vertices[0])[2]>0


def test_soft_finger_patch_preserves_nominal_torque_bound_without_glue():
    radius=nominal_patch_radius(1.2,.005)
    assert np.isclose(radius,.004166666666666667)
    assert np.isclose(1.2*radius*10,.005*10)
    assert 1.2*radius*0==0


def test_path_review_finds_transient_tilt_despite_level_endpoints():
    poses=np.zeros((161,3,7));poses[:,:,3]=1.;poses[:,:,2]=.8
    q=Rotation.from_euler('y',10.,degrees=True).as_quat();poses[30,0,3:]=q[[3,0,1,2]]
    hands=np.zeros((161,2,7));hands[:,:,3]=1.
    trace=dict(tray_pose=poses,rigid_pose=hands,finger_contact_force=np.zeros((160,25,3,2)))
    spans=[dict(prompt='Pick up the tray',start=20,end=80),dict(prompt='Place the tray',start=80,end=140)]
    result=path_stability(trace,spans,dict(sensor_paths=['/left_gripper_link','/right_gripper_link']))
    pick=result['measurements']['Pick up the tray']
    assert np.isclose(pick['maximum_tilt_deg'],10.) and np.isclose(pick['endpoint_tilt_deg'],0.)
    assert np.isclose(pick['maximum_angular_speed_deg_s'],200.)
    assert result['user_defined_hard_stability_threshold'] is None


def test_physics_only_result_cannot_qualify_as_video_demo(tmp_path):
    import json
    import runpy
    from pathlib import Path
    (tmp_path/'result.json').write_text(json.dumps(dict(scope='physics_only_probe_not_video_demo',passed=True)))
    audit=runpy.run_path(str(Path(__file__).resolve().parents[1]/'scripts/audit_isaacsim_fast_pickplace.py'))['audit']
    result=audit(tmp_path)
    assert result['passed'] is False
    assert 'physics_only_probe_is_not_a_closed_video_demo' in result['errors']


def test_failed_pair_cannot_create_training_segments(tmp_path,monkeypatch):
    pytest.importorskip('fcntl')  # This producer is a Linux server entry point.
    import json,runpy
    from pathlib import Path
    root=Path(__file__).resolve().parents[1]
    monkeypatch.syspath_prepend(str(root/'scripts'))
    case=tmp_path/'failed_case';case.mkdir()
    (case/'result.json').write_text(json.dumps(dict(video_demo_complete=False)))
    export=runpy.run_path(str(root/'scripts/collect_isaac_fixed_pickplace.py'))['export_pair']
    target=tmp_path/'dataset_run'
    with pytest.raises(ValueError,match='native_pair_audit_failed'):
        export(target,case,dict(code=str(root)))
    assert not target.exists()


def test_place_rejects_missing_actual_hold_without_regrasp_or_pose_reset():
    teacher=FastPickPlace.__new__(FastPickPlace)
    teacher.obs=lambda:dict(finger_force=np.zeros((3,2)),long_edge_sign=np.zeros((3,2)),table_force=np.ones(3))
    with pytest.raises(Exception,match='place_initial_actual_opposed_hold_missing'):
        teacher.place()


def test_fixed_base_failure_does_not_search_another_station(monkeypatch):
    from r1pro_teleop.single_tray_3table import observer
    monkeypatch.setattr(observer,'table_front_region_violation',lambda *a:False)
    teacher=FastPickPlace.__new__(FastPickPlace);teacher.fixed_base_world=[.3,0.,0.]
    teacher.obs=lambda:dict(tray_pose=np.array([[.85,0.,.8,1.,0.,0.,0.]]))
    teacher.r=SimpleNamespace(yaw=lambda q:0.,size=np.array([[.56,.43,.105]]))
    teacher.goals=lambda *a:dict(left=(np.array([.85,.205,.875]),np.eye(3)),right=(np.array([.85,-.205,.875]),np.eye(3)))
    attempted=[]
    def fail(*a,base_world=None):
        attempted.append(base_world.copy());raise ValueError('private_ik_failed')
    teacher.solve=fail
    with pytest.raises(Exception,match='fixed_base_sample_path_unavailable'):
        teacher.choose_station(0,{})
    assert len(attempted)==1
    np.testing.assert_array_equal(attempted[0],[.3,0.,0.])


def test_place_records_each_actual_held_initial_state_without_canonical_reset():
    for height in (.94,1.02):
        teacher=FastPickPlace.__new__(FastPickPlace);teacher.held=set();saved={}
        state=np.linspace(-.5,.5,19);pose=np.array([.85,.01,height,1.,0.,0.,0.])
        teacher.obs=lambda:dict(state=state,tray_pose=pose[None],finger_force=np.array([[4.,5.]]),long_edge_sign=np.array([[1.,-1.]]),table_force=np.zeros(1))
        teacher.r=SimpleNamespace(frames=199,write=lambda name,row:saved.update(row))
        def stop(prompt):raise RuntimeError('stopped_before_any_motion')
        teacher.begin_timed=stop
        with pytest.raises(RuntimeError,match='stopped_before_any_motion'):teacher.place()
        np.testing.assert_array_equal(saved['state'],state)
        np.testing.assert_array_equal(saved['tray_pose'],pose)
        assert saved['reset_between_pick_and_place'] is False


def test_episode_front_search_keeps_original_front_for_large_tray_yaw():
    from r1pro_teleop.real2sim.isaac_fast_pickplace import episode_front_stations
    from r1pro_teleop.single_tray_3table.observer import table_front_region_violation
    table=dict(table_id='front_left',center_world=[.85,0.,0.],dimensions_m=[1.2,.6,.8],yaw_world=np.pi/2)
    yaw=np.deg2rad(75)
    candidates=list(episode_front_stations([.85,.04,.801],yaw,table))
    assert candidates
    assert all(not table_front_region_violation(table,np.r_[b[:2],0.]) for b in candidates)
    assert all(abs(.5*np.arctan2(np.sin(2*(b[2]-yaw)),np.cos(2*(b[2]-yaw))))<=np.deg2rad(15)+1e-10 for b in candidates)
    assert any(np.isclose(b[2],np.deg2rad(60)) for b in candidates)
    assert len(set(tuple(np.round(b,9)) for b in candidates))==len(candidates)


def test_joint_front_search_returns_same_station_used_for_whole_path():
    teacher=FastPickPlace.__new__(FastPickPlace);teacher.search_front_stations=True
    teacher.obs=lambda:dict(tray_pose=np.array([[.85,.04,.8,1.,0.,0.,0.]]))
    events=[];attempted=[]
    teacher.r=SimpleNamespace(yaw=lambda q:np.deg2rad(75),event=lambda *a,**kw:events.append(kw))
    teacher.goals=lambda *a:dict(left=(np.array([.85,.24,.875]),np.eye(3)),right=(np.array([.85,-.16,.875]),np.eye(3)))
    teacher.solve=lambda *a,base_world=None:attempted.append(base_world.copy())
    table=dict(table_id='front_left',center_world=[.85,0.,0.],dimensions_m=[1.2,.6,.8],yaw_world=np.pi/2)
    base,face=teacher.choose_station(0,table)
    assert len(attempted)==39 and face==base[2]
    assert all(np.array_equal(b,base) for b in attempted)
    assert events[-1]['approach_and_compensated_lift_and_place_checked']


def test_preparation_station_requires_single_arm_path_not_bilateral_grasp():
    teacher=DiversePickPlace.__new__(DiversePickPlace);teacher.fixed_base_world=None
    teacher.obs=lambda:dict(tray_pose=np.array([[.85,.04,.801,1.,0.,0.,0.]]))
    saved={};calls=[]
    teacher.r=SimpleNamespace(context=dict(table_id='front_left',center_world=[.85,0.,0.],dimensions_m=[1.2,.6,.8],yaw_world=np.pi/2),
                              write=lambda name,row:saved.update({name:list(row)}))
    def single_arm(*,plan_only,base_world):
        assert plan_only and np.array_equal(teacher.fixed_base_world,base_world)
        calls.append(base_world.copy())
        return ['left']
    teacher.supported_preadjustment=single_arm
    teacher.solve=lambda *a,**kw:pytest.fail('must not demand bilateral reach before single-arm preparation')
    base=teacher.choose_supported_station()
    np.testing.assert_array_equal(base,calls[0]);assert teacher.fixed_base_world is None
    assert saved['supported_station_registry.json'][0]['candidate_sides']==['left']


def test_released_arm_reset_preserves_base_and_actual_tray():
    teacher=DiversePickPlace.__new__(DiversePickPlace);teacher.held=set()
    teacher.initial=np.arange(19,dtype=float)/10
    command=np.arange(19,dtype=float)/20;before=command[16:].copy()
    pose=np.array([.85,.21,.8,1.,0.,0.,0.]);events=[];supports=[]
    teacher.r=SimpleNamespace(command=command,event=lambda name,**kw:events.append(name))
    teacher.obs=lambda:dict(tray_pose=pose[None].copy(),state=teacher.r.command.copy())
    teacher.stable_support=lambda:supports.append(True)
    teacher.joints=lambda target:setattr(teacher.r,'command',target.copy())
    teacher.reset_released_arms()
    np.testing.assert_array_equal(teacher.r.command[16:],before)
    np.testing.assert_array_equal(teacher.r.command[[7,15]],[.08,.08])
    np.testing.assert_array_equal(teacher.obs()['tray_pose'][0],pose)
    assert len(supports)==2 and events[-1]=='released_arm_reset_complete'


def test_arm_reset_refuses_a_still_held_tray():
    teacher=DiversePickPlace.__new__(DiversePickPlace);teacher.held={'left'}
    with pytest.raises(Exception,match='arm_reset_requires_released_tray'):
        teacher.reset_released_arms()
