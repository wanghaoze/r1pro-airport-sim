"""Isolated skill diagnostics from verified expert physics initial snapshots.

This does not run the production DAG or train a policy. Default diagnostics do not query a teacher;
Explicit train-only curriculum collection queries an isolated simulation expert.
These diagnostics never claim full-task success. Each new diagnostic restores its initial state once
and subsequently executes only checkpoint-backed VLA actions and real guards.
"""
from pathlib import Path
from dataclasses import replace
from types import SimpleNamespace
import argparse,hashlib,json,sys,time,traceback
import numpy as np
# Both project scripts/ and the preparation runs/vla_deploy directory work.
PROJECT_ROOT=next((parent for parent in Path(__file__).resolve().parents if (parent/'r1pro_teleop').is_dir()),
    Path(__file__).resolve().parents[1])
sys.path.insert(0,str(PROJECT_ROOT))

SKILLS=('initialize_posture','navigate_to_tray','push_adjust_tray','grasp_lift_tray','carry_tray','place_release_tray')

def verify_curriculum_checkpoint(status_path,metadata,verifier=None):
    """Hash actual local trained bytes, not a caller supplied checkpoint name."""
    if verifier is None:
        from scripts.serve_pi05_airport import verify_training_checkpoint
        verifier=verify_training_checkpoint
    from r1pro_teleop.vla.rollout import validate_server_metadata
    validate_server_metadata(metadata)
    _,checkpoint,identity=verifier(status_path)
    if identity.get('prompt_mode','legacy') != metadata.get('prompt_mode','legacy'):
        raise ValueError('Curriculum local/server prompt mode mismatch')
    if any(identity.get(key)!=metadata.get(key) for key in ('checkpoint_id','training_steps','checkpoint_step')):
        raise ValueError('Curriculum local trained checkpoint differs from loaded policy')
    return Path(checkpoint),identity

def verified_curriculum_fixture(episode):
    """Reject historical local operations with missing destination records."""
    trace,collection,scene,frame=source_identity(episode)
    if scene['split']!='train':raise ValueError('Curriculum DAgger is train-only')
    from r1pro_teleop.vla.rollout import selected_sources
    selected_sources(collection,scene_ids=[scene['scene_id']],train_only=True)
    if episode['skill']=='initialize_posture':return
    events=[json.loads(line) for line in (trace.parent/'events.jsonl').read_text().splitlines()]
    operations=[e for e in events if e.get('event')=='operation_selected' and e['frame']<=frame]
    transitions=[e for e in events if e.get('event')=='state_transition' and e['frame']<=frame]
    if not operations or not transitions:raise ValueError('Curriculum source operation context missing')
    selected,transition=operations[-1],transitions[-1]
    operation=selected['operation']
    if (transition.get('target_tray')!=operation['tray'] or transition.get('target_slot')!=operation['slot'] or
        selected.get('operation_index')!=episode.get('operation_index')):
        raise ValueError('Curriculum local operation destination is not recorded; no inferred fixture')

class CurriculumRoundView:
    """Attach immutable source initialization and actual learner context to every label."""
    def __init__(self,round_data,episode,provenance):
        if episode['split']!='train' or provenance.get('initial_restore_count')!=1:
            raise ValueError('Train-only curriculum requires exactly one verified initial restore')
        self.round=round_data;self.initial=dict(provenance)
        self.initial.update(episode_index=episode['episode_index'],skill=episode['skill'],collection_mode='expert_snapshot_curriculum')
        if self.initial.get('source_trace_sha256')!=episode['source_trace_sha256'] or self.initial.get('source_frame')!=episode['source_start_frame']:
            raise ValueError('Curriculum initial provenance differs from selected episode')
        self.decision_context=None

    def collect_intervention(self,**kwargs):
        from r1pro_teleop.vla.dagger import state_digest
        if self.decision_context is None:raise ValueError('Actual learner decision context required')
        context=dict(self.initial,**self.decision_context,learner_state_sha256=state_digest(kwargs['simulator_state']))
        if kwargs['split']!='train' or context['skill']!=self.initial['skill'] or kwargs['observation']['prompt']!=context['prompt']:
            raise ValueError('Curriculum learner skill/prompt/split mismatch')
        # Standard collector performs isolated fresh-state planning, label replay
        # validation and raw learner/physics/image persistence without rollback.
        row=self.round.collect_intervention(**kwargs)
        if row['state_sha256']!=context['learner_state_sha256']:raise ValueError('Curriculum visited state differs from label')
        directory=Path(row['sample_dir']);context_path=directory/'curriculum_context.json'
        with context_path.open('x') as stream:json.dump(context,stream,indent=2)
        row.update(collection_mode='expert_snapshot_curriculum',curriculum_context=context,curriculum_context_sha256=sha(context_path))
        (directory/'metadata.json').write_text(json.dumps(row,indent=2),encoding='utf-8')
        # The new round remains collecting. Preserve the original standard label
        # schema and hashes, and include binding in its aggregation input row.
        path=self.round.directory/'interventions.jsonl';temporary=path.with_suffix('.tmp')
        temporary.write_text(''.join(json.dumps(value)+'\n' for value in self.round.rows),encoding='utf-8');temporary.replace(path)
        return row

