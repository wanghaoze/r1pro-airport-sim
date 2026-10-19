"""Geometric self-view test; downward vision is not a backwards wrist flip."""
import numpy as np
import mujoco


def self_view_hits(model, data, origin, camera_rotation, geom_ids, half_angle_deg=5.):
    """Test center and eight perimeter rays against protected body geometry.

    Uses the actual camera optical axis (-Z in MuJoCo), not its horizontal sign.
    Does not mutate geom groups, contacts, forces, model, or simulation state.
    """
    if not geom_ids:
        raise ValueError('Self-view guard needs protected robot geometry')
    rot=np.asarray(camera_rotation).reshape(3,3)
    az=np.arange(8)*np.pi/4
    rays=np.vstack([-rot[:,2],-rot[:,2]+np.tan(np.deg2rad(half_angle_deg))*(np.cos(az)[:,None]*rot[:,0]+np.sin(az)[:,None]*rot[:,1])])
    rays/=np.linalg.norm(rays,axis=1)[:,None]
    ids=np.asarray(geom_ids,dtype=int)
    delta=data.geom_xpos[ids]-origin
    proj=delta@rays.T
    radius=model.geom_rbound[ids,None]
    perp2=np.maximum(0,np.sum(delta*delta,axis=1)[:,None]-proj*proj)
    possible=(proj+radius>=0)&(perp2<=radius*radius+1e-12)
    hits=[]
    for row,g in enumerate(ids):
        for j in np.flatnonzero(possible[row]):
            if model.geom_type[g]==mujoco.mjtGeom.mjGEOM_MESH:
                distance=mujoco.mj_rayMesh(model,data,int(g),origin,rays[j])
            else:
                distance=mujoco.mju_rayGeom(data.geom_xpos[g],data.geom_xmat[g],model.geom_size[g],origin,rays[j],int(model.geom_type[g]))
            if distance>=0:
                hits.append(int(g));break
    return hits
