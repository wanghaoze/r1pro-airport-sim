"""Read-only validation of paired model videos/traces, then delivery metadata."""
import argparse,hashlib,json,subprocess,time
from pathlib import Path
from fractions import Fraction
import h5py,numpy as np


def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for block in iter(lambda:f.read(8*1024*1024),b''):h.update(block)
    return h.hexdigest()


def write(p,d):
    tmp=p.with_suffix('.tmp');tmp.write_text(json.dumps(d,indent=2));tmp.replace(p)


def run(root):
    launch=json.loads((root/'launch.json').read_text())
    while True:
        p=root/'pipeline_status.json';s=json.loads(p.read_text()) if p.exists() else {}
        if s.get('stage')=='complete':break
        if s.get('stage')=='failed':raise RuntimeError('pipeline_failed:'+json.dumps(s))
        stat=Path('/proc')/str(launch['pid'])/'stat'
        if not stat.exists() or stat.read_text().rsplit(')',1)[1].split()[19]!=launch['start_ticks']:raise RuntimeError('supervisor_identity_disappeared_before_completion')
        write(root/'delivery_status.json',dict(stage='waiting_for_closed_loop',pipeline_stage=s.get('stage'),heartbeat_unix=time.time()));time.sleep(10)
    reports={};paths=[];traces=[];initial={}
    for name in ['real_only','mixed']:
        assert json.loads((root/'logs'/f'{name}.exit.json').read_text())['returncode']==0
        s=json.loads((root/name/'summary.json').read_text());assert len(s['cases'])==20
        reports[name]=dict(groups=s['groups'],infrastructure_failures=s['infrastructure_failures'],cases=[])
        for result in s['cases']:
            case=root/name/result['case_id'];frames=result['frames'];assert frames>0
            assert all(result[k]==0 for k in ['teacher_fallback_calls','ik_calls','inverse_solver_calls','online_state_resets'])
            key=result['case_id'];init=result['initial_integration_sha256']
            if key in initial:assert initial[key]==init
            initial[key]=init
            trace=case/'attempt/trace.h5'
            with h5py.File(trace) as f:
                assert int(f.attrs['num_frames'])==frames
                assert all(len(f[k])==frames for k in ['qpos','qvel','action19','ctrl_substeps','executed_substeps','transition_completed'])
                assert np.isfinite(f['qpos'][:]).all() and np.isfinite(f['action19'][:]).all()
                assert f['transition_completed'][:].all()
                terminal=json.loads(f.attrs['terminal_snapshot_json']);assert not terminal.get('invalid')
                timestep_seconds=float(terminal['time']-f['sim_time'][0]);assert abs(timestep_seconds-frames/20)<1e-6
            media=[]
            for camera in ['head_left','head_right','left_wrist','right_wrist']:
                p=case/'videos'/f'{camera}.mp4'
                d=json.loads(subprocess.check_output(['ffprobe','-v','error','-count_frames','-select_streams','v:0','-show_entries','stream=width,height,avg_frame_rate,nb_read_frames','-of','json',str(p)]))['streams'][0]
                assert int(d['nb_read_frames'])==frames and Fraction(d['avg_frame_rate'])==20 and d['width']==d['height']==224
                media.append(dict(path=str(p),sha256=sha(p),**d));paths.append(str(p))
            decisions=sorted(case.glob('decision_*.npz'));assert len(decisions)==result['inference_calls']
            for d in decisions:
                with np.load(d) as a:assert a['raw_actions'].shape==(20,19) and np.isfinite(a['raw_actions']).all()
            traces.append(str(trace));receipt=dict(case_id=key,success=result['success'],failure_reason=result['failure_reason'],frames=frames,trace=str(trace),trace_sha256=sha(trace),videos=media,raw_decisions=len(decisions),same_paired_initial_state=True)
            write(case/'media_closure.json',receipt);reports[name]['cases'].append(receipt)
    write(root/'delivery_report.json',dict(scope='paired_independent_pick_place_simulation_not_real_robot_or_full_task',models=reports,video_count=len(paths),trace_count=len(traces),no_fallback=True))
    (root/'VIDEO_PATHS.txt').write_text('\n'.join(paths)+'\n');(root/'TRAJECTORY_PATHS.txt').write_text('\n'.join(traces)+'\n')
    write(root/'delivery_status.json',dict(stage='complete',video_count=len(paths),trace_count=len(traces),heartbeat_unix=time.time()))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);a=p.parse_args()
    try:run(a.run)
    except Exception as e:
        write(a.run/'delivery_status.json',dict(stage='failed',error=repr(e),heartbeat_unix=time.time()));raise
