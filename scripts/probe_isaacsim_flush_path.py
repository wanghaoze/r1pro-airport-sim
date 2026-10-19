"""Private kinematic regression at an actual failed native state; no physics."""
import argparse
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import numpy as np
import mujoco
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from r1pro_teleop.real2sim.isaac_mobile import mobile_targets
from r1pro_teleop.real2sim.isaac_three_tray_teacher import NativeTeacher
from r1pro_teleop.real2sim.isaac_three_tray_observer import ThreeTrayObserver


def main():
    p=argparse.ArgumentParser();p.add_argument('--scene-root',type=Path,required=True);p.add_argument('--case',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--frame',type=int,default=-1);p.add_argument('--shift-y',type=float,default=0.)
    p.add_argument('--tray',type=int,default=2)
    p.add_argument('--handover',action='store_true')
    p.add_argument('--mode',choices=['flush','place','departure','left_clearance','left_withdrawal'],default='flush');a=p.parse_args()
    m=mujoco.MjModel.from_xml_path(str(a.scene_root/'asset/import_only.xml'));d=mujoco.MjData(m)
    d.qpos[:]=m.key_qpos[0];mujoco.mj_forward(m,d)
    q=d.body('base_link').xquat
    origin=np.r_[d.body('base_link').xpos[:2],np.arctan2(2*(q[0]*q[3]+q[1]*q[2]),1-2*(q[2]**2+q[3]**2))]
    source_base={n:float(d.qpos[m.jnt_qposadr[m.joint(n).id]]) for n in ('agent_base_x','agent_base_y','agent_base_yaw')}
    trace=np.load(a.case/'native_trace.npz');state=trace['state'][a.frame];pose=trace['tray_pose'][a.frame].copy();pose[2,1]+=a.shift_y
    inv=json.loads((a.scene_root/'preparation/legacy_inventory.json').read_text());manifest=next((a.scene_root/'preparation/scenes/train').glob('*/scene.json'));meta=json.loads(manifest.read_text());row=next(r for r in inv['sources'] if r['parent_scene_id']==meta['parent_scene_id']);parent=json.loads(Path(row['legacy_source']['scene_json']).read_text())
    def sync():
        for n,v in mobile_targets(state).items():d.qpos[m.jnt_qposadr[m.joint(n).id]]=v
        for n,v in zip(('agent_base_x','agent_base_y','agent_base_yaw'),state[16:]):d.qpos[m.jnt_qposadr[m.joint(n).id]]=source_base[n]+v
        for i in range(3):
            joint=m.body(f'tray_{i}').jntadr[0];adr=m.jnt_qposadr[joint];d.qpos[adr:adr+7]=pose[i]
        mujoco.mj_forward(m,d)
    sync();events=[];selected=[]
    obs=dict(tray_pose=pose,robot_position=np.r_[origin[:2]+state[16:18],0.],robot_yaw=origin[2]+state[18])
    def yaw(q):return float(np.arctan2(2*(q[0]*q[3]+q[1]*q[2]),1-2*(q[2]**2+q[3]**2)))
    r=SimpleNamespace(mj=mujoco,model=m,shadow=d,command=trace['action'][a.frame-1 if a.frame>0 else -1],parent=parent,
        size=np.tile([.56,.43,.105],(3,1)),base_origin=origin,source_base_q=source_base,
        sync_planner=sync,observation=lambda:obs,yaw=yaw,event=lambda name,**kw:events.append(dict(event=name,**kw)))
    o=ThreeTrayObserver();o.action=dict(prompt='Flush tray to the left')
    teacher=NativeTeacher(r,o);teacher.active_tray=a.tray;r.context=next(t for t in parent['tables'] if t['table_id']=='front_left')
    teacher.navigate=lambda base:selected.append(base.tolist())
    if a.mode=='left_withdrawal':
        start,R=teacher.tcp('left')
        for height in np.linspace(.015,.12,8):
            target=teacher.solve({'left':(start+[0,0,height],R)})
            selected.append(dict(height=float(height),target=target.tolist()))
    elif a.mode=='left_clearance':
        goal=teacher.goals(a.tray,0.)['left'];target=teacher.solve({'left':goal})
        for width in (.1,.04):
            sync();candidate=target.copy();candidate[7]=width
            for name,value in mobile_targets(candidate).items():d.qpos[m.jnt_qposadr[m.joint(name).id]]=value
            mujoco.mj_forward(m,d);contacts=[]
            for contact in d.contact:
                bodies=[m.body(int(m.geom_bodyid[g])).name for g in (contact.geom1,contact.geom2)]
                if any(n.startswith('left_gripper') for n in bodies) and any(n.startswith('tray_') and n!=f'tray_{a.tray}' for n in bodies):
                    contacts.append(dict(bodies=bodies,distance_m=float(contact.dist)))
            selected.append(dict(opening_m=width,neighbor_contacts=contacts,goal=goal[0].tolist()))
    elif a.mode=='departure':
        starts={s:teacher.tcp(s) for s in ('left','right')}
        for height in np.linspace(.015,.12,8):
            target=teacher.solve({s:(p+np.array([0,0,height]),R) for s,(p,R) in starts.items()})
            selected.append(dict(height=float(height),target=target.tolist()))
    elif a.mode=='flush':
        teacher.flush_station(a.tray)
        if a.handover:
            base=np.asarray(selected[-1]);left=np.array([-np.sin(base[2]),np.cos(base[2]),0.])
            goals=teacher.goals(a.tray,0.)
            required=events[-1]['predicted_right_push_m'];shift=left*(required+.016)
            for t in np.linspace(0,1,8):teacher.solve({'right':(goals['right'][0]+t*shift,goals['right'][1])},base_world=base)
            both={s:(p+shift,R) for s,(p,R) in goals.items()};teacher.solve(both,base_world=base)
            for t in np.linspace(0,1,8):
                teacher.solve({'right':(both['right'][0]+t*np.array([0,-.035,.04]),both['right'][1]),
                    'left':both['left']},base_world=base)
                teacher.solve({'left':(both['left'][0]+t*.04*left,both['left'][1])},base_world=base)
            events.append(dict(event='private_full_handover_knots_solved',right_push_m=float(np.linalg.norm(shift)),left_push_m=.04,physical_task_pass=False))
    else:
        o.action['prompt']='Place the tray';goal=teacher.g.goals[0].copy();goal[1]-=teacher.place_flush_reserve_m;goal[2]=pose[2,2]
        base,_=teacher.choose_station(2,r.context,position=goal,target=True);selected.append(base.tolist())
    a.output.write_text(json.dumps(dict(scope='private_kinematic_only_not_physical_task_pass',selected=selected,events=events),indent=2))
    print(json.dumps(dict(selected=selected,scope='kinematic_only')))


if __name__=='__main__':main()
