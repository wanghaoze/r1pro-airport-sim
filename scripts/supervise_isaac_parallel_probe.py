"""Bounded, single-instance integration staircase; not a data producer."""
import argparse
import fcntl
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
import traceback

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from r1pro_teleop.real2sim.isaac_parallel_collection import write_json
from isaacsim_stage_runner import checked


def main():
    p=argparse.ArgumentParser();p.add_argument('--config',type=Path,required=True);a=p.parse_args()
    cfg=json.loads(a.config.read_text());run=Path(cfg['run']);run.mkdir(exist_ok=True)
    lock=(run/'integration.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    state=dict(scope='parallel_engine_integration_only',training_eligible=False,
               actual_qualified_sources=0,adaptive_collection_ready=False,pid=__import__('os').getpid())
    def report(stage,**kw):
        state.update(stage=stage,heartbeat_unix=time.time(),**kw);write_json(run/'pipeline_status.json',state)
    report('integration_staircase')
    try:
        preflight=cfg.get('preflight_exit_receipt')
        while preflight and not Path(preflight).exists():
            report('waiting_for_shutdown_preflight',receipt=preflight)
            runner=Path(cfg['preflight_runner_identity'])
            if runner.exists() and not checked(json.loads(runner.read_text())) and not Path(preflight).exists():
                raise RuntimeError('shutdown_preflight_waiter_lost')
            time.sleep(5)
        if preflight:
            check=json.loads(Path(preflight).read_text())
            if not check.get('actual_child_wait') or check['returncode']!=0:raise RuntimeError('shutdown_preflight_actual_exit_failed')
        counts=cfg.get('room_counts',[4,8,16,32])
        if counts==[32]:
            for n in (4,8,16):
                ref=cfg['prior_integration_audits'][str(n)];path=Path(ref['path'])
                if hashlib.sha256(path.read_bytes()).hexdigest()!=ref['sha256']:raise RuntimeError('prior_integration_audit_changed')
                value=json.loads(path.read_text())
                if not value['integration_closed'] or value['actual_exit']['returncode']!=0 or len(value['video_checks'])!=4*n:
                    raise RuntimeError('prior_integration_staircase_not_closed')
        elif counts!=[4,8,16,32]:raise ValueError('unregistered_integration_staircase')
        for n in counts:
            stem=f'full_probe_{n:02d}';out=run/stem;receipt=run/(stem+'.exit.json')
            job=run/(stem+'.job.json');config=run/(stem+'.config.json')
            if not job.exists():
                case=dict(cfg['native_config'],rooms=n,output=str(out),frames=1000000)
                write_json(config,case)
                write_json(job,dict(argv=[cfg['native_python'],str(Path(cfg['code'])/'scripts/probe_isaac_parallel_collection.py'),'--config',str(config)],
                    cwd=cfg['project'],log=str(run/(stem+'.log')),launch=str(run/(stem+'.launch.json')),
                    receipt=str(receipt),environment=dict(OMNI_KIT_ACCEPT_EULA='YES',PYTHONUNBUFFERED='1')))
            # Adopt the verified independent waiter; the log is exclusive too.
            runner_identity=Path(str(job.with_suffix(''))+'.runner.json')
            if not receipt.exists():
                if runner_identity.exists():
                    if not checked(json.loads(runner_identity.read_text())):
                        raise RuntimeError('existing_stage_waiter_missing_preserve_child_no_duplicate')
                else:
                    subprocess.Popen([cfg['control_python'],cfg['runner'],'--job',str(job)],
                        cwd=cfg['project'],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,start_new_session=True)
            while not receipt.exists():
                if runner_identity.exists() and not checked(json.loads(runner_identity.read_text())) and not receipt.exists():
                    raise RuntimeError('stage_waiter_lost_without_actual_exit_receipt')
                progress=out/'status.json'
                report('integration_staircase',active_rooms=n,active_output=str(out),
                       native_status=json.loads(progress.read_text()) if progress.exists() else None)
                time.sleep(5)
            actual=json.loads(receipt.read_text())
            if actual.get('returncode')!=0 or actual.get('actual_child_wait') is not True:
                raise RuntimeError('native_integration_probe_failed:'+stem)
            native=json.loads((out/'status.json').read_text())
            if native['stage']!='integration_probe_closed':raise RuntimeError('native_probe_not_closed')
            media=json.loads((out/'media_exit.json').read_text())
            if len(media)!=4*n:raise RuntimeError('native_probe_camera_count')
            results=[]
            for row in media.values():
                if row['returncode']!=0 or row['frames']!=native['frames']:raise RuntimeError('native_probe_encoder_not_closed')
                command=['ffprobe','-v','error','-count_frames','-select_streams','v:0','-show_entries',
                         'stream=nb_read_frames,r_frame_rate,width,height','-of','json',row['path']]
                value=json.loads(subprocess.check_output(command,text=True))['streams'][0]
                if int(value['nb_read_frames'])!=native['frames'] or value['r_frame_rate']!='20/1':
                    raise RuntimeError('native_probe_ffprobe_frame_or_fps_mismatch')
                results.append(dict(path=row['path'],probe=value))
            write_json(out/'integration_audit.json',dict(actual_exit=actual,video_checks=results,
                integration_closed=True,full_task_qualified=False,training_eligible=False,
                limitations=['recorded expert commands, not adaptive controller',
                             'no task contact qualification', 'camera isolation not audited',
                             'dual GPU workload balance not verified']))
        report('integration_complete_adaptive_collection_pending',active_rooms=None)
    except BaseException as exc:
        report('failed',error=repr(exc),traceback=traceback.format_exc())
        raise


if __name__=='__main__':main()
