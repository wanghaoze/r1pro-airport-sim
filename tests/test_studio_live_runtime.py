"""CPU contract tests; these do not establish a successful physical rollout."""
import json
import time
from types import SimpleNamespace
import numpy as np
import pytest
from r1pro_teleop.real2sim import isaac_policy_pickplace as module

@pytest.mark.parametrize('mode',['strict','clip_diagnostic','robot_limits'])
@pytest.mark.parametrize('budget',[17,20])
@pytest.mark.parametrize('prepared',[False,True])
def test_total_simulation_budget_truncates_chunk_without_extra_execution(tmp_path,monkeypatch,budget,mode,prepared):
    calls=[]
    expected_base=np.array([.01,-.02,.03],np.float32) if prepared else np.zeros(3)
    def infer(sample):
        np.testing.assert_allclose(sample['state'][16:],expected_base,rtol=0,atol=1e-8)
        calls.append(1)
        return {'actions':np.zeros((20,19),np.float32)}
    monkeypatch.setattr(module,'FilePolicyClient',lambda *a:SimpleNamespace(infer=infer))
    obs={'state':np.zeros(19),'tray_pose':np.array([[0,0,.8,1,0,0,0]]),'finger_force':np.zeros((1,2)),
         'long_edge_sign':np.array([[1,-1]]),'table_force':np.ones(1),'front_region_ok':True,
         'policy_images':{c:np.zeros((4,4,3),np.uint8) for c in ['head_left','left_wrist','right_wrist']}}
    # Physics may overshoot the gripper target; rate limits use the held command.
    obs['state'][[7,15]]=.08044
    runtime=SimpleNamespace(command=np.zeros(19),room_id=0,output=tmp_path,frames=0,tables=[{'center_world':[0,0,.7],'dimensions_m':[1,1,.1]}],
        fixed_episode_base_command=np.zeros(3),model=SimpleNamespace(joint=lambda _:SimpleNamespace(id=0),jnt_limited=[True],jnt_range=np.array([[-100,100]])),
        observation=lambda:dict(obs,measured_wall_time=time.time()),write=lambda *a:None,event=lambda *a,**kw:None,worker_done=lambda:None)
    def tick(command,**kwargs):
        assert np.array_equal(command[16:],runtime.fixed_episode_base_command)
        assert 'raw_command' in kwargs
        runtime.frames+=1
        return obs
    runtime.tick=tick
    case={'original_room_id':31,'parent_split':'train','policy':{'directory':str(tmp_path),'checkpoint_id':'test',
        'action_safety_mode':mode,'frames_per_action':1000,'max_simulation_frames':budget}}
    if prepared:
        case['prepared_pick_start']=dict(schema='prepared_pick_pose_diagnostic/2',initialization_only=True,
            online_teacher=False,full_task_success_eligible=False,training_eligible=False,
            state16=np.zeros(16).tolist(),tray_pose=[0,0,.8,1,0,0,0],base_world=[0,0,0],
            original_state=np.r_[np.zeros(16),expected_base].tolist(),source_initial_base_state=[0,0,0],
            policy_initial_base_state=expected_base.tolist())
    result=module.run_policy_room(runtime,case)
    assert result['action_safety_mode']=='robot_limits' and not result['pure_model_success_eligible']
    assert runtime.frames==budget
    assert len(calls)==int(np.ceil(budget/5))
    assert result['error']['message']=='simulation_time_budget_reached'
    assert result['original_room_id']==31 and not result['passed'] and not result['teacher_fallback']

def test_original_room_and_request_timeout(tmp_path):
    (tmp_path/'ready.json').write_text(json.dumps({'checkpoint_id':'test','horizon':20}))
    client=module.FilePolicyClient(tmp_path,31,'test',20,.001)
    sample={'state':np.zeros(19),'prompt':'Pick up the tray',**{'image/'+c:np.zeros((4,4,3),np.uint8) for c in ['head_left','left_wrist','right_wrist']}}
    with pytest.raises(TimeoutError,match='policy_inference_response_timeout'):client.infer(sample)
    assert (tmp_path/'room031_000000.request.npz').exists()


def test_explicit_clip_diagnostic_retains_raw_and_gripper_units():
    model=SimpleNamespace(joint=lambda _:SimpleNamespace(id=0),jnt_range=np.array([[-1.,1.]]))
    raw=np.zeros((20,19),np.float32);raw[0,11]=-1.2;raw[0,7]=2.5;raw[0,16]=4.
    applied,changes=module.clip_diagnostic_actions(raw,model)
    assert raw[0,11]<-1 and applied[0,11]==-1
    assert applied[0,7]==2 and applied[0,16]==4
    assert len(changes)==2
    model.jnt_limited=[True];model.jnt_range=np.array([[-1.7453,0.3491]])
    clipped,_=module.clip_diagnostic_actions(np.full((20,19),-2.,np.float32),model)
    module.validate_actions(clipped,model)
    raw[0,0]=np.nan
    with pytest.raises(ValueError):module.clip_diagnostic_actions(raw,model)

def test_robot_limits_caps_and_tracking_guard():
    model=SimpleNamespace(joint=lambda _:SimpleNamespace(id=0),jnt_limited=[True],jnt_range=np.array([[-2.,2.]]))
    lim=module.load_limits()
    target=np.ones(19);previous=np.zeros(19);state=np.zeros(19)
    out=module.robot_limit_command(target,previous,state,model,lim,.1)
    assert np.allclose(out[np.r_[0:7,8:15]],.075)
    assert np.allclose(out[[7,15]],.08) and np.all(out[[7,15]]<=.08)
    with pytest.raises(ValueError,match='tracking'):module.robot_limit_command(target,previous,state+1,model,lim,.1)
    with pytest.raises(ValueError,match='stale'):module.robot_limit_command(target,previous,state,model,lim,.6)

