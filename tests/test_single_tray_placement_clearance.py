from types import SimpleNamespace
import numpy as np
from r1pro_teleop.single_tray_lab.placement_clearance import grippers_clear_of_tray


def fixture():
    points={'left':np.array([.67,-.04,1.171]),'right':np.array([.67,-.44,1.171])}
    c=SimpleNamespace(p=SimpleNamespace(front_normal=(-1,0,0)),sim=SimpleNamespace(tcp=lambda s:(points[s],np.eye(3))))
    o=dict(tray_corners=np.array([[x,y,z] for x in (.563,.994) for y in (-.52,.04) for z in (.8,.905)]))
    return c,o,points


def test_actual_teacher_height_and_lower_no_withdraw_are_clear():
    c,o,p=fixture();assert grippers_clear_of_tray(c,o)
    for point in p.values():point[2]=1.074
    assert grippers_clear_of_tray(c,o)


def test_released_near_rim_is_not_ready_to_load():
    c,o,p=fixture();p['left'][2]=.925
    assert not grippers_clear_of_tray(c,o)
    p['left'][0]=.47
    assert grippers_clear_of_tray(c,o)
    p['right'][2]=.92
    assert not grippers_clear_of_tray(c,o)


def test_invalid_measured_tcp_or_tray_fails_closed():
    c,o,p=fixture();p['right'][0]=np.nan
    assert not grippers_clear_of_tray(c,o)
    c,o,p=fixture();o['tray_corners'][0,0]=np.inf
    assert not grippers_clear_of_tray(c,o)
