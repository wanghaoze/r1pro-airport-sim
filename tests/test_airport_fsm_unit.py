"""Pure/math/metadata/control-flow tests; NOT a MuJoCo physical success benchmark."""
from __future__ import annotations
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import json
import subprocess
import sys
import time
import numpy as np
import h5py
import pytest

from r1pro_teleop.airport_fsm.contracts import Config, Criteria, Fault, State, StableGate, atomic_json, minimum_duration, quintic, wrap_angle, seed_for, fingerprint, sha256_file, camera_shapes, NATIVE_CAMERA_SHAPES
from r1pro_teleop.airport_fsm.geometry import Geometry, Scheduler, Operation, rz, rectangle, overlap, placement_ok
from r1pro_teleop.airport_fsm.trajectory import TimedJointPath
from r1pro_teleop.airport_fsm.registry import prepare, load_sources, split_scenes, coverage
from r1pro_teleop.airport_fsm.trace import Trace, segments_from_trace, events_from_trace
from r1pro_teleop.airport_fsm.machine import Machine


def spec_fixture(sid='airport_fixture'):
    return {'scene_id':sid,'seed':123,'difficulty':'ordinary','front_count':3,'split':'train',
            'camera':{'width':1280,'height':720},'lighting':{'mode':'indoor_bright'},'aisle_gap_m':1.5,
            'belt_frame':{'origin_world':[.55,.6,.8],'rotation_world_from_belt':[[0,1,0],[-1,0,0],[0,0,1]]},
            'tables':[{'table_id':'front_left','center_world':[.85,0,0],'dimensions_m':[1.2,.6,.8],'yaw_world':np.pi/2},
                      {'table_id':'front_right','center_world':[.85,-1.2,0],'dimensions_m':[1.2,.6,.8],'yaw_world':np.pi/2},
                      {'table_id':'rear','center_world':[-1.25,0,0],'dimensions_m':[1.2,.6,.8],'yaw_world':np.pi/2}],
            'trays':[{'tray_id':f'tray_{i}','position_world':[.85,.6-(.22+i*.445),.801],'yaw_world':0.,'support_table':'front_left' if i<2 else 'front_right','support_parent':'front_left','dimensions_m':[.56,.43,.105]} for i in range(3)],
            'slots':[{'slot_id':f'slot_{i}','position_belt':[.22+i*.445,.3,0.],'yaw_belt':np.pi/2} for i in range(3)],
            'robot':{'base_control_available':False},'yaw_period_rad':float(np.pi)}


def poses(g):
    out=np.zeros((3,7));out[:,:3]=g.goals;out[:,2]+=.001
    out[:,3]=np.cos(g.goal_yaw/2);out[:,6]=np.sin(g.goal_yaw/2)
    return out


def valid_rows(n=24,spec=None):
    g=Geometry(spec or spec_fixture());p=poses(g)
    state=np.zeros((n,16),np.float32);state[:,[7,15]]=.1
    return {'timestamp':np.arange(n)/20,'sim_time':np.arange(n)/20,'qpos':np.zeros((n,37)),
            'qvel':np.zeros((n,37)),'qacc_warmstart':np.zeros((n,37)),'act':np.empty((n,0)),
            'integration_state':np.zeros((n,50)),'ctrl':np.zeros((n,19)),
            'action':state.copy(),'state':state,'base_action':np.zeros((n,3),np.float32),
            'base_state':np.zeros((n,3),np.float32),'tray_pose':np.repeat(p[None],n,axis=0),
            'floor_contact':np.zeros((n,3)),'illegal_collision':np.zeros(n,np.int32),
            'max_penetration':np.zeros(n),'gripper_contact_force':np.zeros((n,3,2)),
            'table_contact':np.ones((n,3)),'support_contact':np.ones((n,3)),
            'min_z':np.full((n,3),.801),'tcp':np.zeros((n,2,3)),
            'wrist_violation':np.zeros(n,bool),'transition_completed':np.ones(n,bool),
            'fsm_state':np.full(n,State.VERIFY_PLACEMENT.value), 'phase':np.full(n,'verified'),
            'target_tray':np.full(n,-1,np.int32),'target_slot':np.full(n,-1,np.int32),'recovery':np.zeros(n,bool)}


