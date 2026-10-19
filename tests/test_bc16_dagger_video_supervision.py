import importlib.util,json,hashlib
from pathlib import Path
import h5py
import pytest

def module():
    path=Path(__file__).resolve().parents[1]/'runs/vla_deploy_20261001/supervise_bc16_dagger_round1_videos.py'
    spec=importlib.util.spec_from_file_location('bc16_native_supervisor',path)
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod);return mod

def fixture(tmp_path):
    mod=module();mod.RUN=tmp_path/'run';mod.EVAL=mod.RUN/'eval';mod.SOURCE=tmp_path/'source'
    mod.RUN.mkdir();checkpoint=tmp_path/'checkpoint'
    def save(path,value):path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value))
    save(mod.RUN/'bc_native16_v3_posttraining_v1_checkpoint_identity.json',dict(checkpoint_id='real-id',checkpoint_step=1999,checkpoint_path=str(checkpoint)))
    save(mod.RUN/'bc_native16_v3_2000/training_status.json',dict(status='checkpoint_saved',checkpoint_verified=True,training_steps=2000,checkpoint=str(checkpoint)))
    rows=[]
    for index,split in [(4,'train'),(7,'train'),(8,'train'),(12,'train')]:
        sid=f'airport_{index:04d}_seed';scene=dict(scene_id=sid,split=split);save(mod.SOURCE/'scenes'/sid/'scene.json',scene)
        xml=mod.SOURCE/'scenes'/sid/'mobile.xml';xml.write_text('<mujoco/>')
        result=dict(scene_id=sid,split=split,task_completed=index==4,frames=20,failure_code=None if index==4 else 'guard',
            checkpoint_id='real-id',inverse_dynamics_calls=0,controller_source='vla_generated',motion_backend='pi05')
        attempt=mod.EVAL/'attempts'/sid/'a000';save(attempt/'result.json',result)
        with h5py.File(attempt/'trace.h5','w') as trace:
            trace.attrs['metadata_json']=json.dumps(dict(scene=scene,scene_xml_sha256=hashlib.sha256(xml.read_bytes()).hexdigest(),checkpoint_id='real-id'))
        rows.append(result)
    report=dict(schema='airport_vla_rollout/1',status='completed',mode='simulation_expert_dagger_collection',source_collection=str(mod.SOURCE),
        inverse_dynamics_calls=0,pure_vla_no_inverse_dynamics_verified=True,oracle_execution_scope='isolated_private_simulator',inverse_dynamics_measurement_scope='live_learner_runtime_only',live_teacher_actions=False,
        checkpoint_metadata=dict(fine_tuned=True,model='pi05',training_steps=2000,checkpoint_step=1999,checkpoint_id='real-id'),attempted=4,results=rows)
    return mod,report

def test_actual_learner_outcome_and_hashes_preserved(tmp_path):
    mod,report=fixture(tmp_path);rows=mod.validate_report(report)
    assert [r['task_completed'] for r in rows]==[True,False,False,False]
    assert all(len(r['trace_sha256'])==64 for r in rows)

@pytest.mark.parametrize('mutation',['waiting','teacher','checkpoint','xml','result','oracle_scope','inverse_scope'])
def test_unverified_evidence_never_triggers_render(tmp_path,mutation):
    mod,report=fixture(tmp_path)
    if mutation=='oracle_scope':report['oracle_execution_scope']='live_learner'
    if mutation=='inverse_scope':report['inverse_dynamics_measurement_scope']='oracle_and_learner'
    if mutation=='waiting':report['status']='running'
    if mutation=='teacher':report['live_teacher_actions']=True
    if mutation=='checkpoint':report['checkpoint_metadata']['checkpoint_id']='different'
    if mutation=='xml':(mod.SOURCE/'scenes'/report['results'][0]['scene_id']/'mobile.xml').write_text('changed')
    if mutation=='result':report['results'][0]['task_completed']=False
    with pytest.raises(ValueError):mod.validate_report(report)
