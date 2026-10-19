from types import SimpleNamespace
from dataclasses import replace
import numpy as np
import pytest
from test_airport_fsm_unit import spec_fixture,valid_rows,poses
from r1pro_teleop.airport_fsm.contracts import Config
from r1pro_teleop.airport_fsm.geometry import Geometry,Scheduler,Operation,placement_ok
from r1pro_teleop.airport_fsm.machine import Machine
from r1pro_teleop.airport_fsm.acceptance_profile import completion_criteria,profile_placement_ok,predicate_with_strict_evidence


def config():return Config(acceptance_profile='completion_first',retained_support_integer_clock_enabled=True)


def shifted_rows():
    g=Geometry(spec_fixture());rows=valid_rows();rows['tray_pose'][:,:,:3]+=.035*g.R[:,0]
    return g,rows


def test_strict_default_is_identical_and_effective_criteria_do_not_mutate():
    c=Config();g,rows=shifted_rows()
    assert completion_criteria(c) is c.criteria
    assert profile_placement_ok(rows,g,c)==placement_ok(rows,g,c.criteria,c.fps)
    effective=completion_criteria(config());assert effective.position_m==.05
    assert config().criteria.position_m==.03 and effective.stable_s==1


def test_final_completion_preserves_strict_reason_and_full_window():
    g,rows=shifted_rows();valid,report=profile_placement_ok(rows,g,config())
    assert valid and not report['strict_accepted']
    assert 'pose_or_gap_outside_contract' in report['strict_report']['reasons']
    assert report['stable_samples']==21
    assert not profile_placement_ok({k:v[:20] for k,v in rows.items()},g,config())[0]


@pytest.mark.parametrize('kind',['support','released','closed','motion','tilt','collision','floor','overlap'])
def test_completion_still_requires_physical_arrangement(kind):
    g,rows=shifted_rows()
    if kind=='support':rows['table_contact'][-1,0]=0
    if kind=='released':rows['gripper_contact_force'][-1,0,0]=.6
    if kind=='closed':rows['state'][-1,7]=.01
    if kind=='motion':rows['tray_pose'][-1,0,0]+=.002
    if kind=='tilt':rows['tray_pose'][:,:,3:]=[np.cos(.1),np.sin(.1),0,0]
    if kind=='collision':rows['illegal_collision'][0]=1
    if kind=='floor':rows['floor_contact'][0,0]=1
    if kind=='overlap':rows['tray_pose'][:,1]=rows['tray_pose'][:,0]
    assert not profile_placement_ok(rows,g,config())[0]


def test_final_accepted_initial_arrangement_records_deviation():
    g,rows=shifted_rows();warnings=[]
    m=Machine.__new__(Machine);m.c=config();m.g=g
    m.log=SimpleNamespace(acceptance_arrays=lambda:rows)
    m.r=SimpleNamespace(record_strict_deviation=lambda *args:warnings.append(args))
    valid,_=m._profile_final_acceptance()
    assert valid and warnings[0][0]=='final_physical_acceptance_failed'


def test_scheduler_skip_records_strict_deviation_and_uses_same_tolerance():
    g,rows=shifted_rows();c=config();p=rows['tray_pose'][-1];warnings=[]
    m=Machine.__new__(Machine);m.c=c;m.g=g
    m.r=SimpleNamespace(record_strict_deviation=lambda *args:warnings.append(args))
    m.scheduler=Scheduler(g,completion_criteria(c),consistent_placement=True)
    assert m.scheduler.choose(p) is None
    m._record_completion_slot_deviations(p)
    assert len(warnings)==3 and all(w[0]=='scheduler_slot_outside_strict_contract' for w in warnings)


