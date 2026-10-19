"""Measured hand withdrawal before the excluded passenger-loading transition."""
import numpy as np


def grippers_clear_of_tray(controller,obs,*,vertical_clearance_m=.03,front_clearance_m=.08):
    """Both real TCPs must clear the rim; no desired pose or joint command counts.

    Front clearance includes the open jaw's approximately 60 mm outer extent.
    This is an endpoint check, while the original substep collision guard stays
    responsible for the motion and the subsequent real environment settlement.
    """
    corners=np.asarray(obs.get('tray_corners'),dtype=float)
    normal=np.asarray(controller.p.front_normal,dtype=float)
    if corners.ndim!=2 or corners.shape[1]!=3 or len(corners)<4 or normal.shape!=(3,) or not np.isfinite(corners).all() or not np.isfinite(normal).all():return False
    top=float(np.max(corners[:,2]));front=float(np.max(corners@normal))
    for side in ('left','right'):
        position=np.asarray(controller.sim.tcp(side)[0],dtype=float)
        if position.shape!=(3,) or not np.isfinite(position).all():return False
        if not (position[2]>=top+vertical_clearance_m or float(position@normal)>=front+front_clearance_m):return False
    return True
