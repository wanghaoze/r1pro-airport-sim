from dataclasses import replace
from types import SimpleNamespace
import numpy as np
import pytest
from r1pro_teleop.airport_fsm.contracts import Config, Fault
from r1pro_teleop.airport_fsm.runtime import Runtime
from test_substep_runtime_replay import airport


def fake(*, enabled=True, dt=.002, origin=32.75):
    r=Runtime.__new__(Runtime)
    r.cfg=Config(retained_support_integer_clock_enabled=enabled)
    r.physics_step_count=0;r.physics_clock_origin_time=origin;r.physics_clock_timestep=dt
    r.retained_support_missing_step=None;r.retained_support_missing_since=None
    r.retained_contact=(0,'left');r.d=SimpleNamespace(time=origin)
    r.m=SimpleNamespace(opt=SimpleNamespace(timestep=dt));r.sim=SimpleNamespace(target=np.zeros(16))
    r.g=SimpleNamespace(support_table=lambda p:'table',tables={'table':{'dimensions_m':[1,1,.8]}})
    e={'table_contact':np.zeros(1),'gripper_contact_force':np.ones((1,2)),
       'min_z':np.array([.8001]),'tray_pose':np.array([[0,0,.8,1,0,0,0]])}
    r.observation=lambda:e;r.trace=None
    return r,e


def advance(r,n):
    for _ in range(n):r.d.time+=r.physics_clock_timestep;r.physics_step_count+=1


def test_integer_inclusive_boundary_and_duplicate_check():
    r,e=fake();events=[];r.trace=SimpleNamespace(event=lambda name,**kw:events.append((name,kw)))
    r.check_retained_contact()
    for _ in range(3):
        advance(r,25);r.check_retained_contact();r.check_retained_contact()
    assert r.d.time-r.retained_support_missing_since>.15
    assert events[-1][1]['boundary_only_difference']
    assert events[-1][1]['elapsed_physics_steps']==75
    advance(r,1)
    with pytest.raises(Fault,match='retained_contact_lost') as exc:r.check_retained_contact()
    assert exc.value.detail['clock']['elapsed_physics_steps']==76


@pytest.mark.parametrize('dt,allowed,rejected',[(.002,75,100),(.003,50,51),(.004,37,38),(.007,21,22)])
def test_exact_threshold_other_timestep(dt,allowed,rejected):
    r,e=fake(dt=dt);r.check_retained_contact();advance(r,allowed);r.check_retained_contact()
    advance(r,rejected-allowed)
    with pytest.raises(Fault,match='retained_contact_lost'):r.check_retained_contact()


def test_default_legacy_reproduces_old_boundary():
    assert not Config().retained_support_integer_clock_enabled
    r,e=fake(enabled=False);r.check_retained_contact();advance(r,75)
    with pytest.raises(Fault,match='retained_contact_lost') as exc:r.check_retained_contact()
    assert 'clock' not in exc.value.detail


def test_only_checked_support_resets_timer():
    r,e=fake();r.check_retained_contact();advance(r,25)
    e['table_contact'][0]=1 # unobserved substep support: no reset
    advance(r,1);e['table_contact'][0]=0;r.check_retained_contact()
    assert r.retained_support_missing_step==0
    e['table_contact'][0]=1;r.check_retained_contact()
    assert r.retained_support_missing_step is r.retained_support_missing_since is None
    e['table_contact'][0]=0;r.check_retained_contact();assert r.retained_support_missing_step==26


@pytest.mark.parametrize('field,value',[('physics_step_count',-1),('physics_step_count',True),
    ('physics_clock_origin_time',99.),('physics_clock_timestep',.003),('retained_support_missing_step',None)])
def test_inconsistent_clock_rejected_without_new_grace(field,value):
    r,e=fake();r.check_retained_contact();setattr(r,field,value)
    with pytest.raises(Fault,match='retained_support_clock_inconsistent'):r.check_retained_contact()


@pytest.mark.parametrize('violation',['force','opening','gap','table'])
def test_other_predicates_unchanged_at_inclusive_boundary(violation):
    r,e=fake();r.check_retained_contact();advance(r,75)
    if violation=='force':e['gripper_contact_force'][0,0]=.5
    if violation=='opening':r.sim.target[7]=.01
    if violation=='gap':e['min_z'][0]=.803
    if violation=='table':r.g.support_table=lambda p:None
    with pytest.raises(Fault,match='retained_contact_lost'):r.check_retained_contact()


def test_real_tick_counts_post_before_completed_frame_increment(airport,monkeypatch):
    create,_,_=airport;r=create(False);r.cfg=replace(r.cfg,retained_support_integer_clock_enabled=True)
    observed=[];original=r.check_retained_contact
    def check():observed.append((r.steps,r.physics_step_count));return original()
    monkeypatch.setattr(r,'check_retained_contact',check)
    r.tick();r.tick()
    assert observed==[(0,0),(0,25),(1,25),(1,50)]
    assert r.physics_step_count==50 and r.steps==2
    r.validate_retained_clock_state()


def test_real_guard_failure_counts_actual_partial_substeps(airport,monkeypatch):
    create,_,_=airport;r=create(False);r.cfg=replace(r.cfg,retained_support_integer_clock_enabled=True)
    def fail():
        if r.physics_step_count==3:raise Fault('injected_guard_failure')
    monkeypatch.setattr(r,'guard',fail)
    with pytest.raises(Fault,match='injected_guard_failure'):r.tick()
    assert r.physics_step_count==3 and r.steps==0
    r.validate_retained_clock_state()


def test_config_requires_boolean():
    with pytest.raises(ValueError,match='retained_support_integer_clock_enabled'):
        Config(retained_support_integer_clock_enabled=1).validate()

@pytest.mark.parametrize('field',['physics_step_count','physics_clock_origin_time','physics_clock_timestep','retained_support_missing_step'])
def test_missing_clock_field_rejected_even_without_active_timer(field):
    r,e=fake();delattr(r,field)
    with pytest.raises(Fault,match='retained_support_clock_inconsistent'):r.validate_retained_clock_state()
