"""Immutable-source pure VLA evaluation and fresh-state private expert queries."""
from __future__ import annotations
from dataclasses import replace
import json
from pathlib import Path
import re
import traceback
import numpy as np
from r1pro_teleop.airport_fsm.contracts import atomic_json, sha256_file
from r1pro_teleop.airport_fsm.registry import config_for, scene_rows


def _read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def validate_server_metadata(metadata,expected_checkpoint_id=None):
    from .prompts import validate_prompt_mode
    if isinstance(metadata, dict):
        validate_prompt_mode(metadata.get("prompt_mode", "legacy"))
    if (not isinstance(metadata,dict) or metadata.get('fine_tuned') is not True or
            type(metadata.get('training_steps')) is not int or metadata['training_steps']<=0 or
            metadata.get('action_width')!=19 or metadata.get('action_space')!='mobile19_absolute_v1' or
            metadata.get('control_hz')!=20 or metadata.get('model')!='pi05' or
            type(metadata.get('action_horizon')) is not int or metadata['action_horizon']<1):
        raise ValueError('A loaded fine-tuned pi05 mobile19 20 Hz server is required')
    identity=metadata.get('checkpoint_id','')
    if not isinstance(identity,str) or not re.fullmatch(r'sha256:[0-9a-f]{64}',identity):
        raise ValueError('Server must advertise its verified checkpoint content hash')
    if expected_checkpoint_id is not None and expected_checkpoint_id!=identity:
        raise ValueError('Requested and loaded checkpoint identity disagree')
    return metadata


def verified_server_metadata(host, port, *, expected_checkpoint_id=None, client_factory=None):
    if client_factory is None:
        from openpi_client.websocket_client_policy import WebsocketClientPolicy
        client_factory=WebsocketClientPolicy
    client=client_factory(host=host,port=port)
    try:
        metadata=validate_server_metadata(client.get_server_metadata(),expected_checkpoint_id)
    finally:
        # The official client exposes no public close API. This probe socket
        # owns no policy state; release its transport even on rejected metadata.
        socket=getattr(client,'_ws',None)
        if socket is not None:socket.close()
    return metadata


def selected_sources(collection, *, scene_ids=None, indices=None, train_only=False):
    root=Path(collection).resolve()
    registered=_read(root/'collection.json')
    if registered.get('schema')!='airport_fsm_collection/1':
        raise ValueError('A prepared source collection is required')
    rows=scene_rows(root)
    by_id={r['scene_id']:r for r in rows}
    if len(by_id)!=len(rows):raise ValueError('Duplicate prepared scene identities')
    if (scene_ids is None)==(indices is None):raise ValueError('Select exactly one of scene_ids or indices')
    if indices is not None:
        wanted=[]
        for index in indices:
            if type(index) is not int or index<0:raise ValueError('Scene index must be nonnegative integer')
            matches=[sid for sid in by_id if re.fullmatch(r'airport_'+str(index).zfill(4)+r'_[0-9]+',sid)]
            if len(matches)!=1:raise ValueError('Unknown or ambiguous registered index '+str(index))
            wanted.append(matches[0])
    else:wanted=list(scene_ids)
    if not wanted or len(wanted)!=len(set(wanted)):raise ValueError('Selection must be nonempty and unique')
    selected=[]
    for sid in wanted:
        if sid not in by_id:raise ValueError('Unregistered scene '+str(sid))
        directory=root/'scenes'/sid
        if not directory.resolve().is_relative_to(root):raise ValueError('Source scene path escapes collection')
        spec=_read(directory/'scene.json');preflight=_read(directory/'preflight.json')
        if (spec.get('scene_id')!=sid or spec.get('split')!=by_id[sid].get('split') or
                preflight.get('scene_id')!=sid or preflight.get('split')!=spec.get('split') or
                preflight.get('valid') is not True):raise ValueError('Source scene identity/preflight mismatch')
        if train_only and spec['split']!='train':raise ValueError('DAgger selection must contain only prepared train scenes')
        xml=directory/'mobile.xml'
        if not xml.is_file():raise ValueError('Prepared mobile model is missing')
        if (preflight.get('scene_json_sha256')!=sha256_file(directory/'scene.json') or
                preflight.get('scene_xml_sha256')!=sha256_file(xml)):
            raise ValueError('Source scene changed after preflight')
        selected.append((spec,xml))
    return root,selected


