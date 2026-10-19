"""Read the original planned push curve only; stop before any physical execution."""
import csv
from pathlib import Path
import numpy as np
from scipy.spatial.transform import Rotation,Slerp

def execute_force_feedback(machine,planned,operation,side,position,rotation,relation,free_goal):
 from r1pro_teleop.airport_fsm.runtime import _homogeneous
 from r1pro_teleop.airport_fsm.contracts import Fault,ARM_COLUMNS
 from diagnostic_contact_kinematics import point_velocity
 r=machine.r;path,frames=planned;duration=frames/r.cfg.fps
 begin=r._shadow(path.evaluate(0,duration)[0]).site(side+'_tcp').xmat.reshape(3,3).copy()
 goal=(_homogeneous(position,rotation)@relation)[:3,:3]
 rows=[]
 for t in np.arange(.002,duration+.0001,.002):
  q,v,a,j=path.evaluate(t/duration,duration);d=r._shadow(q);site=d.site(side+'_tcp');R=site.xmat.reshape(3,3).copy()
  d.qvel[:]=0.;d.qvel[r.dofs]=v[ARM_COLUMNS]
  linear,angular=point_velocity(r.mj,r.m,d,int(r.m.site_bodyid[site.id]),site.xpos)
  relative=R@begin.T;rot=Rotation.from_matrix(relative).as_rotvec()
  yaw=np.arctan2(relative[1,0],relative[0,0]);z=Rotation.from_euler('z',yaw).as_matrix()
  swing=Rotation.from_matrix(relative@z.T).as_rotvec()
  row=dict(time_s=float(t),swing_error_rad=float(np.linalg.norm(swing)),tcp_z=float(site.xpos[2]))
  for prefix,values in [('reference_omega',angular),('reference_v',linear),('reference_rotvec',rot),('reference_swing',swing)]:
   row.update({prefix+'_'+axis:float(value) for axis,value in zip('xyz',values)})
  rows.append(row)
 output=Path('/home/michelle/haoze/r1pro-airport-sim/diagnostictools/support_forces_20260929_v1/v11case5_original_reference.csv')
 with output.open('w',newline='') as f:
  w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
 raise Fault('diagnostic_reference_only',dict(frames=frames,duration_s=duration,goal_relative_rotvec=Rotation.from_matrix(goal@begin.T).as_rotvec().tolist(),maximum_swing_rad=max(x['swing_error_rad'] for x in rows),rows=len(rows)))
