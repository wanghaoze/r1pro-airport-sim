"""Conservative timing for the final, physically unloaded tuck only."""
import numpy as np
from .contracts import minimum_duration


def tuck_minimum_seconds(r, scale, floor=.3):
    if scale==1.:
        return floor
    if (r.holding is not None or r.retained_contact is not None or
            np.any(r.observation()['gripper_contact_force']>r.cfg.criteria.contact_n)):
        return floor
    seconds=minimum_duration(r.tucked-r.sim.state(),r.v*scale,r.a*scale,r.j*scale,floor)
    r.trace.event('unloaded_tuck_timing',reference_scale=scale,minimum_seconds=seconds,
                  original_minimum_seconds=floor,counted_in_episode=True,
                  qualification='final_unloaded_retreat_only_original_measured_limits_unchanged')
    return seconds
