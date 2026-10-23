import threading
import time
from types import SimpleNamespace
import numpy as np
import pytest
from r1pro_teleop.real2sim.isaac_parallel_runtime import RoomExchange,ParallelRoomRuntime,validate_actor_order


def wait_pending(exchange):
    deadline=time.monotonic()+2
    while exchange.pending() is None:
        assert time.monotonic()<deadline,'worker did not submit unit-test command'
        time.sleep(.001)


def test_room_waits_for_own_measured_feedback_and_copies_commands():
    exchange=RoomExchange();result=[];command=np.arange(19,dtype=float)
    worker=threading.Thread(target=lambda:result.append(exchange.submit(command)))
    worker.start();wait_pending(exchange)
    copy=exchange.pending();copy[0]=999
    assert exchange.pending()[0]==0 and not result
    feedback={'state':np.full(19,-3.)}
    exchange.complete(feedback);worker.join(2)
    assert not worker.is_alive() and np.array_equal(result[0]['state'],feedback['state'])
    feedback['state'][0]=10
    assert result[0]['state'][0]==-3
    exchange.finish()


def test_failed_room_wakes_waiter_without_synthetic_feedback():
    exchange=RoomExchange();errors=[]
    def run():
        try:exchange.submit(np.zeros(19))
        except RuntimeError as exc:errors.append(str(exc))
    worker=threading.Thread(target=run);worker.start();wait_pending(exchange)
    exchange.abort(RuntimeError('real engine failed'));worker.join(2)
    assert errors==['real engine failed'] and not worker.is_alive()


def test_only_main_thread_can_acknowledge_physics():
    exchange=RoomExchange();errors=[]
    def bad():
        try:exchange.complete({})
        except RuntimeError as exc:errors.append(str(exc))
    t=threading.Thread(target=bad);t.start();t.join(2)
    assert errors==['native_main_thread_required']


def test_two_rooms_cannot_consume_each_others_feedback():
    rooms=[RoomExchange(),RoomExchange()];results={}
    workers=[threading.Thread(target=lambda i=i:results.update({i:rooms[i].submit(np.full(19,i))})) for i in range(2)]
    for w in workers:w.start()
    for room in rooms:wait_pending(room)
    rooms[1].complete({'room':1});workers[1].join(2)
    assert results=={1:{'room':1}} and workers[0].is_alive()
    rooms[0].complete({'room':0});workers[0].join(2)
    assert results[0]=={'room':0}


@pytest.mark.parametrize('raw_delta',[None,.2])
def test_tick_records_actual_feedback_and_terminal_state(tmp_path,raw_delta):
    # No simulated robot here: test the thread/record boundary with explicit
    # synthetic unit-test inputs, never claim a physical case passed.
    room=ParallelRoomRuntime.__new__(ParallelRoomRuntime)
    room.room_id=0;room.output=tmp_path;room.command=np.zeros(19)
    room.fixed_episode_base_command=np.zeros(3);room.base_origin=np.zeros(3)
    room.world=SimpleNamespace(current_time=0.);room.frames=0
    room.context=None;room.manipulating=False;room.observer=None
    room.raw_arrays={};room.events=[];room._closed=False;room.exchange=RoomExchange()
    room._actual=dict(state=np.zeros(19),robot_position=np.zeros(3),tray_pose=np.array([[.8,0,.8,1,0,0,0]]))
    result=[]
    def worker():
        raw=None if raw_delta is None else np.r_[raw_delta,np.zeros(18)]
        result.append(room.tick(raw_command=raw));room.worker_done()
    w=threading.Thread(target=worker);w.start();wait_pending(room.exchange)
    actual=dict(room._actual,state=np.r_[.123,np.zeros(18)])
    record=dict(completed_real_substeps=25,submitted_control=np.zeros((25,18)),
                finger_contact_force=np.zeros((25,1,2)),table_force=np.ones((25,1)),penetration=np.zeros(25))
    room.complete_tick(actual,.05,record);w.join(2);assert not w.is_alive()
    room.close_trace()
    with np.load(tmp_path/'native_trace.npz') as trace:
        assert trace['state'].shape==(2,19) and trace['raw_action'].shape==(1,19)
        assert trace['state'][1,0]==.123 and trace['raw_action'][0,0]==(raw_delta or 0)
        assert trace['action'][0,0]==0
        assert trace['submitted_control'].shape==(1,25,18)


def test_fixed_base_command_change_rejected_before_submission(tmp_path):
    room=ParallelRoomRuntime.__new__(ParallelRoomRuntime)
    room.command=np.zeros(19);room.fixed_episode_base_command=np.zeros(3)
    command=np.zeros(19);command[16]=.001
    with pytest.raises(Exception,match='episode_fixed_base_command_changed'):
        room.tick(command)


def test_planner_uses_independent_actual_fingers_and_not_targets():
    from r1pro_teleop.real2sim.isaac_mobile import mobile_targets
    names=list(mobile_targets(np.zeros(19)))+['agent_base_x','agent_base_y','agent_base_yaw']
    indices={name:index for index,name in enumerate(names)}
    model=SimpleNamespace(jnt_qposadr=np.arange(len(names)+1),
        joint=lambda name:SimpleNamespace(id=indices[name]),
        body=lambda name:SimpleNamespace(jntadr=[len(names)]))
    room=ParallelRoomRuntime.__new__(ParallelRoomRuntime)
    room.model=model;room.shadow=SimpleNamespace(qpos=np.zeros(len(names)+7))
    room.mj=SimpleNamespace(mj_forward=lambda model,data:None)
    room.source_base_q={name:0. for name in names[-3:]};room.tray_ids=['tray_0']
    actual=np.arange(18)/1000
    obs=dict(joint_position=actual,state=np.ones(19)*.08,
             tray_pose=np.array([[.8,0,.8,1,0,0,0]]))
    room.sync_planner(obs)
    assert np.array_equal(room.shadow.qpos[:18],actual)
    assert room.shadow.qpos[indices['left_gripper_finger_joint1']]!=room.shadow.qpos[indices['left_gripper_finger_joint2']]


def test_32_actor_lexicographic_swap_is_rejected_before_init():
    expected=[f'/World/envs/env_{i}/Scene/base_link' for i in range(32)]
    assert sorted(expected)!=expected
    with pytest.raises(ValueError,match='parallel_actor_order_mismatch'):
        validate_actor_order(expected,sorted(expected),kind='robots')
    with pytest.raises(ValueError,match='parallel_native_actor_order_mismatch'):
        validate_actor_order(expected,expected,kind='trays',native_actual=sorted(expected))
    row=validate_actor_order(expected,expected,kind='robots',native_actual=expected)
    assert row['native_tensor_order_verified']


def test_observation_cannot_reset_or_change_measured_state():
    room=ParallelRoomRuntime.__new__(ParallelRoomRuntime)
    room.command=np.zeros(19);room.context=None;room.manipulating=False
    room._actual=dict(state=np.arange(19,dtype=float),robot_position=np.zeros(3),
        tray_pose=np.array([[.8,0,.8,1,0,0,0]]),joint_position=np.arange(18,dtype=float))
    before={k:v.copy() for k,v in room._actual.items()}
    observation=room.observation();observation['state'][0]=999;observation['tray_pose'][:]=0
    observation['command'][16]=.4
    assert all(np.array_equal(room._actual[k],value) for k,value in before.items())
    assert np.array_equal(room.command,np.zeros(19))
