"""Private static workspace evidence, never a task-success or live-control test."""
from pathlib import Path
import argparse, hashlib, itertools, json, sys, time
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def candidates(xs, tray_ys, offsets):
    values = list(itertools.product(xs, tray_ys, offsets))
    if not values or not np.isfinite(values).all():
        raise ValueError('finite nonempty workspace grid required')
    return [dict(robot_x=float(x), robot_y=float(y+d), tray_y=float(y)) for x,y,d in values]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def probe(scene, *, seeds=4, separation=.14):
    from dataclasses import replace
    from r1pro_teleop.single_tray_lab.control import SingleTrayController
    from r1pro_teleop.airport_arrange import solve
    from scipy.spatial.transform import Rotation
    c = SingleTrayController.from_scene(scene)
    c.p=replace(c.p,grasp_half_separation=separation).validate()
    try:
        initial = c.d.qpos.copy(); original_time=float(c.d.time)
        contacts = c._contacts()
        row = dict(initial_illegal_contacts=contacts['illegal_contacts'],
                   initial_max_penetration_m=contacts['max_penetration'], stages=[])
        goals=c._grasp_goals(); rng=np.random.default_rng(20261006)
        for stage,height in [('approach',c.p.approach_clearance),('contact',0.),('lift',c.p.lift_distance)]:
            start=c.d.qpos.copy(); results={}; solutions={}
            for side,offset in [('left',0),('right',8)]:
                qids=np.array([c.m.jnt_qposadr[j] for j in c.sim.arms[side]])
                ranges=c.m.jnt_range[c.sim.arms[side]]
                target=goals[side][0]+np.array([0,0,height]); rotation=goals[side][1]
                trials=[start[qids].copy()]+[rng.uniform(ranges[:,0]+.02,ranges[:,1]-.02) for _ in range(seeds-1)]
                best=None
                for seed in trials:
                    q,error=solve(c.sim,side,target,rotation,seed)
                    if best is None or error<best[1]:best=(q,error)
                q,error=best; solutions[side]=(qids,q)
                results[side]=dict(weighted_pose_error=float(error),joint_position=q.tolist(),target_position_m=target.tolist())
            endpoint=start.copy()
            for qids,q in solutions.values():endpoint[qids]=q
            path_bad=[]; max_pen=0.
            for alpha in np.linspace(0,1,21):
                c.d.qpos[:]=start+(endpoint-start)*alpha;c.mj.mj_forward(c.m,c.d)
                con=c._contacts();max_pen=max(max_pen,float(con['max_penetration']))
                if con['illegal_contacts'] or con['max_penetration']>c.p.max_penetration_m:
                    path_bad.append(dict(alpha=float(alpha),illegal=con['illegal_contacts'],max_penetration_m=float(con['max_penetration'])))
            for side in results:
                pos,R=c.sim.tcp(side);target=goals[side][0]+np.array([0,0,height])
                results[side].update(position_error_m=float(np.linalg.norm(pos-target)),
                    angle_error_rad=float(np.linalg.norm(Rotation.from_matrix(goals[side][1]@R.T).as_rotvec())))
            row['stages'].append(dict(stage=stage,sides=results,interpolated_collision_samples=path_bad,
                max_penetration_m=max_pen,endpoint_reachable=all(v['position_error_m']<.006 and v['angle_error_rad']<.1 for v in results.values())))
        row['static_candidate']=not row['initial_illegal_contacts'] and row['initial_max_penetration_m']<=c.p.max_penetration_m and all(s['endpoint_reachable'] and not s['interpolated_collision_samples'] for s in row['stages'])
        row.update(shadow_only=True,task_completed=False,physics_episode_executed=False,simulation_time_unchanged=float(c.d.time)==original_time)
        return row
    finally:c.close()


def main():
    from r1pro_teleop.single_tray_lab.scene import LabSceneConfig,generate_scene
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',required=True,type=Path)
    p.add_argument('--robot-xs',nargs='+',type=float,default=[.1,.15,.2,.25])
    p.add_argument('--tray-ys',nargs='+',type=float,default=[-.24])
    p.add_argument('--lateral-offsets',nargs='+',type=float,default=[-.08,0,.08]);p.add_argument('--seeds',type=int,default=4)
    p.add_argument('--separations',nargs='+',type=float,default=[.14,.18,.20,.22])
    args=p.parse_args();out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    report=dict(schema='single_tray_private_workspace/1',source='simulation/program_generated',
        script_sha256=sha(__file__),rows=[],task_success_claim=False)
    grid=list(itertools.product(candidates(args.robot_xs,args.tray_ys,args.lateral_offsets),args.separations))
    for index,(config,separation) in enumerate(grid):
        started=time.monotonic();scene=generate_scene(out/f'case_{index:03d}',LabSceneConfig(**config))
        row=dict(index=index,config=config,grasp_half_separation=separation,scene_xml_sha256=sha(scene['xml']),**probe(scene,seeds=args.seeds,separation=separation))
        row['elapsed_s']=time.monotonic()-started;report['rows'].append(row)
        tmp=out/'status.tmp';tmp.write_text(json.dumps(report,indent=2));tmp.replace(out/'status.json')
        print(json.dumps(dict(index=index,config=config,static_candidate=row['static_candidate'],elapsed_s=row['elapsed_s'])),flush=True)


if __name__=='__main__':main()
