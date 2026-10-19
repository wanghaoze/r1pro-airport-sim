"""Decompose project-owned URDF meshes into portable convex collision parts."""
import argparse
import hashlib
import importlib.metadata
import os
from pathlib import Path
import sys
import time
import xml.etree.ElementTree as ET
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from r1pro_teleop.real2sim.trajectory import sha256,write_json


def load_obj(path):
    vertices=[];faces=[]
    for line in path.read_text().splitlines():
        fields=line.split()
        if not fields:continue
        if fields[0]=='v':vertices.append([float(x) for x in fields[1:4]])
        elif fields[0]=='f':
            indices=[int(x.split('/')[0]) for x in fields[1:]]
            indices=[i-1 if i>0 else len(vertices)+i for i in indices]
            faces.extend([[indices[0],indices[i],indices[i+1]] for i in range(1,len(indices)-1)])
    return np.asarray(vertices,dtype=np.float64),np.asarray(faces,dtype=np.int32)


def main():
    import coacd
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('urdf','mesh-root','output'):p.add_argument('--'+n,required=True)
    a=p.parse_args();out=Path(a.output);out.mkdir(parents=True,exist_ok=False)
    params=dict(threshold=.001,real_metric=True,preprocess_mode='auto',seed=0,mcts_iterations=100)
    write_json(out/'plan.json',dict(params=params,pid=os.getpid(),started_unix=time.time(),
                                  note='1mm mesh approximation parameter; not task acceptance tolerance'))
    coacd.set_log_level('warn');robot=ET.parse(a.urdf);records={};cache={};code=1
    try:
        for side in ('left','right'):
            for number in (1,2):
                name=f'{side}_gripper_finger_link{number}'
                collision=robot.find(f"./link[@name='{name}']/collision")
                mesh=collision.find('geometry/mesh');origin=collision.find('origin')
                if mesh.get('scale','1 1 1')!='1 1 1':raise ValueError('real2sim_unscaled_source_finger_required')
                source=Path(a.mesh_root)/Path(mesh.get('filename')).name
                v,f=load_obj(source);key=hashlib.sha256(v.tobytes()+f.tobytes()).hexdigest()
                if key not in cache:cache[key]=coacd.run_coacd(coacd.Mesh(v,f),**params)
                parts=[]
                for i,(vertices,faces) in enumerate(cache[key]):
                    file=out/f'{name}_{i:03d}.obj'
                    text=['v '+' '.join(format(x,'.17g') for x in point) for point in vertices]
                    text+=['f '+' '.join(str(int(x)+1) for x in face) for face in faces]
                    file.write_text('\n'.join(text)+'\n');parts.append(dict(file=file.name,sha256=sha256(file)))
                records[name]=dict(source_mesh=str(source.resolve()),source_mesh_sha256=sha256(source),
                    origin_xyz=origin.get('xyz','0 0 0'),origin_rpy=origin.get('rpy','0 0 0'),parts=parts)
                write_json(out/'status.json',dict(link=name,parts=len(parts),heartbeat_unix=time.time()))
        write_json(out/'manifest.json',dict(schema='real2sim_finger_collision/1',urdf_sha256=sha256(a.urdf),
            method='CoACD_convex_parts_from_URDF_collision_mesh_not_single_convex_hull',
            package_version=importlib.metadata.version('coacd'),params=params,links=records))
        code=0
    finally:write_json(out/'exit.json',dict(exit_code=code,finished_unix=time.time()))


if __name__=='__main__':main()
