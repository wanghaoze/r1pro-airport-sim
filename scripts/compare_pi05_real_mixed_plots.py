"""Paired all-frame real-test inference and scientific comparison plots."""
import argparse
import dataclasses
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import numpy as np

ROOT=Path('/home/michelle/haoze/r1pro-airport-sim')
CODE=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(CODE),str(ROOT/'third_party/openpi/src'),str(ROOT/'third_party/openpi/packages/openpi-client/src')]
from r1pro_teleop.vla.real_sim_data import Cache,sha,write
PURE=ROOT/'runs/real_only_pi05_20261012_v1'
MIXED=ROOT/'runs/real_sim_pickplace_20261009_v3'
ORDER=np.array([*range(7),*range(8,15),7,15])
NAMES=[*[f'left_arm_{i}' for i in range(7)],*[f'right_arm_{i}' for i in range(7)],'left_gripper','right_gripper']
LABELS={'real_only':'Real-only','mixed':'Mixed (90% real / 10% sim)'}


def aligned_cache():
    a=Cache(PURE/'cache/test');b=Cache(MIXED/'cache/test')
    if a.manifest!=b.manifest:raise ValueError('different_test_manifests')
    if a.manifest['source_domains']!=['real']:raise ValueError('real_test_required')
    test={e['raw_file_name'] for e in a.manifest['episodes']}
    for root in (PURE,MIXED):
        train=Cache(root/'cache/train')
        if test & {e['raw_file_name'] for e in train.manifest['episodes']}:raise ValueError('training_recording_leak')
    return a


def infer(run,name):
    from r1pro_teleop.vla.training import TrainingSpec,build_openpi_config
    from r1pro_teleop.vla.training_accelerated import vision_parameter_filter
    from flax import nnx
    from openpi.policies import policy_config
    root=PURE if name=='real_only' else MIXED
    status=json.loads((root/'pi05/training_status.json').read_text())
    if status['stage']!='trained' or status['updates']!=10000:raise ValueError('completed_checkpoint_required')
    spec=TrainingSpec(**status['spec']);cfg=build_openpi_config(spec)
    cfg=dataclasses.replace(cfg,freeze_filter=nnx.Any(cfg.freeze_filter,vision_parameter_filter))
    cache=aligned_cache();out=run/name;out.mkdir(parents=True,exist_ok=True)
    cp=Path(status['checkpoint'])
    receipt=dict(checkpoint=str(cp),checkpoint_metadata_sha256=sha(cp/'_CHECKPOINT_METADATA'),
        normalization_files={str(p):sha(p) for p in (cp/'assets').rglob('*.json')},
        test_manifest_sha256=sha(cache.path/'manifest.json'),updates=status['updates'],
        protocol='all 20Hz test frames; H20; first-step traces; no clipping; valid horizon only',
        seed='42000 + global_cache_frame_index; identical noise per model',
        scope='offline_real_test_prediction_not_robot_execution',project_training_source=status['source'])
    write(out/'identity.json',receipt)
    policy=policy_config.create_trained_policy(cfg,cp)
    predicted=np.empty((len(cache.state),20,16),np.float32);truth=np.empty_like(predicted)
    valid=np.empty((len(cache.state),20),bool);episode=np.empty(len(cache.state),np.int32);frame=np.empty(len(cache.state),np.int32)
    started=time.monotonic();rows=[]
    for ep,e in enumerate(cache.manifest['episodes']):
        rows.append(dict(episode_index=ep,raw_file_name=e['raw_file_name'],source_episode_index=e['episode_index'],
                         prompt=e['prompt'],frames=e['frames'],offset=e['offset']))
        for i in range(e['offset'],e['offset']+e['frames']):
            sample=cache.get(i);noise=np.random.default_rng(42000+i).standard_normal((20,32)).astype(np.float32)
            pred=np.asarray(policy.infer({k:v for k,v in sample.items() if k!='actions'},noise=noise)['actions'])
            if pred.shape!=(20,19) or not np.isfinite(pred).all():raise ValueError('invalid_model_output')
            predicted[i]=pred[:,ORDER];truth[i]=sample['actions'][:,ORDER]
            valid[i]=np.arange(20)<int(cache.ends[i]-i);episode[i]=ep;frame[i]=i-e['offset']
            if i%25==0 or i==len(cache.state)-1:
                elapsed=time.monotonic()-started
                write(out/'progress.json',dict(stage='inference',frames_done=i+1,total_frames=len(cache.state),
                    elapsed_seconds=elapsed,eta_seconds=elapsed/(i+1)*(len(cache.state)-i-1),heartbeat_unix=time.time()))
        # Preserve completed episode inference separately if a later call fails.
        sl=slice(e['offset'],e['offset']+e['frames'])
        np.savez_compressed(out/f'episode_{ep:03d}_predictions.npz',predicted=predicted[sl],ground_truth=truth[sl],valid_horizon=valid[sl])
    np.savez_compressed(out/'predictions_and_ground_truth.npz',predicted=predicted,ground_truth=truth,
        valid_horizon=valid,episode_index=episode,frame_index=frame,dimension_names=np.array(NAMES),
        predicted_output_present=np.ones_like(predicted,bool))
    write(out/'episodes.json',rows)
    write(out/'progress.json',dict(stage='complete',frames_done=len(cache.state),total_frames=len(cache.state),elapsed_seconds=time.monotonic()-started,heartbeat_unix=time.time()))


