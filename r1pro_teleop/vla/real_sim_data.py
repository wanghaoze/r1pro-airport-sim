"""Explicit real joint-space mapping, episode holdouts and source-balanced sampling."""
import hashlib
import json
from pathlib import Path
import subprocess
from concurrent.futures import ThreadPoolExecutor,as_completed
import numpy as np

CAMERAS=('head_left','left_wrist','right_wrist')
REAL_CAMERAS=('head_rgb','left_wrist_rgb','right_wrist_rgb')
PROMPTS=('Pick up the tray','Place the tray','Flush tray to the left')
ARMS=np.r_[np.arange(7),np.arange(8,15)]
GRIPPERS=np.array([7,15])


def write(path,data):
    p=Path(path);p.parent.mkdir(parents=True,exist_ok=True);tmp=p.with_suffix('.tmp');tmp.write_text(json.dumps(data,indent=2,allow_nan=False));tmp.replace(p)


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda:f.read(8*1024**2),b''):h.update(chunk)
    return h.hexdigest()


def split_for(raw_file,seed=42):
    n=int(hashlib.sha256(f'{seed}|{raw_file}'.encode()).hexdigest()[:8],16)%100
    return 'train' if n<80 else 'val' if n<90 else 'test'


def resample_indices(timestamps,fps=20):
    t=np.asarray(timestamps,dtype=np.float64)
    if len(t)<2 or not np.isfinite(t).all() or np.any(np.diff(t)<=0):raise ValueError('invalid_real_timestamps')
    grid=t[0]+np.arange(int(np.floor((t[-1]-t[0])*fps+1e-5))+1)/fps
    right=np.minimum(np.searchsorted(t,grid),len(t)-1);left=np.maximum(right-1,0)
    return np.where(grid-t[left]<=t[right]-grid,left,right)


def map_real(columns,gripper_unit):
    if gripper_unit!='mm':raise ValueError('explicit_supported_gripper_mm_contract_required')
    vectors={}
    for domain in ['observation.state','action']:
        parts=[np.asarray(columns[domain+'.'+name],dtype=np.float32) for name in ['left_arm','left_gripper','right_arm','right_gripper']]
        parts=[p.reshape(-1,1) if p.ndim==1 else p for p in parts]
        if [p.shape[1] for p in parts]!=[7,1,7,1]:raise ValueError('real_arm_gripper_order_not_7_1_7_1')
        v=np.concatenate(parts,axis=1)
        if not np.isfinite(v).all():raise ValueError('nonfinite_real_arm_or_gripper')
        # Sensor feedback can overshoot nominal stroke; preserve it exactly.
        # Only commanded targets are checked against the documented contract.
        if domain=='action' and (np.any(v[:,GRIPPERS]<-.5) or np.any(v[:,GRIPPERS]>100.5)):raise ValueError('real_gripper_command_outside_documented_mm_range')
        v[:,GRIPPERS]*=.001;vectors[domain]=v
    velocity=np.asarray(columns['action.chassis.velocities'])
    if velocity.shape[1]!=6 or np.any(velocity!=0):raise ValueError('moving_chassis_requires_explicit_velocity_to_position_contract')
    chassis=np.asarray(columns['observation.state.chassis'],dtype=np.float32)
    state=np.c_[vectors['observation.state'],chassis-chassis[0]].astype(np.float32)
    action=np.c_[vectors['action'],np.zeros_like(chassis)].astype(np.float32)
    return state,action


def decode_selected(video,indices,target):
    filt='scale=224:224:force_original_aspect_ratio=decrease,pad=224:224:(ow-iw)/2:(oh-ih)/2'
    argv=['ffmpeg','-v','error','-threads','1','-i',str(video),'-vf',filt,'-f','rawvideo','-pix_fmt','rgb24','-threads','1','pipe:1']
    with subprocess.Popen(argv,stdout=subprocess.PIPE,stderr=subprocess.PIPE) as p:
        frame=0;cursor=0;size=224*224*3
        while True:
            data=p.stdout.read(size)
            if not data:break
            if len(data)!=size:raise ValueError('partial_real_rgb_frame')
            while cursor<len(indices) and indices[cursor]==frame:
                target[cursor]=np.frombuffer(data,dtype=np.uint8).reshape(224,224,3);cursor+=1
            frame+=1
        error=p.stderr.read().decode(errors='replace');code=p.wait()
        if code or cursor!=len(indices):raise ValueError(f'video_decode_failed:{code}:{cursor}/{len(indices)}:{error}')
    return frame