def write_trace(path,spec,rows):
    tr=Trace(path,{'scene_id':spec['scene_id'],'split':spec['split'],'unit_test_mock':True})
    for i in range(len(rows['timestamp'])):tr.append({k:v[i] for k,v in rows.items()})
    tr.close({'qpos':rows['qpos'][-1],'qvel':rows['qvel'][-1],'time':rows['timestamp'][-1]+.05})
    return path/'trace.h5'


@pytest.mark.parametrize('bad', [.0,.81,float('inf'),float('nan')])
def test_invalid_limit_fraction_rejected(bad):
    with pytest.raises(ValueError):replace(Config(),limit_fraction=bad).validate()


def test_verified_power_requires_external_profile():
    with pytest.raises(ValueError,match='hardware_profile'):replace(Config(),limit_mode='verified80').validate()


def test_recovered_bc_is_not_silently_enabled():
    with pytest.raises(ValueError):replace(Config(),include_recovered_in_bc=True).validate()


def test_split_counts_are_exact():
    with pytest.raises(ValueError):replace(Config(),split_counts=(320,40,50)).validate()


def test_per_camera_native_shapes_preserve_uncropped_head():
    spec=spec_fixture();spec['camera']['streams']={
        'head':{'width':1920,'height':1536},
        'left_wrist':{'width':1280,'height':720},
        'right_wrist':{'width':1280,'height':720}}
    assert camera_shapes(spec)==NATIVE_CAMERA_SHAPES


def test_stability_requires_elapsed_full_second():
    gate=StableGate(1.,20)
    assert not any(gate.update(True) for _ in range(20))
    assert gate.update(True)
    assert not gate.update(False)


def test_quintic_reference_limits():
    T=minimum_duration([1.,.05],[.8,.05],[1.2,.3],[7.,2.])
    u=np.linspace(0,1,10001)
    d=np.array([1.,.05]);v=(30*u**2-60*u**3+30*u**4)[:,None]*d/T
    a=(60*u-180*u**2+120*u**3)[:,None]*d/T**2
    j=(60-360*u+360*u**2)[:,None]*d/T**3
    assert np.all(np.max(abs(v),axis=0)<=np.array([.8,.05])+1e-10)
    assert np.all(np.max(abs(a),axis=0)<=np.array([1.2,.3])+1e-10)
    assert np.all(np.max(abs(j),axis=0)<=np.array([7.,2.])+1e-10)
    assert quintic(0)==0 and quintic(1)==1


@pytest.mark.parametrize('seed',range(6))
def test_c2_spline_analytical_bounds_dominate_dense_samples(seed):
    rng=np.random.default_rng(seed);p=np.cumsum(rng.uniform(-.08,.08,(8,4)),axis=0)
    v,a,j=np.ones(4)*.7,np.ones(4)*1.1,np.ones(4)*8.
    curve=TimedJointPath(p,v,a,j)
    q,d1,d2,d3=curve.evaluate(np.linspace(0,1,4001))
    assert np.allclose(q[0],p[0]) and np.allclose(q[-1],p[-1])
    assert np.max(abs(d1[0]))<1e-12 and np.max(abs(d1[-1]))<1e-12
    assert np.max(abs(d2[0]))<1e-12 and np.max(abs(d2[-1]))<1e-12
    for actual,cap in ((d1,v),(d2,a),(d3,j)):assert np.all(np.max(abs(actual),axis=0)<=cap+1e-7)


def test_spline_stationary_and_duplicate_knots():
    curve=TimedJointPath([[1.,2.],[1.,2.],[1.,2.]],1.,1.,1.)
    q,v,a,j=curve.evaluate(np.linspace(0,1,10))
    assert np.allclose(q,[1.,2.]) and np.max(abs(v))==0


