"""Additional held-placement bases preserve the existing first eighteen."""
import numpy as np
import pytest

from r1pro_teleop.airport_fsm import placement_reachability as placement
from r1pro_teleop.airport_fsm.contracts import Config, Fault
from test_placement_reachability import _carried_runtime


def carried(*, enabled):
    runtime=_carried_runtime([.2,.3,.4],1.2)
    runtime.cfg=Config(acceptance_profile='completion_first',
        retained_support_integer_clock_enabled=True,
        completion_place_extended_base_search_enabled=enabled,
        placement_max_probes=36 if enabled else 18).validate()
    return runtime


def candidates(runtime):
    return list(placement.carried_placement_candidates(runtime,[.28,.38,0.],
        [.85,.38],goal_tray_yaw=0.))


def test_flag_defaults_off_and_original_eighteen_are_exact_first_eighteen():
    assert Config().completion_place_extended_base_search_enabled is False
    old=candidates(carried(enabled=False))
    new=candidates(carried(enabled=True))
    assert len(old)==18 and len(new)==36
    for actual,reference in zip(new[:18],old):
        np.testing.assert_array_equal(actual,reference)
    for actual,reference in zip(candidates(carried(enabled=True)),new):
        np.testing.assert_array_equal(actual,reference)


def test_new_geometry_uses_measured_heading_and_bounded_offsets():
    values=candidates(carried(enabled=True))
    heading=-.8
    assert len(values)==36
    for index,(yaw_offset,distance,sideways) in enumerate(
            (y,d,s) for y in (0.,.12,-.12) for d in (.47,.67) for s in (0.,.08,-.08)):
        yaw=placement.wrap_angle(heading+yaw_offset)
        forward=np.array([np.cos(yaw),np.sin(yaw)])
        lateral=np.array([-forward[1],forward[0]])
        np.testing.assert_allclose(values[18+index],
            np.r_[np.array([.85,.38])-distance*forward+sideways*lateral,yaw],atol=1e-12)
    keys={tuple(np.round(np.r_[v[:2],placement.wrap_angle(v[2])],8)) for v in values}
    assert len(keys)==36


def test_degenerate_original_families_deduplicate_and_keep_maximum():
    runtime=_carried_runtime([.2,.3,0.],0.)
    runtime.cfg=carried(enabled=True).cfg
    values=candidates(runtime)
    assert len(values)==27 # original two families coincide; eighteen new remain
    keys=[tuple(np.round(np.r_[v[:2],placement.wrap_angle(v[2])],8)) for v in values]
    assert len(keys)==len(set(keys))
    assert len(values)<=36


def test_screen_can_examine_36_only_under_declared_profile(monkeypatch):
    monkeypatch.setattr(placement,'loaded_planning_copy',lambda runtime:object())
    calls=[]
    def reject(probe,staged,final,yaw,base):
        calls.append(float(base[0]));raise Fault('ik_unreachable')
    monkeypatch.setattr(placement,'qualify_placement',reject)
    choices=[np.array([i,0.,0.]) for i in range(50)]
    runtime=carried(enabled=True)
    screen=placement.screen_placement(runtime,[0,0,0],[0,0,0],0,[0,0,0],
        candidates=choices,max_candidates=36)
    assert screen.examined==len(screen.rejected)==len(calls)==36
    assert all(item['reason']=='ik_unreachable' for item in screen.rejected)
    with pytest.raises(ValueError,match='36'):
        placement.screen_placement(runtime,[0,0,0],[0,0,0],0,[0,0,0],max_candidates=37)
    with pytest.raises(ValueError,match='18'):
        placement.screen_placement(carried(enabled=False),[0,0,0],[0,0,0],0,[0,0,0],
            max_candidates=36)