def per_dimension_mse(pred,truth,valid):
    if pred.shape!=truth.shape or valid.shape!=pred.shape[:2]:raise ValueError('metric_shape_mismatch')
    return np.mean(((pred.astype(np.float64)-truth.astype(np.float64))**2)[valid],axis=0)


def plots(run):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import csv
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,'axes.spines.top':False,
        'axes.spines.right':False,'axes.grid':True,'grid.alpha':.17,'axes.axisbelow':True,'savefig.facecolor':'white'})
    arrays={name:np.load(run/name/'predictions_and_ground_truth.npz') for name in LABELS}
    a=arrays['real_only'];b=arrays['mixed']
    for key in ['ground_truth','valid_horizon','episode_index','frame_index']:
        np.testing.assert_array_equal(a[key],b[key])
    episodes=json.loads((run/'real_only/episodes.json').read_text());truth=a['ground_truth'];valid=a['valid_horizon']
    colors={'real_only':'#0072B2','mixed':'#D55E00'};styles={'real_only':'-','mixed':'--'}
    preds={n:d['predicted'] for n,d in arrays.items()};files=[]
    def save(fig,path):
        path.parent.mkdir(parents=True,exist_ok=True)
        fig.savefig(path.with_suffix('.png'),dpi=135);fig.savefig(path.with_suffix('.pdf'))
        plt.close(fig);files.append(str(path.with_suffix('.png').relative_to(run)))
    metrics={}
    for name,pred in preds.items():
        total=per_dimension_mse(pred,truth,valid);first=((pred[:,0].astype(float)-truth[:,0])**2).mean(0)
        metrics[name]=dict(overall=dict(per_dimension_mse_rad2_or_m2=total.tolist(),first_step_per_dimension_mse=first.tolist(),
            arm_mse_rad2=float(total[:14].mean()),gripper_mse_mm2=float(total[14:].mean()*1e6),
            frames=len(pred),valid_chunk_timesteps=int(valid.sum()),missing_output_fraction=0),by_episode={},by_action={})
        for e in episodes:
            ix=a['episode_index']==e['episode_index'];m=per_dimension_mse(pred[ix],truth[ix],valid[ix])
            metrics[name]['by_episode'][str(e['episode_index'])]=dict(e,per_dimension_mse=m.tolist(),arm_rmse_deg=float(np.sqrt(m[:14].mean())*180/np.pi),gripper_rmse_mm=float(np.sqrt(m[14:].mean())*1000))
        for action in ['Pick up the tray','Place the tray']:
            eps=[e['episode_index'] for e in episodes if e['prompt']==action];ix=np.isin(a['episode_index'],eps)
            m=per_dimension_mse(pred[ix],truth[ix],valid[ix]);metrics[name]['by_action'][action]=dict(episodes=len(eps),per_dimension_mse=m.tolist(),arm_mse_rad2=float(m[:14].mean()),gripper_mse_mm2=float(m[14:].mean()*1e6))
        write(run/name/'metrics.json',dict(metrics[name],identity=json.loads((run/name/'identity.json').read_text()),not_a_robot_success_rate=True))
        with (run/name/'per_joint_mse.csv').open('w',newline='') as f:
            w=csv.writer(f);w.writerow(['dimension','mse','unit','first_step_mse'])
            for i,n in enumerate(NAMES):w.writerow([n,total[i] if i<14 else total[i]*1e6,'rad^2' if i<14 else 'mm^2',first[i] if i<14 else first[i]*1e6])
    for group in ['real_only','mixed','comparison']:
        series=[group] if group!='comparison' else list(LABELS)
        for e in episodes:
            ix=a['episode_index']==e['episode_index'];x=a['frame_index'][ix]/20
            fig,axes=plt.subplots(4,4,figsize=(19,12),layout='constrained')
            for j,ax in enumerate(axes.flat):
                scale=1 if j<14 else 1000
                ax.plot(x,truth[ix,0,j]*scale,color='#333333',lw=1.8,label='Ground truth',zorder=3)
                for n in series:ax.plot(x,preds[n][ix,0,j]*scale,color=colors[n],ls=styles[n],lw=1.15,label=LABELS[n])
                ax.set_title(NAMES[j]);ax.set_ylabel('rad' if j<14 else 'mm');ax.set_xlabel('Time (s)')
                if j==0:ax.legend(fontsize=8)
            fig.suptitle(f"{e['prompt']} | episode {e['episode_index']:03d} | first-step predictions, all 20 Hz frames\nOffline real test; full values shown; no clipping or robot execution",fontsize=15)
            save(fig,run/group/f"episode_{e['episode_index']:03d}_joints")
        for subset in ['all','pick','place']:
            for typ,unit,scale,ids,root in [('joint_mse','rad²',1,range(14),False),('joint_mse_deg2','deg²',(180/np.pi)**2,range(14),False),('joint_rmse_deg','deg',(180/np.pi)**2,range(14),True),('gripper_mse_mm2','mm²',1e6,range(14,16),False),('gripper_rmse_mm','mm',1e6,range(14,16),True)]:
                ids=list(ids);fig,ax=plt.subplots(figsize=(14,5.5),layout='constrained');x=np.arange(len(ids));width=.7/len(series)
                for k,n in enumerate(series):
                    row=metrics[n]['overall']['per_dimension_mse_rad2_or_m2'] if subset=='all' else metrics[n]['by_action']['Pick up the tray' if subset=='pick' else 'Place the tray']['per_dimension_mse']
                    y=np.array(row)[ids]*scale;y=np.sqrt(y) if root else y
                    ax.bar(x+(k-(len(series)-1)/2)*width,y,width,label=LABELS[n],color=colors[n],hatch=None if n=='real_only' else '//',alpha=.9)
                ax.set_xticks(x,[NAMES[i] for i in ids],rotation=40,ha='right');ax.set_ylim(bottom=0);ax.set_ylabel(('RMSE' if root else 'MSE')+f' ({unit})');ax.legend()
                ax.set_title(f"{subset.upper()} real held-out episodes | valid H20 targets at every frame\n{'Arms only' if ids[0]<14 else 'Grippers only'}; no clipping; overlapping horizons micro-averaged")
                save(fig,run/group/(typ if subset=='all' else subset+'/'+typ))
    # Per-episode aggregate and horizon growth make failures visible beyond joint averages.
    fig,axes=plt.subplots(2,1,figsize=(15,8),layout='constrained');x=np.arange(len(episodes));width=.36
    for k,n in enumerate(LABELS):
        rows=metrics[n]['by_episode']
        for ax,key in zip(axes,['arm_rmse_deg','gripper_rmse_mm']):ax.bar(x+(k-.5)*width,[rows[str(i)][key] for i in x],width,label=LABELS[n],color=colors[n])
    for ax,unit in zip(axes,['Arm RMSE (deg)','Gripper RMSE (mm)']):
        ax.set_ylabel(unit);ax.set_xticks(x,[f"{i:03d}\n{'Pick' if e['prompt'].startswith('Pick') else 'Place'}" for i,e in enumerate(episodes)]);ax.legend();ax.set_ylim(bottom=0)
    fig.suptitle('Per-episode errors | all-frame valid H20 predictions');save(fig,run/'comparison/episode_rmse')
    fig,axes=plt.subplots(1,2,figsize=(13,5),layout='constrained')
    for n,pred in preds.items():
        errors=(pred.astype(float)-truth.astype(float))**2
        by_h=np.array([errors[valid[:,h],h].mean(0) for h in range(20)])
        axes[0].plot(np.arange(20)/20,np.sqrt(by_h[:,:14].mean(1))*180/np.pi,label=LABELS[n],color=colors[n],ls=styles[n])
        axes[1].plot(np.arange(20)/20,np.sqrt(by_h[:,14:].mean(1))*1000,label=LABELS[n],color=colors[n],ls=styles[n])
    for ax,unit in zip(axes,['Arm RMSE (deg)','Gripper RMSE (mm)']):ax.set_xlabel('Prediction horizon (s)');ax.set_ylabel(unit);ax.legend();ax.set_ylim(bottom=0)
    fig.suptitle('Error versus prediction horizon | valid real-test targets only');save(fig,run/'comparison/horizon_rmse')
    write(run/'comparison_metrics.json',dict(models=metrics,frames=len(truth),episodes=len(episodes),
        same_test_frames=True,same_flow_noise=True,not_a_robot_success_rate=True,
        caveat='Checkpoints differ in data mixture AND initialization; not a controlled causal ablation of simulation data alone.'))
    html=['<!doctype html><meta charset="utf-8"><title>π0.5 real-only vs mixed</title><style>body{font:16px system-ui;margin:32px;max-width:1500px}img{width:100%;height:auto}summary{cursor:pointer;padding:12px;background:#eef2f5}a{color:#00629b}</style>',
          '<h1>π0.5: Real-only vs Mixed</h1><p>19 real test episodes (11 Pick, 8 Place), all 3653 frames at 20 Hz. Identical flow noise; valid H20 only. Offline predictions, not robot execution. Checkpoint initialization differs: this is not a data-mixture-only causal ablation.</p>']
    for group in ['comparison','real_only','mixed']:
        html.append(f'<h2>{group}</h2>')
        for path in [p for p in files if p.startswith(group+'/')]:html.append(f'<details><summary>{path} — <a href="{path}">PNG</a> / <a href="{path[:-4]}.pdf">PDF</a></summary><img loading="lazy" src="{path}"></details>')
    (run/'index.html').write_text('\n'.join(html),encoding='utf-8')
    write(run/'plot_manifest.json',dict(png_files=files,png_count=len(files),pdf_count=len(files),complete=True))