def curriculum_observer(machine,round_data,expert,path,episode,provenance,*,query_interval,max_queries):
    from r1pro_teleop.vla.rollout import DaggerObserver
    view=CurriculumRoundView(round_data,episode,provenance)
    class Observer(DaggerObserver):
        def __call__(self,payload):
            view.decision_context=dict(step=int(payload['step']),decision=self.decisions+1,
                skill=machine.current_skill,prompt=payload['prompt'])
            return super().__call__(payload)
        def _event(self,event):
            super()._event(dict(event,collection_mode='expert_snapshot_curriculum',initial_source=view.initial))
    return Observer(machine,view,expert,path,query_interval=query_interval,max_queries=max_queries)

def verify_curriculum_labels(round_data):
    """A context-persistence error cannot make an unbound label trainable."""
    from r1pro_teleop.vla.dagger import verify_curriculum_context
    hash_cache={}
    required=('source_trace','source_trace_sha256','source_frame','source_scene_sha256','scene_xml_sha256',
              'episode_index','skill','initial_restore_count','learner_state_sha256','step','decision','prompt')
    for row in round_data.rows:
        verify_curriculum_context(row,required=True,hash_cache=hash_cache)
        context=row.get('curriculum_context',{})
        path=Path(row['sample_dir'])/'curriculum_context.json'
        if (not path.resolve().is_relative_to(round_data.directory.resolve()) or
            any(key not in context for key in required) or context.get('initial_restore_count')!=1 or
            context.get('collection_mode')!='expert_snapshot_curriculum' or context.get('step',0)<=0 or
            context.get('learner_state_sha256')!=row['state_sha256'] or context.get('prompt')!=row['prompt'] or
            not path.is_file() or row.get('curriculum_context_sha256')!=sha(path) or read(path)!=context):
            raise ValueError('Curriculum label lacks verified source/visited-state binding')

def read(path):return json.loads(Path(path).read_text(encoding='utf-8'))
def sha(path):
    result=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):result.update(block)
    return result.hexdigest()

def source_identity(episode):
    trace=Path(episode['source_trace']).resolve();collection=trace.parents[3]
    sid=episode['scene_id'];frame=episode['source_start_frame']
    if (trace.parent.parent.name!=sid or trace.parent.parent.parent.name!='attempts' or
        episode['skill'] not in SKILLS or type(frame) is not int or frame<0 or
        sha(trace)!=episode['source_trace_sha256']):raise ValueError('Expert episode identity/hash mismatch')
    result=read(trace.parent/'result.json');scene=read(collection/'scenes'/sid/'scene.json')
    if (result.get('task_completed') is not True or result.get('controller_source','program_generated')!='program_generated' or
        scene['split']!=episode['split'] or scene['scene_id']!=sid):raise ValueError('Expected successful simulation expert provenance')
    return trace,collection,scene,frame

def numeric_snapshot(runtime):
    integration=np.empty(runtime.integration_size,np.float64)
    runtime.mj.mj_getState(runtime.m,runtime.d,integration,runtime.integration_spec)
    return dict(integration_state=integration,qpos=runtime.d.qpos.copy(),qvel=runtime.d.qvel.copy(),
        ctrl=runtime.d.ctrl.copy(),act=runtime.d.act.copy(),qacc_warmstart=runtime.d.qacc_warmstart.copy(),
        time=float(runtime.d.time),joint_target=runtime.sim.target.copy(),base_target=runtime.sim.base_target.copy())

