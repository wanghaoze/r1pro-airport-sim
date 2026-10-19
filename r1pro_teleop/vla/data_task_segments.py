"""Pure complete-action boundaries; no simulation, media or dataset writes.

Inputs are the original phase partition and intent/physical evidence events.
Unqualified action windows remain inventory; structurally invalid or incomplete
raw cases are excluded. Phase fragments are never relabeled as whole actions.
"""
from copy import deepcopy
import hashlib
import json
import math
from .prompts import skill_prompt


class WholeCaseExcluded(ValueError):
    pass


_STATES = {'ALIGN_BASE':'navigate_to_tray','ADJUST_TRAY':'push_adjust_tray',
           'APPROACH_TRAY':'grasp_lift_tray','GRASP_TRAY':'grasp_lift_tray',
           'TRANSPORT_TRAY':'carry_tray','PLACE_TRAY':'place_release_tray'}
_PHASES = {
    'navigate_to_tray':{'unknown'},
    'grasp_lift_tray':{'pregrasp','approach','contact','close','load_transfer','lift','stabilize'},
    'carry_tray':{'transport'},
    'place_release_tray':{'preplace','descend','support_contact','unload','open','retreat'},
    'push_adjust_tray':{'approach','close','adjust','pull','open','retreat'},
}


def _hash(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),
                                     allow_nan=False).encode()).hexdigest()


def _reject(reason):
    raise WholeCaseExcluded(reason)


