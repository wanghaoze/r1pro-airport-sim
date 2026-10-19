from copy import deepcopy
import pytest
from r1pro_teleop.vla.data_task_segments import complete_action_segments,WholeCaseExcluded

PROVENANCE=dict(trace_sha256='trace',result_sha256='result',scene_sha256='scene',scene_id='s',split='train')

def case(sequence):
    rows=[];events=[dict(event='operation_selected',frame=0,operation_index=1,operation={'tray':0,'slot':0})]
    for i,(state,phase) in enumerate(sequence):
        rows.append(dict(start_frame=i*2,end_frame=(i+1)*2,state=state,phase=phase,
            target_tray_id='tray_0',target_slot_id='slot_0',recovery=False,evidence={'table_support_observed':True}))
    return rows,events

def run(rows,events,**kw):
    n=rows[-1]['end_frame']
    return complete_action_segments(rows,events,dict(task_completed=True,**kw),num_frames=n,
        transition_completed=[True]*n,provenance=PROVENANCE,settle_frames=0)

GRASP=[('APPROACH_TRAY','approach'),('GRASP_TRAY','contact'),('GRASP_TRAY','close'),
       ('GRASP_TRAY','load_transfer'),('GRASP_TRAY','lift'),('GRASP_TRAY','stabilize')]
PLACE=[('TRANSPORT_TRAY','preplace'),('PLACE_TRAY','descend'),('PLACE_TRAY','support_contact'),
       ('PLACE_TRAY','open'),('PLACE_TRAY','retreat')]
PUSH=[('ADJUST_TRAY','approach'),('ADJUST_TRAY','close'),('ADJUST_TRAY','adjust'),
      ('ADJUST_TRAY','open'),('PLACE_TRAY','retreat')]

def physical(events,kind,frame):events.append(dict(event=kind,frame=frame,target_tray_id='tray_0'))

def test_grasp_whole_approach_to_stabilized_lift_preserves_original():
    rows,events=case(GRASP);physical(events,'bilateral_grasp_observed',4);physical(events,'lift_above_2cm',8)
    before=deepcopy(rows);plan=run(rows,events)
    assert rows==before
    assert len(plan['segments'])==1 and not plan['inventory']
    row=plan['segments'][0]
    assert (row['start_frame'],row['end_frame'],row['frames'])==(0,12,12)
    assert row['source_constituents']==rows and row['operation']=={'tray':0,'slot':0}
    assert row['language_prompt']=='Grasp and lift the selected tray.'

def test_preplace_and_retreat_belong_whole_place():
    rows,events=case(PLACE);physical(events,'open_release',6)
    plan=run(rows,events)
    assert [(r['skill'],r['frames']) for r in plan['segments']]==[('place_release_tray',10)]

def test_push_shared_place_retreat_not_fake_place():
    rows,events=case(PUSH);physical(events,'table_push_or_rotate',4)
    plan=run(rows,events)
    assert [(r['skill'],r['frames']) for r in plan['segments']]==[('push_adjust_tray',10)]

def test_zero_frame_contact_transition_retained_as_intent_evidence():
    rows,events=case([p for p in GRASP if p[1]!='contact'])
    events.append(dict(event='state_transition',frame=2,phase='contact'))
    physical(events,'bilateral_grasp_observed',3);physical(events,'lift_above_2cm',6)
    assert len(run(rows,events)['segments'])==1

def test_legal_recovery_keeps_measured_span_and_source_acceptance():
    rows,events=case(PUSH);rows[2]['recovery']=True
    physical(events,'table_push_or_rotate',4)
    row=run(rows,events,recovery_used=True,acceptance_profile='completion_first')['segments'][0]
    assert row['recovery'] and row['source_recovery_used']
    assert row['source_acceptance_profile']=='completion_first'

def test_missing_physics_or_unknown_phase_inventory_not_false_complete_action():
    rows,events=case(GRASP)
    assert run(rows,events)['segments']==[]
    assert run(rows,events)['inventory'][0]['reason']=='missing_grasp_physics_evidence'
    rows[0]['phase']='unrecognized'
    plan=run(rows,events)
    assert not plan['segments'] and plan['inventory'][0]['source_constituents']==rows

def test_operation_hard_boundary_prevents_joining_grasp_halves():
    rows,events=case(GRASP)
    events.append(dict(event='operation_selected',frame=6,operation_index=2,operation={'tray':1,'slot':1}))
    physical(events,'bilateral_grasp_observed',4);physical(events,'lift_above_2cm',8)
    plan=run(rows,events)
    assert not plan['segments'] and len(plan['inventory'])==2


def test_supported_push_retained_handoff_requires_original_completed_primitive():
    rows,events=case(PUSH[:3]);physical(events,'table_push_or_rotate',4)
    events.append(dict(event='separation_contact_retained',frame=6))
    assert not run(rows,events)['segments']
    events.append(dict(event='primitive_complete',primitive='push',frame=6))
    row=run(rows,events)['segments'][0]
    assert row['completion_branch']=='supported_push_contact_retained_for_grasp'
    assert row['end_frame']==6