def make_cache(records,destination,on_progress=None):
    import pyarrow.parquet as pq
    dest=Path(destination);dest.mkdir(parents=True,exist_ok=False)
    n=sum(len(r['indices']) for r in records)
    arrays={k:np.lib.format.open_memmap(dest/(k+'.npy'),mode='w+',dtype=np.float32,shape=(n,19)) for k in ['state','action']}
    images={c:np.lib.format.open_memmap(dest/(c+'.npy'),mode='w+',dtype=np.uint8,shape=(n,224,224,3)) for c in CAMERAS}
    ends=np.empty(n,dtype=np.int64);task=np.empty(n,dtype=np.int32);episodes=[];offset=0
    offsets=np.cumsum([0]+[len(r['indices']) for r in records]);finished={}
    def materialize(i,r):
        offset=int(offsets[i])
        table=pq.read_table(r['parquet']);columns={k:table[k].to_pylist() for k in table.column_names};indices=np.asarray(r['indices'],dtype=int);count=len(indices)
        if r['domain']=='real':state,action=map_real(columns,'mm')
        else:state=np.asarray(columns['observation.state'],dtype=np.float32);action=np.asarray(columns['action'],dtype=np.float32)
        arrays['state'][offset:offset+count]=state[indices];arrays['action'][offset:offset+count]=action[indices]
        ends[offset:offset+count]=offset+count;task[offset:offset+count]=r['task_index']
        videos={}
        for c in CAMERAS:
            frames=decode_selected(r['videos'][c],indices,images[c][offset:offset+count])
            if frames!=len(state):raise ValueError('original_video_numeric_frame_count_mismatch')
            videos[c]=dict(path=r['videos'][c],sha256=sha(r['videos'][c]),original_frames=frames)
        return dict(r,offset=offset,frames=count,parquet_sha256=sha(r['parquet']),verified_videos=videos)
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures={pool.submit(materialize,i,r):i for i,r in enumerate(records)}
        for future in as_completed(futures):
            i=futures[future];finished[i]=future.result();offset+=finished[i]['frames']
            if on_progress:on_progress(dict(completed_episodes=len(finished),total_episodes=len(records),written_frames=offset,total_frames=n,decode_workers=8,progress_counts_closed_episodes_not_prefix=True))
    episodes=[finished[i] for i in range(len(records))]
    for a in [*arrays.values(),*images.values()]:a.flush()
    np.save(dest/'end.npy',ends);np.save(dest/'task.npy',task)
    write(dest/'manifest.json',dict(frames=n,episodes=episodes,ready=True,fps=20,images='aspect_preserving_224_uint8_rgb',sample_alignment='same_nearest_timestamp_indices_for_video_state_action',gripper_mm_to_m=.001,arm_units='rad',base_target='static_zero_velocity_explicit_hold_relative_origin',mse_channels='14_arm_rad_and2_gripper_m; exclude_base_velocity_vs_position',source_domains=sorted(set(r['domain'] for r in records))))


class Cache:
    def __init__(self,path):
        self.path=Path(path);self.manifest=json.loads((self.path/'manifest.json').read_text());self.state=np.load(self.path/'state.npy',mmap_mode='r');self.action=np.load(self.path/'action.npy',mmap_mode='r');self.ends=np.load(self.path/'end.npy',mmap_mode='r');self.task=np.load(self.path/'task.npy',mmap_mode='r');self.images={c:np.load(self.path/(c+'.npy'),mmap_mode='r') for c in CAMERAS}
    def get(self,index):
        chunk=np.minimum(index+np.arange(20),self.ends[index]-1)
        return dict(state=np.asarray(self.state[index]).copy(),actions=np.asarray(self.action[chunk]).copy(),prompt=PROMPTS[int(self.task[index])],**{'image/'+c:np.asarray(self.images[c][index]).copy() for c in CAMERAS})


def mixed_schedule(real_tasks,sim_tasks,steps=10000,batch=8,seed=42):
    rng=np.random.default_rng(seed);domains=np.zeros(steps*batch,dtype=np.int8)
    domains[rng.choice(len(domains),size=int(len(domains)*.1),replace=False)]=1;indices=np.empty(len(domains),dtype=np.int64)
    for domain,tasks in enumerate([real_tasks,sim_tasks]):
        classes=sorted(set(map(int,tasks)));positions=np.flatnonzero(domains==domain)
        pools={cls:np.flatnonzero(tasks==cls) for cls in classes}
        for pos in positions:
            cls=int(rng.choice(classes));indices[pos]=int(rng.choice(pools[cls]))
    return domains.reshape(steps,batch),indices.reshape(steps,batch)


def mse_groups(prediction,target,valid=None):
    p=np.asarray(prediction,dtype=np.float64);t=np.asarray(target,dtype=np.float64)
    if p.shape!=t.shape or p.shape[-1]!=19 or not np.isfinite(p).all() or not np.isfinite(t).all():raise ValueError('invalid_aligned_mse_arrays')
    error=(p-t)**2
    if valid is not None:error=error[np.asarray(valid,dtype=bool)]
    per_channel=np.mean(error.reshape(-1,19),axis=0)
    return dict(arm_mse_rad2=float(per_channel[ARMS].mean()),gripper_mse_m2=float(per_channel[GRIPPERS].mean()),gripper_mse_mm2=float(per_channel[GRIPPERS].mean()*1e6),per_channel_mse=per_channel[:16].tolist(),base_excluded=True)