def test_async_buffer_skips_elapsed_predictions():
    import threading
    gate=threading.Event();calls=[]
    def infer(images,state,prompt):
        calls.append(1)
        if len(calls)>1:gate.wait(2)
        return np.tile(np.arange(20)[:,None],(1,19))
    buffer=module.AsyncChunkBuffer(SimpleNamespace(infer=infer),20)
    images={'head':np.zeros((2,2,3))};state=np.zeros(19)
    try:
        a,offset,origin=buffer.get(images,state,'Pick',0);assert offset==0
        a,offset,origin=buffer.get(images,state,'Pick',5);assert offset==5 and origin==0
        gate.set();buffer.pending.result()
        a,offset,origin=buffer.get(images,state,'Pick',10);assert offset==5 and origin==5
    finally:gate.set();buffer.close()


@pytest.mark.parametrize('ending',['budget','physics','stop'])
def test_pending_file_inference_does_not_delay_room_exit(tmp_path,ending):
    directory=tmp_path/'policy';directory.mkdir()
    (directory/'ready.json').write_text(json.dumps({'checkpoint_id':'test','horizon':20}))
    np.savez(directory/'room000_000000.reply.npz',actions=np.zeros((20,19),np.float32))
    obs={'state':np.zeros(19),'tray_pose':np.array([[0,0,.8,1,0,0,0]]),
         'finger_force':np.zeros((1,2)),'long_edge_sign':np.array([[1,-1]]),
         'table_force':np.ones(1),'front_region_ok':True,
         'policy_images':{c:np.zeros((4,4,3),np.uint8) for c in ['head_left','left_wrist','right_wrist']}}
    written={};done=[]
    runtime=SimpleNamespace(command=np.zeros(19),room_id=0,output=tmp_path,frames=0,
        tables=[{'center_world':[0,0,.7],'dimensions_m':[1,1,.1]}],fixed_episode_base_command=np.zeros(3),
        model=SimpleNamespace(joint=lambda _:SimpleNamespace(id=0),jnt_limited=[True],jnt_range=np.array([[-100,100]])),
        observation=lambda:dict(obs,measured_wall_time=time.time()),
        write=lambda name,value:written.update({name:value}),event=lambda *a,**kw:None,worker_done=lambda:done.append(True))
    def tick(command,**kwargs):
        runtime.frames+=1
        if runtime.frames==6:
            deadline=time.monotonic()+2
            while not (directory/'room000_000001.request.npz').exists():
                assert time.monotonic()<deadline,'prefetch did not start'
                time.sleep(.005)
            if ending=='physics':raise ValueError('test_physics_guard')
            if ending=='stop':(tmp_path/'stop_requested').touch()
        return obs
    runtime.tick=tick
    case={'parent_split':'train','policy':{'directory':str(directory),'checkpoint_id':'test',
        'runtime_profile':'realtime','frames_per_action':100,'max_simulation_frames':10,
        'inference_timeout_seconds':3}}
    started=time.monotonic()
    result=module.run_policy_room(runtime,case)
    assert time.monotonic()-started<2
    assert done==[True] and written['worker_result.json']==result
    expected={'budget':'simulation_time_budget_reached','physics':'test_physics_guard','stop':'policy_stopped_by_user'}
    assert result['error']['message']==expected[ending]
    assert result['failure_category']==('user_cancelled' if ending=='stop' else 'model_failure')
    assert not result['passed'] and not result['training_eligible']
    assert (directory/'room000_000001.request.npz').exists()
    assert not (directory/'stop').exists()
    assert (tmp_path/'stop_requested').exists()==(ending=='stop')
    with np.load(tmp_path/'model_actions.npz') as saved:assert int(saved['executed_frames'])==runtime.frames


@pytest.mark.parametrize('ready_reply',[False,True])
def test_stop_during_file_inference_preserves_cancellation(tmp_path,ready_reply):
    from concurrent.futures import ThreadPoolExecutor
    from r1pro_teleop.vla.policy import Pi05Policy,PolicyContract
    directory=tmp_path/'policy';directory.mkdir()
    (directory/'ready.json').write_text(json.dumps({'checkpoint_id':'test','horizon':20}))
    client=module.FilePolicyClient(directory,0,'test',20,3)
    policy=Pi05Policy(client,PolicyContract('test',action_horizon=20))
    images={c:np.zeros((4,4,3),np.uint8) for c in policy.contract.camera_names}
    with ThreadPoolExecutor(max_workers=1) as pool:
        try:
            if ready_reply:
                np.savez(directory/'room000_000000.reply.npz',actions=np.zeros((20,19)))
                (tmp_path/'stop_requested').touch()
            future=pool.submit(policy.infer,images,np.zeros(19),'Pick up the tray')
            if not ready_reply:
                deadline=time.monotonic()+2
                while not (directory/'room000_000000.request.npz').exists():
                    assert time.monotonic()<deadline
                    time.sleep(.005)
                (tmp_path/'stop_requested').touch()
            with pytest.raises(InterruptedError,match='policy_stopped_by_user'):future.result(timeout=1)
            if ready_reply:assert not list(directory.glob('*.request.npz'))
        finally:client.close()
