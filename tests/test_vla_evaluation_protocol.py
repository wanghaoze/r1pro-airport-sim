import json
import pytest
from r1pro_teleop.vla.evaluation_protocol import build_protocol,verify_protocol,evaluation_summary,summary_text
from test_vla_rollout import source


def test_fixed_test_protocol_binds_original_full_split_not_success_subset(tmp_path):
    root,scene=source(tmp_path)
    inventory=tmp_path/'success.jsonl';inventory.write_text(json.dumps(dict(scene_id=scene['scene_id'],split='test',task_completed=True))+'\n')
    with pytest.raises(ValueError,match='test_split_count'):build_protocol(root,inventory)
    protocol=build_protocol(root,inventory,expected_test_cases=1)
    assert protocol['main_denominator']==1 and protocol['teacher_success_subset_denominator']==1
    assert protocol['milestones']==[10,100,1000,10000,100000]
    verify_protocol(protocol)
    (root/'scenes'/scene['scene_id']/'mobile.xml').write_text('changed')
    with pytest.raises(ValueError):verify_protocol(protocol)


def protocol():
    return dict(scene_ids=['a','b','c','d'],teacher_success_subset_scene_ids=['a','c'],protocol_id='bound')


def result(sid,success=False,strict=False,failure=None):
    return dict(scene_id=sid,task_completed=success,strict_success=strict,
        failure_code=failure,inverse_dynamics_calls=0,motion_backend='pi05',
        controller_source='vla_generated',frames=2)


def test_missing_and_infrastructure_cases_stay_in_original_denominator():
    report=dict(results=[result('a',True,True),result('b',failure='vla_inference_failed')])
    summary=evaluation_summary(protocol(),report);main=summary['main_test']
    assert main['denominator']==4 and main['approximate_success_rate']==.25
    assert main['attempted']==2 and main['not_run']==2 and main['infrastructure_failures']==1
    assert main['required_infrastructure_rerun_scene_ids']==['c','d','b']
    assert summary['teacher_success_subset']['approximate_success_rate']==.5
    assert not main['coverage_complete'] and not main['pure_no_inverse_measurements_verified']
    assert '1/4' in summary_text(summary)


def test_temporary_unsupported_is_task_failure_not_infrastructure_or_removed_case():
    report=dict(results=[result('a',True,False),result('b',failure='vla_unsupported_temporary_carry'),
                         result('c'),result('d')])
    summary=evaluation_summary(protocol(),report);main=summary['main_test']
    assert main['approximate_completed']==1 and main['strict_completed']==0
    assert main['task_failures']==3 and main['infrastructure_failures']==0
    assert main['coverage_complete'] and summary['status']=='evaluation_complete'


def test_inverse_measurement_violation_never_calls_evaluation_verified():
    rows=[result(sid) for sid in protocol()['scene_ids']];rows[1]['inverse_dynamics_calls']=1
    summary=evaluation_summary(protocol(),dict(results=rows))
    assert summary['status']=='controller_verification_failed'


@pytest.mark.parametrize('changed',[
    {'inverse_dynamics_calls':None},{'inverse_dynamics_calls':1},
    {'physical_episode_started':False},{'frames':0},
    {'motion_backend':'teacher'},{'controller_source':'program_generated'},
])
def test_success_flag_without_verified_live_policy_cannot_raise_success_rate(changed):
    rows=[result(sid) for sid in protocol()['scene_ids']]
    rows[0].update(task_completed=True,strict_success=True,**changed)
    main=evaluation_summary(protocol(),dict(results=rows))['main_test']
    assert main['raw_completed_flags']==1
    assert main['approximate_completed']==main['strict_completed']==0
    assert main['approximate_success_rate']==0
    assert main['task_failures']>=0
    assert main['infrastructure_failures']+main['controller_verification_failures']==1


@pytest.mark.parametrize('rows',[[result('a'),result('a')],[result('unknown')]])
def test_duplicate_or_foreign_scene_cannot_change_denominator(rows):
    with pytest.raises(ValueError):evaluation_summary(protocol(),dict(results=rows))


def test_temporary_goal_fails_before_any_model_or_solver_execution():
    from types import SimpleNamespace
    from r1pro_teleop.vla.machine import VLAMachine
    from r1pro_teleop.vla.policy import PolicyError
    from r1pro_teleop.airport_fsm.geometry import Operation
    from r1pro_teleop.airport_fsm.contracts import State
    import numpy as np
    machine=VLAMachine.__new__(VLAMachine);events=[]
    machine.c=SimpleNamespace(vla_prompt_mode='task_complete_action8_v1')
    machine.g=SimpleNamespace(ids=['tray_0'],spec={'slots':[]})
    machine.transition=lambda *args,**kwargs:None
    machine.log=SimpleNamespace(event=lambda name,**kwargs:events.append((name,kwargs)))
    machine.executor=SimpleNamespace(execute_operation=lambda *a,**kw:pytest.fail('unsupported goal executed model'))
    op=Operation(0,-1,np.zeros(3),0.,temporary=True)
    with pytest.raises(PolicyError,match='vla_unsupported_temporary_carry'):
        machine._node(op,'carry_tray',State.TRANSPORT_TRAY,lambda *_:False)
    assert events[0][0]=='vla_unsupported_action_goal' and events[0][1]['teacher_fallback_enabled'] is False
