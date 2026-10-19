from pathlib import Path
import importlib.util,json
from types import SimpleNamespace
import pytest


def module():
 p=Path(__file__).resolve().parents[1]/'runs/vla_deploy_20261001/supervise_bc16_round2_skill_curriculum.py'
 s=importlib.util.spec_from_file_location('skill_supervisor',p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m


def fixture():
 identity=dict(checkpoint_id='sha256:'+'f'*64,training_steps=3000,checkpoint_step=2999)
 report=dict(schema='airport_vla_rollout/1',status='completed',mode='pure_vla_evaluation',oracle_execution_scope='not_constructed',live_teacher_actions=False,inverse_dynamics_calls=0,attempted=3,checkpoint_metadata=dict(identity),results=[dict(inverse_dynamics_calls=0,checkpoint_id=identity['checkpoint_id']) for _ in range(3)])
 return report,identity


def test_waits_completed_pure_even_if_full_tasks_failed():
 m=module();report,identity=fixture();report['completed']=0;m.validate_completed_pure(report,identity)
 report['status']='running'
 with pytest.raises(ValueError):m.validate_completed_pure(report,identity)


@pytest.mark.parametrize('key,value',[('mode','simulation_expert_dagger_collection'),('oracle_execution_scope','isolated_private_simulator'),('inverse_dynamics_calls',1)])
def test_wrong_actual_run_never_starts_new_skill_work(key,value):
 m=module();report,identity=fixture();report[key]=value
 with pytest.raises(ValueError):m.validate_completed_pure(report,identity)


def test_training_local_and_live_checkpoint_must_be_final_same_identity():
 m=module();report,identity=fixture();report['checkpoint_metadata']['checkpoint_id']='old-bc16'
 with pytest.raises(ValueError):m.validate_completed_pure(report,identity)


def test_commands_keep_native_sequential_skills_and_train_only_curriculum(tmp_path):
 m=module();identity=fixture()[1]
 baseline=m.command(tmp_path,tmp_path/'baseline',m.BASELINE_EPISODES,identity)
 collection=m.command(tmp_path,tmp_path/'curriculum',m.CURRICULUM_EPISODES,identity,curriculum=True)
 assert m.BASELINE_EPISODES==[0,1,34,2,13,15] and m.CURRICULUM_EPISODES==[2,13,15]
 assert '--collect-curriculum-dagger' not in baseline and '--model-render-max-dim' not in baseline
 assert baseline[baseline.index('--max-skill-steps')+1]=='240'
 assert collection[collection.index('--max-skill-steps')+1]=='600'
 assert collection[collection.index('--query-interval')+1]=='4' and collection[collection.index('--max-queries')+1]=='24'
 assert '--training-status' in collection and '--collect-curriculum-dagger' in collection


def test_measured_graphics_gpu_pid_is_found_without_compute_only_assumption(monkeypatch):
 m=module();xml='<nvidia_smi_log><gpu><uuid>'+m.EXPECTED_UUID+'</uuid><processes><process_info><pid>123</pid><type>G</type></process_info></processes></gpu><gpu><uuid>other</uuid><processes><process_info><pid>999</pid><type>C</type></process_info></processes></gpu></nvidia_smi_log>'
 monkeypatch.setattr(m.subprocess,'run',lambda *a,**kw:SimpleNamespace(stdout=xml))
 assert m.own_gpu_rows(123)==[dict(index=0,uuid=m.EXPECTED_UUID,type='G')]
 assert m.own_gpu_rows(777)==[]
