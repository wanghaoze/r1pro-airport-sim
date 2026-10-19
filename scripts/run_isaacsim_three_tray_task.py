"""Actual native three-tray expert episode; success comes from measured observer."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import traceback

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for data in iter(lambda:f.read(8*1024**2),b''):h.update(data)
    return h.hexdigest()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--scene-root',required=True,type=Path)
    p.add_argument('--output',required=True,type=Path)
    p.add_argument('--seed',type=int,default=42)
    p.add_argument('--episode-id',required=True)
    p.add_argument('--place-flush-reserve-m',type=float,default=.042)
    p.add_argument('--no-video-diagnostic',action='store_true',help='Controller regression only; never a training source or media-complete demo')
    args=p.parse_args();out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    def write(name,value):(out/name).write_text(json.dumps(value,indent=2))
    write('status.json',dict(stage='initializing_native_task',training_started=False,pid=os.getpid(),unix=time.time()))
    from isaacsim import SimulationApp
    app=SimulationApp(dict(headless=True,active_gpu=0,physics_gpu=0,multi_gpu=False,fast_shutdown=True))
    runtime=None;code=1;error=None;observer=None;final=None
    try:
        from r1pro_teleop.real2sim.isaac_three_tray_runtime import NativeRuntime
        from r1pro_teleop.real2sim.isaac_three_tray_teacher import NativeTeacher
        from r1pro_teleop.real2sim.isaac_three_tray_observer import ThreeTrayObserver
        runtime=NativeRuntime(args.scene_root,out,seed=args.seed,episode_id=args.episode_id,record=not args.no_video_diagnostic)
        observer=ThreeTrayObserver();teacher=NativeTeacher(runtime,observer,place_flush_reserve_m=args.place_flush_reserve_m)
        write('controller_profile.json',dict(place_flush_reserve_m=args.place_flush_reserve_m,
            task_conditions_changed=False,kinematics_used_for_teacher_only=True))
        write('status.json',dict(stage='full_native_task_running',execution_mode='controller_diagnostic' if args.no_video_diagnostic else 'expert_collection',
            model_executed=False,training_started=False,pid=os.getpid(),unix=time.time()))
        final=teacher.run();code=0
    except Exception as exc:
        error=dict(error_type=type(exc).__name__,message=str(exc),traceback=traceback.format_exc())
        write('failure.json',error)
    finally:
        exits={}
        if runtime is not None:
            try:
                final=runtime.observation();exits=runtime.close()
            except Exception as exc:
                code=1;write('recording_failure.json',dict(error=repr(exc),traceback=traceback.format_exc()))
            if any(row['returncode']!=0 for row in exits.values()):code=1
            if observer is not None:
                from r1pro_teleop.real2sim.three_tray_migration import PROFILE,RULE
                trace=out/'native_trace.npz'
                write('observer_events.json',observer.events)
                qualification=observer.qualification(args.episode_id,digest(trace),final) if trace.exists() else dict(complete_task_success=False)
                if code or not qualification['complete_task_success']:code=1
                qualification.update(controller_error=error,source='simulation/program_generated',
                    model_executed=False,teacher_used_for_collection_only=True)
                write('qualification.json',qualification)
                write('episode.json',dict(schema='airport_isaac_episode/1',engine='isaacsim',physics_backend='physx',
                    profile=PROFILE,task_rule_revision=RULE,source='simulation/program_generated',
                    execution_mode='controller_diagnostic' if args.no_video_diagnostic else 'expert_collection',free_run_diagnostic=False,episode_id=args.episode_id,
                    native_training_eligible=not args.no_video_diagnostic,
                    parent_scene_id=runtime.parent['scene_id'],split=runtime.parent['split'],
                    exit_receipt='process_exit.json',trace='native_trace.npz',qualification='qualification.json',
                    fps=20,physics_dt=.002,substeps_per_frame=25,actions=observer.spans,
                    payload_load_events=observer.loads,videos={name:dict(path=Path(row['path']).name,sha256=digest(row['path']))
                        for name,row in exits.items() if Path(row['path']).is_file()},
                    initial_pose_record='initialization.json',native_contacts='native_contacts.jsonl',
                    native_contacts_sha256=digest(out/'native_contacts.jsonl') if (out/'native_contacts.jsonl').exists() else None))
        write('status.json',dict(stage=('native_controller_diagnostic_passed' if args.no_video_diagnostic else 'native_task_success_pending_media_exit_closure') if code==0 else 'failed',
            task_success=code==0,training_started=False,model_executed=False,error=error,
            frames=runtime.frames if runtime is not None else 0,unix=time.time()))
        app.close(exit_code=code)


if __name__=='__main__':main()
