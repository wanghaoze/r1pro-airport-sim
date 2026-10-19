"""Static inspection images of saved physics states; not a training replay."""
import argparse
import json
from pathlib import Path
import h5py
import mujoco
import numpy as np
from PIL import Image
from r1pro_teleop.airport_fsm.registry import config_for
from r1pro_teleop.airport_fsm.runtime import Runtime

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--root',type=Path,required=True)
p.add_argument('--scene-id',required=True)
p.add_argument('--attempt',default='a000')
p.add_argument('--output',type=Path,required=True)
a=p.parse_args()
folder=a.root/'scenes'/a.scene_id
episode=a.root/'attempts'/a.scene_id/a.attempt
result=json.loads((episode/'result.json').read_text())
assert result.get('physics_success') and not result.get('recovery_used'), 'Requires a clean completed episode'
spec=json.loads((folder/'scene.json').read_text())
a.output.mkdir(parents=True,exist_ok=False)
r=Runtime(spec,folder/'mobile.xml',config_for(a.root),render=True)
camera=mujoco.MjvCamera()
camera.lookat[:]=[.4,-.3,.8]
camera.distance=4.3;camera.azimuth=140;camera.elevation=-35
try:
    with h5py.File(episode/'trace.h5') as f, mujoco.Renderer(r.m,height=900,width=1600) as renderer:
        force=f['gripper_contact_force'][:]
        bilateral=np.any(np.all(force>.5,axis=2),axis=1)
        indices={'initial':0,'contact':int(np.flatnonzero(bilateral)[0]),'final':len(f['qpos'])-1}
        for label,index in indices.items():
            r.d.qpos[:]=f['qpos'][index]
            mujoco.mj_forward(r.m,r.d)
            renderer.update_scene(r.d,camera=camera,scene_option=r.sim.options)
            Image.fromarray(renderer.render()).save(a.output/(label+'_overview.png'))
            for name in r.sim.camera_shapes:
                Image.fromarray(r.sim.image(name)).save(a.output/(label+'_'+name+'.png'))
        (a.output/'source.json').write_text(json.dumps({'purpose':'static_inspection_only_not_training_video','source':str(episode),'frames':indices,'physics_result':result},indent=2))
finally:
    r.close()
