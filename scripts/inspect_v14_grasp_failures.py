"""Small read-only snapshots of the alternate-rim ablation failures."""
from pathlib import Path
import argparse
import json
import h5py
import numpy as np
from scipy.spatial.transform import Rotation

parser=argparse.ArgumentParser()
parser.add_argument('--root',type=Path,required=True)
parser.add_argument('--output',type=Path,required=True)
args=parser.parse_args()
if args.output.exists():raise ValueError('Output exists')
rows=[]
for case in (6,7):
    attempt=next((args.root/'attempts').glob(f'airport_{case:04d}_*/a000'))
    events=[json.loads(line) for line in (attempt/'events.jsonl').read_text().splitlines()]
    op=[e for e in events if e['event']=='operation_selected'][-1]
    candidate=[e for e in events if e['event']=='affordance_candidate'][-1]
    lift=next(e for e in events if e['event']=='primitive_start' and e['primitive']=='lift' and e['frame']>=op['frame'])
    tray=op['operation']['tray']
    with h5py.File(attempt/'trace.h5') as h:
        frames=sorted(set([lift['frame'],len(h['timestamp'])-1]+list(range(max(0,len(h['timestamp'])-5),len(h['timestamp'])))))
        snapshots=[]
        for frame in frames:
            pose=h['tray_pose'][frame,tray];angles=Rotation.from_quat(np.r_[pose[4:],pose[3]]).as_euler('xyz',degrees=True)
            snapshots.append(dict(frame=frame,pose=pose.tolist(),rollpitchyaw_deg=angles.tolist(),
                base_state=h['base_state'][frame].tolist(),
                min_z=float(h['min_z'][frame,tray]),
                lift_clearance=float(h['min_z'][frame,tray]-h['min_z'][lift['frame'],tray]),
                gripper_force=h['gripper_contact_force'][frame,tray].tolist()))
    rows.append(dict(case=case,operation=op,candidate=candidate,snapshots=snapshots))
args.output.write_text(json.dumps(rows,indent=2));print(json.dumps(rows))
