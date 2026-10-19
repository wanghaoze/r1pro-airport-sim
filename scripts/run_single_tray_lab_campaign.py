"""Durable physical candidate campaign; preserve every failure, never relabel old data."""
from pathlib import Path
import argparse, concurrent.futures, itertools, json, os, subprocess, sys, time

def write(path,value):
    tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(value,indent=2));tmp.replace(path)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--workers',type=int,default=4)
    parser.add_argument('--candidates',type=Path,help='Explicit new candidate JSON list; do not repeat an obsolete grid')
    args=parser.parse_args()
    if not 1<=args.workers<=16:parser.error('--workers must be within 1..16')
    configurations=json.loads(args.candidates.read_text()) if args.candidates else [
        dict(robot_x=x,tray_y=y,robot_y=robot_y) for x,y,robot_y in
        itertools.product([-.10,0.,.10,.20,.30,.40],[-.28,-.24,-.20],[0.,-.10,.10])]
    if not isinstance(configurations,list) or not configurations:parser.error('Nonempty candidate list required')
    import math
    for row in configurations:
        if not isinstance(row,dict) or not all(k in row for k in ('robot_x','robot_y','tray_y')):parser.error('Candidate requires robot_x/robot_y/tray_y')
        if not all(isinstance(row[k],(int,float)) and not isinstance(row[k],bool) and math.isfinite(row[k]) for k in ('robot_x','robot_y','tray_y')):parser.error('Finite candidate geometry required')
        if 'grasp_half_separation' in row and not 0<row['grasp_half_separation']<.26:parser.error('Grasp separation must stay on long rim')
    out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    root=Path(__file__).resolve().parents[1]
    status=dict(schema='single_tray_lab_campaign/1',stage='physical_candidate_generation',pid=os.getpid(),
        task_profile='single_tray_action3_v1',prompts=['Pick up the tray','Place the tray','Flush tray to the left'],
        selected=len(configurations),completed=0,successful_complete_tasks=0,results=[],
        training_started=False,dataset_ready=False,table_model_unchanged=True,source='simulation/program_generated')
    write(out/'status.json',status)
    def one(index,values):
        x,y,robot_y=(values[k] for k in ('robot_x','tray_y','robot_y'));folder=out/'cases'/f'case_{index:03d}';folder.parent.mkdir(exist_ok=True)
        split='val' if index%9==7 else 'test' if index%9==8 else 'train'
        command=[sys.executable,str(root/'scripts/run_single_tray_lab.py'),'--output',str(folder),
                 '--seed',str(202610050+index),'--robot-x',str(x),'--robot-y',str(robot_y),'--tray-y',str(y),'--split',split]
        if 'grasp_half_separation' in values:command.extend(['--grasp-half-separation',str(values['grasp_half_separation'])])
        for key in ('lift_clearance','gripper_kp','arm_kp','noslip_iterations','friction_impratio','lift_stop_margin','place_release_clearance','soft_payload_penetration','push_reference_lead','hard_penetration_limit','push_vertical_relief','push_table_contact_grace_frames','handover_left_tangent'):
            if key in values:command.extend(['--'+key.replace('_','-'),str(values[key])])
        if values.get('follow_tray_pose'):command.append('--follow-tray-pose')
        if values.get('push_command_reference'):command.append('--push-command-reference')
        if values.get('place_inboard_slow_recipe'):command.append('--place-inboard-slow-recipe')
        if values.get('push_right_outward_release'):command.append('--push-right-outward-release')
        if 'push_lead_frame' in values:command.extend(['--push-lead-frame',values['push_lead_frame']])
        for key in ('grasp_mode','rim_height','held_tracking_tolerance'):
            if key in values:command.extend(['--'+key.replace('_','-'),str(values[key])])
        env=dict(os.environ,CUDA_VISIBLE_DEVICES='',OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1')
        with (out/f'case_{index:03d}.log').open('x') as stream:
            process=subprocess.Popen(command,cwd=root,env=env,stdout=stream,stderr=subprocess.STDOUT)
            write(out/f'case_{index:03d}_process.json',dict(pid=process.pid,command=command,cwd=str(root)))
            code=process.wait()
        result_path=folder/'result.json'
        result=json.loads(result_path.read_text()) if result_path.exists() else {'task_completed':False,'failure_code':'candidate_process_failed_without_result'}
        return dict(index=index,robot_x=x,robot_y=robot_y,tray_y=y,split=split,returncode=code,
                    task_completed=result.get('task_completed') is True and result.get('physics_success') is True and code==0,
                    failure_code=result.get('failure_code'),frames=result.get('frames',0),result=str(result_path))
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        jobs=[pool.submit(one,i,v) for i,v in enumerate(configurations)]
        for job in concurrent.futures.as_completed(jobs):
            row=job.result();status['results'].append(row);status['completed']+=1
            status['successful_complete_tasks']+=int(row['task_completed']);write(out/'status.json',status)
    status['stage']='physical_candidates_complete_requires_native_replay_and_export_audit'
    write(out/'status.json',status)

if __name__=='__main__':main()