def restore_initial_once(runtime,snapshot):
    integration=np.asarray(snapshot['integration_state'],np.float64)
    if integration.shape!=(runtime.integration_size,) or not np.isfinite(integration).all():
        raise ValueError('Complete finite integration snapshot required')
    for key in ('qpos','qvel','ctrl','act','qacc_warmstart'):
        value=np.asarray(snapshot[key]);target=getattr(runtime.d,key)
        if value.shape!=target.shape or not np.isfinite(value).all():raise ValueError('Snapshot shape/finite mismatch: '+key)
    runtime.mj.mj_setState(runtime.m,runtime.d,integration,runtime.integration_spec)
    runtime.mj.mj_forward(runtime.m,runtime.d)
    # Warmstart is solver state, not an artificial trajectory correction.
    runtime.d.qacc_warmstart[:]=snapshot['qacc_warmstart']
    for key in ('qpos','qvel','ctrl','act'):
        if not np.array_equal(getattr(runtime.d,key),snapshot[key]):raise ValueError('Full snapshot restoration differs: '+key)
    if abs(runtime.d.time-snapshot['time'])>1e-10:raise ValueError('Snapshot time mismatch')
    runtime.sim.target=np.asarray(snapshot['joint_target']).copy();runtime.sim.base_target=np.asarray(snapshot['base_target']).copy()
    runtime.physics_clock_origin_time=float(runtime.d.time);runtime.physics_step_count=0
    runtime.physical_time_start=float(runtime.d.time);runtime.steps=0;runtime.wall_start=time.monotonic()

def continuous_cpu_prefix_snapshot(collection,scene,data,frame):
    """Replay original controls on CPU; no renderer or guessed actuator state."""
    from r1pro_teleop.airport_fsm.runtime import Runtime
    from r1pro_teleop.airport_fsm.registry import config_for
    r=Runtime(scene,collection/'scenes'/scene['scene_id']/'mobile.xml',config_for(collection),render=False)
    try:
        integration=np.asarray(data['integration_state'][0],np.float64)
        if integration.shape!=(r.integration_size,) or not np.isfinite(integration).all():
            raise ValueError('Continuous prefix requires a complete original initial integration state')
        r.mj.mj_setState(r.m,r.d,integration,r.integration_spec);r.mj.mj_forward(r.m,r.d)
        r.d.qacc_warmstart[:]=data['qacc_warmstart'][0]
        schema=data.attrs['schema']
        if schema not in ('airport_fsm_raw/1','airport_fsm_raw/2'):raise ValueError('Original control semantics unknown')
        for index in range(frame+1):
            if (np.max(np.abs(r.d.qpos-data['qpos'][index]))>r.cfg.replay_tolerance or
                np.max(np.abs(r.d.qvel-data['qvel'][index]))>r.cfg.replay_tolerance*10 or
                abs(r.d.time-float(data['sim_time'][index]))>1e-8):raise ValueError('Continuous expert prefix diverged')
            if index==frame:return numeric_snapshot(r)
            if not bool(data['transition_completed'][index]):raise ValueError('Cannot use an incomplete original control interval')
            r.sim.target=data['action'][index].copy();r.sim.base_target=data['base_action'][index].copy()
            if schema=='airport_fsm_raw/1':
                r.sim.apply_target()
                recorded=data['ctrl'][index+1]
                if not np.array_equal(r.d.ctrl,recorded):raise ValueError('Original servo reconstruction disagrees with next-row applied ctrl')
                controls=np.repeat(recorded[None,:],r.sim.nstep,axis=0)
            else:
                count=int(data['executed_substeps'][index])
                if count!=r.sim.nstep:raise ValueError('Incomplete raw/2 prefix interval')
                controls=np.asarray(data['ctrl_substeps'][index,:count])
            if controls.shape!=(r.sim.nstep,r.m.nu) or not np.isfinite(controls).all():raise ValueError('Invalid actual actuator control journal')
            for ctrl in controls:
                r.d.ctrl[:]=ctrl;r.mj.mj_step(r.m,r.d);r.mj.mj_forward(r.m,r.d)
        raise ValueError('Expert prefix did not reach requested snapshot')
    finally:r.close()

def decode_full_vector(runtime,data,metadata,frame):
    """Decode actual ctrl/act via MuJoCo API, never infer missing arrays."""
    vector=np.asarray(data['integration_state'][frame],np.float64)
    declared=metadata.get('integration_state_spec',data.attrs.get('integration_state_spec'))
    if declared is not None and int(declared)!=int(runtime.integration_spec):raise ValueError('Source integration state spec mismatch')
    if data.attrs['schema'] not in ('airport_fsm_raw/1','airport_fsm_raw/2'):
        raise ValueError('Source schema does not declare MuJoCo INTEGRATION state semantics')
    if vector.shape!=(runtime.integration_size,) or not np.isfinite(vector).all():raise ValueError('Invalid original complete state vector')
    private=runtime.mj.MjData(runtime.m)
    runtime.mj.mj_setState(runtime.m,private,vector,runtime.integration_spec)
    runtime.mj.mj_forward(runtime.m,private)
    private.qacc_warmstart[:]=data['qacc_warmstart'][frame]
    for key in ('qpos','qvel','ctrl','act'):
        if key in data and not np.array_equal(getattr(private,key),data[key][frame]):
            raise ValueError('Decoded complete state disagrees with original '+key)
    if abs(float(private.time)-float(data['sim_time'][frame]))>1e-10:raise ValueError('Decoded complete state time mismatch')
    proxy=SimpleNamespace(m=runtime.m,mj=runtime.mj,d=private,integration_size=runtime.integration_size,
        integration_spec=runtime.integration_spec,sim=runtime.sim)
    return numeric_snapshot(proxy)

