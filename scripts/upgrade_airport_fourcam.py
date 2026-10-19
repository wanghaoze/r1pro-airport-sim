"""Fork a scene manifest with four measured-intrinsic pinhole cameras.

Published TF frame-to-optical mappings remain explicit unverified assumptions.
No distortion model is guessed. Old datasets and physical geometry are untouched.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET

import numpy as np
from scipy.spatial.transform import Rotation


def digest(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def fmt(v):
    return ' '.join(format(float(x), '.15g') for x in v)


def camera_profile(audit):
    streams = {}
    for name, key, parent, child in (
        ('head_left', '_calib_head_left_camera_info', 'torso_link4', 'camera_head_left'),
        ('head_right', '_calib_head_right_camera_info', 'torso_link4', 'camera_head_right'),
        ('left_wrist', '_hdas_camera_wrist_left_color_camera_info', 'left_gripper_link', 'arm_left'),
        ('right_wrist', '_hdas_camera_wrist_right_color_camera_info', 'right_gripper_link', 'arm_right'),
    ):
        info = audit['intrinsics'][key]
        edges = [e for e in audit['tf_edges'] if e['parent'] == parent and e['child'] == child]
        if len(edges) != 1:
            raise ValueError('Missing or ambiguous camera TF: ' + name)
        e = edges[0]
        streams[name] = dict(width=info['width'], height=info['height'], K=info['k'],
                             D=info['d'], R=info['r'], P=info['p'],
                             reported_distortion_model=info['distortion_model'],
                             distortion_applied=False, parent=parent, published_frame=child,
                             position_m=e['xyz'], quaternion_xyzw=e['quat_xyzw'],
                             optical_frame_mapping='assumed_published_frame_is_optical_NEEDS_REVIEW',
                             intrinsics_source_sha256=info['source_sha256'])
    return dict(profile='r1pro_fourcam_capture_20260922_pinhole_v1',
                calibration_status='measured_intrinsics_published_tf_unverified_optical_mapping',
                deployment_calibration_validated=False, projection='pinhole_K_no_distortion',
                distortion_status='not_applied_head_8_coeff_semantics_unconfirmed',
                training_domain='ideal_pinhole_not_raw_distorted_sensor',
                source_capture_hz=30, fps=20, width=1280, height=720,
                crop=False, resize=False, streams=streams)


def patch_xml(source, target, profile):
    tree = ET.parse(source); root = tree.getroot()
    # All assets continue to reference the original immutable files.
    compiler = root.find('compiler')
    meshdir = compiler.get('meshdir', '') if compiler is not None else ''
    texturedir = compiler.get('texturedir', '') if compiler is not None else ''
    for node in root.iter():
        if 'file' in node.attrib:
            folder = meshdir if node.tag == 'mesh' else texturedir if node.tag == 'texture' else ''
            node.set('file', str((source.parent / folder / node.get('file')).resolve()).replace('\\', '/'))
    if compiler is not None:
        compiler.attrib.pop('meshdir', None); compiler.attrib.pop('texturedir', None)
    # Retain legacy head for existing UI only; it is excluded from new datasets.
    for name, item in profile['streams'].items():
        for parent in root.iter():
            for node in list(parent):
                if node.tag == 'camera' and node.get('name') == name:
                    parent.remove(node)
        mount = root.find(".//body[@name='%s']" % item['parent'])
        if mount is None:
            raise ValueError('Missing mount: ' + item['parent'])
        optical = Rotation.from_quat(item['quaternion_xyzw']).as_matrix()
        mjrot = optical @ np.diag([1., -1., -1.])
        q = Rotation.from_matrix(mjrot).as_quat()[[3, 0, 1, 2]]
        k = item['K']; w = item['width']; h = item['height']
        ET.SubElement(mount, 'camera', name=name, pos=fmt(item['position_m']), quat=fmt(q),
                      resolution=f'{w} {h}', sensorsize=f'{w} {h}',
                      focalpixel=fmt([k[0], k[4]]),
                      principalpixel=fmt([w/2-k[2], h/2-k[5]]))
    visual = root.find('visual')
    if visual is None: visual = ET.SubElement(root, 'visual')
    glob = visual.find('global')
    if glob is None: glob = ET.SubElement(visual, 'global')
    glob.set('offwidth', str(max(1920, int(glob.get('offwidth', '0')))))
    glob.set('offheight', str(max(1536, int(glob.get('offheight', '0')))))
    ET.indent(tree); tree.write(target, encoding='unicode')


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--manifest', type=Path, required=True)
    p.add_argument('--audit', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    manifest = a.manifest.resolve()
    data = json.loads(manifest.read_text())
    rows = data['scenes'] if isinstance(data, dict) else data
    profile = camera_profile(json.loads(a.audit.read_text()))
    profile['audit_sha256'] = digest(a.audit)
    a.output.mkdir(parents=True, exist_ok=False)
    result = []
    for row in rows:
        src = (manifest.parent / row['json']).resolve()
        spec = json.loads(src.read_text()); sid = spec['scene_id']
        if Path(sid).name != sid or sid in ('.', '..'): raise ValueError('Invalid scene id')
        xml = src.with_name(spec.get('scene_file', 'scene.xml'))
        if digest(xml) != spec['xml_sha256']: raise ValueError('Source XML hash mismatch')
        dest = a.output / spec['difficulty'] / sid
        dest.mkdir(parents=True, exist_ok=False)
        patch_xml(xml, dest / 'scene.xml', profile)
        spec['camera'] = copy.deepcopy(profile)
        spec['camera_upgrade_source_json_sha256'] = digest(src)
        spec['camera_upgrade_source_xml_sha256'] = digest(xml)
        spec['xml_sha256'] = digest(dest / 'scene.xml'); spec['scene_file'] = 'scene.xml'
        (dest / 'scene.json').write_text(json.dumps(spec, indent=2), encoding='utf8')
        result.append({'scene_id': sid, 'json': (dest / 'scene.json').relative_to(a.output).as_posix()})
    (a.output / 'manifest.json').write_text(json.dumps({'scenes': result}, indent=2), encoding='utf8')
    (a.output / 'camera_profile.json').write_text(json.dumps(profile, indent=2), encoding='utf8')
    print(json.dumps({'scenes': len(result), 'manifest': str(a.output / 'manifest.json'),
                      'calibration_status': profile['calibration_status']}))


if __name__ == '__main__': main()
