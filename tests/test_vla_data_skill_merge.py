import copy
import pytest
from r1pro_teleop.vla.data_skill_merge import can_merge, eligible, merge_ready_records, padding_summary, record_sha256


def row(a, b, phase='close', **extra):
    result = dict(schema='airport_vla_segments/1', segment_id=f'p{a}', source_segment_id=f'p{a}',
        scene_id='scene', split='train', trace='/trace.h5', trace_sha256='a'*64,
        collection='/collection', collection_fingerprint='b'*64, attempt='a000',
        scene_source_sha256='c'*64, operation_index=2, skill='grasp_lift_tray',
        language_prompt='Grasp and lift tray.', action_layout='mobile19', action_names=['joint']*19,
        action_semantics='absolute', observation_semantics='before_action', fps=20,
        quality_class='complete_task', episode_strict_success=False,
        acceptance_profile='approximate_completion', strict_deviations={}, approximate_deviation_counts={},
        start_frame=a, end_frame=b, frames=b-a, start_time_s=a/20, end_time_s=b/20,
        interval='half-open', phase=phase, source_phase=phase, supervision_eligible=True,
        training_ready=True, source_needs_review=False, verified_lift_takeoff=None,
        initial_posture_qualification=None, environment_source='simulation',
        controller_source='program_generated', human_demonstration=False,
        videos={k:dict(path='/native/'+k+'.mp4', sha256='d'*64, verified=True,exists=True,
                       measured=dict(fps=20,frames=100),start_frame=a,end_frame=b,
                       source_start_frame=a,source_end_frame=b,start_time_s=a/20,end_time_s=b/20,
                       interval='half-open') for k in ('head_left','head_right','left_wrist','right_wrist')})
    result.update(extra)
    return result


def test_preserve_full_source_records_and_half_open_video_boundaries():
    records=[row(1,20),row(20,25,'lift')]
    original=copy.deepcopy(records)
    result=merge_ready_records(records)
    assert len(result)==1 and result[0]['frames']==24
    assert result[0]['constituent_phase_spans']==original
    assert result[0]['constituent_record_sha256']==[record_sha256(r) for r in original]
    assert result[0]['videos']['head_left']['source_start_frame']==1
    assert result[0]['videos']['head_left']['source_end_frame']==25
    assert records==original


@pytest.mark.parametrize('key,value', [('skill','carry_tray'),('operation_index',3),
    ('scene_id','another'),('trace_sha256','f'*64),('language_prompt','Another prompt'),
    ('split','test'),('start_frame',21),('training_ready',False),('supervision_eligible',False)])
def test_never_merge_different_identity_or_gap(key,value):
    first=row(0,20); second=row(20,40,**{key:value})
    assert not can_merge(first,second)


def test_unresolved_review_is_excluded_and_leaves_frame_gap():
    assert not eligible(row(20,22,source_needs_review=True))
    merged=merge_ready_records([row(0,20),row(20,22,source_needs_review=True),row(22,40)])
    assert len(merged)==2


def test_existing_qualified_takeoff_preserved_without_requalification():
    lift=row(20,40,'lift',source_needs_review=True,
             verified_lift_takeoff=dict(qualification='verified_lift_takeoff',source_interval=[20,40],
                rule_version=2,source_needs_review_preserved=True,source='simulation/program_generated',
                endpoint_observation_frame=40,endpoint_support_contact=0,bilateral_min_force_n=10,
                airborne_tail_interval_frames=15,endpoint_clearance_m=.15,declared_lift_min_m=.1))
    merged=merge_ready_records([row(0,20),lift])[0]
    assert merged['source_needs_review'] is True
    assert merged['verified_lift_takeoff'] is None
    assert merged['constituent_phase_spans'][1]['verified_lift_takeoff']==lift['verified_lift_takeoff']


def test_duplicate_source_segments_are_rejected():
    with pytest.raises(ValueError,match='duplicate'):
        merge_ready_records([row(0,20),row(0,20)])


def test_padding_changes_only_by_real_contiguous_boundaries():
    source=[row(0,2),row(2,40,'lift')]
    before=padding_summary(source)['grasp_lift_tray']
    after=padding_summary(merge_ready_records(source))['grasp_lift_tray']
    assert before['frames']==after['frames']==40
    assert before['padded_action_positions']==227
    assert after['padded_action_positions']==190


def test_overlapping_ineligible_interval_cannot_be_silently_skipped():
    with pytest.raises(ValueError,match='overlapping'):
        merge_ready_records([row(0,20),row(19,20,training_ready=False),row(20,40)])


def test_ineligible_other_trace_is_explicit_fence_even_without_same_trace_gap():
    result=merge_ready_records([row(0,20),row(0,1,segment_id='other',trace='/other.h5',training_ready=False),row(20,40)])
    assert len(result)==2


def test_qualification_name_alone_does_not_resolve_review():
    assert not eligible(row(0,20,source_needs_review=True,
                            verified_lift_takeoff={'qualification':'verified_lift_takeoff','source_interval':[0,20]}))


@pytest.mark.parametrize('value',[float('inf'),float('nan'),True,'0.1',0,-.1])
def test_nonfinite_or_malformed_lift_minimum_cannot_pass(value):
    r=row(0,20,source_needs_review=True)
    r['verified_lift_takeoff']=dict(qualification='verified_lift_takeoff',source_interval=[0,20],
        rule_version=2,source_needs_review_preserved=True,source='simulation/program_generated',
        endpoint_observation_frame=20,endpoint_support_contact=0,bilateral_min_force_n=10,
        airborne_tail_interval_frames=15,endpoint_clearance_m=float('inf'),declared_lift_min_m=value)
    assert not eligible(r)


def test_singleton_unverified_camera_never_eligible():
    r=row(0,20);del r['videos']['head_right']
    assert not eligible(r)
