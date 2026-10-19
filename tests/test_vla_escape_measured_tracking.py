from dataclasses import replace
import numpy as np
import pytest
from test_vla_contact_escape import samples,PAIR
from r1pro_teleop.vla.contact_escape import qualify_private_escape


def qualify(evidence,**kw):
    return qualify_private_escape(evidence,original_pairs=[PAIR],source=evidence[0].source,measured_tracking=True,**kw)


def test_measured_point006_yaw_allowed_with_fixed_qualifier_bound_point01():
    evidence=samples(source='measured_physics');evidence[-1].base_world[2]=.006
    result=qualify(evidence)
    assert result['maximum_actual_yaw_error_rad']==pytest.approx(.006)
    assert result['actual_yaw_bound_rad']==.01 and result['maximum_actual_translation_m']==.002
    assert result['expert_label_authorized'] is False and 'not control improvement' in result['qualification']
    with pytest.raises(ValueError,match='changes_yaw'):
        qualify_private_escape(evidence,original_pairs=[PAIR],source='measured_physics')
    evidence[-1].base_world[2]=.011
    with pytest.raises(ValueError,match='changes_yaw'):qualify(evidence)


def test_shadow_remains_exact_yaw_even_if_candidate_flag_explicit():
    evidence=samples();evidence[-1].base_world[2]=.006
    with pytest.raises(ValueError,match='changes_yaw'):qualify(evidence)
    evidence=samples((-.0002,.003,.002))
    with pytest.raises(ValueError,match='contact_worsened'):qualify(evidence)


def test_post_clear_settling_allowed_only_explicit_measured():
    evidence=samples((-.0002,.003,.002),source='measured_physics')
    result=qualify(evidence)
    assert result['maximum_post_clear_settling_m']==pytest.approx(.001)
    assert list(result['first_clear_sample_by_original_pair'].values())==[1]
    with pytest.raises(ValueError,match='contact_worsened'):
        qualify_private_escape(evidence,original_pairs=[PAIR],source='measured_physics')


@pytest.mark.parametrize('distances,reason',[
    ((-.0002,-.00021,.002),'contact_worsened'),
    ((-.0002,.003,.00099999),'cleared_pair_recontact'),
    ((-.00026,-.0001,.002),'initial_contact_unqualified'),
    ((-.0002,-.0001,.0009),'endpoint_not_clear')])
def test_preclear_setback_recontact_initial_cap_and_endpoint_still_rejected(distances,reason):
    with pytest.raises(ValueError,match=reason):qualify(samples(distances,source='measured_physics'))


def test_clearance_is_per_pair_not_global_one_pair_clearing():
    second=('arm','table')
    evidence=samples((-.0002,.003,.002),source='measured_physics')
    for sample,distance in zip(evidence,[-.0001,-.00015,.002]):sample.distances[second]=distance
    with pytest.raises(ValueError,match='contact_worsened'):
        qualify_private_escape(evidence,original_pairs=[PAIR,second],source='measured_physics',measured_tracking=True)


def test_new_pair_xy_cap_actual_guards_and_sample_cap_unchanged():
    for change,reason in [
        (lambda e:e[-1].distances.update({('new','wall'):.0009}),'new_collision'),
        (lambda e:e[-1].base_world.__setitem__(0,.0101),'translation'),
        (lambda e:e.__setitem__(-1,replace(e[-1],original_guard_passed=False)),'physics_interval_not_verified'),
    ]:
        evidence=samples(source='measured_physics');change(evidence)
        with pytest.raises(ValueError,match=reason):qualify(evidence)
    with pytest.raises(ValueError,match='invalid_private_escape_evidence'):
        qualify([samples(source='measured_physics')[0]]*257)


def test_teacher_candidate_requires_explicit_private_escape_and_boolean_before_constructor_resources(tmp_path):
    from r1pro_teleop.vla.teacher import SimulationExpert,TeacherError
    with pytest.raises(TeacherError,match='requires_private_escape'):
        SimulationExpert(None,tmp_path/'none',private_escape_measured_tracking=True)
    with pytest.raises(TeacherError,match='requires_bool'):
        SimulationExpert(None,tmp_path/'none',private_contact_escape=True,private_escape_measured_tracking=1)
    assert not (tmp_path/'none').exists()


@pytest.mark.parametrize('reference_changes',[False,True])
def test_adapter_actual_tracking_does_not_change_fixed_commands_or_actual_guards(reference_changes):
    from types import SimpleNamespace
    from r1pro_teleop.vla.contact_escape import RuntimeEscapeAdapter,pair_key
    adapter=RuntimeEscapeAdapter.__new__(RuntimeEscapeAdapter)
    pair=pair_key('robot','table');adapter.original={pair:-.0002};adapter.margin=.001
    adapter.start=np.zeros(3);adapter.reference=np.zeros(16);adapter.measured_tracking=True
    sim=SimpleNamespace(base_target=np.zeros(3),target=np.zeros(16))
    sim.base_state=lambda:sim.base_target+np.array([0.,0.,.006 if r.steps else 0.])
    sim.state=lambda:sim.target.copy();d=SimpleNamespace(time=0.)
    model=SimpleNamespace(body_pos=np.zeros((1,3)),body_quat=np.array([[1.,0.,0.,0.]]),body=lambda _:SimpleNamespace(id=0))
    r=SimpleNamespace(sim=sim,d=d,m=model,steps=0,cfg=SimpleNamespace(fps=20));adapter.r=r
    def tick():
        assert sim.base_target[2]==0. and np.array_equal(sim.target,np.zeros(16))
        r.steps+=1;d.time+=.05
        if reference_changes:sim.target[0]=.1
    r.tick=tick;adapter.screen=lambda _:dict(status='screened')
    adapter.distances=lambda _: {pair:-.0002 if not r.steps else (.003 if r.steps<10 else .002)}
    audit={}
    if reference_changes:
        with pytest.raises(ValueError,match='fixed_reference_changed'):adapter.execute(np.array([.005,0.,0.]),audit=audit)
    else:
        evidence=adapter.execute(np.array([.005,0.,0.]),audit=audit)
        assert evidence['measured']['measured_tracking_enabled']
        assert audit['maximum_actual_yaw_error_rad']==pytest.approx(.006)
        assert len(audit['actual_base_world'])==21
        assert audit['control_improvement_claimed'] is False and not audit['full_task_success_claimed']
