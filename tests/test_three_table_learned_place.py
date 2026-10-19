from types import SimpleNamespace
import numpy as np
from r1pro_teleop.single_tray_3table.learned import place_completion,LearnedThreeTable


def source_geometry(excess):
    tables=[dict(table_id=n,center_world=[0,0,0],dimensions_m=[1.2,.6,.8],yaw_world=0.)
        for n in ('front_left','front_right','rear')]
    scene=dict(target_table='front_left',tables=tables,loaded_push_target={'supported_boundary_margin_m':.05})
    corners=np.array([[x,y,z] for x in (-.1,.6+excess) for y in (-.1,.1) for z in (.8,.9)])
    numeric=dict(table_contact_counts=np.array([1,0,0]),tray_corners_world=corners,
        tray_long_axis_world=np.array([1.,0,0]),robot_forward_world=np.array([1.,0,0]))
    return scene,numeric,dict(floor_contact=np.array([0]))


def test_declared_50mm_footprint_does_not_reintroduce_5mm_or_withdrawal_gate():
    scene,numeric,obs=source_geometry(.049)
    assert place_completion(numeric,obs,scene,opposed_seen=True,released=True,front_violation=False)
    scene,numeric,obs=source_geometry(.051)
    assert not place_completion(numeric,obs,scene,opposed_seen=True,released=True,front_violation=False)


def test_place_requires_target_support_no_floor_actual_front_and_release():
    scene,numeric,obs=source_geometry(0.)
    obs['floor_contact'][0]=1
    assert not place_completion(numeric,obs,scene,opposed_seen=True,released=True,front_violation=False)
    obs['floor_contact'][0]=0;numeric['table_contact_counts']=np.array([0,0,2])
    assert not place_completion(numeric,obs,scene,opposed_seen=True,released=True,front_violation=False)
    numeric['table_contact_counts'][0]=1
    assert not place_completion(numeric,obs,scene,opposed_seen=True,released=True,front_violation=True)
    assert not place_completion(numeric,obs,scene,opposed_seen=True,released=False,front_violation=False)


def test_model_carry_does_not_apply_target_side_operation_guard(monkeypatch):
    import r1pro_teleop.single_tray_3table.learned as module
    scene,numeric,obs=source_geometry(0.);numeric['table_contact_counts']=np.zeros(3,int)
    scene.update(tray={'size':[.56,.43,.105]},source_table='rear')
    obs['gripper_contact_force']=np.array([[2.,2.]])
    obs.update(table_contact=np.array([0]),min_z=np.array([.9]))
    numeric.update(gripper_contact_force=np.array([2.,2.]),gripper_tray_contact_points_local=np.array([[[0,-.205,.075]],[[0,.205,.075]]]),
        gripper_tray_contact_normals_local=np.array([[[0,-1.,0]],[[0,1.,0]]]),gripper_tray_contact_active=np.ones((2,1),bool))
    r=SimpleNamespace(steps=3,cfg=SimpleNamespace(fps=20,criteria=SimpleNamespace(contact_n=.5,lifted_m=.04),gripper_open_m=.1),
        sim=SimpleNamespace(target=np.zeros(16)),observation=lambda:obs)
    learner=LearnedThreeTable.__new__(LearnedThreeTable);learner.scene=scene;learner.action='place_empty';learner.opposed_seen=False
    learner.grasp_contact_ticks=np.array([2,2]);learner.grasp_sample_step=2;learner.initial_bottom=.8
    monkeypatch.setattr(module,'contact_snapshot',lambda *a:numeric);monkeypatch.setattr(module,'opposed_contact',lambda *a:True)
    def forbidden(*a):raise AssertionError('front operation guard applied to carried transit')
    monkeypatch.setattr(module,'table_front_region_violation',forbidden)
    assert learner.endpoint(r,None) is False and learner.opposed_seen is True
