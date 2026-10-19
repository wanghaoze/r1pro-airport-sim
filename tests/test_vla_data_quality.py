import json

from r1pro_teleop.vla.data_quality_audit import audit_manifest


def test_audit_exposes_missing_lift_while_preserving_push_only_scene(tmp_path):
    scene_a = tmp_path / 'scene_a'
    scene_b = tmp_path / 'scene_b'
    scene_a.mkdir()
    scene_b.mkdir()
    (scene_a / 'segments.json').write_text(json.dumps([{'segment_id': 'lift_a', 'phase': 'lift'}]))
    (scene_b / 'segments.json').write_text('[]')
    rows = [{'scene_id': sid, 'trace': str(directory / 'trace.h5'), 'training_ready': True,
             'split': 'train', 'skill': 'initialize_posture', 'phase': 'initial_tuck', 'frames': 30,
             'initial_posture_qualification': {'qualification': 'initial_tuck_after_physical_settle'}}
            for sid, directory in [('a', scene_a), ('b', scene_b)]]
    manifest = tmp_path / 'manifest.jsonl'
    manifest.write_text('\n'.join(json.dumps(row) for row in rows))
    result = audit_manifest(manifest)
    assert result['all_scenes_initialize']
    assert not result['all_source_lifts_qualified']
    assert result['by_scene']['a']['unqualified_or_excluded_lift_source_ids'] == ['lift_a']
    assert result['by_scene']['b']['source_lift_operations'] == 0
    rows.append({'scene_id': 'a', 'trace': str(scene_a / 'trace.h5'), 'training_ready': True,
        'split': 'train', 'skill': 'grasp_lift_tray', 'phase': 'lift', 'frames': 40,
        'source_segment_id': 'lift_a', 'verified_lift_takeoff': {'qualification': 'verified_lift_takeoff'}})
    manifest.write_text('\n'.join(json.dumps(row) for row in rows))
    result = audit_manifest(manifest)
    assert result['all_source_lifts_qualified']
    assert result['qualified_lift_operations'] == 1
    assert result['ready_frames'] == 100
    assert result['by_skill']['grasp_lift_tray'] == {'segments': 1, 'frames': 40}
