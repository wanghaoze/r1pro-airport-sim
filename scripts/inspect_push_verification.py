"""Read-only release/settling metrics for a frozen final push failure."""
import argparse
import json
from pathlib import Path
import sys
import h5py
import numpy as np

p=argparse.ArgumentParser();p.add_argument('--controller',type=Path,required=True)
p.add_argument('--root',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
args=p.parse_args();sys.path.insert(0,str(args.controller))
from r1pro_teleop.airport_fsm.registry import config_for
from r1pro_teleop.airport_fsm.geometry import Geometry,quat_yaw_tilt,slot_geometry_ready,rectangle,overlap
from r1pro_teleop.airport_fsm.contracts import wrap_angle
if args.output.exists():raise ValueError('Output exists')
scene=next((args.root/'scenes').glob('airport_0005_*'));attempt=args.root/'attempts'/scene.name/'a000'
events=[json.loads(x) for x in (attempt/'events.jsonl').read_text().splitlines()]
operations=[x for x in events if x['event']=='operation_selected'];op=operations[-1]['operation'];tray=op['tray'];slot=op['slot']
g=Geometry(json.loads((scene/'scene.json').read_text()));cfg=config_for(args.root);c=cfg.criteria
with h5py.File(attempt/'trace.h5') as h:
    mapping=g.best_mapping(h['tray_pose'][operations[0]['frame']])
    selected=[x for x in events if x['frame']>=operations[-1]['frame'] and x['event'] in ('primitive_start','primitive_complete','state_transition')]
    frames=sorted({x['frame'] for x in selected if x['frame']<len(h['timestamp'])}|{len(h['timestamp'])-1})
    rows=[]
    for frame in frames:
        pose=h['tray_pose'][frame];yaw,tilt=quat_yaw_tilt(pose[:,3:]);positions=[];angles=[];sizes=[]
        for s,t in enumerate(mapping):
            accepted=t==tray or g.at_slot(pose,t,s,position_tol=c.position_m,angle_tol=np.deg2rad(c.yaw_deg),tilt_tol=np.deg2rad(c.tilt_deg))
            positions.append(pose[t,:3] if accepted else g.goals[s]);angles.append(yaw[t] if accepted else g.goal_yaw[s]);sizes.append(g.sizes[t])
        local=g.to_belt(np.array(positions));a=np.array(angles)-g.belt_yaw;sizes=np.array(sizes)
        ext=.5*(sizes[:,0]*abs(np.cos(a))+sizes[:,1]*abs(np.sin(a)));gaps=np.diff(local[:,0])-ext[:-1]-ext[1:]
        blocked=[s for s,t in enumerate(mapping) if s!=slot and not g.at_slot(pose,t,s,position_tol=c.position_m,angle_tol=np.deg2rad(c.yaw_deg),tilt_tol=np.deg2rad(c.tilt_deg)) and overlap(g.footprint(pose,tray),rectangle(g.goals[s],g.goal_yaw[s],g.sizes[t]),clearance=.002)]
        rows.append(dict(frame=frame,time_s=frame/cfg.fps,phase=str(h['phase'][frame]),position=pose[tray,:3].tolist(),
            position_error_m=float(np.linalg.norm(pose[tray,:3]-op['destination'])),
            yaw_error_deg=float(np.degrees(wrap_angle(yaw[tray]-op['yaw'],g.period))),tilt_deg=float(np.degrees(tilt[tray])),
            speed_m_s=float(np.linalg.norm(pose[tray,:3]-h['tray_pose'][max(0,frame-1),tray,:3])*cfg.fps),
            table_contact=int(h['table_contact'][frame,tray]),gripper_force=h['gripper_contact_force'][frame,tray].tolist(),
            reserved_gaps_m=gaps.tolist(),footprint_supported=bool(g.footprint_supported(pose[tray,:3],yaw[tray],g.sizes[tray],margin=0.)),
            reserved_slots_blocked=blocked,slot_geometry_ready=bool(slot_geometry_ready(g,pose,mapping,tray,slot,c))))
result=dict(operation=op,mapping=list(mapping),criteria=cfg.dump()['criteria'],metrics=rows)
args.output.write_text(json.dumps(result,indent=2));print(json.dumps(result))
