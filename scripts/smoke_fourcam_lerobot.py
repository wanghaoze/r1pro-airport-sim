"""Stationary camera/loader integration fixture, never a task demonstration."""
import argparse
import json
from pathlib import Path
import numpy as np
from lerobot.datasets.lerobot_dataset import LeRobotDataset
from r1pro_teleop.airport_fsm.contracts import NAMES, camera_shapes
from r1pro_teleop.airport_fsm.registry import config_for
from r1pro_teleop.airport_fsm.runtime import Runtime
from r1pro_teleop.airport_fsm.exporter import video_metadata

p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--scene-id',required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
scene=a.root/'scenes'/a.scene_id
spec=json.loads((scene/'scene.json').read_text()); shapes=camera_shapes(spec)
a.output.mkdir(parents=True,exist_ok=False)
features={'observation.state':{'dtype':'float32','shape':(16,),'names':NAMES},'action':{'dtype':'float32','shape':(16,),'names':NAMES}}
for name,shape in shapes.items():features['observation.images.'+name]={'dtype':'video','shape':shape,'names':['height','width','channels']}
path=a.output/'dataset';repo='local/fourcam-integration-fixture'
r=Runtime(spec,scene/'mobile.xml',config_for(a.root),render=True)
ds=None
try:
    ds=LeRobotDataset.create(repo_id=repo,root=path,robot_type='r1pro_sim_fixture',fps=20,features=features,use_videos=True,vcodec='h264',video_backend='pyav',streaming_encoding=True,image_writer_threads=2)
    ds._streaming_encoder.crf=18
    for i in range(20):
        frame={'observation.state':r.sim.target.astype(np.float32),'action':r.sim.target.astype(np.float32),'task':'TEST FIXTURE stationary camera export; NOT a task demonstration'}
        # State must be measured, not the command, even in a stationary fixture.
        frame['observation.state']=r.sim.state().astype(np.float32)
        for name in shapes:frame['observation.images.'+name]=r.sim.image(name)
        ds.add_frame(frame)
        r.sim.apply_target()
        for _ in range(r.sim.nstep):r.mj.mj_step(r.m,r.d);r.mj.mj_forward(r.m,r.d)
    ds.save_episode();ds.finalize();ds.stop_image_writer();ds=None
    loaded=LeRobotDataset(repo_id=repo,root=path,video_backend='pyav')
    for i in (0,len(loaded)-1):
        sample=loaded[i]
        for name,(h,w,c) in shapes.items():assert tuple(sample['observation.images.'+name].shape)==(c,h,w)
    videos=video_metadata(path,shapes)
    assert len(videos)==4 and all(v['frames']==20 for v in videos)
    report={'fixture_only':True,'training_candidate':False,'task_success_tested':False,'frames':len(loaded),'official_loader_first_last':True,'videos':videos,'camera_calibration':spec['camera']}
    (a.output/'report.json').write_text(json.dumps(report,indent=2));print(json.dumps({k:v for k,v in report.items() if k!='camera_calibration'},indent=2))
finally:
    if ds is not None:ds.stop_image_writer()
    r.close()
