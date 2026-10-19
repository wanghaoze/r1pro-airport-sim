"""New-scope evaluation protocol, real-source audit and GPU-release handoff."""
from pathlib import Path
import hashlib,json,math,os,subprocess,time,socket,xml.etree.ElementTree as ET

from ..vla.data_three_table_single_tray import PROFILE,RULE_REVISION,FINAL_ORIENTATION_DEFINITION
CAMERAS={'head_left':(1920,1536),'head_right':(1920,1536),'left_wrist':(1280,720),'right_wrist':(1280,720)}


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        while chunk:=f.read(8*1024*1024):h.update(chunk)
    return h.hexdigest()


def canonical(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def write(path,value):
    path=Path(path);tmp=path.with_suffix(path.suffix+'.tmp')
    tmp.write_text(json.dumps(value,indent=2,allow_nan=False));tmp.replace(path)


def protocol(path):
    doc=json.loads(Path(path).read_text());rows=doc.get('scenes')
    if doc.get('schema')!='airport_three_table_single_tray_evaluation_protocol/1' or doc.get('task_profile')!=PROFILE or doc.get('base_mode')!='planar_mobile_table_front' or not isinstance(rows,list) or not rows:
        raise ValueError('explicit_new_single_tray_protocol_required')
    identity=canonical({k:v for k,v in doc.items() if k!='protocol_id'})
    if doc.get('protocol_id')!='sha256:'+identity:raise ValueError('protocol_identity_changed')
    if doc.get('task_rule_revision')!=RULE_REVISION or doc.get('final_orientation_definition')!=FINAL_ORIENTATION_DEFINITION:raise ValueError('fresh_robot_forward_protocol_required')
    registry=json.loads(Path(doc['canonical_split_registry']).read_text())
    if sha(doc['canonical_split_registry'])!=doc['canonical_split_registry_sha256']:raise ValueError('canonical_parent_registry_changed')
    canonical_test={k for k,v in registry.items() if v=='test'}
    if len(canonical_test)!=50:raise ValueError('original_canonical_test50_authority_required')
    for key in ('runtime_config','push_reference_scene'):
        if sha(doc[key])!=doc[key+'_sha256']:raise ValueError('actual_recipe_bytes_changed')
    if doc.get('selected')!=len(rows) or doc.get('canonical_parent_population_size')!=50 or doc.get('historical_evaluation_results_reused') is not False:raise ValueError('explicit_new_scope_actual_denominator_required')
    seen=set();parents=set();variants=set()
    for row in rows:
        scene_path=Path(row['scene_json']);scene=json.loads(scene_path.read_text())
        if sha(scene_path)!=row['scene_json_sha256'] or sha(scene['xml'])!=row['scene_xml_sha256'] or scene['xml_sha256']!=row['scene_xml_sha256']:raise ValueError('protocol_source_bytes_changed')
        if scene.get('schema')!='airport_three_table_single_tray_scene/1' or scene.get('task_profile')!=PROFILE or scene.get('task_rule_revision')!=RULE_REVISION or scene.get('final_orientation_definition')!=FINAL_ORIENTATION_DEFINITION or scene.get('base_mode')!='planar_mobile_table_front' or scene.get('model_action_mask')!=[True]*19 or scene.get('route_goal_observation_policy')!='fixed_registered_rear_to_front_left_route':raise ValueError('old_or_hidden_goal_scope_rejected')
        pid=scene['parent_scene_id']
        if pid not in canonical_test or pid!=row['parent_scene_id'] or scene['split']!='test' or row['split']!='test' or scene['scene_id']!=row['scene_id'] or scene['scene_id'] in seen:raise ValueError('canonical_test_parent_duplicate_or_train_leak')
        seed=scene.get('seed')
        if type(seed) is not int or row.get('variant_seed',seed)!=seed or (pid,seed) in variants:
            raise ValueError('canonical_test_variant_duplicate_or_seed_changed')
        if scene['canonical_split_registry_sha256']!=doc['canonical_split_registry_sha256']:raise ValueError('scene_registry_authority_changed')
        trays=[b.get('name') for b in ET.parse(scene['xml']).iter('body') if (b.get('name') or '').startswith('tray')]
        if trays!=['tray']:raise ValueError('exactly_one_tray_model_required')
        seen.add(scene['scene_id']);parents.add(pid);variants.add((pid,seed))
    if 'distinct_parent_count' in doc and doc['distinct_parent_count']!=len(parents):raise ValueError('actual_parent_coverage_changed')
    if 'declared_selection' in doc and doc['declared_selection']!=[
        dict(scene_id=r['scene_id'],parent_scene_id=r['parent_scene_id'],variant_seed=json.loads(Path(r['scene_json']).read_text())['seed']) for r in rows]:
        raise ValueError('declared_variant_selection_changed')
    return doc


def verify_inputs(spec_path,milestone_path,protocol_path):
    spec=json.loads(Path(spec_path).read_text());m=json.loads(Path(milestone_path).read_text());p=protocol(protocol_path)
    execution=p.get('execution',{})
    if type(execution.get('max_action_steps')) is not int or execution['max_action_steps']<=0 or execution.get('execute_steps')!=5 or execution.get('fps')!=20 or execution.get('environment_phase_excluded') is not True:raise ValueError('formal_new_task_explicit_execution_budget_required')
    if spec.get('prompt_mode')!=PROFILE or m.get('prompt_mode')!=PROFILE or m.get('schema')!='airport_pi05_training_milestone/1' or m.get('status')!='milestone_checkpoint' or m.get('checkpoint_verified') is not True:
        raise ValueError('actual_saved_new_task_milestone_required')
    n=m.get('actual_completed_updates')
    if type(n) is not int or n<=0 or m.get('training_steps')!=n or m.get('checkpoint_step')!=n-1:
        raise ValueError('actual_completed_update_identity_required')
    if any(canonical(v)!=canonical(m.get('spec',{}).get(k)) for k,v in spec.items()):raise ValueError('milestone_training_spec_changed')
    if m.get('base_mode')!='planar_mobile_table_front' or m.get('base_actuated') is not True or m.get('model_action_mask')!=[True]*19:
        raise ValueError('fixed_front_checkpoint_required')
    return spec,m,p


ACTION_PROMPTS={'pick_empty':'Pick up the tray','place_empty':'Place the tray','push_loaded':'Flush tray to the left'}

def action_evidence(result,event_rows=None):
    spans=result.get('action_spans',[]);completed={label:False for label in ACTION_PROMPTS}
    for span in spans:
        label=span.get('action_label')
        if label not in completed or span.get('verified') is not True:continue
        start,end,endpoint=span.get('start_frame'),span.get('end_frame'),span.get('measured_endpoint_frame')
        if any(type(v) is not int for v in (start,end,endpoint)) or not 0<=start<=endpoint<end<=result['frames']:raise ValueError('verified_action_span_not_within_actual_trace')
        completed[label]=True
    started={row.get('action_label') for row in event_rows or [] if row.get('event')=='action_start'}
    known=event_rows is not None or result.get('physical_episode_started') is False and result.get('actual_inference_calls')==0
    attempted={label:True if completed[label] or label in started else False if known else None for label in completed}
    statuses={label:'completed_verified' if completed[label] else 'attempted_incomplete' if attempted[label] is True else 'not_attempted' if attempted[label] is False else 'attempt_evidence_unavailable' for label in completed}
    return dict(action_spans=spans,per_action_completed=completed,per_action_attempted=attempted,per_action_status=statuses,actual_inference_calls=result.get('actual_inference_calls'),inverse_solver_calls=result.get('inverse_solver_calls'),teacher_fallback_calls=result.get('teacher_fallback_calls'))

def case_action_evidence(case,result):
    events=Path(case)/'attempt/events.jsonl'
    rows=[json.loads(line) for line in events.read_text().splitlines() if line.strip()] if events.exists() else None
    return action_evidence(result,rows)

def verify_case(case,native,checkpoint_id,scene_id,split,*,require_contact_evidence=False):
    import h5py
    case=Path(case);native=Path(native);r=json.loads((case/'result.json').read_text())
    if r.get('task_profile')!=PROFILE or r.get('checkpoint_id')!=checkpoint_id or r.get('scene_id')!=scene_id or r.get('split')!=split or r.get('inverse_solver_calls')!=0 or r.get('teacher_fallback_calls')!=0:
        raise ValueError('new_scope_actual_learned_result_required')
    with h5py.File(case/'attempt/trace.h5') as f:
        frames=int(f.attrs['num_frames'])
        if f.attrs.get('schema')!='airport_fsm_raw/2' or frames<1 or len(f['qpos'])!=frames or frames not in (r.get('frames'),r.get('frames',-2)+1) or 'terminal_snapshot_json' not in f.attrs:
            raise ValueError('actual_nonempty_raw2_trace_required')
        meta=json.loads(f.attrs['metadata_json'])
        if meta.get('checkpoint_id')!=checkpoint_id or meta.get('task_profile')!=PROFILE or meta.get('task_rule_revision')!=RULE_REVISION or meta.get('base_mode')!='planar_mobile_table_front' or meta.get('base_actuated') is not True or meta.get('model_action_mask')!=[True]*19:
            raise ValueError('actual_fixed_front_trace_contract_required')
    replay=json.loads((native/'manifest.json').read_text())
    errors=replay.get('errors',{})
    if replay.get('schema')!='airport_three_table_original_trace_native_replay/1' or replay.get('frames')!=frames or replay.get('initial_restore_count')!=1 or set(errors)!={'qpos','qvel','time','terminal_qpos','terminal_qvel','terminal_time'} or any(type(v) not in (int,float) or not math.isfinite(v) or v>1e-7 or v<0 for v in errors.values()):
        raise ValueError('full_continuous_native_replay_required')
    sources={'trace':case/'attempt/trace.h5','events':case/'attempt/events.jsonl','scene_xml':case/'scene/mobile.xml','scene_json':case/'scene/scene.json'}
    if replay.get('source_sha256')!={k:sha(v) for k,v in sources.items()}:raise ValueError('replay_source_identity_changed')
    videos=[]
    for camera,(w,h) in CAMERAS.items():
        path=native/(camera+'.mp4')
        if not path.is_file():raise ValueError('missing_native_video:'+camera)
        stream=json.loads(subprocess.check_output(['ffprobe','-v','error','-count_frames','-select_streams','v:0','-show_entries','stream=width,height,avg_frame_rate,nb_read_frames','-of','json',str(path)],text=True))['streams'][0]
        if int(stream['width'])!=w or int(stream['height'])!=h or stream['avg_frame_rate']!='20/1' or int(stream['nb_read_frames'])!=frames:raise ValueError('native_video_not_complete')
        videos.append(dict(camera=camera,path=str(path.resolve()),sha256=sha(path),frames=frames))
    completed=r.get('task_completed') is True and r.get('physics_success') is True
    if completed and ([s.get('action_label') for s in r.get('action_spans',[])]!=['pick_empty','place_empty','push_loaded'] or any(s.get('verified') is not True for s in r['action_spans']) or r.get('actual_handover_verified') is not True):raise ValueError('complete_task_requires_three_verified_actions')
    from ..single_tray_lab.contact_summary import audit_contact_peaks
    contact=audit_contact_peaks(r,case/'attempt/trace.h5',raw_schema='airport_fsm_raw/2',task_profile=PROFILE)
    if require_contact_evidence and contact['coverage']=='unavailable':raise ValueError('formal_new_single_tray_contact_peak_evidence_required')
    return dict(scene_id=scene_id,split=split,task_completed=completed,failure_code=r.get('failure_code'),failure_detail=r.get('failure_detail'),
        strict_success=None,strict_contact_success=contact['strict_contact_success'],strict_contact_evidence=contact,
        frames=frames,result=str((case/'result.json').resolve()),result_sha256=sha(case/'result.json'),
        trace=str((case/'attempt/trace.h5').resolve()),trace_sha256=sha(case/'attempt/trace.h5'),videos=videos,
        native_manifest=str((native/'manifest.json').resolve()),native_manifest_sha256=sha(native/'manifest.json'),**case_action_evidence(case,r))


def verify_zero_frame_infrastructure(case,checkpoint_id,scene_id,split):
    case=Path(case);r=json.loads((case/'result.json').read_text())
    if r.get('task_profile')!=PROFILE or r.get('checkpoint_id')!=checkpoint_id or r.get('scene_id')!=scene_id or r.get('split')!=split or r.get('frames')!=0 or r.get('physical_episode_started') is not False or r.get('actual_inference_calls')!=0 or r.get('task_completed') is not False or r.get('zero_frame_evidence',{}).get('native_video_possible') is not False:
        raise ValueError('actual_zero_frame_initialization_evidence_required')
    trace=case/'attempt/trace.h5'
    if trace.exists():
        import h5py
        with h5py.File(trace) as f:
            if int(f.attrs['num_frames'])!=0:raise ValueError('zero_frame_result_disagrees_with_trace')
    return dict(scene_id=scene_id,split=split,task_completed=False,infrastructure_error=True,physical_episode_started=False,model_task_outcome='unavailable_no_model_execution',failure_code=r.get('failure_code'),failure_detail=r.get('failure_detail'),frames=0,strict_contact_success=None,strict_contact_evidence={'coverage':'unavailable'},videos=[],native_video_status='unavailable_zero_physical_frames',result=str((case/'result.json').resolve()),result_sha256=sha(case/'result.json'),trace=str(trace.resolve()) if trace.exists() else None,trace_sha256=sha(trace) if trace.exists() else None,**case_action_evidence(case,r))

def summary(rows,selected,protocol_id,protocol_doc=None):
    if len(rows)!=selected:raise ValueError('missing_evaluation_cases')
    physical=[r for r in rows if not r.get('infrastructure_error')]
    infrastructure=[r for r in rows if r.get('infrastructure_error')]
    successes=sum(r['task_completed'] is True for r in physical)
    strict_contact=sum(r.get('strict_contact_success') is True for r in rows)
    contact_covered=sum(r.get('strict_contact_evidence',{}).get('coverage')=='every_guarded_physics_substep' for r in rows)
    failures={}
    for r in rows:
        if not r.get('infrastructure_error') and not r['task_completed']:failures[r.get('failure_code') or 'unknown_failure']=failures.get(r.get('failure_code') or 'unknown_failure',0)+1
    coverage={} if protocol_doc is None else dict(evaluation_episode_count=selected,
        distinct_parent_count=len({r['parent_scene_id'] for r in protocol_doc['scenes']}),
        canonical_parent_population_size=protocol_doc['canonical_parent_population_size'],
        evaluated_parent_scene_ids=sorted({r['parent_scene_id'] for r in protocol_doc['scenes']}))
    return dict(schema='airport_three_table_single_tray_evaluation_summary/1',task_profile=PROFILE,protocol_id=protocol_id,**coverage,
        selected=selected,attempted=len(rows),covered=len(physical),infrastructure_error_count=len(infrastructure),infrastructure_cases=infrastructure,complete_tasks=successes,complete_task_rate=successes/selected if not infrastructure else None,model_executed_task_rate=successes/len(physical) if physical else None,
        strict_successes=None,strict_status='unavailable',
        strict_contact_successes=strict_contact,strict_contact_rate=strict_contact/selected if contact_covered==selected else None,
        strict_contact_evidence_covered=contact_covered,strict_contact_evidence_unavailable=selected-contact_covered,
        strict_contact_definition='task_complete_and_all_guarded_hard_le_3mm_soft_le_5mm',
        acceptance_difference_not_control_improvement=True,historical_three_tray_strict_metric_used=False,
        action_complete_counts={prompt:sum(r.get('per_action_completed',{}).get(label) is True for r in rows) for label,prompt in ACTION_PROMPTS.items()},action_attempted_counts={prompt:sum(r.get('per_action_attempted',{}).get(label) is True for r in rows) for label,prompt in ACTION_PROMPTS.items()},action_not_attempted_counts={prompt:sum(r.get('per_action_attempted',{}).get(label) is False for r in rows) for label,prompt in ACTION_PROMPTS.items()},failures=failures,cases=rows)


def handoff(milestone_path,protocol_id,summary_path,owned_processes,gpu_rows):
    if not owned_processes or any(p.get('returncode') is None or p.get('active') is not False for p in owned_processes) or gpu_rows:
        raise ValueError('actual_owned_process_exit_and_gpu_release_required')
    s=json.loads(Path(summary_path).read_text());m=json.loads(Path(milestone_path).read_text())
    if m.get('schema')!='airport_pi05_training_milestone/1' or m.get('prompt_mode')!=PROFILE or m.get('status')!='milestone_checkpoint' or m.get('checkpoint_verified') is not True or type(m.get('actual_completed_updates')) is not int or m['actual_completed_updates']<=0:
        raise ValueError('actual_new_task_milestone_required')
    if s.get('protocol_id')!=protocol_id or s.get('covered')!=s.get('selected') or not s.get('selected') or len(s.get('cases',[]))!=s['selected'] or any(len(c.get('videos',[]))!=4 for c in s['cases']):raise ValueError('complete_native_case_coverage_required')
    for c in s['cases']:
        if {v.get('camera') for v in c['videos']}!=set(CAMERAS):raise ValueError('complete_native_camera_identity_required')
        for v in c['videos']:
            if type(v.get('frames')) is not int or v['frames']<1 or not Path(v.get('path','')).is_file() or sha(v['path'])!=v.get('sha256'):raise ValueError('native_video_changed_after_audit')
        for field in ('trace','result'):
            if not Path(c.get(field,'')).is_file() or sha(c[field])!=c.get(field+'_sha256'):raise ValueError('evaluated_source_changed_after_audit')
    return dict(schema='airport_three_table_single_tray_evaluation_handoff/1',task_profile=PROFILE,
        actual_completed_updates=m['actual_completed_updates'],training_status_sha256=sha(milestone_path),
        status='evaluation_completed_gpu_released',training_resume_allowed=True,new_three_table_single_tray_protocol_id=protocol_id,
        evaluation_summary=str(Path(summary_path).resolve()),evaluation_summary_sha256=sha(summary_path),
        actual_owned_processes=owned_processes,active_owned_gpu_rows=[])


def gpu_processes():
    doc=ET.fromstring(subprocess.check_output(['nvidia-smi','-q','-x'],text=True))
    return [dict(pid=int(p.findtext('pid')),gpu_uuid=g.findtext('uuid'),type=p.findtext('type')) for g in doc.findall('gpu') for p in g.findall('./processes/process_info')]


def run_batch(args):
    spec,m,p=verify_inputs(args.spec,args.milestone,args.protocol)
    max_action_steps=getattr(args,'max_action_steps',p['execution']['max_action_steps'])
    execute_steps=getattr(args,'execute_steps',p['execution']['execute_steps'])
    if max_action_steps!=p['execution']['max_action_steps'] or execute_steps!=p['execution']['execute_steps']:raise ValueError('evaluation_execution_budget_protocol_mismatch')
    out=Path(args.out).resolve();out.mkdir(parents=True,exist_ok=True)
    inputs=dict(spec_sha256=sha(args.spec),milestone_sha256=sha(args.milestone),protocol_sha256=sha(args.protocol),protocol_id=p['protocol_id'],execution=p['execution'],maximum_action_sim_seconds=p['execution']['max_action_steps']/20,maximum_three_action_sim_seconds=3*p['execution']['max_action_steps']/20,excluded_time='passenger_load_settle_environment_time_and_model_render_wall_time',budget_change_is_control_improvement=False)
    if (out/'input_receipt.json').exists() and json.loads((out/'input_receipt.json').read_text())!=inputs:raise ValueError('evaluation_recovery_input_identity_changed')
    write(out/'input_receipt.json',inputs)
    if not args.execute:
        write(out/'status.json',dict(stage='prepared_no_model_or_gpu_execution',selected=len(p['scenes']),**inputs));return
    if not 1<=args.port<=65535 or args.startup_timeout<=0:raise ValueError('invalid_model_service_startup_contract')
    with socket.socket() as probe:probe.bind(('127.0.0.1',args.port))
    release=Path(__file__).resolve().parents[2];env=dict(os.environ,OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1')
    client_src=Path(spec['openpi_root'])/'packages/openpi-client/src';official_src=Path(spec['openpi_root'])/'src'
    client_module=client_src/'openpi_client/websocket_client_policy.py'
    if not client_module.is_file():raise ValueError('verified_project_openpi_client_source_required')
    env['PYTHONPATH']=os.pathsep.join([str(client_src),str(official_src),str(release),env.get('PYTHONPATH','')])
    write(out/'client_source_receipt.json',dict(path=str(client_module),sha256=sha(client_module),installation_changed=False))
    env.pop('JAX_PLATFORMS',None);env.update(CUDA_VISIBLE_DEVICES=args.gpu_uuid,MUJOCO_GL='egl',MUJOCO_EGL_DEVICE_ID=str(args.egl_device))
    from ..vla.three_table_recovery import training_resources,isolate_partial
    from ..vla.training_pipeline import unused_path,wait_owned_startup,verify_owned
    resources=training_resources(min_free_mib=30000,project_root=release.parents[1] if release.parent.name=='releases' else release)
    if not args.gpu_uuid or resources['actual_free_mib'].get(args.gpu_uuid,0)<30000 or any(r['gpu_uuid']==args.gpu_uuid for r in resources['active_owned_compute']):raise ValueError('model_gpu_headroom_or_owned_consumer_blocked')
    write(out/'resource_preflight.json',resources)
    identity_cmd=[args.model_python,str(release/'scripts/serve_pi05_airport.py'),'--training-status',str(args.milestone),'--identity-only']
    identity=json.loads(subprocess.check_output(identity_cmd,cwd=release,env=dict(env,CUDA_VISIBLE_DEVICES='',JAX_PLATFORMS='cpu'),text=True))
    checkpoint_id=identity['checkpoint_id'];owned=[];rows=[];server=None;server_log=None
    def invoke(argv,log_path):
        with unused_path(log_path).open('x') as log:
            proc=subprocess.Popen(argv,cwd=release,env=env,stdout=log,stderr=subprocess.STDOUT)
            receipt=dict(pid=proc.pid,argv=argv,active=True,returncode=None);owned.append(receipt)
            receipt['startup']=wait_owned_startup(proc,argv,release)
            while True:
                try:code=proc.wait(timeout=10);break
                except subprocess.TimeoutExpired:
                    verify_owned(proc,argv,release)
                    write(out/'status.json',dict(stage='running_owned_evaluation_child',active_pid=proc.pid,
                        command=argv,covered=len(rows),selected=len(p['scenes']),**inputs))
            receipt.update(active=False,returncode=code)
            return code
    try:
        from .learned import ThreeTablePolicy
        from r1pro_teleop.vla.policy import PolicyContract
        server_argv=[args.model_python,str(release/'scripts/serve_pi05_airport.py'),'--training-status',str(args.milestone),'--port',str(args.port)]
        server_log=unused_path(out/'model_service.log').open('x');server=subprocess.Popen(server_argv,cwd=release,env=env,stdout=server_log,stderr=subprocess.STDOUT)
        own_server=dict(pid=server.pid,argv=server_argv,active=True,returncode=None);owned.append(own_server)
        own_server['startup']=wait_owned_startup(server,server_argv,release)
        deadline=time.monotonic()+args.startup_timeout
        while True:
            if server.poll() is not None:raise RuntimeError('owned_model_service_exited_during_startup')
            try:
                with socket.create_connection(('127.0.0.1',args.port),timeout=2):pass
                policy=ThreeTablePolicy.from_websocket('127.0.0.1',args.port,PolicyContract(checkpoint_id,action_horizon=spec['action_horizon'],action_width=19,prompt_mode=PROFILE));break
            except Exception:
                if time.monotonic()>deadline:raise
                time.sleep(2)
        initial_gpu=[r for r in gpu_processes() if r['pid']==server.pid]
        if not initial_gpu or any(r['gpu_uuid']!=args.gpu_uuid for r in initial_gpu):raise ValueError('actual_model_gpu_ownership_not_verified')
        write(out/'model_gpu_receipt.json',dict(rows=initial_gpu,checkpoint_id=checkpoint_id))
        for number,row in enumerate(p['scenes']):
            protocol(args.protocol)
            case=out/'cases'/f'{number:04d}';native=out/'native'/f'{number:04d}'
            if (case/'result.json').exists() and (native/'manifest.json').exists():
                rows.append(verify_case(case,native,checkpoint_id,row['scene_id'],row['split'],require_contact_evidence=False));continue
            if case.exists() and not (case/'result.json').exists():isolate_partial(case)
            if native.exists() and not (native/'manifest.json').exists():isolate_partial(native)
            code=0 if (case/'result.json').exists() else invoke([args.sim_python,str(release/'scripts/evaluate_three_table_single_tray_pi05.py'),'--scene',row['scene_json'],'--config',p['runtime_config'],'--push-reference-scene',p['push_reference_scene'],'--output',str(case),'--checkpoint-id',checkpoint_id,'--port',str(args.port),'--action-horizon',str(spec['action_horizon']),'--execute-steps',str(execute_steps),'--max-action-steps',str(max_action_steps)],out/f'case_{number:04d}.log')
            if code not in (0,2):raise RuntimeError('evaluation_child_failed_without_task_result')
            actual_result=json.loads((case/'result.json').read_text())
            if actual_result.get('frames')==0:
                rows.append(verify_zero_frame_infrastructure(case,checkpoint_id,row['scene_id'],row['split']))
                write(out/'status.json',dict(stage='infrastructure_case_failed_continuing_other_cases',attempted=len(rows),covered=sum(not r.get('infrastructure_error') for r in rows),selected=len(p['scenes']),**inputs))
                continue
            if invoke([args.sim_python,str(release/'scripts/render_three_table_original_trace.py'),'--case',str(case),'--output',str(native)],out/f'native_{number:04d}.log')!=0:raise RuntimeError('native_replay_child_failed')
            replay=json.loads((native/'manifest.json').read_text())
            if not replay.get('actual_own_gpu_rows') or any(r['gpu_uuid']!=args.gpu_uuid for r in replay['actual_own_gpu_rows']):raise ValueError('actual_renderer_gpu_ownership_not_verified')
            rows.append(verify_case(case,native,checkpoint_id,row['scene_id'],row['split'],require_contact_evidence=False))
            (out/'video_index.txt').write_text(''.join(f"{r['scene_id']}\t{'success' if r['task_completed'] else r['failure_code']}\t{v['camera']}\t{v['path']}\n" for r in rows for v in r['videos']))
            (out/'trajectory_index.txt').write_text(''.join(r['trace']+'\n' for r in rows if r.get('trace')))
            write(out/'status.json',dict(stage='evaluating',selected=len(p['scenes']),covered=len(rows),complete_tasks=sum(r['task_completed'] for r in rows),**inputs))
        summary_path=out/'evaluation_summary.json';write(summary_path,summary(rows,len(p['scenes']),p['protocol_id'],p))
        (out/'video_index.txt').write_text(''.join(f"{r['scene_id']}\t{'success' if r['task_completed'] else r['failure_code']}\t{v['camera']}\t{v['path']}\n" for r in rows for v in r['videos']))
        (out/'trajectory_index.txt').write_text(''.join(r['trace']+'\n' for r in rows if r.get('trace')))
    except BaseException as exc:
        write(out/'status.json',dict(stage='failed_evaluation_preserving_case_evidence',error=repr(exc),covered=len(rows),**inputs));raise
    finally:
        if server is not None:
            if server.poll() is None:
                if not verify_owned(server,server_argv,release):raise ValueError('model_owner_unverified_never_signal')
                server.terminate()
                try:server.wait(timeout=30)
                except subprocess.TimeoutExpired:server.kill();server.wait()
            own_server.update(active=False,returncode=server.returncode)
        if server_log:server_log.close()
        write(out/'owned_process_exit_receipt.json',dict(processes=owned))
    if any(r.get('infrastructure_error') for r in rows):
        write(out/'status.json',dict(stage='failed_evaluation_infrastructure_preserving_all_cases',attempted=len(rows),covered=sum(not r.get('infrastructure_error') for r in rows),selected=len(p['scenes']),training_resume_allowed=False,summary=str(summary_path),**inputs));raise ValueError('evaluation_infrastructure_failed_requires_new_case_attempts')
    if inputs['milestone_sha256']!=sha(args.milestone) or inputs['spec_sha256']!=sha(args.spec):raise ValueError('training_inputs_changed_during_evaluation')
    if inputs['protocol_sha256']!=sha(args.protocol):raise ValueError('protocol_changed_during_evaluation')
    deadline=time.monotonic()+30
    while True:
        active=[r for r in gpu_processes() if r['pid'] in {v['pid'] for v in owned}]
        if not active:break
        if time.monotonic()>deadline:raise ValueError('owned_gpu_context_not_released')
        time.sleep(1)
    write(out/'completion_receipt.json',handoff(args.milestone,p['protocol_id'],summary_path,owned,active))
    write(out/'status.json',dict(stage='evaluation_completed_gpu_released',training_resume_allowed=True,**inputs))
