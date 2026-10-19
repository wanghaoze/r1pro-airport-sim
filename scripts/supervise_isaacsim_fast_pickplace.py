"""Detached bounded multi-pose fast video benchmark; never feeds BC implicitly."""
import argparse
import fcntl
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
import traceback


def main():
    p=argparse.ArgumentParser();p.add_argument('--config',type=Path,required=True);a=p.parse_args();cfg=json.loads(a.config.read_text());run=Path(cfg['run']);run.mkdir(exist_ok=True)
    sys.path[:0]=[cfg['code'],str(Path(cfg['code'])/'scripts')]
    from isaacsim_stage_runner import atomic,identity,checked
    from r1pro_teleop.vla.isaac_dataset import video_probe,sha
    lock=(run/'benchmark.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    state=dict(stage='native_multi_pose_benchmark',scope='fast_pickplace_not_full_task_not_training',completed_cases=0,successful_cases=0,training_started=False)
    def status(**kw):state.update(kw,heartbeat_unix=time.time());atomic(run/'pipeline_status.json',state)
    def page(rows):
        body='<meta charset="utf-8"><title>Isaac fast Pick / Place</title><style>body{font:18px system-ui;max-width:1200px;margin:32px auto;background:#151a22;color:#eee}video{width:90%}a{color:#85c7ff}</style><h1>Isaac 原速快速取放，多位姿实验</h1><p>目标：夹起与放下各3秒；站位、预备姿态单独记录。真实PhysX，非VLA模型执行，不自动进入训练。</p><p>同MuJoCo的银黑机器人与Blender实验室；四个原相机不变，外部展示相机不用于训练。</p>'
        successes=[r for r in rows if r['passed']];body+=f'<h2>已完成 {len(rows)} / {len(cfg["cases"])}；通过 {len(successes)}</h2>'
        if (run/'multi_pose_overview.mp4').exists():body+='<h2>多位姿合集（原速）</h2><video controls src="multi_pose_overview.mp4"></video>'
        for row in rows:
            body+='<h2>'+row['case_id']+(' — 通过' if row['passed'] else ' — 失败，保留证据')+'</h2>'
            if row.get('overview'):body+='<video controls preload="metadata" src="'+row['overview']+'"></video>'
            body+='<p><a href="'+row['directory']+'/result.json">实际时间、位移、接触与速度统计</a> | <a href="'+row['directory']+'/presentation.mp4">含预备过程的完整视频</a></p>'
        body+='<p><a href="pipeline_status.json">后台实时状态</a> | <a href="real_train_motion_reference.json">真机训练集速度参考</a></p>';tmp=run/'index.tmp';tmp.write_text(body);tmp.replace(run/'index.html')
    rows=[];consecutive=0
    try:
        previous=cfg.get('wait_before_start')
        while previous and not Path(previous['receipt']).exists():
            child=previous['child'];runner=previous['runner']
            if not checked(child) and not checked(runner):raise RuntimeError('previous_native_missing_independent_wait_receipt')
            status(stage='waiting_previous_native_close_not_interrupted',previous_native=child);time.sleep(5)
        status(stage='native_multi_pose_benchmark')
        for i,case in enumerate(cfg['cases']):
            name=f'case_{i:03d}';out=run/name;receipt=run/(name+'.exit.json');launch=run/(name+'.launch.json');job=run/(name+'.job.json');case_cfg=run/(name+'.config.json')
            params=dict(case,output=str(out),scene_root=cfg['scene_root'],lab_assets=cfg['lab_assets']);atomic(case_cfg,params)
            argv=[cfg['isaac_python'],str(Path(cfg['code'])/'scripts/run_isaacsim_fast_pickplace.py'),'--config',str(case_cfg)]
            if not receipt.exists() and not job.exists():
                atomic(job,dict(argv=argv,cwd=cfg['project'],log=str(run/(name+'.log')),launch=str(launch),receipt=str(receipt),environment={'OMNI_KIT_ACCEPT_EULA':'YES'}))
                subprocess.Popen([sys.executable,str(Path(cfg['code'])/'scripts/isaacsim_stage_runner.py'),'--job',str(job)],cwd=cfg['project'],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
            while not receipt.exists():
                progress=out/'progress.json';j=json.loads(launch.read_text()) if launch.exists() else None
                if j and not checked(j):
                    runner=run/(name+'.job.runner.json')
                    if not runner.exists() or not checked(json.loads(runner.read_text())):raise RuntimeError('native_child_missing_wait_receipt')
                status(active_case=case['case_id'],child=j,progress=json.loads(progress.read_text()) if progress.exists() else {});page(rows);time.sleep(5)
            exit=json.loads(receipt.read_text());result=json.loads((out/'result.json').read_text()) if (out/'result.json').exists() else {};passed=exit['returncode']==0 and result.get('passed') is True
            row=dict(case_id=case['case_id'],directory=name,passed=passed,actual_exit=exit,actions=result.get('actions',[]),motion=result.get('motion',{}));overview=None
            if passed:
                for cam,record in result['native_encoders'].items():
                    probe=video_probe(record['path'])
                    if record['returncode'] or probe['frames']!=result['frames'] or probe['fps']!=20:raise RuntimeError('native_media_not_closed:'+cam)
                for attempt in range(3):
                    export=out/('clips' if attempt==0 else f'clips_attempt_{attempt}');manifest=export/'manifest.json'
                    if manifest.exists():
                        saved=json.loads(manifest.read_text());overview=str(Path(saved.get('overview_path',str(export/'presentation_6s.mp4'))).relative_to(run));break
                    if export.exists():continue
                    export.mkdir();clips=[]
                    try:
                        for span in result['actions']:
                            stem='pick_up_the_tray' if span['prompt']=='Pick up the tray' else 'place_the_tray'
                            clip_frames=span['end']-span['start']
                            for cam in result['native_encoders']:
                                target=export/(stem+'_'+cam+'.mp4');subprocess.run(['ffmpeg','-nostdin','-v','error','-n','-ss',f"{span['start']/20:.6f}",'-i',str(out/(cam+'.mp4')),'-frames:v',str(clip_frames),'-vf','setpts=PTS-STARTPTS','-an','-c:v','libx264','-preset','fast','-crf','17','-threads','2',str(target)],check=True)
                                probe=video_probe(target)
                                if probe['frames']!=clip_frames or probe['fps']!=20:raise RuntimeError('complete_action_clip_alignment_failed')
                                clips.append(dict(prompt=span['prompt'],camera=cam,path=str(target),sha256=sha(target),**probe))
                        pair_frames=result['actions'][-1]['end']-result['actions'][0]['start']
                        target=export/('presentation_6s.mp4' if pair_frames==120 else 'presentation_complete_pair.mp4');subprocess.run(['ffmpeg','-nostdin','-v','error','-n','-ss',f"{result['actions'][0]['start']/20:.6f}",'-i',str(out/'presentation.mp4'),'-frames:v',str(pair_frames),'-vf','setpts=PTS-STARTPTS','-an','-c:v','libx264','-preset','fast','-crf','17','-threads','2',str(target)],check=True)
                        if video_probe(target)['frames']!=pair_frames:raise RuntimeError('complete_pair_overview_not_closed')
                        atomic(manifest,dict(ready=True,training_eligible=False,clips=clips,overview_path=str(target),source_trace_sha256=sha(out/'native_trace.npz'),original_speed=True));overview=str(target.relative_to(run));break
                    except (subprocess.CalledProcessError,OSError) as exc:
                        status(last_export_error=repr(exc),export_attempt=attempt);time.sleep((2,5,10)[attempt])
                row.update(overview=overview,source_trace_sha256=sha(out/'native_trace.npz'));consecutive=0
            else:consecutive+=1;row['error']=result.get('error')
            rows.append(row);atomic(run/'results.json',rows);status(completed_cases=len(rows),successful_cases=sum(r['passed'] for r in rows),last_case=row);page(rows)
            if consecutive>=3:raise RuntimeError('three_consecutive_physical_failures_require_diagnosis')
        videos=[run/r['overview'] for r in rows if r.get('overview')]
        if videos and not (run/'multi_pose_overview.mp4').exists():
            listing=run/'concat.txt';listing.write_text(''.join("file '"+str(p)+"'\n" for p in videos));subprocess.run(['ffmpeg','-nostdin','-v','error','-n','-f','concat','-safe','0','-i',str(listing),'-c','copy',str(run/'multi_pose_overview.mp4')],check=True)
        status(stage='complete',model_executed=False,training_eligible=False);page(rows)
    except BaseException as exc:status(stage='failed',last_error=repr(exc));(run/'exception.txt').write_text(traceback.format_exc());raise


if __name__=='__main__':main()