class DaggerObserver:
    """Fixed-schedule side queries; rejected oracle labels do not replace actions."""
    def __init__(self,machine,round_data,expert,events_path,*,query_interval=2,max_queries=2):
        if any(type(x) is not int or x<1 for x in (query_interval,max_queries)):
            raise ValueError('Oracle query interval/budget must be positive integers')
        self.machine,self.round,self.expert=machine,round_data,expert
        self.path=Path(events_path);self.interval=query_interval;self.max_queries=max_queries
        self.decisions,self.queries,self.accepted,self.rejected=0,0,0,0

    def _event(self,value):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.path.open('a',encoding='utf-8') as stream:stream.write(json.dumps(value)+'\n')

    def __call__(self,payload):
        self.decisions+=1
        # Skip the first model decision after settling. Every N subsequent
        # chunks is a declared query at an actually learner-visited state.
        if self.decisions==1 or (self.decisions-1)%self.interval or payload['step']<=0 or self.queries>=self.max_queries:return
        m=self.machine;self.queries+=1
        record={'scene_id':m.r.spec['scene_id'],'step':int(payload['step']),
                'skill':m.current_skill,'query':self.queries,'decision':self.decisions,
                'reason':'fixed_query_schedule_after_first_learner_chunk'}
        snapshot=self.expert.capture()
        from .dagger import state_digest
        before=state_digest(snapshot)
        record['state_sha256']=before
        observation={'state':payload['state'],'prompt':payload['prompt'],
                     **{'image/'+key:value for key,value in payload['images'].items()}}
        try:
            row=self.round.collect_intervention(scene_id=m.r.spec['scene_id'],split=m.r.spec['split'],
                simulator_state=snapshot,observation=observation,learner_action=payload['actions'],
                expert_replan=lambda state,obs:self.expert.label(m.current_operation,m.current_skill,state,
                                                               horizon=len(payload['actions'])),
                verify_label=self.expert.verify_label,reason=record['reason'])
            self.accepted+=1;record.update(status='oracle_label_collected',sample_dir=row['sample_dir'])
        except Exception as exc:
            self.rejected+=1;record.update(status='oracle_rejected',error=repr(exc))
        # An oracle planning rejection is recoverable; mutation of live physics
        # is never recoverable and must terminate the learner with evidence.
        if state_digest(self.expert.capture())!=before:
            record.update(status='oracle_modified_live_learner_state');self._event(record)
            raise RuntimeError('Oracle modified the live learner state')
        self._event(record)


