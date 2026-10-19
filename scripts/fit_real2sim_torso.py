"""Finite offline free-space torso servo fit; never counted as task success."""
import argparse
import os
from pathlib import Path
import sys
import time
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from r1pro_teleop.real2sim import Trajectory, r1pro_map, replay
from r1pro_teleop.real2sim.model import build_model
from r1pro_teleop.real2sim.backends import MujocoBackend
from r1pro_teleop.real2sim.registration import estimate_registration
from r1pro_teleop.real2sim.mujoco_registration import apply_initial_registration
from r1pro_teleop.real2sim.trajectory import write_json


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('source-bundle','scene-xml','urdf','output'):p.add_argument('--'+n,required=True)
    a=p.parse_args();out=Path(a.output);out.mkdir(parents=True,exist_ok=False)
    candidates=[(250.,25.),(2500.,200.),(10000.,400.)]
    source=Trajectory.load(a.source_bundle)
    if source.provenance['prompt']!='Pick up the tray':raise ValueError('real2sim_fit_pick_pregrasp_required')
    grips=source.commands[:,[7,15]]
    closed=grips <= (grips.min(0)+grips.max(0))/2
    stop=int(np.flatnonzero(closed.any(1))[0])
    if stop<2:raise ValueError('real2sim_fit_pregrasp_missing')
    t=Trajectory(source.timestamps[:stop],source.feedback[:stop],source.commands[:stop],source.channels,source.provenance)
    write_json(out/'plan.json',dict(scope='free_space_servo_fit_not_task_episode',candidates=candidates,
        frames=stop,duration=float(t.seconds[-1]),pid=os.getpid(),cwd=os.getcwd(),started_unix=time.time(),
        criterion='lowest_torso_mse_against_original_pregrasp_feedback_without_nonfloor_contacts',
        source=t.provenance,base_world=[0,3,0],geometry_collision_and_inertia='unchanged',
        note='effective simulation gains only; not hardware identification or held-load fitting'))
    code=1
    try:
        results=[]
        for index,(kp,kv) in enumerate(candidates):
            model=out/f'candidate_{index}.xml';build_model(a.scene_xml,a.urdf,model,torso_kp=kp,torso_kv=kv)
            b=MujocoBackend(model,r1pro_map())
            r=dict(schema='real2sim_registration/1',units='metres_radians',quaternion_order='wxyz',frame='scene_world',
                base_pose=dict(xyz=[0,3,0],quaternion_wxyz=[1,0,0,0]),tray_pose=dict(xyz=[.85,0,.801],quaternion_wxyz=[1,0,0,0]))
            apply_initial_registration(b.model,r)
            contact_frames=[]
            def sample(i,stamp,positions):
                for c in b.data.contact:
                    if c.geom1 < 0 or c.geom2 < 0:continue
                    bodies=[b.model.body(b.model.geom_bodyid[g]).name for g in (c.geom1,c.geom2)]
                    if any(n.startswith(('left_arm','right_arm','left_gripper','right_gripper','torso')) for n in bodies):
                        contact_frames.append(i);break
            result=replay(t,r1pro_map(),b,on_sample=sample)
            np.savez_compressed(out/f'candidate_{index}.npz',actual=result['actual'],reference=result['feedback_at_actual_time'])
            row=dict(kp=kp,kv=kv,metrics=result['metrics'],unexpected_contact_frames=len(contact_frames),
                     steps=result['physics_steps'],online_state_resets=result['online_state_resets'])
            results.append(row);write_json(out/f'candidate_{index}.json',row)
        eligible=[r for r in results if r['unexpected_contact_frames']==0]
        if not eligible:raise RuntimeError('real2sim_fit_no_contact_free_candidate')
        selected=min(eligible,key=lambda r:r['metrics']['torso']['mse'])
        write_json(out/'summary.json',dict(candidates=results,selected=selected,
            scope='simulation_effective_torso_servo_pregrasp_fit_not_hardware_calibration',
            task_success=None,held_load_validation=False,finished_unix=time.time()))
        code=0
    finally:write_json(out/'exit.json',dict(exit_code=code,finished_unix=time.time()))


if __name__=='__main__':main()