def test_stable_seed_across_interpreter_processes():
    value=seed_for('a',123,2)
    code="from r1pro_teleop.airport_fsm.contracts import seed_for;print(seed_for('a',123,2))"
    assert int(subprocess.check_output([sys.executable,'-c',code]))==value
    assert seed_for('a',123,3)!=value


def test_sat_touch_and_clearance():
    a=rectangle([0,0],0,[1,1]);b=rectangle([1,0],0,[1,1])
    assert not overlap(a,b)
    assert overlap(a,b,clearance=.001)
    assert overlap(a,rectangle([.8,0],.2,[1,1]))


def test_frame_roundtrip_uses_actual_belt_matrix():
    s=spec_fixture();s['belt_frame']['rotation_world_from_belt']=rz(.713).tolist()
    g=Geometry(s);p=np.array([.3,.25,.08])
    assert np.allclose(g.to_belt(g.to_world(p)),p)
    assert np.isclose(g.goal_yaw[0],.713+np.pi/2)


def test_reject_invalid_frame():
    s=spec_fixture();s['belt_frame']['rotation_world_from_belt'][0][0]=2
    with pytest.raises(Fault):Geometry(s)


def test_dynamic_mapping_and_already_sorted_permutation():
    g=Geometry(spec_fixture());p=poses(g)[[2,0,1]]
    scheduler=Scheduler(g)
    assert scheduler.choose(p) is None
    assert scheduler.mapping==(1,2,0)


def test_scheduler_uses_centralized_placement_tolerance():
    g=Geometry(spec_fixture());p=poses(g)
    p[0,0]+=0.02
    assert Scheduler(g).choose(p) is not None
    assert Scheduler(g, Criteria(position_m=.03, yaw_deg=5., tilt_deg=5.)).choose(p) is None


def test_descent_preserves_feedback_corrected_lateral_target():
    # A repeatable 2 cm servo offset must stay compensated during descent.
    # Resetting XY to the nominal slot regresses the measured position.
    g=Geometry(spec_fixture());p=poses(g);p[0,2]=.92
    cfg=Config();moves=[]
    r=SimpleNamespace(cfg=cfg,g=g,holding=0,grasp_rel={},phase='transport',
                      sim=SimpleNamespace(target=np.zeros(16),base_state=lambda:np.zeros(3)))
    def observation():
        return dict(tray_pose=p.copy(),min_z=p[:,2].copy(),
                    gripper_contact_force=np.ones((3,2)),table_contact=np.ones(3))
    def motion(position,yaw=None,**kwargs):
        moves.append((r.phase,np.asarray(position).copy()))
        p[0,:3]=position;p[0,0]-=.02
    r.observation=observation;r.object_motion=motion
    r.navigate=lambda goal:None;r.remember_grasp=lambda tray:None
    r.wait=lambda *args,**kwargs:True;r.joints=lambda *args,**kwargs:None
    m=object.__new__(Machine);m.r=r;m.c=cfg;m.g=g
    m.log=SimpleNamespace(event=lambda *args,**kwargs:None)
    m.transition=lambda state,phase,**kwargs:setattr(r,'phase',phase)
    m.retreat=lambda:None
    op=Operation(0,0,g.goals[0].copy(),g.goal_yaw[0])
    m._place_location=lambda operation:operation.destination.copy()
    m.carry_place(op)
    assert np.allclose(p[0,:2],op.destination[:2])
    assert np.allclose(moves[-1][1][:2],moves[-2][1][:2])


def test_top_tray_selected_before_lower():
    g=Geometry(spec_fixture());p=poses(g)
    p[0,:3]=[-1.25,0,.801];p[1,:3]=[-1.25,0,.911]
    assert not g.top_available(p,0) and g.top_available(p,1)
    op=Scheduler(g).choose(p)
    assert op.tray!=0


def test_occupied_slot_requests_buffer():
    g=Geometry(spec_fixture());p=poses(g)
    p[0,:3]=[-1.25,0,.801];p[1,:3]=g.goals[0]
    scheduler=Scheduler(g);scheduler.mapping=(0,1,2)
    op=scheduler.choose(p)
    assert op.tray==1 and op.temporary and op.slot==-1
    assert not g.blockers(p,1,op.destination,op.yaw,.025)


