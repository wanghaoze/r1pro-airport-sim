"""Versioned URDF finger collision bundles; visual meshes and inertia untouched."""
import json
from pathlib import Path
import xml.etree.ElementTree as ET
from .trajectory import sha256


def apply_finger_collision_bundle(root, bundle, urdf_hash):
    directory=Path(bundle).resolve()
    manifest=json.loads((directory/'manifest.json').read_text())
    if manifest['schema']!='real2sim_finger_collision/1' or manifest['urdf_sha256']!=urdf_hash:
        raise ValueError('real2sim_collision_urdf_identity_mismatch')
    changes=[]
    for side in ('left','right'):
        for number in (1,2):
            name=f'{side}_gripper_finger_link{number}'
            body=root.find(f".//body[@name='{name}']")
            old=[g for g in body.findall('geom') if g.get('type')=='box']
            if len(old)!=1:raise ValueError('real2sim_expected_one_original_finger_box')
            old=old[0];attributes=dict(old.attrib);body.remove(old)
            record=manifest['links'][name]
            for i,part in enumerate(record['parts']):
                path=(directory/part['file']).resolve()
                if not path.is_relative_to(directory) or sha256(path)!=part['sha256']:
                    raise ValueError('real2sim_collision_part_identity_mismatch')
                mesh=f'real2sim_{name}_part_{i}'
                ET.SubElement(root.find('asset'),'mesh',name=mesh,file=str(path))
                geom=dict(attributes)
                for key in ('size','pos','quat','euler','axisangle','xyaxes','zaxis'):geom.pop(key,None)
                geom.update(type='mesh',mesh=mesh,pos=record['origin_xyz'],euler=record['origin_rpy'],
                            name=attributes['name'] if i==0 else attributes['name']+f'_part_{i}')
                # URDF rpy is radians; the project compiler already uses radians.
                ET.SubElement(body,'geom',**geom)
            changes.append(dict(link=name,prior_geom=attributes,parts=len(record['parts']),
                                source_mesh_sha256=record['source_mesh_sha256']))
    return dict(bundle=str(directory),manifest_sha256=sha256(directory/'manifest.json'),
                method=manifest['method'],changes=changes,visual_inertia_unchanged=True)
