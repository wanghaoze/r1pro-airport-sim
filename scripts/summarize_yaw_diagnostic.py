"""Read frozen yaw trace and already completed private candidate geometry."""
import json
from pathlib import Path
import sys
import h5py
import numpy as np

root=Path('/home/michelle/haoze/r1pro-airport-sim')
release=root/'releases/robust_v15b_20260929'
sys.path.insert(0,str(release))
from r1pro_teleop.airport_fsm.geometry import Geometry,quat_yaw_tilt
from r1pro_teleop.airport_fsm.registry import config_for
collection=release/'runs/ablation/command'
scene=next((collection/'scenes').glob('airport_0005_*'))
g=Geometry(json.loads((scene/'scene.json').read_text()))
c=config_for(collection).criteria
diagnostics=root/'diagnostictools/support_forces_20260929_v1'
result={}
with h5py.File(collection/'attempts'/scene.name/'a000/trace.h5') as h:
    rows=[]
    for seconds in [0,.5,1,1.5,2,2.5,2.85]:
        frame=2466+round(seconds*20)
        pose=h['tray_pose'][frame]
        yaw,tilt=quat_yaw_tilt(pose[:,3:])
        rows.append(dict(seconds=seconds,frame=frame,yaw_deg=float(np.degrees(yaw[1])),position=pose[1,:3].tolist()))
    result['original_yaw_progression']=rows
for name,folder in [(x,f'local_full_push_case5_yaw_{x}') for x in ['1.5','3','4.5']]+[('c2_feedback','local_full_push_case5_c2_feedback')]:
    summary=json.loads((diagnostics/folder/'summary.json').read_text())
    pose=np.array(summary['final_all_poses']);mapping=summary['slot_mapping'];tray=1
    yaw,tilt=quat_yaw_tilt(pose[:,3:]);positions=[];angles=[];sizes=[]
    for slot,t in enumerate(mapping):
        accepted=t==tray or g.at_slot(pose,t,slot,position_tol=c.position_m,angle_tol=np.deg2rad(c.yaw_deg),tilt_tol=np.deg2rad(c.tilt_deg))
        positions.append(pose[t,:3] if accepted else g.goals[slot]);angles.append(yaw[t] if accepted else g.goal_yaw[slot]);sizes.append(g.sizes[t])
    local=g.to_belt(np.array(positions));a=np.array(angles)-g.belt_yaw;sizes=np.array(sizes)
    ext=.5*(sizes[:,0]*abs(np.cos(a))+sizes[:,1]*abs(np.sin(a)))
    result[name]=dict(gaps_m=(np.diff(local[:,0])-ext[:-1]-ext[1:]).tolist(),yaw_deg=float(np.degrees(yaw[tray])),slot_geometry_ready=summary['final_slot_geometry_ready'],failure=summary['failure'])
print(json.dumps(result,indent=2))