def test_target_on_destination_blocker_is_buffered_without_mutating_scene():
    g=Geometry(spec_fixture());p=poses(g)
    p[1,:3]=p[0,:3];p[0,2]+=.07
    original=p.copy()
    scheduler=Scheduler(g);scheduler.mapping=(0,1,2)
    op=scheduler.choose(p)
    assert op.tray==0 and op.temporary and op.slot==-1
    assert g.footprint_supported(op.destination,op.yaw,g.sizes[op.tray])
    assert not g.blockers(p,op.tray,op.destination,op.yaw,.025)
    assert np.array_equal(p,original)


def test_stack_clearance_keeps_no_free_buffer_failure(monkeypatch):
    g=Geometry(spec_fixture());p=poses(g)
    p[1,:3]=p[0,:3];p[0,2]+=.07
    scheduler=Scheduler(g);scheduler.mapping=(0,1,2)
    def unavailable(*args):raise Fault('no_free_buffer')
    monkeypatch.setattr(g,'buffer',unavailable)
    with pytest.raises(Fault,match='no_free_buffer'):scheduler.choose(p)


def test_aligned_neighbour_intruding_next_slot_gets_local_repair():
    g=Geometry(spec_fixture());p=poses(g)
    p[1,:3]+=g.R[:,0]*.025
    p[2,:3]=[-1.25,0,.801]
    scheduler=Scheduler(g,Criteria());scheduler.mapping=(0,1,2)
    op=scheduler.choose(p)
    assert op.tray==1 and op.slot==1 and not op.temporary
    assert np.allclose(op.destination,g.goals[1])


def test_supported_push_accepted_but_cross_table_rejected():
    g=Geometry(spec_fixture());p=poses(g);p[2,:3]+=g.R[:,0]*.08
    assert g.push_possible(p,2,g.goals[2],g.goal_yaw[2])
    p[2,:3]=[-1.25,0,.801]
    assert not g.push_possible(p,2,g.goals[2],g.goal_yaw[2],5.)


def test_inward_push_can_restore_table_inset_without_overhang():
    g=Geometry(spec_fixture());p=poses(g)
    p[2,0]=.832
    assert not g.footprint_supported(p[2,:3],g.goal_yaw[2],g.sizes[2])
    assert g.push_possible(p,2,g.goals[2],g.goal_yaw[2])
    p[2,0]=.829
    assert not g.push_possible(p,2,g.goals[2],g.goal_yaw[2])


def test_push_that_hits_neighbour_rejected():
    g=Geometry(spec_fixture());p=poses(g)
    destination=p[2,:3]-g.R[:,0]*.08
    assert not g.push_possible(p,2,destination,g.goal_yaw[2])


def test_final_gate_passes_valid_placement():
    ok,report=placement_ok(valid_rows(),Geometry(spec_fixture()),Criteria())
    assert ok and np.allclose(report['placement']['final_gaps_m'],.015)


@pytest.mark.parametrize('failure',['floor_contact','illegal_collision','max_penetration','wrist_violation','transition_completed'])
def test_any_earlier_fault_prevents_final_success(failure):
    a=valid_rows(60)
    if failure=='transition_completed':a[failure][0]=False
    elif failure=='max_penetration':a[failure][0]=.004
    else:a[failure][0]=1
    assert not placement_ok(a,Geometry(spec_fixture()),Criteria())[0]


def test_pi_symmetry_must_be_explicit():
    s=spec_fixture();a=valid_rows(spec=s);a['tray_pose'][:,:,3:]=[0,0,0,1]
    assert placement_ok(a,Geometry(s),Criteria())[0]
    s['yaw_period_rad']=float(2*np.pi)
    assert not placement_ok(a,Geometry(s),Criteria())[0]


def test_two_pi_wrap_at_boundary():
    assert abs(wrap_angle(-np.pi+.01-(np.pi-.01))-.02)<1e-9


