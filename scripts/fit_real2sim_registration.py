"""Offline initial held-tray pose fit to native collision geometry, no dynamics."""
import argparse
import copy
import json
from pathlib import Path
import sys
import numpy as np
from scipy.optimize import least_squares
from scipy.spatial.transform import Rotation
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from r1pro_teleop.real2sim import Trajectory,r1pro_map
from r1pro_teleop.real2sim.backends import MujocoBackend
from r1pro_teleop.real2sim.mujoco_registration import apply_initial_registration
from r1pro_teleop.real2sim.trajectory import write_json,sha256


def main():
    import mujoco
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('model','source-bundle','registration','output'):p.add_argument('--'+n,required=True)
    p.add_argument('--seed-z-shift',type=float,default=-.04)
    p.add_argument('--max-roll-deg',type=float,default=5.)
    p.add_argument('--max-pitch-deg',type=float,default=5.)
    a=p.parse_args();out=Path(a.output);out.mkdir(parents=True,exist_ok=False)
    seed=json.loads(Path(a.registration).read_text());t=Trajectory.load(a.source_bundle)
    if seed['source_parquet_sha256']!=t.provenance['parquet_sha256'] or t.provenance['prompt']!='Place the tray':
        raise ValueError('real2sim_registration_fit_requires_matching_place_source')
    b=MujocoBackend(a.model,r1pro_map());apply_initial_registration(b.model,seed);b.initialize(r1pro_map().encode(t.feedback[0]))
    m,d=b.model,b.data;address=m.jnt_qposadr[m.joint('tray_free').id]
    position=np.array(seed['tray_pose']['xyz']);position[2]+=a.seed_z_shift
    rotation=Rotation.from_quat(np.array(seed['tray_pose']['quaternion_wxyz'])[[1,2,3,0]])
    groups=[]
    for side in ('left','right'):
        for i in (1,2):
            bid=m.body(f'{side}_gripper_finger_link{i}').id
            groups.append([g for g in range(m.ngeom) if m.geom_bodyid[g]==bid and m.geom_contype[g]])
    palms=[m.geom(n).id for n in ('robot_geom_41','robot_geom_65')]
    rims=[m.geom(n).id for n in ('tray_contact_004','tray_contact_012')]
    bounds=np.array([.03,.03,.03,np.deg2rad(a.max_roll_deg),np.deg2rad(a.max_pitch_deg),np.deg2rad(10)])
    plan=dict(method='bounded_static_collision_pose_fit_no_physics_no_robot_state_changes',
              bounds_delta_xyz_rpy=bounds.tolist(),seed_z_shift_m=a.seed_z_shift,max_nfev=200,
              penetration_residual_weight=10.,
              model_sha256=sha256(a.model),source_registration_sha256=sha256(a.registration))
    write_json(out/'plan.json',plan)
    def distances(x):
        q=(Rotation.from_euler('xyz',x[3:])*rotation).as_quat()
        d.qpos[address:address+3]=position+x[:3];d.qpos[address+3:address+7]=q[[3,0,1,2]]
        mujoco.mj_forward(m,d)
        fingers=np.array([min(mujoco.mj_geomDistance(m,d,g,rims[i//2],1,None) for g in group) for i,group in enumerate(groups)])
        palm=np.array([mujoco.mj_geomDistance(m,d,g,rims[i],1,None) for i,g in enumerate(palms)])
        return fingers,palm
    def residual(x):
        f,palm=distances(x)
        return np.r_[np.maximum(f,0)+10*np.minimum(f,0),10*np.minimum(palm,0),.0002*x/bounds]
    initial=distances(np.zeros(6))
    fit=least_squares(residual,np.zeros(6),bounds=(-bounds,bounds),max_nfev=200,diff_step=1e-3,ftol=1e-10,xtol=1e-10,gtol=1e-10)
    final=distances(fit.x)
    report=dict(plan=plan,optimizer_converged=bool(fit.success),nfev=fit.nfev,delta=fit.x.tolist(),
        initial_finger_distances_m=initial[0].tolist(),initial_palm_distances_m=initial[1].tolist(),
        final_finger_distances_m=final[0].tolist(),final_palm_distances_m=final[1].tolist(),cost=float(fit.cost),
        task_success=None,note='local fit is not a proof of global feasibility or a dynamics result')
    result=copy.deepcopy(seed);result['tray_pose']=dict(xyz=d.qpos[address:address+3].tolist(),quaternion_wxyz=d.qpos[address+3:address+7].tolist())
    result['tray_in_base_xyz']=(d.qpos[address:address+3]-np.array(seed['base_pose']['xyz'])).tolist()
    result['tray_yaw_rad']=float(Rotation.from_quat(d.qpos[address+3:address+7][[1,2,3,0]]).as_euler('xyz')[2])
    result['refinement']=report;result['method']+='__native_finger_mesh_static_pose_fit'
    model_manifest=Path(a.model).with_suffix('.manifest.json')
    if model_manifest.exists():
        geometry=json.loads(model_manifest.read_text()).get('estimated_tray_geometry')
        if geometry:
            result['geometry_prior']['tray_size_xyz_m'][1]*=geometry['width_scale']
            result['geometry_prior']['source']='existing_asset_with_explicit_estimated_width_scale'
    write_json(out/'case_001.json',result);write_json(out/'summary.json',report);print(json.dumps(report,indent=2))


if __name__=='__main__':main()