def expert_snapshot(episode,runtime):
    import h5py
    trace,collection,scene,frame=source_identity(episode)
    with h5py.File(trace,'r') as data:
        metadata=json.loads(data.attrs['metadata_json']);n=int(data.attrs['num_frames'])
        if (frame>=n or metadata.get('controller_source')!='program_generated' or metadata.get('scene')!=scene or
            metadata.get('scene_xml_sha256')!=sha(runtime.sim.scene) or
            not np.isclose(metadata['physics_timestep_s'],runtime.m.opt.timestep,rtol=0,atol=1e-12)):
            raise ValueError('Source snapshot physics/scene mismatch')
        # The previous command is part of initial controller state. Never use
        # action[frame:] as a learner fallback or future execution reference.
        previous=frame-1
        target=data['action'][previous].copy() if previous>=0 else runtime.sim.target.copy()
        base=data['base_action'][previous].copy() if previous>=0 else runtime.sim.base_target.copy()
        full=(all(key in data for key in ('integration_state','qpos','qvel','qacc_warmstart','sim_time')) and
              data['integration_state'].ndim==2 and data['integration_state'].shape[0]>=n and
              data['integration_state'].shape[1]==runtime.integration_size)
        if full:
            snapshot=decode_full_vector(runtime,data,metadata,frame)
            snapshot.update(joint_target=target,base_target=base)
            origin='recorded_full_integration_vector_API_decoded_ctrl_act'
        else:
            # Capture a complete state after continuous original prefix
            # integration. No per-frame qpos/qvel restoration or guessed ctrl.
            snapshot=continuous_cpu_prefix_snapshot(collection,scene,data,frame)
            snapshot.update(joint_target=target,base_target=base);origin='verified_continuous_expert_prefix_snapshot'
        initial_bottom=data['min_z'][0].copy()
        declared_spec=metadata.get('integration_state_spec',data.attrs.get('integration_state_spec'))
    restore_initial_once(runtime,snapshot)
    runtime.initial_bottom=initial_bottom
    return dict(origin=origin,source_trace=str(trace),source_trace_sha256=sha(trace),source_frame=frame,
        source_scene_sha256=sha(collection/'scenes'/scene['scene_id']/'scene.json'),scene_xml_sha256=sha(runtime.sim.scene),
        integration_state_spec=int(runtime.integration_spec),integration_state_spec_name='mjSTATE_INTEGRATION',
        source_declared_integration_state_spec=None if declared_spec is None else int(declared_spec),
        state_spec_validation_basis='explicit_source_spec_and_API_fields' if declared_spec is not None else
            'legacy_airport_fsm_raw_schema_INTEGRATION_contract_plus_API_width_qpos_qvel_ctrl_act_time_checks',
        split=scene['split'],initial_time=snapshot['time'],initial_restore_count=1,
        prior_controller_command_frame=previous if previous>=0 else None),collection

def operation_for(episode,runtime):
    from r1pro_teleop.airport_fsm.geometry import Operation,quat_yaw_tilt
    if episode['skill']=='initialize_posture':
        pose=runtime.observation()['tray_pose'][0];return Operation(0,-1,pose[:3].copy(),float(quat_yaw_tilt(pose[3:])[0]))
    events=Path(episode['source_trace']).parent/'events.jsonl'
    selected=[read_event for line in events.read_text().splitlines()
        if (read_event:=json.loads(line)).get('event')=='operation_selected' and read_event['frame']<=episode['source_start_frame']]
    if not selected:raise ValueError('No recorded expert operation for requested skill')
    event=selected[-1]
    if episode.get('operation_index') is not None and event['operation_index']!=episode['operation_index']:
        raise ValueError('Recorded operation index differs from episode')
    values=event['operation'];values['destination']=np.asarray(values['destination'],float)
    return Operation(**values)