@pytest.mark.parametrize('kind',['motion','tilt','support','closed','contact','gap','nan'])
def test_final_gate_rejects_incomplete_physical_outcome(kind):
    a=valid_rows()
    if kind=='motion':a['tray_pose'][-1,0,0]+=.002
    if kind=='tilt':a['tray_pose'][:,:,3:]=[np.cos(.1),np.sin(.1),0,0]
    if kind=='support':a['table_contact'][-1,0]=0
    if kind=='closed':a['state'][-1,7]=.004
    if kind=='contact':a['gripper_contact_force'][-1,0,0]=1.
    if kind=='gap':a['tray_pose'][:,2,1]-=.02
    if kind=='nan':a['action'][0,0]=np.nan
    assert not placement_ok(a,Geometry(spec_fixture()),Criteria())[0]


def test_zero_act_hdf5_journal_and_half_open_segments(tmp_path):
    s=spec_fixture();a=valid_rows()
    path=write_trace(tmp_path/'a000',s,a)
    with h5py.File(path) as f:
        assert 'act' not in f and json.loads(f.attrs['empty_shape:act'])==[0]
        assert len(f['timestamp'])==24
    seg=segments_from_trace(path,s,{'physics_success':True,'recovery_used':False})
    assert seg[0]['start_frame']==0 and seg[-1]['end_frame']==24
    assert all(x['start_frame']<x['end_frame'] for x in seg)


def test_recovery_segments_not_bc(tmp_path):
    s=spec_fixture();a=valid_rows();a['recovery'][8:12]=True
    a['fsm_state']=np.array([State.RECOVER.value if 8<=i<12 else State.VERIFY_PLACEMENT.value for i in range(24)])
    path=write_trace(tmp_path/'a000',s,a)
    segments=segments_from_trace(path,s,{'physics_success':True,'recovery_used':True})
    assert any(x['recovery'] for x in segments)
    assert not any(x['training_candidate'] for x in segments)
    assert sum(x['end_frame']-x['start_frame'] for x in segments)==24


@pytest.mark.parametrize('strict_success,expected_candidate', [(False, False), (True, True)])
def test_approximate_completion_segments_require_strict_success_for_bc(
        tmp_path, strict_success, expected_candidate):
    s=spec_fixture();path=write_trace(tmp_path/'a000',s,valid_rows())
    result={'physics_success':True,'task_completed':True,'recovery_used':False,
            'approximate_completion_enabled':True,'strict_success':strict_success,
            'training_candidate':expected_candidate}
    segments=segments_from_trace(path,s,result)
    assert segments and all(x['episode_task_completed'] for x in segments)
    assert any(x['success'] for x in segments)
    assert all(x['training_candidate']==expected_candidate for x in segments if x['success'])


def test_evidence_events_do_not_invent_lift_from_phase(tmp_path):
    s=spec_fixture();a=valid_rows();a['phase']=np.full(24,'lift');a['target_tray'][:]=0
    path=write_trace(tmp_path/'a000',s,a)
    events=events_from_trace(path,s,{'physics_success':False})
    assert not any(e['event']=='lift_above_2cm' for e in events)


def test_evidence_detects_contact_lift_release(tmp_path):
    s=spec_fixture();a=valid_rows()
    a['gripper_contact_force'][2:15,0]=2;a['state'][2:15,[7,15]]=.02
    a['support_contact'][6:14,0]=0;a['table_contact'][6:14,0]=0;a['min_z'][6:14,0]+=.04
    path=write_trace(tmp_path/'a000',s,a)
    names=[e['event'] for e in events_from_trace(path,s,{'physics_success':False})]
    assert 'gripper_contact' in names and 'lift_above_2cm' in names and 'open_release' in names


def source_manifest(tmp_path,n=400):
    root=tmp_path/'sources';root.mkdir();entries=[]
    for i in range(n):
        directory=root/f'scene_{i:04d}';directory.mkdir()
        xml=directory/'scene.xml';xml.write_text('<mujoco/>')
        s=spec_fixture(f'airport_{i:04d}');s['seed']=i;s['xml_sha256']=sha256_file(xml)
        s['front_count']=i%4;s['difficulty']='complex' if i%20==0 else 'ordinary'
        atomic_json(directory/'scene.json',s)
        entries.append({'scene_id':s['scene_id'],'json':f'scene_{i:04d}/scene.json'})
    manifest=root/'manifest.json';atomic_json(manifest,{'scenes':entries});return manifest


