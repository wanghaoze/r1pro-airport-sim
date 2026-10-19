"""Synthetic observer state transitions; not a physical demo or dataset."""
import numpy as np
import pytest
from r1pro_teleop.real2sim.isaac_three_tray_observer import ThreeTrayObserver, NativeTaskFault
from r1pro_teleop.real2sim.three_tray_migration import PROMPTS


def obs():
    return dict(finger_force=np.zeros((3,2)),long_edge_sign=np.zeros((3,2),int),loaded=np.zeros(3,bool),
        tray_pose=np.tile([0,0,.8,1,0,0,0],(3,1)).astype(float),table_force=np.ones(3),
        command=np.array([0.]*7+[.1]+[0.]*7+[.1]+[0.]*3),robot_left=np.array([0.,1.,0.]),
        lift_clearance=np.zeros(3),axis_error_rad=np.zeros(3),front_region_ok=True,
        payload_on_tray=np.zeros(3,bool),boundary_ok=np.ones(3,bool))


def complete_cycle(o,state,i,frame):
    tray=f'tray_{i}';o.begin(PROMPTS[0],frame,tray,i);state['finger_force'][i]=2.;state['long_edge_sign'][i]=[1,-1]
    for j in range(3):o.observe(state,frame+j+1)
    state['table_force'][i]=0.;state['lift_clearance'][i]=.1;o.finish(state,frame+4)
    o.begin(PROMPTS[1],frame+4,tray,i)
    for j in range(3):o.observe(state,frame+5+j)
    state['table_force'][i]=1.;state['finger_force'][i]=0.;o.finish(state,frame+8,support_stable=True)
    o.loaded(frame+8,tray,i,protected_unchanged=True);state['loaded'][i]=True
    o.begin(PROMPTS[2],frame+10,tray,i);state['finger_force'][i,1]=2.
    o.push_stage('right_push',state,frame+10);state['tray_pose'][i,1]+=.02;o.observe(state,frame+11)
    o.push_stage('left_acquire',state,frame+12);state['finger_force'][i,0]=2.
    for j in range(3):o.observe(state,frame+13+j)
    o.push_stage('right_release',state,frame+16);state['finger_force'][i,1]=0.;o.observe(state,frame+17)
    o.push_stage('left_push',state,frame+18);state['tray_pose'][i,1]+=.031;o.observe(state,frame+19)
    o.push_stage('left_release',state,frame+20);state['finger_force'][i]=0.;state['payload_on_tray'][i]=True
    o.finish(state,frame+21,support_stable=True)


def test_three_cycles_require_real_ordered_handover_and_native_support():
    o=ThreeTrayObserver();s=obs()
    for i in range(3):complete_cycle(o,s,i,i*25)
    q=o.qualification('e','hash',s)
    assert q['complete_task_success'] and len(o.spans)==9 and len(o.loads)==3
    assert [a['prompt'] for a in o.spans]==list(PROMPTS)*3
    s['table_force'][2]=0
    assert not o.qualification('e','hash',s)['complete_task_success']


def test_pick_does_not_pass_on_contact_intent_or_tcp_motion():
    o=ThreeTrayObserver();s=obs();o.begin(PROMPTS[0],0,'tray_0',0)
    s['lift_clearance'][0]=.2;s['table_force'][0]=0.
    with pytest.raises(NativeTaskFault,match='empty_pick_endpoint'):
        o.finish(s,4)
    s['finger_force'][0]=2;s['long_edge_sign'][0]=[1,1]
    for i in range(3):o.observe(s,i+1)
    with pytest.raises(NativeTaskFault,match='empty_pick_endpoint'):
        o.finish(s,4)


def test_right_release_cannot_precede_stable_left_grasp():
    o=ThreeTrayObserver();s=obs();o.cycle=dict(cycle_id=0,tray_id='tray_0',left_stable_grasp=False)
    o.begin(PROMPTS[2],0,'tray_0',0)
    with pytest.raises(NativeTaskFault,match='without_stable_left'):
        o.push_stage('right_release',s,1)
    with pytest.raises(NativeTaskFault,match='before_actual_right_release|right_release_unverified'):
        o.push_stage('left_push',s,1)


def test_warp_positions_use_explicit_numpy_conversion():
    from r1pro_teleop.real2sim.isaac_three_tray_runtime import cpu
    class WarpArray:
        def numpy(self):return np.zeros((1,63,3))
        def __array__(self,*args):raise AssertionError('Warp does not implement NumPy sequence conversion')
    assert cpu(WarpArray()).shape==(1,63,3)


def test_transient_left_zero_does_not_fake_a_supported_right_release():
    o=ThreeTrayObserver();s=obs();s['loaded'][0]=True
    o.cycle=dict(cycle_id=0,tray_id='tray_0',left_stable_grasp=True)
    o.begin(PROMPTS[2],0,'tray_0',0);o.push_stage('right_release',s,1)
    o.observe(s,2)
    assert not o.cycle.get('right_release_after_left_grasp')
    s['finger_force'][0,0]=2.;o.observe(s,3)
    assert o.cycle['right_release_after_left_grasp']


def test_moving_loaded_payload_is_not_final_stable_success():
    o=ThreeTrayObserver();s=obs()
    for i in range(3):complete_cycle(o,s,i,i*25)
    s['payload_speed']=np.array([0.,.3,0.])
    assert not o.qualification('e','hash',s)['complete_task_success']


def test_same_physics_time_cache_keeps_feedback_separate_from_new_command():
    from types import SimpleNamespace
    from r1pro_teleop.real2sim.isaac_three_tray_runtime import NativeRuntime
    r=NativeRuntime.__new__(NativeRuntime)
    r.world=SimpleNamespace(current_time=5.);r._last_obs_time=5.
    r._last_obs=dict(state=np.zeros(19),command=np.zeros(19),robot_position=np.array([.3,0.,0.]))
    r.command=np.ones(19);r.context=None;r.manipulating=False
    s=r.observation()
    assert np.array_equal(s['state'],np.zeros(19))
    assert np.array_equal(s['command'],np.ones(19))
    assert np.array_equal(r._last_obs['command'],np.zeros(19))
    r.context=dict(table_id='front_left',center_world=[.85,0.,0.],dimensions_m=[1.2,.6,.8],yaw_world=np.pi/2)
    r.base_origin=np.zeros(3);r.tables=[r.context]
    r.manipulating=True;r._last_obs['robot_position']=np.array([.85,.7,0.])
    assert not r.observation()['front_region_ok']
    r.world.current_time=5.002
    with pytest.raises(AttributeError):r.observation()  # No SDK object: a fresh read must be attempted.
