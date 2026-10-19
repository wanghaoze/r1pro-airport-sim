"""Render four native views and verify camera-only upgrade preserves physics."""
import argparse
import json
from pathlib import Path
import mujoco
import numpy as np
from PIL import Image

p=argparse.ArgumentParser();p.add_argument('--scene',type=Path,required=True);p.add_argument('--source',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
spec=json.loads(a.scene.read_text());a.output.mkdir(parents=True,exist_ok=False)
m=mujoco.MjModel.from_xml_path(str(a.scene.with_name(spec['scene_file']).resolve()))
old=mujoco.MjModel.from_xml_path(str(a.source.resolve()))
checks={}
for name in ('body_mass','body_inertia','body_pos','body_quat','geom_pos','geom_quat','geom_friction','geom_contype','geom_conaffinity','jnt_range','actuator_gainprm','actuator_biasprm','key_qpos','key_ctrl'):
    np.testing.assert_array_equal(getattr(m,name),getattr(old,name));checks[name]=True
d=mujoco.MjData(m);mujoco.mj_resetDataKeyframe(m,d,m.key('teleop_home').id);mujoco.mj_forward(m,d)
cams={}
for name,item in spec['camera']['streams'].items():
    with mujoco.Renderer(m,height=item['height'],width=item['width']) as renderer:
        renderer.update_scene(d,camera=name)
        im=renderer.render().copy()
    assert im.shape==(item['height'],item['width'],3)
    assert im.std()>2
    Image.fromarray(im).save(a.output/(name+'.png'))
    cid=m.camera(name).id
    cams[name]={'shape':list(im.shape),'std':float(im.std()),'world_position':d.cam_xpos[cid].tolist(),'forward':(-d.cam_xmat[cid].reshape(3,3)[:,2]).tolist()}
report={'physics_unchanged':checks,'cameras':cams,'calibration_status':spec['camera']['calibration_status'],'deployment_calibration_validated':False}
(a.output/'report.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