def test_400_manifest_registered_exact_split_and_idempotent_resume(tmp_path):
    manifest=source_manifest(tmp_path);out=tmp_path/'collection'
    first=prepare(manifest,out,Config(),half_turn_equivalent=True)
    second=prepare(manifest,out,Config(),half_turn_equivalent=True)
    assert first['fingerprint']==second['fingerprint']
    split=json.loads((out/'splits/scenes.json').read_text())
    assert len(split)==400 and [list(split.values()).count(x) for x in ('train','val','test')]==[300,50,50]
    r=coverage(out)
    assert r['registered']==400 and r['counts']['not_attempted']==400
    assert not r['all_scenes_have_validated_lerobot']
    with pytest.raises(Fault):prepare(manifest,out,replace(Config(),base_speed=.25),half_turn_equivalent=True)


def test_399_manifest_is_not_silently_promoted_to_400(tmp_path):
    with pytest.raises(Fault,match='scene_count_mismatch'):load_sources(source_manifest(tmp_path,399),400)


def test_duplicate_scene_rejected(tmp_path):
    manifest=source_manifest(tmp_path,2);d=json.loads(manifest.read_text());d['scenes'][1]=d['scenes'][0]
    atomic_json(manifest,d)
    with pytest.raises(Fault,match='duplicate'):load_sources(manifest,2)


def test_changed_source_xml_rejected(tmp_path):
    manifest=source_manifest(tmp_path,1);(manifest.parent/'scene_0000/scene.xml').write_text('<mujoco model="changed"/>')
    with pytest.raises(Fault,match='checksum'):load_sources(manifest,1)


def test_split_is_independent_of_input_order():
    a=[f'a{i}' for i in range(400)]
    assert split_scenes(a,(300,50,50),123)==split_scenes(a[::-1],(300,50,50),123)


class MockRuntime:
    """Only tests FSM sequencing. No test below claims simulated contact physics."""
    def __init__(self,tmp_path,carry=False):
        self.cfg=Config();self.spec=spec_fixture();self.g=Geometry(self.spec)
        self.pose=poses(self.g)
        self.pose[2,:3]=[-1.25,0,.801] if carry else self.pose[2,:3]+self.g.R[:,0]*.08
        scene=tmp_path/'mock_scene.xml';scene.write_text('<mock_for_unit_control_flow_only/>')
        target=np.zeros(16,np.float32);target[[7,15]]=.1
        self.sim=SimpleNamespace(scene=scene,target=target,state=lambda:target.copy(),nstep=25)
        self.m=SimpleNamespace(opt=SimpleNamespace(timestep=.002))
        self.d=SimpleNamespace(qpos=np.zeros(37),qvel=np.zeros(37),time=0.)
        self.physical_time_start=0.
        self.limits={'unit_test_mock_not_physics':True};self.trace=None;self.allowed_tray=None;self.target_slot=-1
        self.fsm_state=State.SEARCH_TARGET;self.phase='unknown';self.recovery=False;self.holding=None
        self.steps=0;self.wall_start=time.monotonic();self.peak_power=0.;self.id_calls=0;self.id_slowdowns=0
        self.tucked=target.copy();self.initial_bottom=np.full(3,.801)
    def observation(self):
        a=valid_rows(1);e={k:v[0] for k,v in a.items() if k in ('tray_pose','floor_contact','illegal_collision','max_penetration','gripper_contact_force','table_contact','support_contact','min_z','tcp')}
        e['tray_pose']=self.pose.copy();return e
    def tick(self):
        row={k:v[0] for k,v in valid_rows(1).items()}
        row.update(self.observation(),timestamp=self.steps/20,sim_time=self.steps/20,
                   fsm_state=self.fsm_state.value,phase=self.phase,recovery=self.recovery,
                   target_tray=-1 if self.allowed_tray is None else self.allowed_tray,target_slot=self.target_slot)
        if self.trace:self.trace.append(row)
        self.steps+=1;self.d.time=self.steps/20
    def wait(self,seconds,predicate=None,stable_seconds=None):
        gate=StableGate(stable_seconds or .1,20)
        for _ in range(max(1,round(seconds*20))):
            self.tick()
            if predicate is not None and gate.update(bool(predicate(self.observation()))):return True
        return predicate is None
    def joints(self,*_,**__):self.tick()
    def close(self):pass