def complete_action_segments(phases, events, result, *, num_frames, fps=20,
                             transition_completed, provenance, settle_frames=40,
                             numeric_evidence=None, contact_threshold_n=.5, lifted_threshold_m=.02):
    """Return whole-action candidates plus explicit nontraining frame inventory.

``provenance`` contains caller-verified source trace/result/scene hashes and split.
This pure function preserves them; filesystem authenticity belongs to the caller.
Physical evidence event frames must refer to the original trace, not inferred
from state labels. No resampling, added tail frames or changed actions occur.
"""
    if isinstance(contact_threshold_n,bool) or not isinstance(contact_threshold_n,(int,float)) or not math.isfinite(contact_threshold_n) or contact_threshold_n<0:
        _reject('invalid_source_contact_threshold')
    if isinstance(lifted_threshold_m,bool) or not isinstance(lifted_threshold_m,(int,float)) or not math.isfinite(lifted_threshold_m) or lifted_threshold_m<0:
        _reject('invalid_source_lift_threshold')
    if result.get('task_completed',result.get('physics_success')) is not True:
        _reject('source_task_not_completed')
    if result.get('diagnostic_only'):
        _reject('source_recovery_or_diagnostic')
    if result.get('controller_source','program_generated')!='program_generated':
        _reject('source_not_simulation_expert')
    if type(num_frames) is not int or num_frames<=0 or type(settle_frames) is not int or settle_frames<0:
        _reject('invalid_frame_count')
    if isinstance(fps,bool) or not isinstance(fps,(int,float)) or not math.isfinite(fps) or fps!=20:
        _reject('native_20hz_required')
    if len(transition_completed)!=num_frames or not all(bool(x) for x in transition_completed):
        _reject('incomplete_control_interval')
    required=('trace_sha256','result_sha256','scene_sha256','scene_id','split')
    if any(not provenance.get(k) for k in required) or provenance['split'] not in ('train','val','test'):
        _reject('missing_source_identity')
    previous=0
    for row in phases:
        a,b=row['start_frame'],row['end_frame']
        if type(a) is not int or type(b) is not int or a!=previous or not a<b<=num_frames:
            _reject('invalid_original_phase_partition')
        previous=b
    if previous!=num_frames:_reject('incomplete_original_phase_partition')
    for event in events:
        if type(event.get('frame')) is not int or not 0<=event['frame']<=num_frames:
            _reject('invalid_event_frame')
        if event.get('event') in ('snapshot_rollback','qpos_reset','state_restore_during_execution'):
            _reject('source_rollback_or_failed_operation')
    operations=[e for e in events if e.get('event')=='operation_selected']
    if not operations:_reject('missing_operation_boundaries')
    if any(operations[i]['frame']>=operations[i+1]['frame'] for i in range(len(operations)-1)):
        _reject('nonmonotonic_operation_boundaries')
    indices=[e.get('operation_index') for e in operations]
    if any(type(i) is not int for i in indices) or len(set(indices))!=len(indices):
        _reject('duplicate_or_missing_operation_index')
    output=[];inventory=[]
    for row in phases:
        b=min(row['end_frame'],settle_frames,operations[0]['frame'])
        if row['start_frame']<b:
            inventory.append(dict(reason='physical_initial_settling_not_action',start_frame=row['start_frame'],end_frame=b,source_constituents=[deepcopy(row.get("_source_constituent",row))]))

    def emit(skill,rows,operation):
        a,b=rows[0]['start_frame'],rows[-1]['end_frame']
        names=[r['phase'] for r in rows]
        timeline=[(e['frame'],e['phase']) for e in events if e.get('event')=='state_transition' and 'phase' in e and a<=e['frame']<b and
            (_STATES.get(e.get('state'))==skill or (skill=='place_release_tray' and e.get('state')=='TRANSPORT_TRAY' and e['phase']=='preplace') or (skill=='push_adjust_tray' and e.get('state')=='PLACE_TRAY' and e['phase']=='retreat') or 'state' not in e)]
        timeline += [(r['start_frame'],r['phase']) for r in rows]
        names=[phase for _,phase in sorted(timeline,key=lambda value:value[0])]
        auxiliary=skill=='place_release_tray' and any(r['state']=='ADJUST_TRAY' for r in rows)
        allowed=_PHASES.get(skill,{'unknown'}) | (_PHASES['push_adjust_tray'] if auxiliary else set())
        unknown=[p for p in names if p not in allowed]
        if unknown:
            inventory.append(dict(reason='unknown_action_phase',skill=skill,start_frame=a,end_frame=b,source_constituents=[deepcopy(r.get("_source_constituent",r)) for r in rows],phases=unknown))
            return
        def ordered(groups):
            cursor=0
            for alternatives in groups:
                matches=[i for i in range(cursor,len(names)) if names[i] in alternatives]
                if not matches:_reject('incomplete_whole_action:'+skill)
                cursor=matches[0]+1
        physical={e['event'] for e in events if a<=e['frame']<b and
            (e.get('target_tray_id') is None or e.get('target_tray_id')==rows[0].get('target_tray_id'))}
        proof=[deepcopy(e) for e in events if a<=e['frame']<=b and e.get('event') in ('primitive_start','primitive_complete','separation_contact_retained','retained_push_phase_end')]
        completed=lambda primitive: any(e.get('event')=='primitive_complete' and e.get('primitive')==primitive for e in proof)
        branch='ordinary_complete_action';grasp_measurement=None
        if skill=='grasp_lift_tray':
            ordered(({'pregrasp','approach'},{'contact'},{'close'},{'lift'},{'stabilize'}))
            if not {'bilateral_grasp_observed','lift_above_2cm'}<=physical:
                if numeric_evidence is None:_reject('missing_grasp_physics_evidence')
                try:
                    frame=b-1;t=int(numeric_evidence['target_tray'][frame])
                    forces=numeric_evidence['gripper_contact_force'][frame][t]
                    support_value=numeric_evidence['support_contact'][frame][t]
                    rise=float(numeric_evidence['min_z'][frame][t])-float(numeric_evidence['min_z'][0][t])
                    valid=all(math.isfinite(float(v)) for v in forces) and min(forces)>contact_threshold_n and support_value==0 and math.isfinite(rise) and rise>lifted_threshold_m
                except (KeyError,IndexError,TypeError,ValueError):_reject('invalid_actual_grasp_measurement')
                if not valid:_reject('missing_grasp_physics_evidence')
                grasp_measurement=dict(frame=frame,target_index=t,forces_n=deepcopy(forces),support_contact=support_value,lift_from_original_initial_m=rise,source_contact_n=contact_threshold_n,source_lifted_m=lifted_threshold_m,missing_discrete_events=sorted({'bilateral_grasp_observed','lift_above_2cm'}-physical))
        elif skill=='place_release_tray':
            retained=any(e.get('event')=='primitive_start' and e.get('primitive')=='place' and e.get('parameters',{}).get('retained_side') in ('left','right') for e in proof)
            if auxiliary:
                ordered(({'descend'},{'support_contact'},{'open'},{'retreat'}))
                if numeric_evidence is None:_reject('missing_actual_final_release_measurement')
                try:
                    frame=b-1;t=int(numeric_evidence['target_tray'][frame])
                    forces=numeric_evidence['gripper_contact_force'][frame][t]
                    support_value=numeric_evidence['support_contact'][frame][t]
                    floor_value=numeric_evidence['floor_contact'][frame][t]
                    valid=all(math.isfinite(float(v)) for v in forces) and max(forces)<=contact_threshold_n and support_value>0 and floor_value==0
                except (KeyError,IndexError,TypeError,ValueError):_reject('invalid_actual_final_release_measurement')
                if not valid:_reject('supported_push_handoff_not_fully_released')
                branch='place_release_after_supported_push_handoff'
            elif retained and completed('place'):
                _reject('supported_place_handoff_without_final_release')
            else:ordered(({'descend'},{'support_contact'},{'open'},{'retreat'}))
            support=any(r.get('evidence',{}).get('table_support_observed') for r in rows)
            if ('open_release' not in physical and not completed('place')) or not (support or 'table_support_restored' in physical):
                _reject('missing_release_physics_evidence')
        elif skill=='push_adjust_tray':
            retained_end=any(e.get('event')=='separation_contact_retained' and e['frame']==b for e in proof)
            prior_place=[e for e in events if e.get('event')=='primitive_start' and e.get('primitive')=='place' and e['frame']<=a]
            prior_complete=any(e.get('event')=='primitive_complete' and e.get('primitive')=='place' and e['frame']==a for e in events)
            retained_start=bool(prior_place and prior_place[-1].get('parameters',{}).get('retained_side') in ('left','right') and prior_complete)
            if retained_end and completed('push'):
                ordered(({'approach'},{'close'},{'adjust','pull'}));branch='supported_push_contact_retained_for_grasp'
            elif retained_start and completed('push'):
                ordered(({'adjust','pull'},{'open'},{'retreat'}));branch='supported_push_from_place_retained_contact'
            else:ordered(({'approach'},{'close'},{'adjust','pull'},{'open'},{'retreat'}))
            if 'table_push_or_rotate' not in physical and not completed('push'):_reject('missing_push_physics_evidence')
        originals=[deepcopy(r.get('_source_constituent',r)) for r in rows]
        output.append(dict(schema='airport_whole_action_segment/1',**deepcopy(provenance),
            skill=skill,base_skill=skill,language_prompt=skill_prompt(skill),prompt_mode='skill_only_v1',
            start_frame=a,end_frame=b,frames=b-a,interval='half-open',fps=fps,
            operation_index=None if operation is None else operation['operation_index'],
            operation=None if operation is None else deepcopy(operation['operation']),
            temporary=False if operation is None else bool(operation['operation'].get('temporary',False)),
            operation_destination=None if operation is None else deepcopy(operation['operation'].get('destination')),
            target_tray_id=rows[0].get('target_tray_id'),target_slot_id=rows[0].get('target_slot_id'),
            source_constituents=originals,source_constituents_sha256=_hash(originals),
            source_constituent_intersections=[dict(segment_id=r.get('segment_id'),start_frame=r['start_frame'],end_frame=r['end_frame']) for r in rows],
            boundary_semantics='complete_action_original_frames',task_completed=True,
            completion_branch=branch,actual_grasp_measurement=grasp_measurement,
            included_auxiliary_skills=['push_adjust_tray'] if auxiliary else [],
            overlaps_allowed_explicit=auxiliary,
            actual_final_release_measurement=None if not auxiliary else dict(frame=b-1,target_index=t,forces_n=deepcopy(forces),support_contact=support_value,floor_contact=floor_value,source_contact_threshold_n=contact_threshold_n),
            release_scope='actual_bilateral_release_after_auxiliary_push' if auxiliary else ('original_completed_place_guard' if skill=='place_release_tray' else None),
            full_bilateral_release_claimed=skill=='place_release_tray',
            source_completion_events=proof,source_completion_events_sha256=_hash(proof),
            recovery=any(r.get('recovery',False) or r.get('state')=='RECOVER' for r in rows),
            source_recovery_used=bool(result.get('recovery_used',False)),
            source_acceptance_profile=result.get('acceptance_profile','strict')))

    first=operations[0]['frame']
    init=[]
    for row in phases:
        a,b=max(row['start_frame'],settle_frames),min(row['end_frame'],first)
        if a<b:
            if row['state']!='SEARCH_TARGET' or row['phase']!='unknown':_reject('unknown_initialization_phase')
            init.append({**row,'start_frame':a,'end_frame':b,'_source_constituent':deepcopy(row)})
    if init:emit('initialize_posture',init,None)
    for index,operation in enumerate(operations):
        lo=operation['frame'];hi=operations[index+1]['frame'] if index+1<len(operations) else num_frames
        if not isinstance(operation.get('operation'),dict):_reject('missing_operation_context')
        groups=[]
        for row in phases:
            a,b=max(row['start_frame'],lo),min(row['end_frame'],hi)
            if a>=b:continue
            row={**row,'start_frame':a,'end_frame':b,'_source_constituent':deepcopy(row)}
            skill=_STATES.get(row['state'])
            if skill is None:
                inventory.append(dict(reason='noncanonical_state',start_frame=a,end_frame=b,source_constituents=[deepcopy(row.get("_source_constituent",row))]))
                if groups:groups[-1]['closed']=True
                continue
            if row['phase']=='preplace' and row['state']=='TRANSPORT_TRAY':skill='place_release_tray'
            if row['phase']=='retreat' and row['state']=='PLACE_TRAY' and groups and groups[-1]['skill']=='push_adjust_tray':
                skill='push_adjust_tray'
            if groups and groups[-1]['skill']==skill and not groups[-1].get('closed'):
                if row['start_frame']!=groups[-1]['rows'][-1]['end_frame']:_reject('action_frame_gap')
                groups[-1]['rows'].append(row)
            else:
                groups.append(dict(skill=skill,rows=[row]))
        if not groups:_reject('operation_without_action')
        for group_index,group in enumerate(groups):
            rows=group['rows']
            if (group['skill']=='place_release_tray' and rows[-1]['phase']=='open' and group_index+1<len(groups) and groups[group_index+1]['skill']=='push_adjust_tray' and groups[group_index+1]['rows'][-1]['phase']=='retreat'):
                rows=rows+groups[group_index+1]['rows']
            targets={(r.get('target_tray_id'),r.get('target_slot_id')) for r in rows}
            if len(targets)!=1:_reject('action_target_changed')
            try:
                emit(group['skill'],rows,operation)
            except WholeCaseExcluded as exc:
                rows=group['rows']
                reason='interrupted_setup_not_completed_action' if group['skill']=='grasp_lift_tray' and all(r['phase'] in ('pregrasp','approach') for r in rows) else str(exc)
                inventory.append(dict(reason=reason,skill=group['skill'],start_frame=rows[0]['start_frame'],end_frame=rows[-1]['end_frame'],source_constituents=[deepcopy(r.get("_source_constituent",r)) for r in rows],operation_index=operation['operation_index']))
    for a,b in zip(output,output[1:]):
        if a['end_frame']>b['start_frame'] and not (a.get('overlaps_allowed_explicit') and b['skill']=='push_adjust_tray' and b['end_frame']<=a['end_frame']):
            _reject('unexplained_overlapping_action_ranges')
    for item in inventory:
        item["source_constituents_sha256"]=_hash(item["source_constituents"])
    coverage=sorted([(r["start_frame"],r["end_frame"]) for r in output+inventory])
    previous=0
    for a,b in coverage:
        if a>previous:_reject("unaccounted_source_frames")
        previous=max(previous,b)
    if previous!=num_frames:_reject("unaccounted_source_tail")
    return dict(schema="airport_complete_action_plan/1",segments=output,inventory=inventory,
                raw_frames=num_frames,action_candidate_frames=sum(r["frames"] for r in output),
                actionepisodes_are_disjoint_partition=False if any(r.get("overlaps_allowed_explicit") for r in output) else True,
                inventory_frames=sum(r["end_frame"]-r["start_frame"] for r in inventory),
                action_label_mapping_status="assigned_by_materializer_not_boundary_algorithm",
                source_task_completed=True,source_recovery_used=bool(result.get("recovery_used",False)))
