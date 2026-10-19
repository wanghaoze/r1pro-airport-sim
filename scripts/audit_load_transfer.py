"""Read-only command/measurement geometry around an existing push handoff."""
import argparse
import csv
import json
from pathlib import Path
import sys
import h5py
import numpy as np


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--release',type=Path,required=True)
    parser.add_argument('--collection',type=Path)
    parser.add_argument('--case',type=int,default=4)
    parser.add_argument('--push-index',type=int,default=0)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists(): raise ValueError('Output already exists')
    sys.path.insert(0,str(args.release))
    from r1pro_teleop.airport_fsm.runtime import Runtime
    from r1pro_teleop.airport_fsm.registry import config_for
    root=args.collection or args.release/'runs/regression'
    scene=next((root/'scenes').glob(f'airport_{args.case:04d}_*'))
    attempt=root/'attempts'/scene.name/'a000'
    events=[json.loads(line) for line in (attempt/'events.jsonl').read_text().splitlines()]
    event=[e for e in events if e['event']=='primitive_push_compliance_reference'][args.push_index]
    start=int(event['frame']); side=event['side']; index=0 if side=='left' else 1
    r=Runtime(json.loads((scene/'scene.json').read_text()),scene/'mobile.xml',config_for(root),render=False)
    rows=[]
    with h5py.File(attempt/'trace.h5') as h:
        tray=int(h['target_tray'][start])
        for frame in range(start-60,min(start+61,len(h['timestamp']))):
            r.mj.mj_setState(r.m,r.d,h['integration_state'][frame],r.integration_spec)
            r.mj.mj_forward(r.m,r.d)
            # Runtime's compliance reference fixes the chassis at its measured
            # pose. The servo base goal can differ and is not a TCP deflection.
            shadow=r._shadow(h['action'][frame])
            actual=r.d.site(side+'_tcp'); commanded=shadow.site(side+'_tcp')
            pose=h['tray_pose'][frame,tray]
            row=dict(frame=frame,seconds_after_push=(frame-start)/20,
                table_contact=int(h['table_contact'][frame,tray]),
                retained_force_n=float(h['gripper_contact_force'][frame,tray,index]),
                free_force_n=float(h['gripper_contact_force'][frame,tray,1-index]),
                retained_command_opening=float(h['action'][frame,7+8*index]),
                tray_x=float(pose[0]),tray_y=float(pose[1]),tray_z=float(pose[2]))
            for j,axis in enumerate('xyz'):
                row['tcp_'+axis]=float(actual.xpos[j]);row['command_tcp_'+axis]=float(commanded.xpos[j])
                row['deflection_'+axis]=float(commanded.xpos[j]-actual.xpos[j])
            rows.append(row)
    args.output.parent.mkdir(exist_ok=True,parents=True)
    with args.output.open('x',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    print(json.dumps({'start_frame':start,'side':side,'rows':len(rows),'at_start':rows[60],
        'arm_kp':r.m.actuator_gainprm[r.aids,0].tolist(),
        'arm_kv':(-r.m.actuator_biasprm[r.aids,2]).tolist()}))
    r.sim.close()


if __name__=='__main__':main()
