"""Paired all-frame fixed real Val/Test inference on registered checkpoints."""
import argparse
import dataclasses
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import numpy as np

CODE=Path(__file__).resolve().parents[1]
ROOT=Path(os.environ.get('AIRPORT_PROJECT','/home/michelle/haoze/r1pro-airport-sim'))
sys.path[:0]=[str(CODE),str(ROOT/'third_party/openpi/src'),str(ROOT/'third_party/openpi/packages/openpi-client/src')]
from r1pro_teleop.vla.real_sim_data import Cache,sha,write,mse_groups


def load_registered_policy(entry):
    from resume_isaacsim_bc_after_video import verified_legacy_gpu_runtime
    os.environ.update(verified_legacy_gpu_runtime())
    os.environ['XLA_PYTHON_CLIENT_PREALLOCATE']='false'
    os.environ.setdefault('CUDA_VISIBLE_DEVICES','0')
    os.environ.setdefault('OMP_NUM_THREADS','2')
    if sha(entry['receipt'])!=entry['receiptSha256']:raise ValueError('checkpoint_receipt_changed')
    if not entry.get('contentBindings'):raise ValueError('checkpoint_content_identity_not_frozen')
    for path,expected in entry['contentBindings'].items():
        if sha(path)!=expected:raise ValueError('checkpoint_content_changed')
    from r1pro_teleop.vla.training import TrainingSpec,build_openpi_config
    from r1pro_teleop.vla.training_accelerated import vision_parameter_filter
    from flax import nnx
    from openpi.policies import policy_config
    spec=TrainingSpec(**entry['spec']);cfg=build_openpi_config(spec)
    if spec.action_horizon!=20:raise ValueError('H20_checkpoint_required')
    cfg=dataclasses.replace(cfg,freeze_filter=nnx.Any(cfg.freeze_filter,vision_parameter_filter))
    cp=Path(entry['checkpoint'])
    if not (cp/'params/manifest.ocdbt').exists():raise ValueError('checkpoint_weights_missing')
    # create_trained_policy loads this checkpoint's own assets/normalization.
    return policy_config.create_trained_policy(cfg,cp)


def sample_contract(cache,split):
    if split not in ('val','test') or cache.manifest.get('source_domains')!=['real'] or not cache.manifest.get('ready'):raise ValueError('fixed_real_holdout_required')
    keys=[]
    for e in cache.manifest['episodes']:
        if e['split']!=split:raise ValueError('holdout_split_mismatch')
        keys.extend([[split,e['dataset'],e['raw_file_name'],e['episode_index'],i] for i in range(e['frames'])])
    if len(keys)!=len(cache.state):raise ValueError('sample_key_coverage')
    return dict(protocol='real_all_frames_h20_noise42000_v1',split=split,manifestSha256=sha(cache.path/'manifest.json'),
        sampleKeysSha256=hashlib.sha256(json.dumps(keys,separators=(',',':')).encode()).hexdigest(),
        horizon=20,stride=1,noise='float32 standard_normal(20,32), seed=42000+global_cache_frame_index',
        paddingExcluded=True,baseChannelsExcluded=True,frames=len(keys),scope='offline_real_prediction_not_robot_execution')


def infer(run,index):
    request=json.loads((run/'request.json').read_text());split=request['payload']['split']
    entries=json.loads((run/'checkpoints.json').read_text());entry=entries[index]
    root=ROOT/'runs/real_sim_pickplace_20261009_v3/cache';cache=Cache(root/split)
    contract=sample_contract(cache,split)
    test={(e['dataset'],e['raw_file_name']) for e in cache.manifest['episodes']}
    for source in (root/'train',Path(entry['run'])/'cache/train'):
        manifest=json.loads((source/'manifest.json').read_text())
        if test & {(e.get('dataset'),e.get('raw_file_name')) for e in manifest['episodes']}:raise ValueError('holdout_training_recording_leak')
    out=run/entry['id'];out.mkdir(exist_ok=False)
    identity=dict(entry,contract=contract,checkpointMetadataSha256=sha(Path(entry['checkpoint'])/'_CHECKPOINT_METADATA'),
        normalization={str(p):sha(p) for p in (Path(entry['checkpoint'])/'assets').rglob('*.json')})
    write(out/'identity.json',identity);write(run/'progress.json',dict(stage='initializing',completed=index,total=len(entries),heartbeat_unix=time.time()))
    policy=load_registered_policy(entry)
    predicted=np.empty((len(cache.state),20,19),np.float32);truth=np.empty_like(predicted);valid=np.empty((len(cache.state),20),bool)
    start=time.monotonic();episodes=[]
    for ep,e in enumerate(cache.manifest['episodes']):
        for i in range(e['offset'],e['offset']+e['frames']):
            sample=cache.get(i);noise=np.random.default_rng(42000+i).standard_normal((20,32)).astype(np.float32)
            pred=np.asarray(policy.infer({k:v for k,v in sample.items() if k!='actions'},noise=noise)['actions'])
            if pred.shape!=(20,19) or not np.isfinite(pred).all():raise ValueError('invalid_model_output')
            predicted[i]=pred;truth[i]=sample['actions'];valid[i]=np.arange(20)<int(cache.ends[i]-i)
            if i%25==0 or i==len(cache.state)-1:
                elapsed=time.monotonic()-start;remaining=len(cache.state)*(len(entries)-index)-i-1
                write(run/'progress.json',dict(stage='inference',checkpointId=entry['id'],completed=index*len(cache.state)+i+1,total=len(entries)*len(cache.state),
                    eta_seconds=elapsed/(i+1)*remaining,eta_scope='remaining_inference_excludes_model_initialization',heartbeat_unix=time.time()))
        sl=slice(e['offset'],e['offset']+e['frames'])
        np.savez_compressed(out/f'episode_{ep:03d}.npz',predicted=predicted[sl],truth=truth[sl],valid=valid[sl])
        episodes.append(dict(raw_file_name=e['raw_file_name'],episode_index=e['episode_index'],prompt=e['prompt'],**mse_groups(predicted[sl],truth[sl],valid[sl])))
    overall=mse_groups(predicted,truth,valid);first=mse_groups(predicted[:,0],truth[:,0])
    actions={prompt:mse_groups(predicted[cache.task==idx],truth[cache.task==idx],valid[cache.task==idx]) for idx,prompt in enumerate(('Pick up the tray','Place the tray')) if np.any(cache.task==idx)}
    report=dict(id=entry['id'],label=entry['label'],contract=contract,armMseRad2=overall['arm_mse_rad2'],gripperMseMm2=overall['gripper_mse_mm2'],
        firstArmMseRad2=first['arm_mse_rad2'],firstGripperMseMm2=first['gripper_mse_mm2'],perChannelMseRad2OrM2=overall['per_channel_mse'],
        byAction=actions,byEpisode=episodes,frames=len(cache.state),validTimesteps=int(valid.sum()),validMaskSha256=hashlib.sha256(valid.tobytes()).hexdigest(),truthSha256=hashlib.sha256(truth.tobytes()).hexdigest())
    write(out/'report.json',report)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--run',type=Path,required=True);parser.add_argument('--index',type=int,required=True);args=parser.parse_args();infer(args.run,args.index)
