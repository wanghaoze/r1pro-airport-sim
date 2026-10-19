import ast
import inspect
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import pytest
from r1pro_teleop.single_tray_lab.learned import validate_chunk, completion, LearnedSingleTray,PhysicalHandover,SingleTrayPolicy
from r1pro_teleop.single_tray_lab.control import ControlProfile,SingleTrayController
from r1pro_teleop.vla.policy import PolicyError


@pytest.mark.parametrize('value',[float('nan'),float('inf'),.001])
def test_nonzero_or_nonfinite_base_fails_closed(value):
    a=np.zeros((2,19));a[0,16]=value
    with pytest.raises(PolicyError):validate_chunk(a,-np.ones(16),np.ones(16))


def test_absolute_bounds_reject_before_servo():
    a=np.zeros((1,19));a[0,0]=1.001
    with pytest.raises(PolicyError):validate_chunk(a,-np.ones(16),np.ones(16))
    assert np.array_equal(validate_chunk(np.zeros((1,19)),-np.ones(16),np.ones(16)),np.zeros((1,19)))


def obs():
    return dict(payload_loaded=False,table_contacts=0,tray_bottom_z=.9,gripper_contact_force={'left':1.,'right':1.},
        gripper_openings=np.array([.017,.017]),tray_position=np.array([.85,-.24,.801]),payload_support_contacts=0)


def test_pick_requires_bilateral_airborne_actual_contact():
    o=obs();p=ControlProfile()
    assert completion('pick_empty',o,p,initial_bottom=.8,on_table=False,handover=False)
    o['gripper_contact_force']['left']=0
    assert not completion('pick_empty',o,p,initial_bottom=.8,on_table=False,handover=False)


def test_push_requires_load_release_handover_and_goal():
    o=obs();p=ControlProfile();o.update(payload_loaded=True,payload_support_contacts=2,tray_position=np.array(p.loaded_goal_position),gripper_openings=np.array([.1,.1]),gripper_contact_force={'left':0.,'right':0.})
    o['tray_corners']=np.array([np.asarray(p.loaded_goal_position)+[dx,dy,dz] for dx in (-.215,.215) for dy in (-.28,.28) for dz in (0,.105)])
    assert not completion('push_loaded',o,p,initial_bottom=.8,on_table=True,handover=False)
    assert completion('push_loaded',o,p,initial_bottom=.8,on_table=True,handover=True)
    o['payload_loaded']=False
    assert not completion('push_loaded',o,p,initial_bottom=.8,on_table=True,handover=True)


def test_empty_place_uses_measured_table_support_release_not_original_xy():
    o=obs();p=ControlProfile();o.update(table_contacts=4,tray_position=np.array([.85,-.19,.801]),
        gripper_openings=np.array([.1,.1]),gripper_contact_force={'left':0.,'right':0.})
    assert np.linalg.norm(o['tray_position'][:2]-p.empty_place_position[:2])>p.position_tolerance_m
    assert completion('place_empty',o,p,initial_bottom=.8,on_table=True,handover=False,withdrawn=True)
    assert not completion('place_empty',o,p,initial_bottom=.8,on_table=True,handover=False)
    assert not completion('place_empty',o,p,initial_bottom=.8,on_table=False,handover=False)
    o['gripper_contact_force']['left']=1.
    assert not completion('place_empty',o,p,initial_bottom=.8,on_table=True,handover=False)


def test_flush_goal_uses_source_lateral_and_real_footprint_not_xy_center():
    c=object.__new__(SingleTrayController);c.p=ControlProfile();o=obs()
    o.update(payload_loaded=True,payload_support_contacts=2,table_contacts=4,gripper_openings=np.array([.1,.1]),gripper_contact_force={'left':0.,'right':0.})
    def set_position(x,y):
        o['tray_position']=np.array([x,y,.801])
        o['tray_corners']=np.array([[x+dx,y+dy,.801+dz] for dx in (-.215,.215) for dy in (-.28,.28) for dz in (0,.105)])
    set_position(.90,.295)
    assert c.loaded_goal_reached(o)
    assert completion('push_loaded',o,c.p,initial_bottom=.8,on_table=c._on_table(o),handover=True,loaded_goal=c.loaded_goal_reached(o))
    set_position(.90,.255)
    assert not c.loaded_goal_reached(o)
    assert not completion('push_loaded',o,c.p,initial_bottom=.8,on_table=c._on_table(o),handover=True,loaded_goal=c.loaded_goal_reached(o))
    set_position(1.0,.295)
    assert not c._on_table(o)
    assert not completion('push_loaded',o,c.p,initial_bottom=.8,on_table=c._on_table(o),handover=True,loaded_goal=c.loaded_goal_reached(o))