def skill_predicate(machine,skill):
    r=machine.r
    if skill=='initialize_posture':
        from r1pro_teleop.vla.machine import initial_posture_ready
        return initial_posture_ready,3
    if skill=='navigate_to_tray':return machine._navigation_ready,4
    if skill=='push_adjust_tray':return machine._placed,20
    if skill=='place_release_tray':return machine._released,4
    if skill=='carry_tray':return lambda runtime,op:bool(np.linalg.norm(runtime.observation()['tray_pose'][op.tray,:2]-op.destination[:2])<=.18),2
    if skill=='grasp_lift_tray':
        def lifted(runtime,op):
            e=runtime.observation();return bool(np.min(e['gripper_contact_force'][op.tray])>.5 and
                e['min_z'][op.tray]-runtime.initial_bottom[op.tray]>=runtime.cfg.completion_lift_min_m)
        return lifted,2
    raise ValueError('Unsupported isolated skill')

def skill_state(skill):
    from r1pro_teleop.airport_fsm.contracts import State
    return dict(initialize_posture=State.SEARCH_TARGET,navigate_to_tray=State.ALIGN_BASE,
        push_adjust_tray=State.ADJUST_TRAY,grasp_lift_tray=State.GRASP_TRAY,
        carry_tray=State.TRANSPORT_TRAY,place_release_tray=State.PLACE_TRAY)[skill]

def restore_contact_bookkeeping(runtime,operation,skill):
    if skill in ('carry_tray','place_release_tray'):
        force=runtime.observation()['gripper_contact_force'][operation.tray]
        if np.min(force)<=.5:raise ValueError('Held skill source initial state lacks measured dual contact')
        runtime.remember_grasp(operation.tray)

def restore_scheduler_context(machine,episode):
    """Restore recorded high-level geometry, never future expert commands."""
    import h5py
    from r1pro_teleop.airport_fsm.geometry import Scheduler
    from r1pro_teleop.airport_fsm.acceptance_profile import completion_criteria
    from r1pro_teleop.airport_fsm.reservation_plan import validate_plan
    trace=Path(episode['source_trace']);frame=episode['source_start_frame']
    events=[json.loads(line) for line in (trace.parent/'events.jsonl').read_text().splitlines()]
    selected=[event for event in events if event.get('event')=='operation_selected' and event['frame']<=frame]
    if not selected:return dict(mapping=None,reservation_plan=None)
    c=machine.c
    if not hasattr(machine,'scheduler'):
        machine.scheduler=Scheduler(machine.g,completion_criteria(c),consistent_placement=c.consistent_placement,
            require_full_footprint=c.acceptance_profile=='strict',use_actual_gap=c.acceptance_profile=='completion_first',
            approximate_overlap_cap_m=min(c.completion_collision_penetration_m,.02) if c.approximate_completion_enabled else 0.)
    with h5py.File(trace,'r') as data:
        machine.scheduler.mapping=machine.g.best_mapping(data['tray_pose'][selected[0]['frame']])
    plan=None
    for event in events:
        if event['frame']>frame:continue
        if event.get('event')=='adaptive_reservation_selected':plan=event['plan']
        if event.get('event') in ('adaptive_reservation_completed','adaptive_reservation_invalidated'):plan=None
    validate_plan(machine.g,machine.scheduler.mapping,plan);machine.scheduler.reservation_plan=plan
    machine.operations=selected[-1]['operation_index']
    return dict(mapping=list(machine.scheduler.mapping),reservation_plan=plan,
                first_operation_frame=selected[0]['frame'],last_operation_index=machine.operations)

