"""Preregistered held-out full-DAG evaluation and honest fixed denominators."""
from pathlib import Path
import hashlib
import json
from .rollout import selected_sources
from r1pro_teleop.airport_fsm.registry import scene_rows

MILESTONES=(10,100,1000,10000,100000)
INFRASTRUCTURE_FAILURE_CODES=frozenset({
    'runtime_initialization_failed','vla_openpi_client_missing','vla_inference_failed',
    'vla_checkpoint_identity_mismatch','vla_server_action_contract_mismatch',
    'vla_server_prompt_contract_mismatch','interrupted',
})


def file_sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def build_protocol(collection,successful_inventory,*,expected_test_cases=50):
    collection=Path(collection).resolve()
    wanted=sorted(row['scene_id'] for row in scene_rows(collection) if row['split']=='test')
    if len(wanted)!=expected_test_cases:raise ValueError('fixed_original_test_split_count_mismatch')
    _,selected=selected_sources(collection,scene_ids=wanted)
    inventory=Path(successful_inventory).resolve()
    successful=[json.loads(line) for line in inventory.read_text(encoding='utf-8').splitlines() if line.strip()]
    subset=sorted({row['scene_id'] for row in successful if row.get('split')=='test' and row.get('task_completed') is True})
    if not set(subset)<=set(wanted):raise ValueError('successful_test_subset_not_in_fixed_original_test_split')
    cases=[]
    for scene,xml in selected:
        sid=scene['scene_id'];directory=collection/'scenes'/sid
        cases.append(dict(scene_id=sid,split='test',scene_json_sha256=file_sha(directory/'scene.json'),
            scene_xml_sha256=file_sha(xml),preflight_sha256=file_sha(directory/'preflight.json'),
            teacher_success_subset=sid in subset))
    result=dict(schema='airport_vla_fixed_test_protocol/1',source_collection=str(collection),
        source_collection_sha256=file_sha(collection/'collection.json'),
        source_inventory=str(inventory),source_inventory_sha256=file_sha(inventory),
        scene_ids=wanted,teacher_success_subset_scene_ids=subset,cases=cases,
        milestones=list(MILESTONES),main_denominator=len(wanted),teacher_success_subset_denominator=len(subset),
        evaluation_scope='fresh_complete_DAG_from_original_initial_scene',
        prompt_mode='task_complete_action8_v1',unsupported_temporary_carry='task_failure_no_teacher_fallback',
        source='simulation',physical_failure_evidence_required=True,
        required_artifacts=['trace.h5','task_dag.json','events.jsonl','result.json',
                            'head_left.mp4','head_right.mp4','left_wrist.mp4','right_wrist.mp4'])
    result['protocol_id']='sha256:'+hashlib.sha256(json.dumps(result,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    return result


def verify_protocol(protocol):
    expected=build_protocol(protocol['source_collection'],protocol['source_inventory'],
                            expected_test_cases=protocol['main_denominator'])
    if expected!=protocol:raise ValueError('fixed_evaluation_protocol_source_changed')
    return protocol


def evaluation_summary(protocol,report):
    expected=protocol['scene_ids'];subset=protocol['teacher_success_subset_scene_ids']
    rows=report.get('results',[]);by_id={r['scene_id']:r for r in rows}
    if len(by_id)!=len(rows) or not set(by_id)<=set(expected):raise ValueError('unexpected_or_duplicate_evaluation_scene')
    def statistics(ids):
        known=[by_id[sid] for sid in ids if sid in by_id]
        def infrastructure(row):
            return (row.get('failure_code') in INFRASTRUCTURE_FAILURE_CODES or
                    row.get('physical_episode_started') is False or
                    type(row.get('inverse_dynamics_calls')) is not int or
                    type(row.get('frames')) is not int or row['frames']<=0)
        def controller_valid(row):
            return (row.get('inverse_dynamics_calls')==0 and row.get('motion_backend')=='pi05' and
                    row.get('controller_source')=='vla_generated')
        eligible=[r for r in known if not infrastructure(r) and controller_valid(r)]
        raw_completed=sum(r.get('task_completed') is True for r in known)
        completed=sum(r.get('task_completed') is True for r in eligible)
        strict=sum(r.get('strict_success') is True and r.get('task_completed') is True for r in eligible)
        infra=sum(infrastructure(r) for r in known)
        invalid_controller=sum(not infrastructure(r) and not controller_valid(r) for r in known)
        not_run=[sid for sid in ids if sid not in by_id]
        inverse_verified=len(eligible)
        return dict(denominator=len(ids),attempted=len(known),not_run=len(not_run),not_run_scene_ids=not_run,
            raw_completed_flags=raw_completed,approximate_completed=completed,strict_completed=strict,
            approximate_success_rate=completed/len(ids) if ids else None,
            strict_success_rate=strict/len(ids) if ids else None,
            infrastructure_failures=infra,controller_verification_failures=invalid_controller,task_failures=len(known)-completed-infra-invalid_controller,
            resource_truncations=sum(r.get('failure_code') in ('vla_operation_step_budget_exhausted','vla_skill_budget_exhausted','operation_budget_exhausted') for r in known),
            coverage_complete=len(known)==len(ids),pure_no_inverse_measurements_verified=inverse_verified==len(known) and not not_run,
            required_infrastructure_rerun_scene_ids=not_run+[r['scene_id'] for r in known if infrastructure(r)])
    main=statistics(expected);teacher=statistics(subset)
    state=('evaluation_incomplete_requires_remaining_cases' if not main['coverage_complete'] else
           'infrastructure_reruns_required' if main['infrastructure_failures'] else
           'controller_verification_failed' if not main['pure_no_inverse_measurements_verified'] else 'evaluation_complete')
    return dict(schema='airport_vla_fixed_test_summary/1',protocol_id=protocol['protocol_id'],
        checkpoint_metadata=report.get('checkpoint_metadata'),main_test=main,
        teacher_success_subset=teacher,
        status=state,
        no_teacher_fallback=True,classification='actual_results_only_no_prediction_claims')


def summary_text(summary):
    main=summary['main_test'];subset=summary['teacher_success_subset']
    return ('Main fixed test: approximate {}/{} ({:.2%}); strict {}/{} ({:.2%}).\n'
        'Attempted {}; not run {}; infrastructure failures {}; task failures {}; resource truncations {}.\n'
        'Teacher-success subset: approximate {}/{}; strict {}/{}.\n'
        'Status: {}. Pure no-inverse verified: {}.\n').format(
        main['approximate_completed'],main['denominator'],main['approximate_success_rate'],
        main['strict_completed'],main['denominator'],main['strict_success_rate'],
        main['attempted'],main['not_run'],main['infrastructure_failures'],main['task_failures'],main['resource_truncations'],
        subset['approximate_completed'],subset['denominator'],subset['strict_completed'],subset['denominator'],
        summary['status'],main['pure_no_inverse_measurements_verified'])
