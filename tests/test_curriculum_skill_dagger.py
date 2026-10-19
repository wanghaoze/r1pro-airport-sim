from pathlib import Path
from types import SimpleNamespace
import json,importlib.util,hashlib
import numpy as np
import pytest
from r1pro_teleop.vla.dagger import DaggerRound,ExpertLabel,state_digest


def module():
 p=Path(__file__).resolve().parents[1]/'scripts/diagnose_pi05_skills.py'
 s=importlib.util.spec_from_file_location('curriculum_diag',p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m


def metadata():return dict(fine_tuned=True,training_steps=3000,checkpoint_step=2999,checkpoint_id='sha256:'+'a'*64,action_width=19,action_horizon=20,action_space='mobile19_absolute_v1',control_hz=20,model='pi05')


def test_local_checkpoint_hash_must_match_live_model(tmp_path):
 m=module();live=metadata();identity={k:live[k] for k in ('checkpoint_id','training_steps','checkpoint_step')}
 verifier=lambda p:(None,tmp_path,identity)
 assert m.verify_curriculum_checkpoint(tmp_path,live,verifier)[0]==tmp_path
 identity['checkpoint_id']='sha256:'+'b'*64
 with pytest.raises(ValueError,match='differs'):m.verify_curriculum_checkpoint(tmp_path,live,verifier)


@pytest.mark.parametrize('split',['val','test'])
def test_curriculum_never_uses_held_out_source(split,monkeypatch,tmp_path):
 m=module();monkeypatch.setattr(m,'source_identity',lambda e:(tmp_path,tmp_path,dict(split=split),40))
 with pytest.raises(ValueError,match='train-only'):m.verified_curriculum_fixture({})


def test_unlogged_separation_operation_is_not_guessed(monkeypatch,tmp_path):
 m=module();trace=tmp_path/'trace.h5';episode=dict(skill='push_adjust_tray',operation_index=1)
 monkeypatch.setattr(m,'source_identity',lambda e:(trace,tmp_path,dict(split='train',scene_id='s'),40))
 import r1pro_teleop.vla.rollout as rollout
 monkeypatch.setattr(rollout,'selected_sources',lambda *a,**kw:None)
 events=[dict(event='operation_selected',frame=0,operation_index=1,operation=dict(tray=2,slot=0)),dict(event='state_transition',frame=40,target_tray=2,target_slot=-1)]
 (tmp_path/'events.jsonl').write_text('\n'.join(json.dumps(e) for e in events))
 with pytest.raises(ValueError,match='not recorded'):m.verified_curriculum_fixture(episode)
 events[1]['target_slot']=0;(tmp_path/'events.jsonl').write_text('\n'.join(json.dumps(e) for e in events))
 m.verified_curriculum_fixture(episode)


def fixture(tmp_path,*,reject=False,mutate=False):
 m=module();checkpoint=tmp_path/'checkpoint/params';checkpoint.mkdir(parents=True);(checkpoint/'bytes').write_bytes(b'unit-test-saved-params')
 round_data=DaggerRound(tmp_path/'round',checkpoint.parent,round_index=2,train_scene_ids=['s'])
 snapshot=dict(qpos=np.zeros(2),qvel=np.zeros(2),ctrl=np.zeros(1),time=np.array(1.))
 machine=SimpleNamespace(r=SimpleNamespace(spec=dict(scene_id='s',split='train')),current_skill='carry_tray',current_operation=object())
 class Expert:
  def capture(self):return {k:v.copy() for k,v in snapshot.items()}
  def label(self,op,skill,state,horizon):
   assert op is machine.current_operation and skill=='carry_tray'
   if mutate:snapshot['qpos'][0]=10
   return ExpertLabel(state_digest(state),np.ones((horizon,19),np.float32),'unit-test-expert',replanned_from_learner_state=True,planning_verified=True,teacher_artifact='unit-test-verified-artifact')
  def verify_label(self,state,label):return not reject
 source=tmp_path/'source/attempts/s/a000/trace.h5';source.parent.mkdir(parents=True);source.write_bytes(b'unit-test-source-snapshot')
 (source.parent/'result.json').write_text(json.dumps(dict(task_completed=True,controller_source='program_generated')))
 scene=tmp_path/'source/scenes/s/scene.json';scene.parent.mkdir(parents=True);scene.write_text(json.dumps(dict(scene_id='s',split='train')))
 xml=scene.parent/'mobile.xml';xml.write_bytes(b'unit-test-model')
 digest=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
 episode=dict(episode_index=13,skill='carry_tray',split='train',source_trace_sha256=digest(source),source_start_frame=50)
 provenance=dict(initial_restore_count=1,source_trace=str(source),source_trace_sha256=digest(source),source_frame=50,source_scene_sha256=digest(scene),scene_xml_sha256=digest(xml))
 observer=m.curriculum_observer(machine,round_data,Expert(),tmp_path/'events.jsonl',episode,provenance,query_interval=1,max_queries=1)
 raw=np.full((20,19),.2,np.float32)
 payload=dict(step=0,state=np.zeros(19,np.float32),prompt='Carry tray t for slot s.',actions=raw,servo_actions=np.zeros((20,19)),images={k:np.zeros((4,4,3),np.uint8) for k in ('head_left','left_wrist','right_wrist')})
 return observer,round_data,snapshot,payload


def test_real_visited_state_label_binds_source_and_preserves_raw_actions(tmp_path):
 observer,round_data,snapshot,payload=fixture(tmp_path)
 observer(payload);assert observer.queries==0
 payload['step']=5;snapshot['qpos'][0]=3;before=state_digest(snapshot);observer(payload)
 assert observer.accepted==1 and state_digest(snapshot)==before
 row=round_data.rows[0];context=row['curriculum_context']
 assert context['learner_state_sha256']==before and context['source_frame']==50 and context['episode_index']==13
 assert context['step']==5 and context['skill']=='carry_tray' and context['initial_restore_count']==1
 assert context['collection_mode']=='expert_snapshot_curriculum'
 with np.load(Path(row['sample_dir'])/'label.npz') as data:np.testing.assert_array_equal(data['learner_actions'],payload['actions'])
 persisted=json.loads((round_data.directory/'interventions.jsonl').read_text())
 assert persisted['curriculum_context_sha256']==row['curriculum_context_sha256']


def test_rejected_oracle_does_not_label_or_rollback_live_learner(tmp_path):
 observer,round_data,snapshot,payload=fixture(tmp_path,reject=True);observer(payload)
 snapshot['qpos'][0]=4;before=state_digest(snapshot);payload['step']=5;observer(payload)
 assert observer.rejected==1 and not round_data.rows and state_digest(snapshot)==before
 assert json.loads(observer.path.read_text())['status']=='oracle_rejected'


def test_private_oracle_mutation_of_live_state_is_hard_failure(tmp_path):
 observer,round_data,snapshot,payload=fixture(tmp_path,mutate=True);observer(payload);payload['step']=5
 with pytest.raises(RuntimeError,match='modified the live'):observer(payload)
 assert json.loads(observer.path.read_text())['status']=='oracle_modified_live_learner_state'

def test_curriculum_context_change_cannot_finalize_as_training_data(tmp_path):
 observer,round_data,snapshot,payload=fixture(tmp_path);observer(payload);payload['step']=5;observer(payload)
 m=module();m.verify_curriculum_labels(round_data)
 row=round_data.rows[0];p=Path(row['sample_dir'])/'curriculum_context.json';d=json.loads(p.read_text());d['source_frame']=51;p.write_text(json.dumps(d))
 with pytest.raises(ValueError,match='Curriculum'):m.verify_curriculum_labels(round_data)

@pytest.mark.parametrize('change',['sidecar','row','missing','source'])
def test_curriculum_rechecked_after_finalize_at_aggregation_and_direct_loader(tmp_path,monkeypatch,change):
 from r1pro_teleop.vla.dagger import aggregation_manifest
 from r1pro_teleop.vla.dagger_dataset import DaggerChunkDataset,SimulationExpert
 observer,round_data,snapshot,payload=fixture(tmp_path);observer(payload);payload['step']=5;observer(payload)
 round_data.metadata['collection_mode']='expert_snapshot_curriculum';round_data.finalize()
 aggregate=tmp_path/'aggregate.json';aggregation_manifest([round_data.directory],aggregate,train_scene_ids=['s'])
 monkeypatch.setattr(SimulationExpert,'verify_label',staticmethod(lambda state,label:True))
 assert len(DaggerChunkDataset(aggregate,action_horizon=20,train_scene_ids=['s']))==1
 row=round_data.rows[0];sample=Path(row['sample_dir'])
 if change=='sidecar':(sample/'curriculum_context.json').write_text('{}')
 if change=='source':Path(row['curriculum_context']['source_trace']).write_bytes(b'changed source')
 if change in ('row','missing'):
  if change=='row':row['curriculum_context']['skill']='initialize_posture'
  else:
   row.pop('curriculum_context');row.pop('curriculum_context_sha256');row.pop('collection_mode');(sample/'curriculum_context.json').unlink()
  (round_data.directory/'interventions.jsonl').write_text(json.dumps(row)+'\n')
  value=json.loads(aggregate.read_text());value['interventions']=[row];aggregate.write_text(json.dumps(value))
 with pytest.raises(ValueError,match='Curriculum'):
  aggregation_manifest([round_data.directory],tmp_path/'second.json',train_scene_ids=['s'])
 with pytest.raises(ValueError,match='Curriculum'):
  DaggerChunkDataset(aggregate,action_horizon=20,train_scene_ids=['s'])