def diagnose_one(episode,directory,metadata,*,host,port,max_steps,actuator_saturation=False,
                 round_data=None,query_interval=4,max_queries=24,expert_factory=None,private_oracle_contact_escape=False,private_oracle_measured_tracking=False,
                 init_arm_tolerance=.06,init_gripper_tolerance=.005,initializer_base_hold=False,grasp_base_hold=False):
    if type(private_oracle_measured_tracking) is not bool:raise ValueError('Private oracle measured tracking must be boolean')
    if private_oracle_measured_tracking and (round_data is None or private_oracle_contact_escape is not True):
        raise ValueError('Private oracle measured tracking requires isolated curriculum collection and private contact escape')
    if type(private_oracle_contact_escape) is not bool or (private_oracle_contact_escape and round_data is None):
        raise ValueError("Private oracle escape requires isolated curriculum collection")
    from r1pro_teleop.airport_fsm.runtime import Runtime
    from r1pro_teleop.airport_fsm.registry import config_for
    from r1pro_teleop.vla.machine import VLAMachine,stable_evaluation
    from r1pro_teleop.vla.data import language_prompt
    trace,collection,scene,_=source_identity(episode)
    if round_data is not None:verified_curriculum_fixture(episode)
    config=replace(config_for(collection),motion_backend='pi05',vla_host=host,vla_port=port,
        vla_prompt_mode=metadata.get('prompt_mode','legacy'),
        vla_checkpoint_id=metadata['checkpoint_id'],vla_action_horizon=metadata['action_horizon'],
        vla_execute_steps=min(5,metadata['action_horizon']),vla_max_skill_steps=max_steps,
        vla_servo_projection_enabled=True,vla_servo_projection_mode='actuator_saturation' if actuator_saturation else 'bounded',
        vla_reference_rate_limit_enabled=True,vla_reference_rate_fraction=.5,
        vla_initialize_arm_tolerance_rad=init_arm_tolerance,vla_initialize_gripper_tolerance_m=init_gripper_tolerance,
        vla_initializer_base_hold_enabled=initializer_base_hold,vla_grasp_base_hold_enabled=grasp_base_hold)
    config.validate();runtime=Runtime(scene,collection/'scenes'/scene['scene_id']/'mobile.xml',config,render=True)
    machine=None;observer=None;source_hash=sha(trace);result=dict(schema='airport_vla_isolated_skill_diagnostic/1',
        purpose='diagnostic_not_full_DAG_success',task_completed=False,physics_success=False,training_candidate=False,
        scene_id=scene['scene_id'],split=scene['split'],skill=episode['skill'],checkpoint_id=metadata['checkpoint_id'],
        initial_state_source='simulation/program_generated',controller_source='vla_generated',live_teacher_actions=False)
    try:
        provenance,_=expert_snapshot(episode,runtime);result['initial_snapshot']=provenance
        operation=operation_for(episode,runtime);skill=episode['skill']
        restore_contact_bookkeeping(runtime,operation,skill)  # Measured safety bookkeeping; no IK or weld.
        machine=VLAMachine(runtime,directory,seed=int(scene['seed']))
        result['source_scheduler_context']=restore_scheduler_context(machine,episode)
        metadata_trace=json.loads(machine.log.file.attrs['metadata_json'])
        metadata_trace.update(diagnostic=True,initial_snapshot=provenance,full_DAG_evaluation=False)
        machine.log.file.attrs['metadata_json']=json.dumps(metadata_trace)
        machine.current_operation=operation;machine.current_skill=skill
        prompt=episode['language_prompt']
        segment=dict(skill=skill,target_tray_id=runtime.g.ids[operation.tray],
            target_slot_id=None if operation.slot<0 else runtime.g.spec['slots'][operation.slot]['slot_id'])
        if language_prompt(segment,dict(temporary=operation.temporary))!=prompt:raise ValueError('Diagnostic prompt differs from recorded expert task')
        machine.transition(skill_state(skill),'vla_'+skill,tray=operation.tray,slot=operation.slot)
        machine.log.event('vla_skill_started',skill=skill,prompt=prompt,diagnostic=True)
        predicate,stable=skill_predicate(machine,skill)
        result['initial_predicate_already_true']=bool(predicate(runtime,operation))
        if round_data is not None:
            if expert_factory is None:
                from r1pro_teleop.vla.teacher import SimulationExpert
                expert_factory=SimulationExpert
            expert_kwargs={'machine':machine}
            if private_oracle_contact_escape:expert_kwargs['private_contact_escape']=True
            if private_oracle_measured_tracking:expert_kwargs['private_escape_measured_tracking']=True
            expert=expert_factory(runtime,Path(directory)/'private_oracle',**expert_kwargs)
            observer=curriculum_observer(machine,round_data,expert,Path(directory)/'curriculum_oracle_events.jsonl',
                episode,provenance,query_interval=query_interval,max_queries=max_queries)
            machine.executor.on_decision=observer
            result.update(collection_mode='expert_snapshot_curriculum',oracle_execution_scope='isolated_private_simulator',
                inverse_dynamics_measurement_scope='live_learner_runtime_only',method='simulation_expert_dagger',
                private_oracle_contact_escape=private_oracle_contact_escape,
                private_oracle_measured_tracking=private_oracle_measured_tracking,
                private_escape_qualification_mode='bounded_measured_tracking_after_clearance' if private_oracle_measured_tracking else 'exact_yaw_global_monotonic')
        kwargs={}
        if skill=='initialize_posture' and initializer_base_hold:
            from r1pro_teleop.vla.executor import InitializerBaseHold
            kwargs['reference_constraint']=InitializerBaseHold(Path(directory)/'vla_initializer_base_hold')
        elif skill=='grasp_lift_tray' and grasp_base_hold:
            from r1pro_teleop.vla.executor import GraspBaseHold
            kwargs['reference_constraint']=GraspBaseHold(Path(directory)/'vla_grasp_base_hold')
        result['skill_completed']=machine.executor.execute_operation(operation,prompt,stable_evaluation(predicate,stable),**kwargs)
        if skill=='initialize_posture':
            from r1pro_teleop.vla.machine import initial_posture_metrics
            result['initial_posture_completed']=initial_posture_metrics(runtime)
            machine.log.event('vla_skill_completed',skill=skill,initial_posture=result['initial_posture_completed'],
                qualification='isolated_phase_only_not_full_task_success')
        result['status']='completed'
    except Exception as exc:
        result.update(status='failed',skill_completed=False,failure_code=getattr(exc,'code',str(exc)),error=repr(exc))
        Path(directory).mkdir(parents=True,exist_ok=True)
        (Path(directory)/'exception.txt').write_text(traceback.format_exc())
    finally:
        result.update(inverse_dynamics_calls=runtime.id_calls,actual_control_steps=runtime.steps)
        result['policy_actions_executed']=runtime.steps>0
        if episode['skill']=='initialize_posture':
            from r1pro_teleop.vla.machine import initial_posture_metrics
            result['initial_posture_at_finish']=initial_posture_metrics(runtime)
        if observer is not None:
            result.update(oracle_queries=observer.queries,oracle_labels=observer.accepted,oracle_rejected=observer.rejected)
        if machine is not None:
            result.update(projection=machine.executor.projection_stats,rate_limit=machine.executor.rate_limit_stats)
            result['reference_constraints']=machine.executor.reference_constraint_stats
            machine.log.close(dict(qpos=runtime.d.qpos,qvel=runtime.d.qvel,time=float(runtime.d.time)))
        runtime.close()
    if runtime.id_calls!=0:result.update(status='failed',skill_completed=False,failure_code='diagnostic_inverse_call_forbidden')
    if sha(trace)!=source_hash:raise RuntimeError('Expert source trace changed during diagnostic')
    with (Path(directory)/'diagnostic_result.json').open('x') as stream:json.dump(result,stream,indent=2)
    return result

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--dataset-manifest',required=True)
    p.add_argument('--episode-indices',type=int,nargs='+',required=True);p.add_argument('--output',required=True)
    p.add_argument('--checkpoint-id',required=True);p.add_argument('--host',default='127.0.0.1');p.add_argument('--port',type=int,default=8765)
    p.add_argument('--max-skill-steps',type=int,default=2400);p.add_argument('--actuator-saturation',action='store_true')
    p.add_argument('--collect-curriculum-dagger',action='store_true');p.add_argument('--training-status')
    p.add_argument('--round-index',type=int,default=0);p.add_argument('--query-interval',type=int,default=4)
    p.add_argument('--max-queries',type=int,default=24)
    p.add_argument('--init-arm-tolerance',type=float,default=.06)
    p.add_argument('--init-gripper-tolerance',type=float,default=.005)
    p.add_argument('--initializer-base-hold',action='store_true')
    p.add_argument('--grasp-base-hold',action='store_true',help='Grasp only; diagnostic reference rate limiter is always enabled')
    p.add_argument('--private-oracle-contact-escape',action='store_true',help='Requires explicit curriculum DAgger collection')
    p.add_argument('--private-oracle-measured-tracking',action='store_true',help='Private label qualification only; requires curriculum and contact escape')
    args=p.parse_args(argv)
    if args.private_oracle_measured_tracking and not (args.collect_curriculum_dagger and args.private_oracle_contact_escape):
        p.error('--private-oracle-measured-tracking requires --collect-curriculum-dagger and --private-oracle-contact-escape')
    if args.private_oracle_contact_escape and not args.collect_curriculum_dagger:p.error('--private-oracle-contact-escape requires --collect-curriculum-dagger')
    from r1pro_teleop.vla.rollout import verified_server_metadata
    if args.max_skill_steps<1 or len(set(args.episode_indices))!=len(args.episode_indices):p.error('Positive skill budget and unique episode indices required')
    manifest=read(args.dataset_manifest)
    if manifest.get('schema')!='airport_pi05_training/1':raise ValueError('Verified airport training episode manifest required')
    episodes=[next(ep for ep in manifest['episodes'] if ep['episode_index']==index) for index in args.episode_indices]
    output=Path(args.output).resolve()
    for episode in episodes:
        _,collection,_,_=source_identity(episode)
        if output==collection or output.is_relative_to(collection):raise ValueError('Diagnostic outputs cannot modify expert collection')
    if args.collect_curriculum_dagger:
        if not args.training_status or args.round_index<0 or args.query_interval<1 or args.max_queries<1:
            p.error('Curriculum requires training status, nonnegative round and positive query budgets')
        for episode in episodes:verified_curriculum_fixture(episode)
    elif args.training_status:p.error('Training status is only used for explicit curriculum collection')
    metadata=verified_server_metadata(args.host,args.port,expected_checkpoint_id=args.checkpoint_id)
    round_data=None;identity=None
    if args.collect_curriculum_dagger:
        checkpoint,identity=verify_curriculum_checkpoint(args.training_status,metadata)
    output.mkdir(parents=True,exist_ok=False);rows=[]
    if args.collect_curriculum_dagger:
        from r1pro_teleop.vla.dagger import DaggerRound
        round_data=DaggerRound(output/'dagger_round',checkpoint,round_index=args.round_index,
            train_scene_ids=[episode['scene_id'] for episode in episodes])
        round_data.metadata.update(collection_mode='expert_snapshot_curriculum',full_DAG_success_eligible=False,
            task_completed=False,training_identity=identity,dataset_manifest_sha256=sha(Path(args.dataset_manifest)),
            private_oracle_measured_tracking=args.private_oracle_measured_tracking,
            private_escape_qualification_mode='bounded_measured_tracking_after_clearance' if args.private_oracle_measured_tracking else 'exact_yaw_global_monotonic')
        round_data._write()
    for episode in episodes:
        directory=output/('episode_'+str(episode['episode_index']).zfill(6))
        rows.append(diagnose_one(episode,directory,metadata,host=args.host,port=args.port,
            max_steps=args.max_skill_steps,actuator_saturation=args.actuator_saturation,round_data=round_data,
            query_interval=args.query_interval,max_queries=args.max_queries,private_oracle_contact_escape=args.private_oracle_contact_escape,
            private_oracle_measured_tracking=args.private_oracle_measured_tracking,
            init_arm_tolerance=args.init_arm_tolerance,init_gripper_tolerance=args.init_gripper_tolerance,
            initializer_base_hold=args.initializer_base_hold,grasp_base_hold=args.grasp_base_hold))
    report=dict(schema='airport_vla_isolated_skill_diagnostic_run/1',status='completed',checkpoint_metadata=metadata,
        full_DAG_success_eligible=False,task_completed=False,initial_state_source='simulation/program_generated',results=rows)
    report['model_skill_completed']=sum(row.get('skill_completed') is True and row.get('policy_actions_executed') is True and
        row.get('initial_predicate_already_true') is not True for row in rows)
    report['initially_satisfied']=sum(row.get('initial_predicate_already_true') is True for row in rows)
    if round_data is not None:
        if round_data.rows:
            try:verify_curriculum_labels(round_data)
            except Exception:
                round_data.metadata.update(status='failed_curriculum_binding_not_training_data');round_data._write();raise
            round_data.finalize()
        else:
            round_data.metadata.update(status='no_valid_labels_not_training_data');round_data._write()
        report.update(collection_mode='expert_snapshot_curriculum',method='simulation_expert_dagger',
            live_teacher_actions=False,oracle_execution_scope='isolated_private_simulator',
            inverse_dynamics_measurement_scope='live_learner_runtime_only',dagger_round=round_data.metadata,
            inverse_dynamics_calls=sum(row['inverse_dynamics_calls'] for row in rows),
            oracle_queries=sum(row.get('oracle_queries',0) for row in rows),oracle_labels=len(round_data.rows),
            oracle_rejected=sum(row.get('oracle_rejected',0) for row in rows),
            max_skill_steps=args.max_skill_steps,query_interval=args.query_interval,max_queries_per_skill=args.max_queries,
            private_oracle_measured_tracking=args.private_oracle_measured_tracking,
            private_escape_qualification_mode='bounded_measured_tracking_after_clearance' if args.private_oracle_measured_tracking else 'exact_yaw_global_monotonic',
            qualification='Expert snapshot curriculum; no fresh-scene DAG success; collection does not train')
    with (output/'diagnostic_report.json').open('x') as stream:json.dump(report,stream,indent=2)
    print(json.dumps(report,indent=2))

if __name__=='__main__':main()