def test_fallback_flush_uses_actual_corner_edge_after_yaw_not_body_center():
    c=object.__new__(SingleTrayController);c.p=ControlProfile();o=obs()
    o.update(payload_loaded=True,payload_support_contacts=2,table_contacts=4,
        gripper_openings=np.array([.1,.1]),gripper_contact_force={'left':0.,'right':0.})
    # Actual yaw increases the projected half length from .28 to .31048 m.
    half=.3104841179980649;y=.26
    o['tray_position']=np.array([.874,y,.801])
    o['tray_corners']=np.array([[x,y+dy,z] for x in (.60,1.14) for dy in (-half,half) for z in (.8,.905)])
    assert abs(y-c.p.loaded_goal_position[1])>c.p.position_tolerance_m
    assert c.loaded_goal_reached(o)
    assert completion('push_loaded',o,c.p,initial_bottom=.8,on_table=True,handover=True)
    assert not completion('push_loaded',o,c.p,initial_bottom=.8,on_table=False,handover=True)
    o['tray_corners'][:,1]-=.04
    assert not completion('push_loaded',o,c.p,initial_bottom=.8,on_table=True,handover=True)
    o['tray_corners'][0,1]=np.nan
    assert not completion('push_loaded',o,c.p,initial_bottom=.8,on_table=True,handover=True)
    del o['tray_corners']
    assert not completion('push_loaded',o,c.p,initial_bottom=.8,on_table=True,handover=True)


def test_learned_module_has_no_teacher_or_inverse_solver_calls():
    tree=ast.parse(Path(inspect.getfile(LearnedSingleTray)).read_text())
    forbidden={'ik','solve','move','acquire','release','_held_move','pick_empty','place_empty','push_loaded','plan_joint_goal'}
    assert not any(isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr in forbidden for n in ast.walk(tree))


def test_bad_policy_cannot_execute_a_substep_or_mutate_target(tmp_path):
    original=np.zeros(16);sim=SimpleNamespace(target=original.copy(),state=lambda:np.zeros(16),base_state=lambda:np.zeros(3))
    c=SimpleNamespace(sim=sim,p=ControlProfile(),frames=0,base_origin=np.zeros(3),observation=obs,event=lambda *a,**k:None)
    c.tick=lambda:pytest.fail('Invalid chunk reached live physics')
    raw=np.zeros((1,19));raw[0,17]=.01
    learner=object.__new__(LearnedSingleTray);learner.c=c;learner.max_steps=1;learner.execute_steps=1
    learner.policy=SimpleNamespace(contract=SimpleNamespace(checkpoint_id='test'),infer=lambda *a:raw)
    learner.images=lambda:{};learner.lower=-np.ones(16);learner.upper=np.ones(16);learner.output=tmp_path;learner.decisions=0
    with pytest.raises(PolicyError,match='base_action_forbidden'):learner.execute('pick_empty')
    assert np.array_equal(c.sim.target,original)
    assert c.frames==0


def test_handover_requires_actual_order_and_both_push_directions():
    p=ControlProfile();o=obs();o['tray_position']=np.array([.85,-.24,.8]);h=PhysicalHandover(p,o['tray_position'])
    with pytest.raises(PolicyError,match='before_right_push'):h.update(o)
    h=PhysicalHandover(p,o['tray_position']);o['gripper_contact_force']={'left':0.,'right':2.}
    o['tray_position'][1]+=.005;assert not h.update(o)
    o['gripper_contact_force']['left']=2.
    for _ in range(3):assert not h.update(o)
    o['gripper_contact_force']['right']=0.;assert not h.update(o)
    o['tray_position'][1]+=.005;assert h.update(o)
    o['gripper_contact_force']['left']=0.
    with pytest.raises(PolicyError,match='release_before_goal'):h.update(o)


