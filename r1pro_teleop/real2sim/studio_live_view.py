"""Read-only native body poses and cameras; never drives physics or fabricates frames."""
import base64
import io
import json
import time
import numpy as np
from PIL import Image

def image_url(rgb):
    image=Image.fromarray(np.asarray(rgb)[:,:,:3].astype(np.uint8));image.thumbnail((384,216))
    buf=io.BytesIO();image.save(buf,format='JPEG',quality=65)
    return 'data:image/jpeg;base64,'+base64.b64encode(buf.getvalue()).decode()

def publish(out,cases,views,readers,origins,cameras,presentation,states,frame,started,cpu):
    if len(cases)!=1:raise ValueError('live_view_requires_one_room')
    p,q=map(cpu,views[0].get_world_poses());bodies={}
    for name,index in readers[0].index.items():
        bodies[name]={'position':(p[index]-origins[0]).tolist(),'quaternionWxyz':q[index].tolist()}
    images={name:image_url(cam.get_rgba()) for ri,name,cam in cameras if ri==0 and name!='head_right'}
    images['overview']=image_url(presentation[0].get_rgba())
    data=dict(frame=frame,frameSampledAt=time.time(),simulationSeconds=frame/20,rolloutWallSeconds=time.monotonic()-started,
        originalRoomId=cases[0]['original_room_id'],bodies=bodies,state19=states[0].tolist(),images=images,
        poseSource='measured_native_physx',geometry='source_geometry_with_measured_body_poses',quaternionOrder='wxyz')
    path=out/'live.json';tmp=out/'live.tmp';tmp.write_text(json.dumps(data,allow_nan=False));tmp.replace(path)
