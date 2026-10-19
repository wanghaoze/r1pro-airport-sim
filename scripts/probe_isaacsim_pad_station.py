"""Private geometry-only pad-normal station check; never steps physics."""
import argparse
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import numpy as np
import mujoco


def main():
    p=argparse.ArgumentParser();p.add_argument('--project',type=Path,required=True);p.add_argument('--code',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--aligned-legacy',action='store_true');p.add_argument('--case-config',type=Path);a=p.parse_args();sys.path.insert(0,str(a.code))
    from r1pro_teleop.real2sim.isaac_fast_pickplace import FastPickPlace
    from r1pro_teleop.real2sim.isaac_mobile import mobile_targets
    from r1pro_teleop.single_tray_3table.observer import table_front_region_violation
    s=a.project/'runs/isaacsim_three_tray_workflow_20261015_v1/scene_mechanics_v2'
    m=mujoco.MjModel.from_xml_path(str(s/'asset/import_only.xml'));d=mujoco.MjData(m);d.qpos[:]=m.key_qpos[0];mujoco.mj_forward(m,d)
    yaw=lambda q:float(np.arctan2(2*(q[0]*q[3]+q[1]*q[2]),1-2*(q[2]**2+q[3]**2)))
    origin=np.r_[d.body('base_link').xpos[:2],yaw(d.body('base_link').xquat)]
    source_base={n:float(d.qpos[m.jnt_qposadr[m.joint(n).id]]) for n in ('agent_base_x','agent_base_y','agent_base_yaw')}
    z=np.load(a.project/'runs/isaacsim_fast_stability_20261016_v4/case_000/native_trace.npz');state=z['state'][0].copy();pose=z['tray_pose'][0].copy()
    cfg=json.loads(a.case_config.read_text()) if a.case_config else {}
    if cfg:pose[0]=cfg['tray_pose']
    inv=json.loads((s/'preparation/legacy_inventory.json').read_text());meta=json.loads(next((s/'preparation/scenes/train').glob('*/scene.json')).read_text())
    row=next(r for r in inv['sources'] if r['parent_scene_id']==meta['parent_scene_id']);parent=json.loads(Path(row['legacy_source']['scene_json']).read_text())
    def sync():
        for n,v in mobile_targets(state).items():d.qpos[m.jnt_qposadr[m.joint(n).id]]=v
        for n,v in zip(('agent_base_x','agent_base_y','agent_base_yaw'),state[16:]):d.qpos[m.jnt_qposadr[m.joint(n).id]]=source_base[n]+v
        for i in range(3):
            adr=m.jnt_qposadr[m.body(f'tray_{i}').jntadr[0]];d.qpos[adr:adr+7]=pose[i]
        mujoco.mj_forward(m,d)
    sync();events=[];obs=dict(tray_pose=pose,robot_position=np.r_[origin[:2]+state[16:18],0.],robot_yaw=origin[2]+state[18])
    r=SimpleNamespace(mj=mujoco,model=m,shadow=d,command=state.copy(),parent=parent,size=np.tile([.56,.43,.105],(3,1)),base_origin=origin,source_base_q=source_base,
        sync_planner=sync,observation=lambda:obs,yaw=yaw,event=lambda name,**kw:events.append(dict(event=name,**kw)))
    t=FastPickPlace(r,SimpleNamespace(action=None));t.grasp_pitch_degrees=-30. if a.aligned_legacy else 0.;t.align_pad_normal=a.aligned_legacy;table=next(t for t in parent['tables'] if t['table_id']=='front_left')
    t.fixed_base_world=cfg.get('fixed_base_world');t.lift_height_m=cfg.get('lift_height_m',.18)
    if a.aligned_legacy:
        try:
            selected,_=t.choose_station(0,table);report=dict(scope='private_kinematic_only_not_physical_task_pass',passed=True,selected_base=selected.tolist(),align_pad_normal=True,grasp_pitch_degrees=-30.,events=events)
        except Exception as exc:report=dict(scope='private_kinematic_only_not_physical_task_pass',passed=False,error=repr(exc),events=events)
        a.output.write_text(json.dumps(report,indent=2));print(json.dumps({k:v for k,v in report.items() if k!='events'}));return
    goals=t.goals(0,0.);failed=[];selected=None
    for distance in (.45,.40,.35):
        for lateral in (0.,-.10,.10,-.20,.20):
            base=np.r_[pose[0,:2]-[distance,0]+[0,lateral],0.]
            if table_front_region_violation(table,np.r_[base[:2],0.]):continue
            try:
                for u in np.linspace(0,1,13):
                    t.solve({side:(v+[0,0,.12*u],R) for side,(v,R) in goals.items()},base_world=base)
                    t.solve({side:(v+[0,0,.18*u],R) for side,(v,R) in goals.items()},base_world=base)
                selected=base.tolist();break
            except Exception as exc:failed.append(dict(base=base.tolist(),error=repr(exc)))
        if selected:break
    report=dict(scope='private_kinematic_only_not_physical_task_pass',passed=selected is not None,selected_base=selected,grasp_pitch_degrees=0.,failed_candidates=failed,events=events)
    a.output.write_text(json.dumps(report,indent=2));print(json.dumps({k:v for k,v in report.items() if k not in ('events','failed_candidates')}))


if __name__=='__main__':main()
