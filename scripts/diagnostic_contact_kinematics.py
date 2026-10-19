"""Read-only Jacobian point velocities and contact wrenches; private diagnostics."""
import json
import numpy as np
from scipy.spatial.transform import Rotation


def point_velocity(mj,m,d,body,point):
    jp=np.zeros((3,m.nv));jr=np.zeros((3,m.nv))
    mj.mj_jac(m,d,jp,jr,np.asarray(point,float),int(body))
    return jp@d.qvel,jr@d.qvel


def measure(r,tray,side):
    mj,m,d=r.mj,r.m,r.d;bid=m.body(r.g.ids[tray]).id
    tables={m.body(name).id for name in ('front_left','front_right','rear')}
    fingers={i for i in range(m.nbody) if 'gripper_finger' in m.body(i).name}
    body=d.body(bid);com=body.xipos.copy();v,w=point_velocity(mj,m,d,bid,com)
    site=d.site(side+'_tcp');tcp=site.xpos.copy();R=site.xmat.reshape(3,3).copy()
    tv,tw=point_velocity(mj,m,d,int(m.site_bodyid[site.id]),tcp)
    shadow=r._shadow(r.sim.target);command=shadow.site(side+'_tcp')
    dp=command.xpos-tcp;dr=Rotation.from_matrix(command.xmat.reshape(3,3)@R.T).as_rotvec()
    result={}
    for prefix,value in [('tray_com_v',v),('tray_omega',w),('tcp_v',tv),('tcp_omega',tw),('command_minus_measured_tcp',dp),('command_minus_measured_rotvec',dr)]:
        for axis,x in zip('xyz',value):result[prefix+'_'+axis]=float(x)
    result['tray_pitch_rad']=float(Rotation.from_matrix(body.xmat.reshape(3,3)).as_euler('xyz')[1])
    vertices=r.evidence.local_vertices[bid]@body.xmat.reshape(3,3).T+body.xpos
    lowest=vertices[np.argmin(vertices[:,2])];lv,_=point_velocity(mj,m,d,bid,lowest)
    result['lowest_vertex_vz']=float(lv[2]);result['lowest_vertex_index']=int(np.argmin(vertices[:,2]))
    rows=[];table_moment=np.zeros(3);hand_moment=np.zeros(3)
    for i in range(d.ncon):
        c=d.contact[i];b1,b2=map(int,m.geom_bodyid[[c.geom1,c.geom2]])
        if b1==bid and b2 in tables|fingers:other=b2;sign=-1.
        elif b2==bid and b1 in tables|fingers:other=b1;sign=1.
        else:continue
        local=np.zeros(6);mj.mj_contactForce(m,d,i,local);force=sign*(np.asarray(c.frame).reshape(3,3).T@local[:3]);torque=sign*(np.asarray(c.frame).reshape(3,3).T@local[3:])
        trayv,_=point_velocity(mj,m,d,bid,c.pos);otherv,_=point_velocity(mj,m,d,other,c.pos)
        normal=d.body(other).xmat.reshape(3,3)[:,2] if other in tables else np.array([0.,0.,1.])
        moment=np.cross(c.pos-com,force)+torque
        if other in tables:table_moment+=moment
        else:hand_moment+=moment
        rows.append(dict(kind='table' if other in tables else 'hand',other_body=m.body(other).name,geom1=m.geom(int(c.geom1)).name,geom2=m.geom(int(c.geom2)).name,pos=c.pos.tolist(),distance_m=float(c.dist),local_normal_force_n=float(local[0]),signed_world_z_force_n=float(force[2]),relative_support_normal_velocity_m_s=float((trayv-otherv)@normal),moment_world_nm=moment.tolist()))
    for prefix,value in [('table_moment',table_moment),('hand_moment',hand_moment)]:
        for axis,x in zip('xyz',value):result[prefix+'_'+axis]=float(x)
    result['contacts_json']=json.dumps(rows,separators=(',',':'))
    return result