class FlowMachine(Machine):
    def __init__(self,*args,fail=None,**kwargs):
        super().__init__(*args,**kwargs);self.calls=[];self.fail=fail;self.recoveries=0
    def align(self,tray,slot):self.calls.append('align');return 0.,0.
    def grasp(self,tray,*_):
        self.calls.append('grasp')
        if self.fail=='hard':raise Fault('illegal_collision')
    def carry_place(self,op):self.calls.append('carry');self.r.pose[op.tray,:3]=op.destination+[0,0,.001]
    def separate_if_needed(self,tray):return False
    def push(self,op,**_):
        self.calls.append('push')
        if self.fail=='soft':raise Fault('push_no_progress',recoverable=True)
        self.r.pose[op.tray,:3]=op.destination+[0,0,.001]
    def recover(self,fault):
        self.recoveries+=1;self.recovery_used=True
        self.transition(State.RECOVER,'recover');self.r.tick()


@pytest.mark.parametrize('carry',[False,True])
def test_real_fsm_dispatch_with_mock_runtime(tmp_path,carry):
    r=MockRuntime(tmp_path,carry);m=FlowMachine(r,tmp_path/'a000')
    report=m.run();result=m.finish(True,report)
    assert result['physics_success'] # mocked control-flow outcome ONLY
    assert ('carry' in m.calls)==carry and ('push' in m.calls)==(not carry)
    assert m.operations==1


@pytest.mark.parametrize('strict_runtime_passed,expected_candidate',
                         [(False, False), (True, True)])
def test_approximate_finish_keeps_completion_but_gates_bc_on_strict(
        tmp_path, strict_runtime_passed, expected_candidate):
    r=MockRuntime(tmp_path)
    r.cfg=Config(acceptance_profile='completion_first',approximate_completion_enabled=True)
    r.strict_runtime_passed=strict_runtime_passed
    m=FlowMachine(r,tmp_path/'a000')
    result=m.finish(True,{'strict_accepted':strict_runtime_passed})
    assert result['task_completed']
    assert result['strict_success']==strict_runtime_passed
    assert result['training_candidate']==expected_candidate


def test_hard_collision_is_never_retried(tmp_path):
    r=MockRuntime(tmp_path,True);m=FlowMachine(r,tmp_path/'a000',fail='hard')
    with pytest.raises(Fault,match='illegal_collision') as exc:m.run()
    result=m.finish(False,error=exc.value)
    assert m.recoveries==0 and not result['physics_success']


def test_soft_failure_retries_are_bounded(tmp_path):
    r=MockRuntime(tmp_path);m=FlowMachine(r,tmp_path/'a000',fail='soft')
    with pytest.raises(Fault,match='push_no_progress') as exc:m.run()
    result=m.finish(False,error=exc.value)
    assert m.calls.count('push')==r.cfg.max_local_retries
    assert m.recoveries==r.cfg.max_local_retries-1 and result['recovery_used']
    assert not result['training_candidate']


def test_native_export_implementation_has_no_crop_resize_or_rate_change():
    import ast
    from r1pro_teleop.airport_fsm import exporter
    tree=ast.parse(Path(exporter.__file__).read_text(encoding='utf8'))
    forbidden={'resize','crop','setpts'}
    assert not any(isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr in forbidden for n in ast.walk(tree))


def test_live_runtime_never_assigns_tray_qpos():
    import ast
    from r1pro_teleop.airport_fsm import runtime
    tree=ast.parse(Path(runtime.__file__).read_text(encoding='utf8'))
    for node in ast.walk(tree):
        if isinstance(node,ast.Assign):
            text=ast.unparse(node)
            assert not text.startswith('self.d.qpos[') and not text.startswith('self.sim.data.qpos[')


