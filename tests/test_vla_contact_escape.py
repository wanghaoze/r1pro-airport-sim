import numpy as np
import pytest

from r1pro_teleop.vla.contact_escape import EscapeSample, base_escape_candidates, qualify_private_escape

PAIR=('base_link_geom','rear_table')


def samples(distances=(-.0002,-.0001,.0011), source='planning_shadow'):
    return [EscapeSample(np.array([i*.001,0.,0.]),np.zeros(16),{PAIR:d},source,
                         physics_time=i*.05 if source=='measured_physics' else None,
                         transition_completed=i>0,original_guard_passed=i>0)
            for i,d in enumerate(distances)]


def test_normals_propose_bounded_outward_translation_without_yaw_or_joint_edits():
    out=base_escape_candidates([1.,2.,.5],[[2.,0.],[2.,0.]])
    assert len(out)==3
    assert all(np.array_equal(p[1:],np.array([2.,.5])) for p in out)
    assert [p[0]-1 for p in out]==pytest.approx([.002,.005,.01])
    assert base_escape_candidates([0.,0.,0.],[[1.,0.],[-1.,0.]])==[]


def test_shadow_qualification_cannot_authorize_physics_or_teacher_label():
    result=qualify_private_escape(samples(),original_pairs=[PAIR],source='planning_shadow')
    assert result['source']=='planning_shadow'
    assert result['expert_label_authorized'] is False
    assert result['teacher_integration'] is False
    assert result['planning_clearance_m']==.001


@pytest.mark.parametrize('distances,error',[
    ((-.0003,-.0001,.0011),'initial_contact_unqualified'),
    ((-.0002,-.00021,.0011),'contact_worsened'),
    ((-.0002,-.0001,.0009),'endpoint_not_clear'),
    ((-.0002,.00100001,.00099999),'cleared_pair_recontact'),
    ((-.0002,-.00020009,-.00020018,.0011),'contact_worsened'),
])
def test_old_pairs_cannot_worsen_accumulate_tolerance_or_recontact(distances,error):
    with pytest.raises(ValueError,match=error):
        qualify_private_escape(samples(distances),original_pairs=[PAIR],source='planning_shadow')


def test_new_collision_missing_pair_and_unbounded_motion_rejected():
    for mutation,error in [
        (lambda s:s.distances.update({('wrist','table'):.0009}),'new_collision'),
        (lambda s:s.distances.clear(),'distance_missing'),
        (lambda s:s.base_world.__setitem__(0,.02),'translation'),
        (lambda s:s.joints.__setitem__(0,.02),'arm_pose'),
    ]:
        evidence=samples();mutation(evidence[1])
        with pytest.raises(ValueError,match=error):
            qualify_private_escape(evidence,original_pairs=[PAIR],source='planning_shadow')


def test_physical_qualification_requires_actual_completed_time_and_original_guards():
    evidence=samples(source='measured_physics')
    assert qualify_private_escape(evidence,original_pairs=[PAIR],source='measured_physics')['source']=='measured_physics'
    for change in ('transition_completed','original_guard_passed','physics_time'):
        evidence=samples(source='measured_physics')
        values=dict(evidence[1].__dict__);values[change]=False if change!='physics_time' else 0.
        evidence[1]=EscapeSample(**values)
        with pytest.raises(ValueError,match='physics_interval_not_verified'):
            qualify_private_escape(evidence,original_pairs=[PAIR],source='measured_physics')


@pytest.mark.parametrize('fail_tick',[None,4])
def test_runtime_adapter_executes_real_ticks_and_retains_failed_prefix(fail_tick):
    from types import SimpleNamespace
    from r1pro_teleop.vla.contact_escape import RuntimeEscapeAdapter, pair_key
    adapter=RuntimeEscapeAdapter.__new__(RuntimeEscapeAdapter)
    pair=pair_key('robot','table');adapter.original={pair:-.0002};adapter.margin=.001
    adapter.start=np.zeros(3);adapter.reference=np.zeros(16)
    d=SimpleNamespace(time=2.)
    sim=SimpleNamespace(base_target=np.zeros(3),target=np.zeros(16))
    sim.base_state=lambda:sim.base_target.copy();sim.state=lambda:sim.target.copy()
    model=SimpleNamespace(body_pos=np.zeros((1,3)),body_quat=np.array([[1.,0,0,0]]),body=lambda n:SimpleNamespace(id=0))
    runtime=SimpleNamespace(d=d,sim=sim,m=model,cfg=SimpleNamespace(fps=20),steps=40)
    def tick():
        if fail_tick is not None and runtime.steps-40==fail_tick-1:raise RuntimeError('unchanged_camera_guard')
        d.time+=.05;runtime.steps+=1
    runtime.tick=tick;adapter.r=runtime
    adapter.screen=lambda target:dict(status='screened')
    adapter.distances=lambda data:{pair:-.0002+sim.base_target[0]}
    audit={}
    if fail_tick:
        with pytest.raises(RuntimeError,match='unchanged_camera_guard'):
            adapter.execute(np.array([.002,0,0]),audit=audit)
        assert audit['status']=='private_prefix_rejected'
        assert audit['failed_tick']==4 and len(audit['physics_times'])==4
    else:
        evidence=adapter.execute(np.array([.002,0,0]),audit=audit)
        assert runtime.steps==60 and len(evidence['physics_times'])==21
        assert np.all(np.diff(evidence['physics_times'])>0)
        assert audit['status']=='private_prefix_qualified'
        assert np.array_equal(sim.target,np.zeros(16))


