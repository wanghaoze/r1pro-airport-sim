"""python -m r1pro_teleop.airport_fsm --help"""
from __future__ import annotations
from pathlib import Path
from contextlib import contextmanager
import argparse
import json
import os
import sys
from .contracts import Config, Fault, atomic_json


@contextmanager
def collection_lock(root):
    """OS-released advisory lock; no stale-PID lock deletion race."""
    root=Path(root).resolve();root.parent.mkdir(parents=True,exist_ok=True)
    path=root.parent/('.'+root.name+'.airport_fsm.lock')
    stream=open(path,'a+',encoding='utf-8')
    try:
        if os.name=='posix':
            import fcntl
            try:fcntl.flock(stream.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError as exc:raise Fault('collection_already_in_use',str(root)) from exc
        else:
            raise Fault('batch_lock_requires_posix','Run the batch collector in the Linux Conda server environment')
        stream.seek(0);stream.truncate();stream.write(json.dumps({'pid':os.getpid(),'root':str(root)}));stream.flush()
        yield
    finally:
        stream.close()


def positive(text):
    n=int(text)
    if n<1:raise argparse.ArgumentTypeError('Must be positive')
    return n


def parser():
    p=argparse.ArgumentParser(description='Simulation-only, bounded airport tray FSM and LeRobot collector')
    sub=p.add_subparsers(dest='command',required=True)
    q=sub.add_parser('prepare',help='Register ALL existing manifest scenes; no motion')
    q.add_argument('--manifest',type=Path,required=True);q.add_argument('--output',type=Path,required=True)
    q.add_argument('--config',type=Path);q.add_argument('--half-turn-equivalent',action='store_true',help='Explicit unmarked-rectangle pi symmetry, not a silent criterion change')
    q=sub.add_parser('preflight',help='Check selected mobile scenes; default all registered scenes')
    q.add_argument('--root',type=Path,required=True);q.add_argument('--workers',type=positive,default=4)
    q.add_argument('--scene-ids',nargs='+')
    q=sub.add_parser('generate',help='Bounded retries; resume without overwriting previous attempts')
    q.add_argument('--root',type=Path,required=True);q.add_argument('--workers',type=positive,default=4)
    q.add_argument('--limit',type=positive);q.add_argument('--scene-ids',nargs='+')
    q=sub.add_parser('export',help='Native deterministic replay and official LeRobot shards')
    q.add_argument('--root',type=Path,required=True);q.add_argument('--shard-size',type=positive,default=8)
    q.add_argument('--action-layout',choices=['legacy16','mobile19'],default='mobile19')
    q.add_argument('--repo-prefix',default='local/r1pro-airport')
    q=sub.add_parser('report',help='Coverage accounting; nonzero exit for missing successful scenes')
    q.add_argument('--root',type=Path,required=True);q.add_argument('--require-all-exported',action='store_true')
    q.add_argument('--require-all-physics',action='store_true');q.add_argument('--require-all-attempted',action='store_true')
    q=sub.add_parser('render-diagnostic',help='Original-size three-camera failed-attempt replay')
    q.add_argument('--root',type=Path,required=True);q.add_argument('--scene-id',required=True);q.add_argument('--attempt',required=True)
    for name in ('attempt','preflight-one'):
        q=sub.add_parser(name,help=argparse.SUPPRESS)
        q.add_argument('--root',type=Path,required=True);q.add_argument('--scene-id',required=True)
        if name=='attempt':q.add_argument('--attempt',type=int,required=True)
    return p


def main(argv=None):
    a=parser().parse_args(argv)
    from .registry import prepare,config_for,scene_rows,materialize_scene,coverage
    from .batch import preflight,generate,preflight_one,stop_children
    try:
        if a.command in ('attempt','preflight-one'):
            rows={r['scene_id']:r for r in scene_rows(a.root)}
            if a.scene_id not in rows:raise Fault('unregistered_scene_requested',a.scene_id)
            if a.command=='preflight-one':
                result=preflight_one(a.root,rows[a.scene_id]);return 0 if result['valid'] else 1
            cfg=config_for(a.root)
            if not 0<=a.attempt<cfg.max_attempts_per_scene:raise Fault('attempt_index_out_of_budget')
            spec,xml=materialize_scene(a.root,rows[a.scene_id])
            from .machine import run_attempt
            result=run_attempt(spec,xml,cfg,Path(a.root)/'attempts'/a.scene_id/f'a{a.attempt:03d}',a.attempt)
            print(json.dumps({k:result.get(k) for k in ('scene_id','attempt','physics_success','failure_code','frames')}),flush=True)
            return 0 if result['physics_success'] else 1
        root=a.output if a.command=='prepare' else a.root
        with collection_lock(root):
            if a.command=='prepare':result=prepare(a.manifest,a.output,Config.load(a.config),half_turn_equivalent=a.half_turn_equivalent)
            elif a.command=='preflight':result=preflight(a.root,a.workers,a.scene_ids)
            elif a.command=='generate':result=generate(a.root,a.workers,a.limit,a.scene_ids)
            elif a.command=='export':
                from .exporter import export_collection
                result=export_collection(a.root,shard_size=a.shard_size,layout=a.action_layout,repo_prefix=a.repo_prefix)
            elif a.command=='render-diagnostic':
                if a.scene_id not in {r['scene_id'] for r in scene_rows(a.root)} or not (a.attempt.startswith('a') and a.attempt[1:].isdigit()):raise Fault('invalid_diagnostic_attempt')
                from .exporter import diagnostic_video
                diagnostic_video(a.root,a.scene_id,a.attempt);return 0
            else:
                from .exporter import aggregate_views,verify_catalog
                aggregate_views(a.root)
                if a.require_all_exported:verify_catalog(a.root)
                result=coverage(a.root)
            summary={k:v for k,v in result.items() if k not in ('scenes','sources','config','strata','episode_quality')}
            print(json.dumps(summary,indent=2,ensure_ascii=False,default=str),flush=True)
            if a.command=='report':
                required=[(a.require_all_exported,'all_scenes_have_validated_lerobot'),(a.require_all_physics,'all_scenes_have_clean_physics_success'),(a.require_all_attempted,'all_scenes_attempted_or_rejected')]
                return 2 if any(flag and not result.get(key,False) for flag,key in required) else 0
            if a.command=='export':return 2 if result.get('export_failures_this_run') else 0
            # generate processes every selected scene even when some fail. Strict
            # success is intentionally a separate report gate, not a loop abort.
            return 0
    except KeyboardInterrupt:
        stop_children();print('Interrupted; completed and partial evidence retained.',file=sys.stderr);return 130
    except Exception as exc:
        stop_children();print(json.dumps({'error':str(exc),'code':exc.code if isinstance(exc,Fault) else type(exc).__name__},ensure_ascii=False),file=sys.stderr);return 1


if __name__=='__main__':raise SystemExit(main())