def run_rollouts(collection,output,metadata,*,host='127.0.0.1',port=8000,scene_ids=None,indices=None,
                 collect_dagger=False,learner_checkpoint=None,round_index=0,query_interval=2,max_queries=2,
                 execute_steps=5,max_skill_steps=6000,servo_projection=False,actuator_saturation=False,reference_rate_limit=False,rate_fraction=.5,model_render_max_dim=0,
                 init_arm_tolerance=.06,init_gripper_tolerance=.005,initializer_base_hold=False,grasp_base_hold=False,attempt_runner=None,expert_factory=None,private_oracle_contact_escape=False,
                 navigation_readiness='legacy',navigation_bearing_max=.55,navigation_lateral_max=.28,navigation_forward_min=.4,navigation_stable_frames=4,
                 private_oracle_measured_tracking=False,record_substep_controls=False):
    if type(record_substep_controls) is not bool:raise ValueError("record_substep_controls must be boolean")
    if type(private_oracle_measured_tracking) is not bool:raise ValueError('Private oracle measured tracking must be boolean')
    if private_oracle_measured_tracking and (collect_dagger is not True or private_oracle_contact_escape is not True):
        raise ValueError('Private oracle measured tracking requires DAgger collection and private contact escape')
    if type(private_oracle_contact_escape) is not bool:raise ValueError('Private oracle escape toggle must be boolean')
    if private_oracle_contact_escape and not collect_dagger:raise ValueError('Private oracle contact escape requires DAgger collection')
    validate_server_metadata(metadata)
    if any(type(flag) is not bool for flag in (servo_projection,actuator_saturation,reference_rate_limit)):
        raise ValueError('VLA controller toggles must be boolean')
    if servo_projection and actuator_saturation:
        raise ValueError('Select bounded servo projection or actuator saturation, not both')
    root,selected=selected_sources(collection,scene_ids=scene_ids,indices=indices,train_only=collect_dagger)
    config=replace(config_for(root),motion_backend='pi05',vla_host=host,vla_port=port,
                   vla_prompt_mode=metadata.get('prompt_mode','legacy'),
                   vla_checkpoint_id=metadata['checkpoint_id'],vla_action_horizon=metadata['action_horizon'],
                   vla_execute_steps=execute_steps,vla_max_skill_steps=max_skill_steps,
                   vla_servo_projection_enabled=servo_projection or actuator_saturation,
                   vla_servo_projection_mode='actuator_saturation' if actuator_saturation else 'bounded',
                   vla_reference_rate_limit_enabled=reference_rate_limit,
                   vla_reference_rate_fraction=rate_fraction, vla_model_render_max_dim=model_render_max_dim,
                   vla_initialize_arm_tolerance_rad=init_arm_tolerance,vla_initialize_gripper_tolerance_m=init_gripper_tolerance,
                   vla_initializer_base_hold_enabled=initializer_base_hold,vla_grasp_base_hold_enabled=grasp_base_hold,
                   vla_navigation_readiness_mode=navigation_readiness,
                   vla_navigation_target_bearing_max_rad=navigation_bearing_max,
                   vla_navigation_target_lateral_max_m=navigation_lateral_max,
                   vla_navigation_target_forward_min_m=navigation_forward_min,
                   vla_navigation_stable_frames=navigation_stable_frames,
                   **({"substep_control_enabled":True} if record_substep_controls else {}))
    config.validate()
    out=Path(output).resolve()
    if out==root or out.is_relative_to(root):raise ValueError('New VLA outputs cannot modify the source collection')
    out.mkdir(parents=True,exist_ok=False)
    mode='simulation_expert_dagger_collection' if collect_dagger else 'pure_vla_evaluation'
    report={'schema':'airport_vla_rollout/1','status':'running','mode':mode,
            'record_substep_controls_override':record_substep_controls,
            'source_collection':str(root),'checkpoint_metadata':metadata,'config':config.dump(),
            'selected_scene_ids':[s['scene_id'] for s,x in selected],'results':[],
            'source':'simulation','controller_source':'vla_generated','live_teacher_actions':False,
            'inverse_dynamics_measurement_scope':'live_learner_runtime_only',
            'oracle_execution_scope':'isolated_private_simulator' if collect_dagger else 'not_constructed',
            'private_oracle_contact_escape':private_oracle_contact_escape,
            'private_oracle_measured_tracking':private_oracle_measured_tracking,
            'private_escape_qualification_mode':'bounded_measured_tracking_after_clearance' if private_oracle_measured_tracking else 'exact_yaw_global_monotonic'}
    atomic_json(out/'rollout_report.json',report)
    observers=[];round_data=None
    try:
        if collect_dagger:
            from .dagger import DaggerRound
            if learner_checkpoint is None:raise ValueError('DAgger requires the verified local learner checkpoint')
            round_data=DaggerRound(out/'dagger_round',learner_checkpoint,round_index=round_index,
                                   train_scene_ids=[s['scene_id'] for s,x in selected])
            round_data.metadata.update(private_oracle_measured_tracking=private_oracle_measured_tracking,
                private_escape_qualification_mode=report['private_escape_qualification_mode'])
            if expert_factory is None:
                from .teacher import SimulationExpert
                expert_factory=SimulationExpert
        if attempt_runner is None:
            from r1pro_teleop.airport_fsm.machine import run_attempt
            attempt_runner=run_attempt
        for spec,xml in selected:
            directory=out/'attempts'/spec['scene_id']/'a000'
            # Machine owns exclusive creation of the attempt leaf. Precreating
            # a000 here makes every real constructor fail before recording.
            directory.parent.mkdir(parents=True,exist_ok=True)
            kwargs={}
            if collect_dagger:
                def install(machine):
                    expert_kwargs={'machine':machine}
                    if private_oracle_contact_escape:expert_kwargs['private_contact_escape']=True
                    if private_oracle_measured_tracking:expert_kwargs['private_escape_measured_tracking']=True
                    expert=expert_factory(machine.r,out/'oracles'/spec['scene_id']/'a000',**expert_kwargs)
                    observer=DaggerObserver(machine,round_data,expert,out/'oracle_queries.jsonl',
                                             query_interval=query_interval,max_queries=max_queries)
                    machine.executor.on_decision=observer;observers.append(observer)
                kwargs['machine_observer']=install
            result=attempt_runner(spec,xml,config,directory,attempt=0,**kwargs)
            report['results'].append(result);atomic_json(out/'rollout_report.json',report)
            if result.get('failure_code')=='interrupted':break
        measurements=[r.get('inverse_dynamics_calls') for r in report['results']]
        report['inverse_dynamics_calls']=sum(x for x in measurements if type(x) is int)
        report['inverse_call_measurements_complete']=all(type(x) is int for x in measurements)
        report['pure_vla_no_inverse_dynamics_verified']=bool(report['results']) and all(
            type(r.get('inverse_dynamics_calls')) is int and r['inverse_dynamics_calls']==0
            and r.get('motion_backend')=='pi05' for r in report['results'])
        report['completed']=sum(r.get('task_completed') is True for r in report['results'])
        report['attempted']=len(report['results'])
        report['success_by_split']={split:{'completed':sum(r.get('task_completed') is True for r in report['results'] if r['split']==split),
            'attempted':sum(r['split']==split for r in report['results'])} for split in sorted({s['split'] for s,x in selected})}
        if round_data is not None:
            report['oracle_queries']=sum(o.queries for o in observers)
            report['oracle_labels']=sum(o.accepted for o in observers)
            report['oracle_rejected']=sum(o.rejected for o in observers)
            if round_data.rows:report['dagger_round']=round_data.finalize()
            else:
                round_data.metadata.update(status='no_verified_labels_not_training_data',label_count=0)
                atomic_json(round_data.directory/'round.json',round_data.metadata)
                report['dagger_round']=round_data.metadata
        report['status']='completed' if report['pure_vla_no_inverse_dynamics_verified'] else 'controller_verification_failed'
        atomic_json(out/'rollout_report.json',report)
        return report
    except BaseException as exc:
        report.update(status='failed',error=repr(exc));atomic_json(out/'rollout_report.json',report)
        (out/'exception.txt').write_text(traceback.format_exc(),encoding='utf-8')
        raise
