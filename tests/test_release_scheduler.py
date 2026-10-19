"""Release-space ordering, including the v10 scene7 measured pre-pick layout."""
import json
from pathlib import Path
import numpy as np
import pytest
from types import SimpleNamespace
from r1pro_teleop.airport_fsm.contracts import Config, Fault
from r1pro_teleop.airport_fsm.geometry import Geometry, Operation
from r1pro_teleop.airport_fsm.scheduler import release_location, release_prerequisite


@pytest.fixture
def scene7():
    scene_root = Path('resources/scenes/server_v7')
    if not scene_root.is_dir():
        scene_root = Path('resources/scenes/formal')
    source = next(scene_root.glob('**/airport_0007_*/scene.json'))
    spec = json.loads(source.read_text())
    # The frozen server source uses pi symmetry; local resources use 2*pi.
    # Explicitly reconstruct the server geometry rather than conflate versions.
    spec['yaw_period_rad'] = float(np.pi)
    g = Geometry(spec)
    pose = np.array([
        [.8497455505809416,.38167704018545834,.7999952170405822,-.0012306207293256745,8.549978243878514e-8,1.4841736262788055e-7,-.9999992427860095],
        [.8486930225723721,-.6612308804395255,.7999975222169077,.45042164276863983,7.696076028216149e-7,-1.061716248870504e-6,.8928159629643052],
        [.7978401472603588,-1.3930659419305575,.7999951506692211,.3947672941052313,1.1114591847841944e-6,5.24057867149002e-7,-.9187811401543481]])
    return g, pose, Operation(2, 1, g.goals[1].copy(), 0.)


def test_real_layout_moves_unverified_release_blocker_before_grasp(scene7):
    g, pose, requested = scene7; before = pose.copy(); cfg = Config()
    with pytest.raises(Fault, match='no_safe_release_clearance'):
        release_location(g, pose, requested, cfg)
    proposed, reason = release_prerequisite(g, pose, requested, [0,2,1], {0}, cfg)
    assert proposed.tray == 1 and proposed.temporary and proposed.slot == -1
    assert reason['selected_blocker'] == 1 and reason['protected_trays'] == [0]
    assert reason['examined'] <= 34
    assert g.support_table(proposed.destination) == 'rear'
    np.testing.assert_array_equal(pose, before)
    release_location(g, pose, proposed, cfg)
    predicted = pose.copy(); predicted[1,:3] = proposed.destination
    predicted[1,3:] = [np.cos(proposed.yaw/2),0,0,np.sin(proposed.yaw/2)]
    release_location(g, predicted, requested, cfg)


def test_verified_neighbours_are_not_rearranged(scene7):
    g, pose, requested = scene7
    with pytest.raises(Fault, match='no_safe_release_precondition') as failure:
        release_prerequisite(g, pose, requested, [0,2,1], {0,1}, Config())
    assert failure.value.detail['eligible_blockers'] == []
    assert not failure.value.recoverable


def test_no_buffer_does_not_create_an_unchecked_fallback(scene7, monkeypatch):
    g, pose, requested = scene7
    monkeypatch.setattr(g, 'footprint_supported', lambda *a, **kw: False)
    g.tables.pop('rear')
    with pytest.raises(Fault, match='no_safe_release_precondition'):
        release_prerequisite(g, pose, requested, [0,2,1], {0}, Config())


def test_feasible_operation_is_not_reordered(scene7):
    g, pose, _ = scene7
    op = Operation(1, -1, np.array([.85,-.8,.8]), 0., True)
    # Keep the other trays far away for a geometrically valid release.
    pose[0,1] = 2.; pose[2,1] = -3.
    proposed, reason = release_prerequisite(g, pose, op, [0,2,1], {0}, Config())
    assert proposed is op and reason is None


def test_rear_buffer_flows_through_place_and_temporary_verification(scene7, monkeypatch):
    from r1pro_teleop.airport_fsm.machine import Machine
    from r1pro_teleop.airport_fsm import primitives
    g, pose, requested = scene7
    cfg = Config(release_preflight_enabled=True, fixed_primitives=True)
    op, _ = release_prerequisite(g, pose, requested, [0,2,1], {0}, cfg)
    m = object.__new__(Machine); m.g=g; m.c=cfg
    m._poses=lambda:pose.copy()
    m.log=SimpleNamespace(event=lambda *a, **kw:None)
    m.transition=lambda *a, **kw:None
    navigated=[]; placed=[]
    observed={'tray_pose':pose.copy(), 'gripper_contact_force':np.full((3,2),10.)}
    m.r=SimpleNamespace(navigate=lambda base:navigated.append(base),
        observation=lambda:observed, remember_grasp=lambda tray:None,
        sim=SimpleNamespace(base_state=lambda:np.zeros(3)))
    monkeypatch.setattr(primitives,'place',lambda machine,operation,staged:placed.append((operation,staged)))
    m.carry_place(op)
    assert placed[0][0] is op and g.support_table(placed[0][1]) == 'rear'
    # Rear is approached from the aisle, facing the opposite table normal.
    assert abs(abs(navigated[0][2])-np.pi) < 1e-8
    observed['tray_pose'][op.tray,:3]=op.destination
    observed['tray_pose'][op.tray,3:]=[1,0,0,0]
    observed['gripper_contact_force'][:]=0
    observed['table_contact']=np.ones(3)
    def wait(seconds,predicate,stable):
        predicate(observed) # first sample establishes speed history
        return predicate(observed)
    m.r.wait=wait
    assert m.verify_operation(op)


def test_airborne_recovery_commands_existing_table_touchdown_not_hover():
    from r1pro_teleop.airport_fsm.machine import Machine
    m=object.__new__(Machine);m.c=Config();m.transition=lambda *a,**kw:None
    m.log=SimpleNamespace(event=lambda *a,**kw:None);m.retreat=lambda:None
    m.g=SimpleNamespace(ids=['tray_0'], tables={'rear':{'dimensions_m':[1.2,.6,.8]}},
        support_table=lambda p:'rear',blockers=lambda *a:[])
    observed={'tray_pose':np.array([[0.,0.,1.,1.,0.,0.,0.]]),
        'table_contact':np.array([0]),'support_contact':np.array([0]),
        'gripper_contact_force':np.array([[10.,10.]])}
    commands=[]
    def motion(position,**kw):
        commands.append(position.copy())
        observed['table_contact'][:]=1;observed['support_contact'][:]=1
    m.r=SimpleNamespace(allowed_tray=0,holding=0,observation=lambda:observed,
        m=SimpleNamespace(body=lambda name:SimpleNamespace(id=0)),
        d=SimpleNamespace(body=lambda index:SimpleNamespace(xmat=np.eye(3).ravel())),
        evidence=SimpleNamespace(local_vertices={0:np.array([[0.,0.,-.01],[0.,0.,.1]])}),
        object_motion=motion,wait=lambda duration,predicate,stable:predicate(observed),
        sim=SimpleNamespace(target=np.zeros(16)),joints=lambda *a,**kw:None)
    m.recover(Fault('planning_failure',recoverable=True))
    assert commands[0][2] == pytest.approx(.8+.01-m.c.primitive_touchdown_preload_m)
    assert m.recovery_used