def test_zero_close_command_allowed_despite_positive_measured_joint_lower(tmp_path):
    m=SimpleNamespace(jnt_limited=np.ones(18,bool),jnt_range=np.tile([.002,.05],(18,1)))
    m.jnt_range[:14]=[-2,2]
    sim=SimpleNamespace(arms={'left':list(range(7)),'right':list(range(7,14))},fingers={'left':[14,15],'right':[16,17]})
    c=SimpleNamespace(sim=sim,m=m)
    policy=SimpleNamespace(contract=SimpleNamespace(prompt_mode='single_tray_action3_v1',action_horizon=20))
    l=LearnedSingleTray(c,policy,lambda:{},output=tmp_path/'decisions')
    assert l.lower[7]==l.lower[15]==0
    assert l.upper[7]==l.upper[15]==.1
    validate_chunk(np.zeros((1,19)),l.lower,l.upper)
    opened=np.zeros((1,19),np.float32);opened[:,[7,15]]=.1
    validate_chunk(opened,l.lower,l.upper)
    opened[0,7]=np.nextafter(np.float32(.1),np.float32(1.))
    with pytest.raises(PolicyError):validate_chunk(opened,l.lower,l.upper)


def client_fixture():
    from r1pro_teleop.vla.policy import PolicyContract
    contract=PolicyContract('fixture',action_horizon=2,prompt_mode='single_tray_action3_v1')
    meta=dict(checkpoint_id='fixture',prompt_mode='single_tray_action3_v1',action_width=19,action_horizon=2,
        control_hz=20,model='pi05',action_space='fixed_front_arm16_zero_padded19',base_mode='fixed_front',
        base_actuated=False,control_mask_applied=True,raw_action_output_field='raw_actions',model_action_mask=[True]*16+[False]*3)
    raw=np.zeros((2,19),np.float32);raw[:,16:]=.03
    command=raw.copy();command[:,16:]=0
    reply=dict(actions=command,raw_actions=raw,model_action_mask=np.r_[np.ones(16,bool),np.zeros(3,bool)])
    return SimpleNamespace(get_server_metadata=lambda:meta,infer=lambda observation:reply),contract,meta,reply


def test_fixed_front_reader_preserves_inactive_raw_but_never_actuates_it():
    client,contract,meta,reply=client_fixture();policy=SingleTrayPolicy.from_client(client,contract)
    images={n:np.zeros((2,2,3),np.uint8) for n in contract.camera_names}
    command=policy.infer(images,np.zeros(19),'Pick up the tray')
    assert np.all(command[:,16:]==0)
    assert np.all(policy.last_raw_actions[:,16:]==np.float32(.03))
    reply['actions'][0,0]=.1
    with pytest.raises(PolicyError):policy.infer(images,np.zeros(19),'Pick up the tray')


def test_old_mobile_server_and_wrong_mask_rejected():
    client,contract,meta,reply=client_fixture();meta['action_space']='mobile19_absolute_v1'
    with pytest.raises(PolicyError):SingleTrayPolicy.from_client(client,contract)
    meta['action_space']='fixed_front_arm16_zero_padded19';meta['model_action_mask']=[1]*16+[0]*3
    with pytest.raises(PolicyError):SingleTrayPolicy.from_client(client,contract)


def test_new_rim_permission_metadata_preserves_legacy_and_rejects_short_contract():
    from r1pro_teleop.single_tray_lab.grasp_contract import long_rim_contract
    client,contract,meta,reply=client_fixture()
    SingleTrayPolicy.from_client(client,contract)  # Legacy source metadata untouched.
    meta['allowed_long_rim_contract']=long_rim_contract()
    SingleTrayPolicy.from_client(client,contract)
    meta['allowed_long_rim_contract']['allowed_long_rims'].append('local_x_positive')
    with pytest.raises(PolicyError,match='rim_contract_mismatch'):SingleTrayPolicy.from_client(client,contract)
