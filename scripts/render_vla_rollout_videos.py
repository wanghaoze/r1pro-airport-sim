"""Native diagnostic heads from actual learned-controller traces; no training export.

The frozen Replay restores initial integration state once, then continuously
integrates original actuator controls. No per-frame state resets are allowed.
"""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import argparse
import hashlib
import json
import os
import subprocess
import sys
import numpy as np


def read(path):return json.loads(Path(path).read_text(encoding='utf-8'))


def digest(path):
    result=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):result.update(block)
    return result.hexdigest()


def render_attempt(attempt,source_collection,output,*,controller_root=None,replay_factory=None,video_checker=None,
                   camera_names=('head_left','head_right'),in_attempt_directory=False):
    attempt=Path(attempt).resolve();source_collection=Path(source_collection).resolve();output=Path(output).resolve()
    result=read(attempt/'result.json');run=attempt.parents[2]
    report=read(run/'rollout_report.json')
    sid=result['scene_id']
    if (result.get('motion_backend')!='pi05' or result.get('controller_source')!='vla_generated' or
            report.get('schema')!='airport_vla_rollout/1' or
            Path(report['source_collection']).resolve()!=source_collection or
            sid!=attempt.parent.name or attempt.parent.parent.name!='attempts' or
            result.get('checkpoint_id')!=report['checkpoint_metadata']['checkpoint_id']):
        raise ValueError('Actual learned rollout provenance mismatch')
    trace=attempt/'trace.h5'
    if not trace.is_file():raise ValueError('Actual learner trace is missing')
    scene_path=source_collection/'scenes'/sid/'scene.json';scene=read(scene_path)
    if scene.get('scene_id')!=sid or scene.get('split')!=result.get('split'):
        raise ValueError('Source scene identity mismatch')
    if (not camera_names or len(set(camera_names))!=len(camera_names) or
            any(name not in ('head_left','head_right','left_wrist','right_wrist') for name in camera_names)):
        raise ValueError('Unsupported native inspection cameras')
    directory=attempt if in_attempt_directory else output/run.name/sid/attempt.name
    if in_attempt_directory:
        if any((directory/name).exists() for name in ['manifest.json','failure.json']+[c+'.mp4' for c in camera_names]):
            raise FileExistsError('Native video evidence already exists; preserve its original files')
    else:directory.mkdir(parents=True,exist_ok=False)
    if replay_factory is None:
        if controller_root is None:raise ValueError('An explicit frozen controller checkout is required')
        sys.path.insert(0,str(Path(controller_root).resolve()))
        from r1pro_teleop.airport_fsm.exporter import Replay,video_metadata
        replay_factory=Replay;video_checker=video_metadata
    import av
    writers={};streams={}
    try:
        with replay_factory(source_collection,{'trace':str(trace),'scene_id':sid},diagnostic=True) as replay:
            metadata=json.loads(replay.f.attrs['metadata_json'])
            if (metadata.get('scene_id')!=sid or metadata.get('split')!=scene['split'] or
                    metadata.get('scene')!=scene or metadata.get('checkpoint_id')!=result['checkpoint_id']):
                raise ValueError('Trace and learner/source identities disagree')
            names=tuple(camera_names)
            replay.shapes={name:replay.shapes[name] for name in names}
            replay.camera_checks={name:replay.camera_checks[name] for name in names}
            runtime=replay.runtime;index=[0]
            original_apply=runtime.sim.apply_target
            def journal_apply():
                original_apply()
                # raw/1 stores ctrl BEFORE apply_target, so the next row's
                # ctrl is the actual command applied in the current interval.
                if index[0]+1>=replay.n:return
                recorded=np.asarray(replay.f['ctrl'][index[0]+1])
                if recorded.shape!=runtime.d.ctrl.shape or not np.isfinite(recorded).all():
                    raise ValueError('Invalid original actuator journal')
                if not np.array_equal(runtime.d.ctrl,recorded):
                    raise ValueError('Frozen action reconstruction differs from original ctrl journal')
                runtime.d.ctrl[:]=recorded
            runtime.sim.apply_target=journal_apply
            for name,(height,width,_) in replay.shapes.items():
                writer=av.open(str(directory/(name+'.mp4')),mode='w')
                stream=writer.add_stream('libx264',rate=20);stream.width=width;stream.height=height
                stream.pix_fmt='yuv420p';stream.options={'crf':'18','preset':'fast','threads':'1'}
                writers[name]=writer;streams[name]=stream
            count=0;max_qvel=0.;max_time=0.
            for i,images in replay:
                index[0]=i
                max_qvel=max(max_qvel,float(np.max(np.abs(runtime.d.qvel-replay.f['qvel'][i]))))
                max_time=max(max_time,abs(float(runtime.d.time)-float(replay.f['sim_time'][i])))
                for name in names:
                    frame=av.VideoFrame.from_ndarray(images[name],format='rgb24');frame.pts=i
                    for packet in streams[name].encode(frame):writers[name].mux(packet)
                count+=1
            if count!=replay.n:raise ValueError('Diagnostic replay frame count mismatch')
            terminal=json.loads(replay.f.attrs['terminal_snapshot_json'])
            terminal_qpos=float(np.max(np.abs(runtime.d.qpos-np.asarray(terminal['qpos']))))
            terminal_qvel=float(np.max(np.abs(runtime.d.qvel-np.asarray(terminal['qvel']))))
            terminal_time=abs(float(runtime.d.time)-float(terminal['time']))
            if (terminal_qpos>replay.cfg.replay_tolerance or terminal_qvel>replay.cfg.replay_tolerance*10 or
                    terminal_time>1e-8):raise ValueError('Diagnostic terminal state did not replay exactly')
            for name in names:
                for packet in streams[name].encode(None):writers[name].mux(packet)
                writers[name].close()
            writers.clear()
            if video_checker is not None:
                checked=video_checker(directory,replay.shapes)
                if len(checked)!=len(names) or any(v['frames']!=count for v in checked):
                    raise ValueError('Native video encoded frame count mismatch')
            trace_hash=digest(trace)
            references=[dict(trace=str(trace),trace_sha256=trace_hash,camera=name,path=str(directory/(name+'.mp4')),
                source_start_frame=0,video_start_frame=0,frames=count,sha256=digest(directory/(name+'.mp4')),native=True)
                for name in names]
            manifest=dict(schema='airport_vla_native_replay/1',status='complete',purpose='inspection_not_training_export',
                scene_id=sid,split=result['split'],attempt=attempt.name,trace=str(trace),trace_sha256=trace_hash,
                learner_run=str(run),source_collection=str(source_collection),source_scene_json_sha256=digest(scene_path),
                source_result=str(attempt/'result.json'),source_result_sha256=digest(attempt/'result.json'),
                scene_xml_sha256=digest(source_collection/'scenes'/sid/'mobile.xml'),checkpoint_id=result['checkpoint_id'],
                controller_source='vla_generated',source='simulation',task_completed=result.get('task_completed') is True,
                training_candidate=False,expert_label=False,frames=count,fps=20,references=references,
                replay_max_qpos_error=replay.maximum_error,replay_max_qvel_error=max_qvel,replay_max_time_error=max_time,
                terminal_qpos_error=terminal_qpos,terminal_qvel_error=terminal_qvel,terminal_time_error=terminal_time,
                camera_checks=replay.camera_checks,control_replay='continuous_initial_restore_only',
                control_journal_semantics=('ctrl_substeps exact interval controls' if replay.schema=='airport_fsm_raw/2' else
                    'raw/1 action[i] frozen servo reconstruction equals ctrl[i+1]; final interval checked against terminal state'))
            (directory/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
            return manifest
    except BaseException as exc:
        for writer in writers.values():writer.close()
        (directory/'failure.json').write_text(json.dumps({'status':'failed','error':repr(exc),
            'purpose':'inspection_not_training_export','source_result':str(attempt/'result.json')}),encoding='utf-8')
        raise


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--runs',nargs='+');p.add_argument('--one');p.add_argument('--source-collection',required=True)
    p.add_argument('--controller-root',required=True);p.add_argument('--output',required=True);p.add_argument('--workers',type=int,default=2)
    args=p.parse_args(argv)
    if bool(args.one)==bool(args.runs):p.error('Use exactly one of --one or --runs')
    if args.one:
        print(json.dumps(render_attempt(args.one,args.source_collection,args.output,controller_root=args.controller_root)),flush=True)
        return
    attempts=[]
    for run in args.runs:
        for result in sorted(Path(run).glob('attempts/*/*/result.json')):
            if (result.parent/'trace.h5').is_file():attempts.append(str(result.parent))
    output=Path(args.output);output.mkdir(parents=True,exist_ok=True)
    env=dict(os.environ,MUJOCO_GL='egl',MUJOCO_EGL_DEVICE_ID='1',OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1')
    def one(attempt):
        run=Path(attempt).parents[2].name;sid=Path(attempt).parent.name
        log=output/(run+'_'+sid+'.log')
        with log.open('x') as stream:
            result=subprocess.run([sys.executable,str(Path(__file__).resolve()),'--one',attempt,
                '--source-collection',args.source_collection,'--controller-root',args.controller_root,'--output',args.output],
                env=env,stdout=stream,stderr=subprocess.STDOUT)
        return dict(attempt=attempt,returncode=result.returncode,log=str(log))
    with ThreadPoolExecutor(max_workers=args.workers) as pool:results=list(pool.map(one,attempts))
    path=output/'render_run_status.json'
    with path.open('x',encoding='utf-8') as stream:json.dump({'attempts':results,'status':'complete' if all(r['returncode']==0 for r in results) else 'partial'},stream,indent=2)
    print(json.dumps(results),flush=True)


if __name__=='__main__':main()