def test_supported_place_handoff_zero_frame_support_and_no_retreat():
    rows,events=case([('PLACE_TRAY','descend'),('PLACE_TRAY','open')])
    events += [dict(event='state_transition',state='PLACE_TRAY',phase='support_contact',frame=2),
               dict(event='primitive_start',primitive='place',frame=0,parameters={'retained_side':'left'}),
               dict(event='primitive_complete',primitive='place',frame=4)]
    plan=run(rows,events)
    assert not plan['segments']
    assert plan['inventory'][0]['reason']=='supported_place_handoff_without_final_release'


def test_supported_push_can_start_from_measured_place_handoff_without_reapproach():
    rows,events=case([('ADJUST_TRAY','adjust'),('ADJUST_TRAY','open'),('PLACE_TRAY','retreat')])
    events += [dict(event='primitive_start',primitive='place',frame=0,parameters={'retained_side':'right'}),
               dict(event='primitive_complete',primitive='place',frame=0),
               dict(event='primitive_complete',primitive='push',frame=2)]
    assert run(rows,events)['segments'][0]['completion_branch']=='supported_push_from_place_retained_contact'


@pytest.mark.parametrize('release_force,qualified',[(.2655,True),(13.0,False)])
def test_whole_place_extends_through_supported_push_until_real_release(release_force,qualified):
    sequence=[('PLACE_TRAY','descend'),('PLACE_TRAY','open'),('ADJUST_TRAY','adjust'),
              ('ADJUST_TRAY','open'),('PLACE_TRAY','retreat')]
    rows,events=case(sequence)
    events += [dict(event='state_transition',state='PLACE_TRAY',phase='support_contact',frame=2),
        dict(event='primitive_start',primitive='place',frame=0,parameters={'retained_side':'right'}),
        dict(event='primitive_complete',primitive='place',frame=4),
        dict(event='primitive_complete',primitive='push',frame=6)]
    numeric=dict(target_tray=[0]*10,gripper_contact_force=[[[0.,13.0]]]*9+[[[0.,release_force]]],
        support_contact=[[4.]]*10,floor_contact=[[0.]]*10)
    plan=complete_action_segments(rows,events,dict(task_completed=True),num_frames=10,
        transition_completed=[True]*10,provenance=PROVENANCE,settle_frames=0,numeric_evidence=numeric)
    places=[r for r in plan['segments'] if r['skill']=='place_release_tray']
    if qualified:
        assert len(places)==1
        assert (places[0]['start_frame'],places[0]['end_frame'])==(0,10)
        assert places[0]['completion_branch']=='place_release_after_supported_push_handoff'
        assert places[0]['included_auxiliary_skills']==['push_adjust_tray']
        assert places[0]['overlaps_allowed_explicit']
        assert not plan['actionepisodes_are_disjoint_partition']
        assert plan['action_candidate_frames']==16 and plan['raw_frames']==10
    else:
        assert not places
        assert any(r['reason']=='supported_push_handoff_not_fully_released' for r in plan['inventory'])


@pytest.mark.parametrize('kind',['valid','contact_lost','supported','low_lift','nonfinite','missing_field'])
def test_actual_bilateral_lift_can_verify_missed_discrete_contact_event(kind):
    rows,events=case(GRASP)
    physical(events,'lift_above_2cm',8)  # Real event retained; no fabricated bilateral event.
    forces=[[[0.,0.]]]*11+[[[15.34,14.45]]]
    support=[[4.]]*11+[[0.]];bottom=[[.8]]*11+[[.96]]
    if kind=='contact_lost':forces[-1]=[[0.,14.45]]
    if kind=='supported':support[-1]=[4.]
    if kind=='low_lift':bottom[-1]=[.81]
    if kind=='nonfinite':forces[-1]=[[float('nan'),14.45]]
    numeric=dict(target_tray=[0]*12,gripper_contact_force=forces,support_contact=support,min_z=bottom)
    if kind=='missing_field':numeric.pop('min_z')
    plan=complete_action_segments(rows,events,dict(task_completed=True),num_frames=12,
        transition_completed=[True]*12,provenance=PROVENANCE,settle_frames=0,numeric_evidence=numeric)
    if kind=='valid':
        row=plan['segments'][0]
        assert row['actual_grasp_measurement']['missing_discrete_events']==['bilateral_grasp_observed']
        assert row['actual_grasp_measurement']['forces_n']==[15.34,14.45]
        assert not any(e.get('event')=='bilateral_grasp_observed' for e in events)
    else:assert not plan['segments']

@pytest.mark.parametrize('bad',['failed','incomplete','diagnostic','reset','partition'])
def test_invalid_whole_case_never_salvages_phase_clips(bad):
    rows,events=case(PUSH);n=10;result=dict(task_completed=True);complete=[True]*n
    if bad=='failed':result['task_completed']=False
    if bad=='incomplete':complete[-1]=False
    if bad=='diagnostic':result['diagnostic_only']=True
    if bad=='reset':events.append(dict(event='snapshot_rollback',frame=3))
    if bad=='partition':rows[1]['start_frame']=3
    with pytest.raises(WholeCaseExcluded):complete_action_segments(rows,events,result,num_frames=n,
        transition_completed=complete,provenance=PROVENANCE)
