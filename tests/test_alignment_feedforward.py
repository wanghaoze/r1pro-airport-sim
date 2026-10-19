from types import SimpleNamespace
import numpy as np
import pytest
from test_release_scheduler import scene7
from r1pro_teleop.airport_fsm.alignment_feedforward import alignment_xy_target
from r1pro_teleop.airport_fsm.contracts import Config
from r1pro_teleop.airport_fsm.geometry import Operation
from r1pro_teleop.airport_fsm import primitives


def data(scene7):
    g,poses,_=scene7;poses=poses.copy();poses[1,1]=-1.;poses[2,1]=-2.
    staged=g.goals[0].copy();target=staged.copy();target[2]=.797
    poses[0,:2]=staged[:2]+[-.0055634,.0070885]
    return g,poses,staged,target


def test_actual_residual_correction_preserves_acceptance_and_z(scene7):
    g,poses,staged,target=data(scene7);before=poses.copy();original=target.copy();goal=staged.copy()
    result,info=alignment_xy_target(g,poses,0,staged,target,0.,alignment_completed=True)
    np.testing.assert_allclose(result[:2],staged[:2]+[.0055634,-.0070885])
    assert info['applied'] and result[2]==target[2] and info['blockers']==[]
    np.testing.assert_array_equal(poses,before);np.testing.assert_array_equal(target,original)
    np.testing.assert_array_equal(staged,goal);np.testing.assert_array_equal(info['acceptance_staged'],goal)
    result[:]=0
    np.testing.assert_array_equal(target,original)


def test_vector_norm_cap_preserves_direction(scene7):
    g,poses,staged,target=data(scene7);poses[0,:2]=staged[:2]+[-.06,.08]
    result,info=alignment_xy_target(g,poses,0,staged,target,0.,alignment_completed=True)
    np.testing.assert_allclose(info['bounded_offset_xy'],[.006,-.008])
    assert np.linalg.norm(result[:2]-target[:2])==pytest.approx(.01)


def test_combined_descent_has_no_independent_measurement(scene7):
    g,poses,staged,target=data(scene7)
    result,info=alignment_xy_target(g,poses,0,staged,target,0.,alignment_completed=False)
    np.testing.assert_array_equal(result,target)
    assert info['rejection']=='no_completed_independent_alignment' and not info['applied']


@pytest.mark.parametrize('reason',['footprint','blocker'])
def test_rejected_candidate_keeps_original_command(scene7,monkeypatch,reason):
    g,poses,staged,target=data(scene7)
    if reason=='footprint':poses[0,:2]=staged[:2]+[0.,-.009]
    else:monkeypatch.setattr(g,'blockers',lambda *a:[1])
    result,info=alignment_xy_target(g,poses,0,staged,target,0.,alignment_completed=True)
    np.testing.assert_array_equal(result,target)
    assert not info['applied'] and info['rejection']==('unsupported_command_footprint' if reason=='footprint' else 'command_release_blocked')


