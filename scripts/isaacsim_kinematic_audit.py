"""Compare measured native body-relative FK with the source joint convention.

MuJoCo is used only for offline mj_forward; no MuJoCo physics or corrective
commands are executed. The report never qualifies a grasp or a task.
"""
import numpy as np


def quaternion_matrix(quaternion):
    q=np.asarray(quaternion,float)
    if q.shape!=(4,) or not np.isfinite(q).all() or np.linalg.norm(q)<1e-9:
        raise ValueError('invalid_native_body_quaternion')
    w,x,y,z=q/np.linalg.norm(q)
    return np.array([[1-2*(y*y+z*z),2*(x*y-z*w),2*(x*z+y*w)],
        [2*(x*y+z*w),1-2*(x*x+z*z),2*(y*z-x*w)],
        [2*(x*z-y*w),2*(y*z+x*w),1-2*(x*x+y*y)]])


def compare(model, measured_joints, body_poses):
    import mujoco
    data=mujoco.MjData(model)
    data.qpos[:]=model.key_qpos[0] if model.nkey else model.qpos0
    for name,value in measured_joints.items():
        j=model.joint(name).id
        if int(model.jnt_type[j]) not in (int(mujoco.mjtJoint.mjJNT_HINGE),int(mujoco.mjtJoint.mjJNT_SLIDE)):
            raise ValueError('scalar_fk_joints_required')
        data.qpos[model.jnt_qposadr[j]]=value
    mujoco.mj_forward(model,data)
    source_base=data.body('base_link');sp=source_base.xpos.copy();sr=source_base.xmat.reshape(3,3).copy()
    np0,nq=body_poses['base_link'];nr=quaternion_matrix(nq)
    rows=[]
    for name,(position,quaternion) in body_poses.items():
        if name=='base_link':continue
        body=data.body(name)
        expected=sr.T@(body.xpos-sp);actual=nr.T@(np.asarray(position)-np0)
        expected_rotation=sr.T@body.xmat.reshape(3,3);actual_rotation=nr.T@quaternion_matrix(quaternion)
        angle=float(np.arccos(np.clip((np.trace(expected_rotation.T@actual_rotation)-1)/2,-1,1)))
        rows.append(dict(body=name,source_relative_position_m=expected.tolist(),native_relative_position_m=actual.tolist(),
            relative_position_error_m=float(np.linalg.norm(actual-expected)),relative_orientation_error_rad=angle))
    return dict(schema='airport_isaac_source_fk_audit/1',rows=rows,
        max_relative_position_error_m=max(r['relative_position_error_m'] for r in rows),
        source_computation='offline_mj_forward_only_no_mj_step',
        physical_execution='native_physx_only',live_control_corrected=False,task_success=None)
