"""Fork scenes; repair floating stacked initializations before collection only.

Uses settled XY/Z/yaw proposals projected upright, then requires the unchanged
two-second preflight. Never modifies an Episode or moves objects during rollout.
"""
import argparse
import copy
import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET
import numpy as np
import mujoco
from r1pro_teleop.airport_fsm.contracts import atomic_json, sha256_file
from r1pro_teleop.airport_fsm.registry import scene_rows, config_for
from r1pro_teleop.airport_fsm.runtime import Runtime
from r1pro_teleop.airport_fsm.geometry import quat_yaw_tilt


def write_xml(src, dst, spec, proposed=None):
    root=ET.parse(src).getroot()
    for node in root.iter():
        if 'file' in node.attrib:node.set('file',str((src.parent/node.get('file')).resolve()))
    if proposed is not None:
        m=mujoco.MjModel.from_xml_path(str(src.resolve()))
        key=root.find("keyframe/key[@name='teleop_home']")
        q=np.fromstring(key.get('qpos'),sep=' ')
        for tray,pose in zip(spec['trays'],proposed):
            yaw,_=quat_yaw_tilt(pose[3:]);quat=[math.cos(yaw/2),0,0,math.sin(yaw/2)]
            body=root.find(".//body[@name='%s']"%tray['tray_id'])
            body.set('pos',' '.join(map(str,pose[:3])));body.set('quat',' '.join(map(str,quat)))
            bid=m.body(tray['tray_id']).id;jid=int(m.body_jntadr[bid]);adr=int(m.jnt_qposadr[jid])
            assert m.jnt_type[jid]==mujoco.mjtJoint.mjJNT_FREE
            q[adr:adr+7]=[*pose[:3],*quat]
            tray.update(position_world=pose[:3].tolist(),yaw_world=float(yaw),roll=0.,pitch=0.)
        key.set('qpos',' '.join(map(str,q)))
    ET.indent(root);ET.ElementTree(root).write(dst,encoding='unicode')


def main():
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    a.output.mkdir(parents=True,exist_ok=False)
    cfg=config_for(a.root);entries=[];repairs=[]
    for row in scene_rows(a.root):
        folder=a.root/'scenes'/row['scene_id'];spec=json.loads((folder/'scene.json').read_text())
        pf=json.loads((folder/'preflight.json').read_text());src=folder/'mobile.xml'
        target=a.output/spec['difficulty']/row['scene_id'];target.mkdir(parents=True)
        spec['initialization_revision']={'source_xml_sha256':sha256_file(src),'source_scene_json_sha256':sha256_file(folder/'scene.json'),'method':'unchanged'}
        write_xml(src,target/'scene.xml',spec)
        if not pf['valid'] and pf.get('failure_code')=='initial_scene_settle_drift':
            original=copy.deepcopy(spec['trays']);steps=[];valid=False
            # Start with a centered stack instead of projecting a tilted nested
            # tray upright at a height that would intersect the lower rim.
            ids={t['tray_id']:i for i,t in enumerate(spec['trays'])}
            proposed=np.array([[*t['position_world'],math.cos(t['yaw_world']/2),0,0,math.sin(t['yaw_world']/2)] for t in spec['trays']])
            for i,tray in enumerate(spec['trays']):
                if tray.get('support_parent') in ids:
                    lower=ids[tray['support_parent']]
                    proposed[i,:2]=proposed[lower,:2];proposed[i,3:]=proposed[lower,3:]
                    proposed[i,2]=proposed[lower,2]+.11
            staging=target/'centered_stack.xml'
            write_xml(target/'scene.xml',staging,spec,proposed);staging.replace(target/'scene.xml')
            for attempt in range(8):
                r=None
                try:
                    r=Runtime(spec,target/'scene.xml',cfg)
                    expected=r.observation()['tray_pose'].copy();r.guard();r.wait(2.)
                    e=r.observation();poses=e['tray_pose'];drift=np.linalg.norm(poses[:,:3]-expected[:,:3],axis=1)
                    tilts=[float(np.rad2deg(quat_yaw_tilt(q[3:])[1])) for q in poses]
                    steps.append({'round':attempt,'drift_m':drift.tolist(),'tilt_deg':tilts,'support':e['support_contact'].tolist()})
                    if max(drift)<=.005 and max(tilts)<=5 and np.all(e['support_contact']>0):valid=True;break
                    if np.any(e['floor_contact']):break
                    if any(r.g.support_table(x[:3]) is None for x in poses):break
                    # Proposal only; subsequent loop validates from zero velocity upright.
                    proposed=poses.copy()
                    if max(tilts)>5:
                        # Re-sample an unstable overlap as a centered upright stack.
                        # This is an explicit scene revision, not a relaxed tilt test.
                        ids={t['tray_id']:i for i,t in enumerate(spec['trays'])}
                        for i,tray in enumerate(spec['trays']):
                            if tray.get('support_parent') in ids:
                                lower=ids[tray['support_parent']]
                                proposed[i,:2]=proposed[lower,:2]
                                proposed[i,3:]=proposed[lower,3:]
                                proposed[i,2]=max(original[i]['position_world'][2],proposed[lower,2]+.11)
                except Exception as exc:
                    steps.append({'round':attempt,'error':str(exc)});break
                finally:
                    if r:r.close()
                staging=target/f'proposal_{attempt}.xml'
                write_xml(target/'scene.xml',staging,spec,proposed)
                # Only our new unregistered candidate scene is revised.
                staging.replace(target/'scene.xml')
            spec['initialization_revision'].update(method='centered_stack_then_projected_upright_settled_initial_state',original_trays=original,verified_stable=valid,steps=steps)
            repairs.append({'scene_id':row['scene_id'],'valid':valid,'steps':steps})
            print(json.dumps(repairs[-1]),flush=True)
        spec['xml_sha256']=sha256_file(target/'scene.xml');spec['scene_file']='scene.xml'
        atomic_json(target/'scene.json',spec)
        entries.append({'scene_id':row['scene_id'],'json':(target/'scene.json').relative_to(a.output).as_posix()})
    atomic_json(a.output/'manifest.json',{'scenes':entries})
    atomic_json(a.output/'repair_report.json',{'repaired':sum(x['valid'] for x in repairs),'attempted':len(repairs),'scenes':repairs})


if __name__=='__main__':main()
