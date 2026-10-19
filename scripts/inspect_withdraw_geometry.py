"""Read-only final reserved footprint and gap audit."""
import json,pathlib,sys,numpy as np
root,source,original,candidate=map(pathlib.Path,sys.argv[1:]);sys.path.insert(0,str(root))
from r1pro_teleop.airport_fsm.geometry import Geometry,quat_yaw_tilt,slot_geometry_ready,rectangle,overlap
from r1pro_teleop.airport_fsm.registry import config_for
scene=next((source/'scenes').glob('airport_0310_*'));g=Geometry(json.loads((scene/'scene.json').read_text()));criteria=config_for(source).criteria
reports={}
for folder in (original,candidate):
 s=json.loads((folder/'summary.json').read_text());pose=np.array(s['final_all_poses']);mapping=s['slot_mapping'];tray=s['tray'];slot=mapping.index(tray);yaw,_=quat_yaw_tilt(pose[:,3:]);positions=[];angles=[];sizes=[];accepted=[]
 for sn,t in enumerate(mapping):
  ok=t==tray or g.at_slot(pose,t,sn,position_tol=criteria.position_m,angle_tol=np.deg2rad(criteria.yaw_deg),tilt_tol=np.deg2rad(criteria.tilt_deg));accepted.append(ok)
  positions.append(pose[t,:3] if ok else g.goals[sn]);angles.append(yaw[t] if ok else g.goal_yaw[sn]);sizes.append(g.sizes[t])
 local=g.to_belt(np.array(positions));angles=np.array(angles)-g.belt_yaw;sizes=np.array(sizes);ext=.5*(sizes[:,0]*abs(np.cos(angles))+sizes[:,1]*abs(np.sin(angles)));gaps=np.diff(local[:,0])-ext[:-1]-ext[1:]
 report=dict(slot=slot,accepted_neighbor_pose=accepted,reserved_gaps_m=gaps.tolist(),required_gap_m=[criteria.gap_min_m+.001,criteria.gap_max_m-.001],footprint_supported=g.footprint_supported(pose[tray,:3],yaw[tray],g.sizes[tray],margin=0.),at_slot=g.at_slot(pose,tray,slot,position_tol=criteria.position_m,angle_tol=np.deg2rad(criteria.yaw_deg),tilt_tol=np.deg2rad(criteria.tilt_deg)),future_overlap_slots=[sn for sn,t in enumerate(mapping) if sn!=slot and not accepted[sn] and overlap(g.footprint(pose,tray),rectangle(g.goals[sn],g.goal_yaw[sn],g.sizes[t]),clearance=.002)],slot_geometry_ready=slot_geometry_ready(g,pose,mapping,tray,slot,criteria))
 (folder/'reserved_geometry.json').write_text(json.dumps(report,indent=2));reports[folder.name]=report
print(json.dumps(reports))