def test_runtime_adapter_screen_rejects_new_pair_without_live_motion():
    from types import SimpleNamespace
    from r1pro_teleop.vla.contact_escape import RuntimeEscapeAdapter, pair_key
    adapter=RuntimeEscapeAdapter.__new__(RuntimeEscapeAdapter)
    adapter.original={pair_key('robot','table'):-.0002};adapter.margin=.001
    adapter.start=np.zeros(3);adapter.reference=np.zeros(16)
    r=SimpleNamespace(d=SimpleNamespace(time=7.),sim=SimpleNamespace(target=np.zeros(16)))
    r._shadow=lambda target,base:SimpleNamespace(time=7.)
    adapter.r=r
    def sample(data,**kw):
        distances={pair_key('robot','table'):-.0002+adapter._proposed[0],pair_key('new_robot','wall'):.0005}
        return EscapeSample(adapter._proposed.copy(),np.zeros(16),distances)
    adapter.sample=sample
    with pytest.raises(ValueError,match='new_collision'):
        adapter.screen(np.array([.002,0,0]))
    assert r.d.time==7. and np.array_equal(r.sim.target,np.zeros(16))


@pytest.mark.parametrize('generated_self_contact',[False,True])
def test_explicit_queries_do_not_invent_filtered_robot_self_collision(generated_self_contact):
    from types import SimpleNamespace
    from r1pro_teleop.vla.contact_escape import RuntimeEscapeAdapter,pair_key
    model=SimpleNamespace(geom_contype=np.ones(3,dtype=int),geom_conaffinity=np.ones(3,dtype=int),
        geom_rbound=np.ones(3),geom_bodyid=np.array([1,2,3]),body_weldid=np.array([0,1,2,3]),
        exclude_signature=np.zeros(0,dtype=int),geom=lambda i:SimpleNamespace(name=['robot0','robot1','table'][i]))
    contacts=[SimpleNamespace(geom1=0,geom2=1)] if generated_self_contact else []
    data=SimpleNamespace(geom_xpos=np.zeros((3,3)),contact=contacts)
    calls=[]
    def distance(m,d,a,b,margin,points):calls.append((a,b));return -.02 if {a,b}=={0,1} else .005
    runtime=SimpleNamespace(m=model,mj=SimpleNamespace(mj_geomDistance=distance),robot_geoms=[0,1],
        robot_bodies={1,2},holding=None,_pair_allowed=lambda a,b:False)
    adapter=RuntimeEscapeAdapter.__new__(RuntimeEscapeAdapter);adapter.r=runtime;adapter.original={};adapter.margin=.001
    result=adapter.distances(data)
    assert (pair_key('robot0','robot1') in result)==generated_self_contact
    assert ({0,1} in [set(pair) for pair in calls])==generated_self_contact


def test_explicit_queries_honor_body_weld_and_model_exclusion():
    from types import SimpleNamespace
    from r1pro_teleop.vla.contact_escape import RuntimeEscapeAdapter
    model=SimpleNamespace(geom_contype=np.ones(4,dtype=int),geom_conaffinity=np.ones(4,dtype=int),
        geom_rbound=np.ones(4),geom_bodyid=np.array([1,1,2,3]),body_weldid=np.array([0,1,1,3]),
        exclude_signature=np.array([(1<<16)+3]),geom=lambda i:SimpleNamespace(name=str(i)))
    runtime=SimpleNamespace(m=model,robot_geoms=[0],robot_bodies={1},holding=None,_pair_allowed=lambda a,b:False,
        mj=SimpleNamespace(mj_geomDistance=lambda *args:pytest.fail('Compiled filtered pair must not be queried')))
    adapter=RuntimeEscapeAdapter.__new__(RuntimeEscapeAdapter);adapter.r=runtime;adapter.original={};adapter.margin=.001
    assert adapter.distances(SimpleNamespace(geom_xpos=np.zeros((4,3)),contact=[]))=={}