@pytest.mark.parametrize('profile',['strict','completion_first'])
def test_verify_operation_agrees_with_scheduler_and_records(profile):
    g,rows=shifted_rows();c=replace(config(),acceptance_profile=profile);warnings=[]
    e={k:v[-1] for k,v in rows.items()}
    def wait(seconds,predicate,stable):
        assert seconds==2 and stable==1
        predicate(e);return predicate(e)
    m=Machine.__new__(Machine);m.c=c;m.g=g;m.transition=lambda *a,**k:None
    m.scheduler=SimpleNamespace(mapping=[0,1,2]);m.r=SimpleNamespace(wait=wait,record_strict_deviation=lambda *a:warnings.append(a))
    assert m.verify_operation(Operation(1,1,g.goals[1],g.goal_yaw[1]))==(profile=='completion_first')
    assert bool(warnings)==(profile=='completion_first')


def test_primitive_predicate_never_swallows_hard_failure_or_marks_strict():
    warnings=[];r=SimpleNamespace(cfg=config(),record_strict_deviation=lambda *a:warnings.append(a))
    predicate=predicate_with_strict_evidence(r,lambda e:e['err']<=.03 and e['support'],
        lambda e:e['err']<=.05 and e['support'],'old_postcondition',lambda e:dict(e))
    assert predicate({'err':.04,'support':True});assert warnings[0][0]=='old_postcondition'
    assert not predicate({'err':.04,'support':False})
    assert not predicate({'err':.06,'support':True})
    assert len(warnings)==1


def test_custom_criteria_are_never_tightened_by_completion_defaults():
    cfg=replace(config(),criteria=replace(config().criteria,position_m=.06,yaw_deg=12,gap_max_m=.07))
    effective=completion_criteria(cfg)
    assert (effective.position_m,effective.yaw_deg,effective.gap_max_m)==(.06,12,.07)

def test_completion_small_overhang_is_geometry_only_and_records_strict_deviation():
    from r1pro_teleop.airport_fsm.geometry import slot_geometry_ready
    g=Geometry(spec_fixture());p=poses(g);p[0,1]+=.0052;c=replace(config(),consistent_placement=True,fixed_primitives=True);effective=completion_criteria(c)
    assert not g.footprint_supported(p[0,:3],0,g.sizes[0],margin=0)
    assert not slot_geometry_ready(g,p,[0,1,2],0,0,effective)
    assert slot_geometry_ready(g,p,[0,1,2],0,0,effective,require_full_footprint=False)
    scheduler=Scheduler(g,effective,consistent_placement=True,require_full_footprint=False)
    assert scheduler.choose(p) is None
    warnings=[];m=Machine.__new__(Machine);m.c=c;m.g=g;m.scheduler=scheduler;m._poses=lambda:p
    m.transition=lambda *a,**k:None
    e={'tray_pose':p,'table_contact':np.ones(3),'gripper_contact_force':np.zeros((3,2))}
    def wait(seconds,predicate,stable):predicate(e);return predicate(e)
    m.r=SimpleNamespace(record_strict_deviation=lambda *a:warnings.append(a),wait=wait)
    op=Operation(0,0,g.goals[0],0)
    assert m._operation_geometry_ready(op)
    m._record_completion_slot_deviations(p)
    assert m.verify_operation(op)
    assert {w[0] for w in warnings}=={'operation_geometry_outside_strict_contract','scheduler_slot_outside_strict_contract','operation_outside_strict_contract'}
    e['table_contact'][0]=0
    assert not m.verify_operation(op)
    e['table_contact'][0]=1;e['gripper_contact_force'][0,0]=.6
    assert not m.verify_operation(op)


def test_completion_com_rule_does_not_allow_negative_gap_or_unsupported_center():
    from r1pro_teleop.airport_fsm.geometry import slot_geometry_ready
    g=Geometry(spec_fixture());p=poses(g);c=completion_criteria(config())
    p[2,1]+=.03
    assert not slot_geometry_ready(g,p,[0,1,2],2,2,c,require_full_footprint=False)
    p=poses(g);g.support_table=lambda position:None
    assert not slot_geometry_ready(g,p,[0,1,2],0,0,c,require_full_footprint=False)

