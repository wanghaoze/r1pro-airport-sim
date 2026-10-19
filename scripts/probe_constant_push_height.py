"""Private kinematic-only command-continuous retained-hand push candidate."""
import argparse
import json
from pathlib import Path
import sys
import h5py
import numpy as np
from scipy.spatial.transform import Rotation, Slerp


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--release',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists():raise ValueError('Output already exists')
    sys.path.insert(0,str(args.release))
    from r1pro_teleop.airport_fsm.runtime import Runtime, _homogeneous
    from r1pro_teleop.airport_fsm.registry import config_for
    from r1pro_teleop.airport_fsm.contracts import State, Fault, wrap_angle
    from r1pro_teleop.airport_fsm.geometry import quat_yaw_tilt, rz
    from r1pro_teleop.airport_fsm.primitives import plan
    root=args.release/'runs/regression'
    scene=next((root/'scenes').glob('airport_0004_*'));attempt=root/'attempts'/scene.name/'a000'
    events=[json.loads(line) for line in (attempt/'events.jsonl').read_text().splitlines()]
    selected=next(e for e in events if e['event']=='primitive_push_compliance_reference')
    frame=selected['frame'];side=selected['side'];free='left' if side=='right' else 'right'
    feed=next(e for e in events if e['frame']==frame and e['event']=='primitive_push_feedforward')
    primitive=next(e for e in events if e['frame']==frame and e['event']=='primitive_start')
    r=Runtime(json.loads((scene/'scene.json').read_text()),scene/'mobile.xml',config_for(root),render=False)
    with h5py.File(attempt/'trace.h5') as h:
        r.mj.mj_setState(r.m,r.d,h['integration_state'][frame],r.integration_spec)
        r.mj.mj_forward(r.m,r.d)
        r.sim.target=h['action'][frame].copy();r.sim.base_target=h['base_action'][frame].copy()
    r.allowed_tray=1;r.retained_contact=(1,side);r.fsm_state=State.ADJUST_TRAY;r.phase='adjust'
    body=r.d.body(r.g.ids[1]);actual_yaw,_=quat_yaw_tilt(r.observation()['tray_pose'][1,3:])
    command=r._shadow(r.sim.target).site(side+'_tcp')
    start_p=command.xpos.copy();start_R=command.xmat.reshape(3,3).copy()
    relation=np.linalg.inv(_homogeneous(body.xpos,body.xmat.reshape(3,3)))@_homogeneous(start_p,start_R)
    final_R=rz(float(wrap_angle(primitive['parameters']['yaw']-actual_yaw,r.g.period)))@body.xmat.reshape(3,3)
    target=_homogeneous(np.array(feed['command_position']),final_R)@relation
    free_p,free_R=r.sim.tcp(free);free_target=free_p.copy();free_target[2]+=.1
    rotation=Slerp([0,1],Rotation.from_matrix(np.stack([start_R,target[:3,:3]])))
    rows=[]
    for count in (4,6,8,12):
        previous=r.sim.target.copy();points=[previous.copy()]
        try:
            for u in np.linspace(0,1,count+1)[1:]:
                goals={side:(start_p+u*(target[:3,3]-start_p),rotation(u).as_matrix()),
                       free:(free_p+u*(free_target-free_p),free_R)}
                previous=r.solve_pair(goals,previous)
                previous[7 if side=='left' else 15]=r.cfg.gripper_close_m
                points.append(previous.copy())
            path,frames=plan(r,points,available=2.9,minimum=2.4,allow_shortcut=False)
            heights=[]
            for u in np.linspace(0,1,201):
                q=path.evaluate(u,frames/r.cfg.fps)[0]
                heights.append(float(r._shadow(q).site(side+'_tcp').xpos[2]))
            rows.append(dict(knots=count+1,planned=True,frames=frames,seconds=frames/r.cfg.fps,
                minimum_command_z=min(heights),maximum_command_z=max(heights),
                normal_deviation_m=max(abs(np.asarray(heights)-start_p[2])),
                controller=type(path).__name__))
        except Fault as exc:
            rows.append(dict(knots=count+1,planned=False,reason=exc.code,detail=exc.detail))
    result=dict(qualification='private_kinematic_only_no_physical_execution',start_frame=frame,
                start_command_position=start_p.tolist(),target_command_position=target[:3,3].tolist(),candidates=rows)
    args.output.write_text(json.dumps(result,indent=2));print(json.dumps(result))
    r.sim.close()


if __name__=='__main__':main()