@pytest.mark.parametrize('enabled,preserve',[(False,False),(False,True),(True,False),(True,True)])
def test_place_integration_uses_command_only_and_original_verification_target(scene7,monkeypatch,enabled,preserve):
    g,poses,staged,target=data(scene7)
    poses[:,3:]=[1.,0.,0.,0.]
    c=Config(fixed_primitives=True,keep_place_contact=False,
        placement_alignment_xy_feedforward_enabled=enabled,placement_preserve_command_grasp_enabled=preserve)
    events=[];targets=[];calls=[]
    log=SimpleNamespace(event=lambda name,**kw:events.append((name,kw)))
    obs={'tray_pose':poses,'table_contact':np.ones(3),'gripper_contact_force':np.zeros((3,2)), 'min_z':np.full(3,.8)}
    r=SimpleNamespace(cfg=c,steps=0,d=SimpleNamespace(time=0.),trace=log,holding=0,
        grasp_rel={'left':np.eye(4),'right':np.eye(4)},retained_contact=None,
        sim=SimpleNamespace(target=np.zeros(16),state=lambda:np.zeros(16)),
        m=SimpleNamespace(body=lambda name:SimpleNamespace(id=0)),
        evidence=SimpleNamespace(local_vertices={0:np.array([[0.,0.,0.]])}),observation=lambda:obs)
    m=SimpleNamespace(r=r,c=c,g=g,log=log,transition=lambda *a,**kw:None,retreat=lambda:calls.append('retreat'))
    monkeypatch.setattr(primitives,'continue_loaded_reference',lambda r:calls.append('rebuild'))
    monkeypatch.setattr(primitives,'valid_command_grasp',lambda *a:True)
    monkeypatch.setattr(primitives,'checked_command_tcp',lambda *a:(None,{}))
    def points(runtime,position,yaw):
        targets.append(position.copy());return [np.zeros(16),np.zeros(16)]
    monkeypatch.setattr(primitives,'object_points',points)
    monkeypatch.setattr(primitives,'plan',lambda runtime,points,**kw:(points,2))
    def execute(runtime,planned,predicate=None):
        runtime.steps+=planned[1];runtime.d.time+=planned[1]/c.fps
        return 2 if predicate is None or predicate(obs) else 0
    monkeypatch.setattr(primitives,'execute',execute)
    monkeypatch.setattr(primitives,'settle',lambda *a,**kw:None)
    op=Operation(0,0,staged.copy(),0.);original=staged.copy()
    assert primitives.place(m,op,staged) is False
    expected=target.copy()
    expected[2]=g.tables[g.support_table(staged)]['dimensions_m'][2]-c.primitive_touchdown_preload_m
    if enabled:expected[:2]+=staged[:2]-poses[0,:2]
    np.testing.assert_allclose(targets[-1],expected)
    np.testing.assert_array_equal(staged,original);np.testing.assert_array_equal(op.destination,original)
    place_event=next(e for name,e in events if name=='primitive_start' and e['primitive']=='place')
    np.testing.assert_array_equal(place_event['parameters']['staged'],original)
    assert len([e for name,e in events if name=='placement_alignment_xy_feedforward'])==int(enabled)
    assert calls.count('rebuild')==2 and calls[-1]=='retreat'


def test_configuration_default_and_prerequisite():
    assert not Config().placement_alignment_xy_feedforward_enabled
    Config(fixed_primitives=True,placement_alignment_xy_feedforward_enabled=True).validate()
    with pytest.raises(ValueError,match='requires fixed_primitives'):
        Config(placement_alignment_xy_feedforward_enabled=True).validate()
    with pytest.raises(ValueError,match='must be boolean'):
        Config(placement_alignment_xy_feedforward_enabled=1).validate()


@pytest.mark.parametrize('offset',[[.000497,-.002194],[0.,.003]])
def test_support_risk_scope_keeps_already_supported_original_command(scene7,offset):
    g,poses,staged,target=data(scene7)
    poses[0,:2]=staged[:2]+offset
    result,info=alignment_xy_target(g,poses,0,staged,target,0.,
        alignment_completed=True,scope='support_risk')
    np.testing.assert_array_equal(result,target)
    assert not info['applied'] and info['projected_uncorrected_footprint_supported']
    assert info['rejection']=='uncorrected_footprint_supported'
    assert info['risk_footprint_margin_m']==0. and info['footprint_margin_m']==.004


def test_support_risk_scope_still_corrects_predicted_edge_overhang(scene7):
    g,poses,staged,target=data(scene7)
    result,info=alignment_xy_target(g,poses,0,staged,target,0.,
        alignment_completed=True,scope='support_risk')
    assert info['applied'] and not info['projected_uncorrected_footprint_supported']
    np.testing.assert_allclose(result[:2],staged[:2]+[.0055634,-.0070885])
    np.testing.assert_array_equal(info['acceptance_staged'],staged)


@pytest.mark.parametrize('scope',['all','support_risk'])
def test_feedforward_scope_configuration(scope):
    assert Config(placement_alignment_xy_feedforward_scope=scope).validate()
    assert Config().placement_alignment_xy_feedforward_scope=='all'


@pytest.mark.parametrize('scope',[None,True,'unsupported',''])
def test_invalid_feedforward_scope_rejected(scope):
    with pytest.raises(ValueError,match='scope'):
        Config(placement_alignment_xy_feedforward_scope=scope).validate()