def test_collection_lock_blocks_same_process_second_writer(tmp_path):
    import os
    from r1pro_teleop.airport_fsm.__main__ import collection_lock
    if os.name != 'posix':
        # Windows must refuse formal batch execution, not silently run unlocked.
        with pytest.raises(Fault, match='batch_lock_requires_posix'):
            with collection_lock(tmp_path/'root'):pass
        return
    with collection_lock(tmp_path/'root'):
        with pytest.raises(Fault,match='already_in_use'):
            with collection_lock(tmp_path/'root'):pass


def pair_runtime():
    from r1pro_teleop.airport_fsm.runtime import Runtime
    r=object.__new__(Runtime)
    r.robot_bodies={10,11};r.table_bodies={30};r.tray_bodies={20:0,21:1}
    r.allowed_tray=0;r.holding=0;r.fsm_state=State.TRANSPORT_TRAY;r.phase='transport'
    body_names={0:'world',10:'base_link',11:'left_gripper_finger1',20:'tray_0',21:'tray_1',30:'front_left'}
    geom_names=['floor','base','finger','tray_0_geom','tray_1_geom','table','wall']
    r.m=SimpleNamespace(geom_bodyid=np.array([0,10,11,20,21,30,0]),
                        body=lambda b:SimpleNamespace(name=body_names[b]),
                        geom=lambda g:SimpleNamespace(name=geom_names[g]))
    return r


def test_payload_collision_is_checked_not_just_robot():
    r=pair_runtime()
    assert not r._pair_allowed(3,5)
    assert not r._pair_allowed(3,4)
    assert not r._pair_allowed(3,0)


def test_contact_allowance_is_phase_specific():
    r=pair_runtime();r.fsm_state=State.PLACE_TRAY;r.phase='descend'
    assert r._pair_allowed(3,5)
    assert not r._pair_allowed(3,4)


def test_floor_exception_does_not_allow_base_through_walls():
    r=pair_runtime()
    assert r._pair_allowed(1,0)
    assert not r._pair_allowed(1,6)


def test_finger_may_touch_only_current_tray_not_table_or_other_tray():
    r=pair_runtime()
    assert r._pair_allowed(2,3)
    assert not r._pair_allowed(2,4)
    assert not r._pair_allowed(2,5)


def test_adjacent_table_seam_is_supported_union():
    g=Geometry(spec_fixture())
    assert g.front_union
    for y in np.linspace(-.615,-.585,11):assert g.support_table([.85,y,.801]).startswith('front')


def test_real_gap_does_not_get_union_support():
    s=spec_fixture();s['tables'][1]['center_world'][1]-=.1
    g=Geometry(s)
    assert not g.front_union and g.support_table([.85,-.65,.801]) is None


def test_low_texture_rejection_is_not_exported_coverage(tmp_path):
    manifest=source_manifest(tmp_path,1);out=tmp_path/'collection'
    prepare(manifest,out,replace(Config(),expected_scenes=1,split_counts=(1,0,0)))
    attempt=out/'attempts/airport_0000/a000'
    atomic_json(attempt/'result.json',{'scene_id':'airport_0000','split':'train','physics_success':True,'recovery_used':False})
    atomic_json(attempt/'export_quality.json',{'status':'rejected','failure_code':'camera_low_texture_needs_review'})
    report=coverage(out)
    assert report['counts']=={'export_quality_rejected':1}
    assert report['exported_scene_count']==0


def test_nonfinite_terminal_is_preserved_as_failure_metadata(tmp_path):
    trace=Trace(tmp_path/'a000',{'unit_test':True})
    trace.append({'qpos':np.array([np.nan])})
    trace.close({'qpos':[np.nan]})
    with h5py.File(tmp_path/'a000/trace.h5') as f:
        assert json.loads(f.attrs['terminal_snapshot_json'])['invalid'] is True
        assert np.isnan(f['qpos'][0,0])
