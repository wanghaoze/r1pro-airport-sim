"""Bounded, offline Place registration diagnosis; never changes source commands."""
import argparse
import copy
import json
from pathlib import Path
import sys
import numpy as np
from scipy.optimize import least_squares
from scipy.spatial.transform import Rotation
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from r1pro_teleop.real2sim import Trajectory, r1pro_map
from r1pro_teleop.real2sim.backends import MujocoBackend
from r1pro_teleop.real2sim.trajectory import write_json, sha256


def main():
    import mujoco
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run', required=True); p.add_argument('--output', required=True)
    a = p.parse_args(); run = Path(a.run); out = Path(a.output); out.mkdir(exist_ok=False, parents=True)
    source = Trajectory.load(run/'case_001/source')
    seed = json.loads((run/'case_001/registration.json').read_text())
    if source.provenance['parquet_sha256'] != seed['source_parquet_sha256']:
        raise ValueError('source_identity_mismatch')
    mapping = r1pro_map(); b = MujocoBackend(run/'case_001/registered_model.xml', mapping)
    b.initialize(mapping.encode(source.feedback[0])); m, d = b.model, b.data
    adr = m.jnt_qposadr[m.joint('tray_free').id]
    pos = np.array(seed['tray_pose']['xyz']); rot = Rotation.from_quat(np.array(seed['tray_pose']['quaternion_wxyz'])[[1,2,3,0]])
    groups = []; axes = []; rims = []
    for side in ('left', 'right'):
        for i in (1, 2):
            bid = m.body(f'{side}_gripper_finger_link{i}').id
            groups.append([g for g in range(m.ngeom) if m.geom_bodyid[g] == bid and m.geom_contype[g]])
            axes.append(d.xaxis[m.joint(f'{side}_gripper_finger_joint{i}').id].copy())
            rims.append(m.geom('tray_contact_004' if side == 'left' else 'tray_contact_012').id)
    palms = [m.geom(n).id for n in ('robot_geom_41', 'robot_geom_65')]
    bounds = np.r_[[.03]*3, np.deg2rad([5.,5.,10.])]
    write_json(out/'plan.json', dict(source_run=str(run), source_sha256=source.provenance['parquet_sha256'],
        model_sha256=sha256(run/'case_001/registered_model.xml'), seeds_z_m=[-.015,0.,.015],
        bounds_xyz_rpy=bounds.tolist(), max_nfev=100, max_physical_candidates=3,
        preserved=['commands','feedback_initialization','dimensions','friction','drives','acceptance'],
        scope='static_pose_search_then_original_command_physics_diagnostic_not_task_acceptance'))

    def distances(x):
        q=(Rotation.from_euler('xyz', x[3:])*rot).as_quat()
        d.qpos[adr:adr+3]=pos+x[:3];d.qpos[adr+3:adr+7]=q[[3,0,1,2]]
        mujoco.mj_forward(m,d)
        result=[]; penetration=[]
        for gs, axis, rim in zip(groups,axes,rims):
            choices=[]
            for g in gs:
                pts=np.zeros(6);dist=mujoco.mj_geomDistance(m,d,g,rim,1.,pts)
                normal=(pts[3:]-pts[:3])/dist if abs(dist)>1e-9 else np.zeros(3)
                alignment=float(-normal@axis)
                # Reward inward-facing contact, not arbitrary proximity to a top edge.
                score=abs(dist)+.025*max(0.,.7-alignment)
                choices.append((score,dist,alignment))
            result.append(min(choices))
            # The closest inward-facing part cannot hide intersection by a
            # different convex part of the same finger.
            penetration.append(min(c[1] for c in choices))
        penetration.extend(mujoco.mj_geomDistance(m,d,g,rims[i*2],1.,None) for i,g in enumerate(palms))
        return np.array(result), np.array(penetration)

    def residual(x):
        v, penetration=distances(x)
        return np.r_[np.maximum(v[:,1],0)+10*np.minimum(v[:,1],0),
                     .025*np.maximum(0.,.7-v[:,2]),20*np.minimum(penetration,0), .0002*x/bounds]

    rows=[]
    for i,z in enumerate((-.015,0.,.015)):
        initial=np.zeros(6);initial[2]=z
        fit=least_squares(residual,initial,bounds=(-bounds,bounds),max_nfev=100,
                          diff_step=1e-3,ftol=1e-8,xtol=1e-8,gtol=1e-8)
        v, penetration=distances(fit.x)
        reg=copy.deepcopy(seed);reg['tray_pose']=dict(xyz=d.qpos[adr:adr+3].tolist(),quaternion_wxyz=d.qpos[adr+3:adr+7].tolist())
        reg['method']+='__inward_contact_direction_fit';reg['tray_in_base_xyz']=(d.qpos[adr:adr+3]-seed['base_pose']['xyz']).tolist()
        reg['tray_yaw_rad']=float(Rotation.from_quat(d.qpos[adr+3:adr+7][[1,2,3,0]]).as_euler('xyz')[2])
        row=dict(candidate=i,converged=bool(fit.success),nfev=int(fit.nfev),delta=fit.x.tolist(),
                 distances_m=v[:,1].tolist(),inward_alignment=v[:,2].tolist(),
                 all_part_min_distances_m=penetration.tolist(),cost=float(fit.cost),task_success=None)
        reg['direction_fit']=row;write_json(out/f'candidate_{i}.json',reg);rows.append(row)
    write_json(out/'summary.json',rows);print(json.dumps(rows))


if __name__ == '__main__': main()
