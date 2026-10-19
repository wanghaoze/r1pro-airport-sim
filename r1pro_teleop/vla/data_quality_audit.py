"""Read-only skill/qualification coverage audit for a prepared training manifest."""
from collections import defaultdict
from pathlib import Path
import argparse
import json


def audit_manifest(path):
    rows = [json.loads(line) for line in Path(path).read_text(encoding='utf-8').splitlines()]
    ready = [row for row in rows if row['training_ready'] and row['split'] == 'train']
    if not ready:
        raise ValueError('no_ready_training_segments')
    skills, phases, scenes = defaultdict(lambda: {'segments': 0, 'frames': 0}), defaultdict(lambda: {'segments': 0, 'frames': 0}), {}
    for row in ready:
        for counter, key in ((skills, row['skill']), (phases, row['phase'])):
            counter[key]['segments'] += 1
            counter[key]['frames'] += row['frames']
        sid = row['scene_id']
        scene = scenes.setdefault(sid, {'initialize_segments': 0, 'initialize_frames': 0,
            'lift_segments': 0, 'lift_frames': 0, 'qualified_lift_source_ids': set(),
            'source_lift_ids': set(), 'trace': row['trace']})
        if row['skill'] == 'initialize_posture':
            scene['initialize_segments'] += 1
            scene['initialize_frames'] += row['frames']
            if not row.get('initial_posture_qualification'):
                raise ValueError('initial_posture_qualification_missing')
        if row['phase'] == 'lift':
            scene['lift_segments'] += 1
            scene['lift_frames'] += row['frames']
            if row.get('verified_lift_takeoff'):
                scene['qualified_lift_source_ids'].add(row['source_segment_id'])
    for sid, scene in scenes.items():
        source_segments = json.loads(Path(scene['trace']).with_name('segments.json').read_text())
        scene['source_lift_ids'] = {segment['segment_id'] for segment in source_segments if segment['phase'] == 'lift'}
        scene['unqualified_or_excluded_lift_source_ids'] = sorted(scene['source_lift_ids'] - scene['qualified_lift_source_ids'])
        scene['source_lift_operations'] = len(scene['source_lift_ids'])
        scene['qualified_lift_operations'] = len(scene['qualified_lift_source_ids'])
        scene['qualified_lift_source_ids'] = sorted(scene['qualified_lift_source_ids'])
        scene['source_lift_ids'] = sorted(scene['source_lift_ids'])
    return {'manifest': str(Path(path).resolve()), 'ready_segments': len(ready),
        'ready_frames': sum(row['frames'] for row in ready), 'scene_count': len(scenes),
        'by_skill': dict(skills), 'by_phase': dict(phases), 'by_scene': scenes,
        'all_scenes_initialize': all(scene['initialize_segments'] > 0 for scene in scenes.values()),
        'all_source_lifts_qualified': all(not scene['unqualified_or_excluded_lift_source_ids'] for scene in scenes.values()),
        'source_lift_operations': sum(scene['source_lift_operations'] for scene in scenes.values()),
        'qualified_lift_operations': sum(scene['qualified_lift_operations'] for scene in scenes.values())}


def excluded_lift_contact_details(audit):
    import h5py
    import numpy as np
    details = []
    for sid, scene in audit['by_scene'].items():
        excluded = set(scene['unqualified_or_excluded_lift_source_ids'])
        if not excluded:
            continue
        trace = Path(scene['trace'])
        segments = json.loads(trace.with_name('segments.json').read_text())
        with h5py.File(trace) as f:
            for segment in segments:
                if segment['segment_id'] not in excluded:
                    continue
                a, b = segment['start_frame'], segment['end_frame']
                tray = int(f['target_tray'][a])
                support = f['support_contact'][a:b, tray]
                nonzero, airborne = np.flatnonzero(support != 0), np.flatnonzero(support == 0)
                last = int(nonzero[-1]) if len(nonzero) else None
                first = int(airborne[0]) if len(airborne) else None
                bottom = f['min_z'][a:b, tray]
                returns = nonzero[nonzero > first] if first is not None else []
                details.append({'scene_id': sid, 'segment_id': segment['segment_id'], 'start_frame': a,
                    'end_frame': b, 'frame0_min_z_m': float(f['min_z'][0, tray]),
                    'start_min_z_m': float(bottom[0]),
                    'first_airborne_offset': first, 'last_supported_offset': last,
                    'continuous_airborne_tail_frames': len(support) - last - 1 if last is not None else len(support),
                    'max_supported_height_vs_frame0_m': float(np.max(bottom[nonzero]-f['min_z'][0, tray])) if len(nonzero) else None,
                    'recontact_offsets': list(map(int, returns)),
                    'max_recontact_bottom_m': float(np.max(bottom[returns])) if len(returns) else None,
                    'max_recontact_height_vs_start_m': float(np.max(bottom[returns]-bottom[0])) if len(returns) else None,
                    'table_contact_at_last_support': float(f['table_contact'][a+last, tray]) if last is not None else None,
                    'minimum_bilateral_force_n': float(np.min(f['gripper_contact_force'][a:b, tray])),
                    'all_intervals_complete': bool(f['transition_completed'][a:b].all()),
                    'recovery': bool(f['recovery'][a:b].any()),
                    'endpoint_support': float(f['support_contact'][b, tray]),
                    'endpoint_clearance_m': float(f['min_z'][b, tray]-f['min_z'][0, tray])})
    return details


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--contact-details', action='store_true')
    args = parser.parse_args()
    result = audit_manifest(args.manifest)
    if args.contact_details:
        result['excluded_lift_contact_details'] = excluded_lift_contact_details(result)
    with Path(args.output).open('x', encoding='utf-8') as stream:
        json.dump(result, stream, indent=2)
    print(json.dumps({key: value for key, value in result.items() if key != 'by_scene'}))


if __name__ == '__main__':
    main()
