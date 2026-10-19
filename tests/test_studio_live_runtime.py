"""CPU contract tests; these do not establish a successful physical rollout."""
import json
from types import SimpleNamespace
import numpy as np
import pytest
from r1pro_teleop.real2sim import isaac_policy_pickplace as module

@pytest.mark.parametrize('budget',[17,20])
def test_total_simulation_budget_truncates_chunk_without_extra_execution(tmp_path,monkeypatch,budget):
    calls=[]
    def infer(_):
        calls.append(1)
        return {'actions':np.zeros((20,19),np.float32)}
    monkeypatch.setattr(module,'FilePolicyClient',lambda *a:SimpleNamespace(infer=infer))
    obs={'state':np.zeros(19),'tray_pose':np.array([[0,0,.8,1,0,0,0]]),'finger_force':np.zeros((1,2)),
         'long_edge_sign':np.array([[1,-1]]),'table_force':np.ones(1),'front_region_ok':True,
         'policy_images':{c:np.zeros((4,4,3),np.uint8) for c in ['head_left','left_wrist','right_wrist']}}
    runtime=SimpleNamespace(room_id=0,output=tmp_path,frames=0,tables=[{'center_world':[0,0,.7],'dimensions_m':[1,1,.1]}],
        fixed_episode_base_command=np.zeros(3),model=SimpleNamespace(joint=lambda _:SimpleNamespace(id=0),jnt_limited=[True],jnt_range=np.array([[-100,100]])),
        observation=lambda:obs,write=lambda *a:None,event=lambda *a,**kw:None,worker_done=lambda:None)
    def tick(command):
        assert np.array_equal(command[16:],runtime.fixed_episode_base_command)
        runtime.frames+=1
        return obs
    runtime.tick=tick
    case={'original_room_id':31,'parent_split':'train','policy':{'directory':str(tmp_path),'checkpoint_id':'test',
        'frames_per_action':1000,'max_simulation_frames':budget}}
    result=module.run_policy_room(runtime,case)
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
    lim=dict(max_step_rad=.1,max_velocity_rad_s=1.5,max_tracking_error_rad=.25,max_observation_age_seconds=.5,gripper_range_m=[0,.08])
    target=np.ones(19);previous=np.zeros(19);state=np.zeros(19)
    out=module.robot_limit_command(target,previous,state,model,lim,.1)
    assert np.allclose(out[np.r_[0:7,8:15]],.075)
    assert out[7]==.08 and out[15]==.08
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
