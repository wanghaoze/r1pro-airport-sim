from types import SimpleNamespace
import numpy as np
import pytest
from r1pro_teleop.single_tray_lab.control import ControlProfile
from r1pro_teleop.single_tray_lab.placement_recipe import PlacementRecipe,flat_footprint_inside,place_empty_recipe


@pytest.mark.parametrize('kwargs',[{'release_clearance_m':.021},{'opening_step_m':0},{'inboard_shift_m':.041},{'settle_frames':True}])
def test_invalid_recipe_fails_closed(kwargs):
    with pytest.raises(ValueError):PlacementRecipe(**kwargs).validate()


def test_future_horizontal_footprint_requires_25mm_margin():
    p=ControlProfile();o=dict(tray_rotation=np.array([[0,-1,0],[1,0,0],[0,0,1]]),tray_position=np.array([.808,-.24,.9]))
    assert flat_footprint_inside(o,p,.025)
    o['tray_position'][0]=.778
    assert not flat_footprint_inside(o,p,.025)


def test_recipe_does_not_change_guard_limit_or_accept_missing_table_support():
    p=ControlProfile();o=dict(tray_position=np.array([.82,-.24,.8]),tray_rotation=np.array([[0,-1,0],[1,0,0],[0,0,1]]),tray_bottom_z=.8,
        tray_corners=np.array([[.6,-.52,.8],[1.04,.04,.9]]),table_contacts=4,gripper_contact_force={'left':0.,'right':0.},gripper_openings=np.array([.1,.1]))
    c=SimpleNamespace(loaded=False,holding_sides={'left','right'},p=p,frames=0,event=lambda *a,**k:None,observation=lambda:o,
        _place_release_ready=lambda o:True,_on_table=lambda o:False,sim=SimpleNamespace(target=np.zeros(16)),_finish_action=lambda start:pytest.fail('Missing support accepted'))
    c._held_move=lambda *a,**k:None
    def tick():c.frames+=1
    c.tick=tick;c.hold=lambda n:o
    with pytest.raises(Exception,match='empty_place_not_released'):place_empty_recipe(c,PlacementRecipe(withdraw=False))
    assert c.p.max_penetration_m==.003
    assert c.frames==200
