import json
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import pytest
from r1pro_teleop.single_tray_3table.free_run import run_time_schedule,RawReplyArchive,stage_frames,PROMPTS

class Trace:
 def __init__(self):self.count=0;self.rows=[];self.events=[]
 def append(self,row):self.rows.append(row);self.count+=1
 def event(self,kind,**details):self.events.append(dict(event=kind,frame=self.count,**details))

class Runtime:
 def __init__(self):
  self.steps=0;self.id_calls=0;self.d=SimpleNamespace(time=0.);self.cfg=SimpleNamespace(vla_model_render_max_dim=0)
  self.sim=SimpleNamespace(state=lambda:np.zeros(16),base_joint_state=lambda:np.zeros(3));self.trace=None
 def apply_model_target(self,raw):self.raw=raw.copy()
 def tick(self):
  self.trace.append(dict(action=self.raw[:16].copy(),base_action=self.raw[16:].copy(),executed_substeps=np.int32(25)));self.steps+=1;self.d.time=self.steps*.05

class Policy:
 def __init__(self):self.client=SimpleNamespace(infer=lambda obs:dict(actions=np.ones((20,19),np.float32)));self.contract=SimpleNamespace(action_horizon=20,camera_names=('head_left','left_wrist','right_wrist'),checkpoint_id='diagnostic')
 def infer(self,images,state,prompt):
  reply=self.client.infer({'state':np.asarray(state,dtype=np.float32),'prompt':prompt,**{'image/'+k:v for k,v in images.items()}})
  value=reply['actions']
  if not np.isfinite(value).all():raise ValueError('model_nonfinite')
  return value


def test_time_schedule_exact_budget_boundary_chunk_truncation_and_environment_no_tick(tmp_path,monkeypatch):
 import r1pro_teleop.single_tray_3table.free_run as m
 monkeypatch.setattr(m,'render_model_observation',lambda *a:np.zeros((2,2,3),np.uint8));r=Runtime();t=Trace();p=Policy();loads=[]
 def load(sim):loads.append((t.count,r.steps,r.d.time));return {'schema':'actual_environment_fixture'}
 result=run_time_schedule(r,p,t,tmp_path,stage_seconds=.5,execute_steps=7,environment_loader=load)
 assert result['recording_completed'] and result['frames']==30 and result['sim_seconds']==1.5 and not result['full_600_sim_seconds_completed']
 assert r.passenger_loaded is True
 assert loads==[(20,20,1.)] and [e['frame'] for e in t.events if e['event']=='free_run_text_stage_start']==[0,10,20]
 assert all(np.array_equal(row['model_raw_action19'],np.ones(19)) for row in t.rows)
 assert all(row['state19'].shape==(19,) and np.array_equal(row['state19'],np.zeros(19)) and np.array_equal(row['cmd19'],row['action19']) and np.array_equal(row['action19'],row['model_raw_action19']) for row in t.rows)
 assert [json.loads(f.read_text())['used_rows'] for f in sorted((tmp_path/'policy_decisions').glob('chunk*.json'))]==[7,3,7,3,7,3]
 assert result['task_completed'] is False and result['training_eligible'] is False and result['success_rate_eligible'] is False
 progress=json.loads((tmp_path/'progress.json').read_text());assert progress['frames']==30 and progress['actual_runtime_ticks']==30 and progress['sim_seconds']==1.5 and progress['current_prompt']==PROMPTS[2] and progress['diagnostic_only'] is True
 assert result['requested_diagnostic_duration_completed'] is True and result['diagnostic_duration_completed'] is False
 assert stage_frames(200)==4000 and len(PROMPTS)==3


def test_nonfinite_reply_saved_before_rejection_no_fake_frames(tmp_path,monkeypatch):
 import r1pro_teleop.single_tray_3table.free_run as m
 monkeypatch.setattr(m,'render_model_observation',lambda *a:np.zeros((2,2,3),np.uint8));p=Policy();p.client.infer=lambda obs:dict(actions=np.full((20,19),np.nan,np.float32),raw_actions=np.full((20,19),np.nan,np.float32),model_action_mask=np.ones(19,bool));r=Runtime();t=Trace()
 result=run_time_schedule(r,p,t,tmp_path,stage_seconds=.5,environment_loader=lambda s:{})
 assert not result['recording_completed'] and t.count==0 and r.steps==0 and result['actual_inference_calls']==1
 with np.load(tmp_path/'policy_decisions/raw_reply_000000.npz',allow_pickle=False) as f:assert np.isnan(f['actions']).all() and f['model_action_mask'].dtype==np.bool_ and f['request_state19'].dtype==np.float32
 with np.load(tmp_path/'policy_decisions/request_000000.npz',allow_pickle=False) as f:assert f['request_state19'].dtype==np.float32 and f['request_state19'].shape==(19,)
 assert json.loads((tmp_path/'policy_decisions/raw_reply_000000.json').read_text())['status']=='reply_archived_before_validation'


def test_raw_outside_workspace_is_not_clipped_or_rejected(tmp_path,monkeypatch):
 import r1pro_teleop.single_tray_3table.free_run as m
 monkeypatch.setattr(m,'render_model_observation',lambda *a:np.zeros((2,2,3),np.uint8));p=Policy();p.client.infer=lambda obs:dict(actions=np.full((20,19),123.,np.float32));r=Runtime();t=Trace()
 result=run_time_schedule(r,p,t,tmp_path,stage_seconds=.05,environment_loader=lambda s:{})
 assert result['frames']==3 and all(np.all(row['model_raw_action19']==123.) for row in t.rows)
 assert np.all(r.raw==123.)


@pytest.mark.parametrize('value',[True,0,-1,.023,float('nan')])
def test_invalid_or_fractional_frame_budget_rejected(value):
 with pytest.raises(ValueError):stage_frames(value)

@pytest.mark.parametrize('value',[{'run_scope':'free_run_diagnostic'},{'run_kind':'free_run_diagnostic'},{'free_run_diagnostic':True}])
def test_free_run_cannot_be_minted_as_successful_source_even_if_claim_flags_are_changed(value):
 from r1pro_teleop.vla.data_three_table_lerobot import reject_free_run_source
 with pytest.raises(ValueError,match='never_training'):reject_free_run_source(dict(value,task_completed=True,physics_success=True,training_eligible=True))
