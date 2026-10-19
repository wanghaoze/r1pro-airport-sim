"""Explicit empty-place servo recipe; caller owns its declared physics profile.

No geometry, gains, motor force caps or penetration limits are modified here.
The demonstrated 40 mm inward/0.5 mm opening recipe settled under a separately
declared 10 mm diagnostic profile; it did not pass the old 3/5 mm limits.
"""
from dataclasses import dataclass,asdict
import math
import numpy as np
from scipy.spatial.transform import Rotation
from r1pro_teleop.airport_fsm.contracts import Fault
from .placement_clearance import grippers_clear_of_tray


@dataclass(frozen=True)
class PlacementRecipe:
    inboard_shift_m: float=.040
    flat_footprint_margin_m: float=.025
    release_clearance_m: float=.002
    lowering_step_m: float=.003
    opening_step_m: float=.0005
    settle_frames: int=20
    max_lower_iterations: int=160
    withdraw: bool=False

    def validate(self):
        numbers=[self.inboard_shift_m,self.flat_footprint_margin_m,self.release_clearance_m,
                 self.lowering_step_m,self.opening_step_m]
        if not np.isfinite(numbers).all() or not 0<=self.inboard_shift_m<=.04 or not 0<=self.flat_footprint_margin_m<=.05 or not 0<=self.release_clearance_m<=.02 or not 0<self.lowering_step_m<=.0075 or not 0<self.opening_step_m<=.002:
            raise ValueError('invalid_explicit_place_recipe_geometry_or_rate')
        if type(self.settle_frames) is not int or self.settle_frames<10 or type(self.max_lower_iterations) is not int or self.max_lower_iterations<1 or type(self.withdraw) is not bool:
            raise ValueError('invalid_explicit_place_recipe_budget')
        return self


def flat_footprint_inside(obs,profile,margin):
    R=np.asarray(obs['tray_rotation']);yaw=math.atan2(R[1,0],R[0,0])
    half=np.abs(Rotation.from_euler('z',yaw).as_matrix()[:2,:2])@(np.asarray(profile.tray_dimensions[:2])/2)
    return bool(np.all(np.abs(np.asarray(obs['tray_position'])[:2]-profile.table_center_xy)+half<=np.asarray(profile.table_half_sizes_xy)-margin))


def place_empty_recipe(controller,recipe=None):
    """Actual actuator-only empty placement. This function never reports task success."""
    recipe=(recipe or PlacementRecipe()).validate();c=controller
    if c.loaded or c.holding_sides!={'left','right'}:raise Fault('single_tray_empty_place_without_grasp')
    c.action='place_empty';start=c.frames;c.event('action_start')
    c.event('empty_place_recipe_parameters',**asdict(recipe),active_hard_penetration_limit_m=c.p.max_penetration_m,
            qualification='Explicit inward/slow-opening control; collision limits unchanged by recipe')
    if recipe.inboard_shift_m:
        c.phase='place_inward_recipe';position=c.observation()['tray_position'].copy()
        position-=recipe.inboard_shift_m*np.asarray(c.p.front_normal)
        c._held_move(position,tuple(sorted(c.holding_sides)),allow_one_hand_recovery=True)
    def ready(o):
        return c._place_release_ready(o) and float(o['tray_bottom_z'])-c.p.tabletop_z<=recipe.release_clearance_m
    c.phase='lower'
    for _ in range(recipe.max_lower_iterations):
        obs=c.observation()
        if ready(obs):break
        gap=float(obs['tray_bottom_z'])-c.p.tabletop_z
        if gap<=recipe.release_clearance_m:raise Fault('single_tray_recipe_release_footprint_unsafe')
        position=obs['tray_position'].copy()
        position[2]-=min(recipe.lowering_step_m,max(.0005,gap-recipe.release_clearance_m*.5))
        c._held_move(position,tuple(sorted(c.holding_sides)),finish_predicate=ready,allow_one_hand_recovery=True)
    else:raise Fault('single_tray_recipe_lowering_budget_exhausted')
    obs=c.observation()
    if not ready(obs) or not flat_footprint_inside(obs,c.p,recipe.flat_footprint_margin_m):
        raise Fault('single_tray_recipe_flat_footprint_margin_not_ready')
    c.event('place_release_geometry_verified',lowest_corner_gap_m=float(obs['tray_bottom_z'])-c.p.tabletop_z,
            allowed_release_clearance_m=recipe.release_clearance_m,flat_footprint_margin_m=recipe.flat_footprint_margin_m,
            tray_corners_xy=np.asarray(obs['tray_corners'])[:,:2].tolist(),table_contact_before_release=bool(obs['table_contacts']),
            qualification='Actual held geometry plus predicted horizontal footprint; real settlement still required')
    c.phase='open'
    opening_budget=math.ceil(c.p.open_command/recipe.opening_step_m)+4
    for _ in range(opening_budget):
        for col in (7,15):c.sim.target[col]+=np.clip(c.p.open_command-c.sim.target[col],-recipe.opening_step_m,recipe.opening_step_m)
        c.tick()
        if np.min(c.sim.target[[7,15]])>=c.p.open_command-1e-6:break
    else:raise Fault('single_tray_recipe_opening_budget_exhausted')
    c.holding_sides.clear()
    if recipe.withdraw:
        c.phase='withdraw';c.move({side:(c.sim.tcp(side)[0]+np.array([0,0,.10]),c.sim.tcp(side)[1]) for side in ('left','right')})
    c.phase='settle';obs=c.hold(recipe.settle_frames)
    if not c._on_table(obs) or max(obs['gripper_contact_force'].values())>c.p.contact_n or min(obs['gripper_openings'])<.06:
        raise Fault('single_tray_empty_place_not_released')
    if not grippers_clear_of_tray(c,obs):raise Fault('single_tray_place_hands_not_clear_for_load')
    c._finish_action(start)
    return obs