def supervise(run):
    import fcntl
    run.mkdir(parents=True,exist_ok=True);(run/'logs').mkdir(exist_ok=True)
    lock=(run/'pipeline.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    for name in ['real_only','mixed','plots']:
        argv=[sys.executable,str(Path(__file__).resolve()),'--run',str(run),'--mode',name]
        with (run/'logs'/f'{name}.log').open('x') as f:p=subprocess.Popen(argv,cwd=ROOT,stdin=subprocess.DEVNULL,stdout=f,stderr=subprocess.STDOUT,start_new_session=True)
        write(run/'logs'/f'{name}.launch.json',dict(pid=p.pid,argv=argv,cwd=str(ROOT),start_ticks=Path(f'/proc/{p.pid}/stat').read_text().rsplit(')',1)[1].split()[19]))
        while p.poll() is None:
            write(run/'pipeline_status.json',dict(stage=name,pid=os.getpid(),active_pid=p.pid,heartbeat_unix=time.time()));time.sleep(5)
        code=p.wait();write(run/'logs'/f'{name}.exit.json',dict(returncode=code,actual_child_wait=True))
        if code:
            write(run/'pipeline_status.json',dict(stage='failed',failed_stage=name,returncode=code,active_pid=None));return
    write(run/'pipeline_status.json',dict(stage='complete',active_pid=None,heartbeat_unix=time.time()))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);p.add_argument('--mode',choices=['real_only','mixed','plots','supervise'],required=True);a=p.parse_args()
    if a.mode in LABELS:infer(a.run,a.mode)
    else:globals()[a.mode](a.run)
