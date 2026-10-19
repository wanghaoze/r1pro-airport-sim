import importlib.util
from pathlib import Path
import pytest
import json

spec = importlib.util.spec_from_file_location('collector', Path(__file__).parents[1]/'scripts/collect_airport_batches.py')
collector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(collector)


def test_400_scenes_accounted_exactly_once():
    rows = [{'scene_id': f's{i:03d}'} for i in range(400)]
    result = collector.batches(rows, 8)
    assert len(result) == 50
    assert [s for group in result for s in group] == [r['scene_id'] for r in rows]


def test_tail_and_invalid_registry():
    assert collector.batches([{'scene_id': str(i)} for i in range(9)], 8)[-1] == ['8']
    with pytest.raises(ValueError, match='duplicate'):
        collector.batches([{'scene_id': 'x'}, {'scene_id': 'x'}], 8)
    with pytest.raises(ValueError, match='positive'):
        collector.batches([], 0)


def test_export_infrastructure_error_is_not_silently_skipped(tmp_path):
    assert not collector.only_quarantined_exports(tmp_path)
    (tmp_path/'quality').mkdir()
    (tmp_path/'quality/export_summary.json').write_text(json.dumps({
        'export_failures_this_run': [{'scene_id':'s1','attempt':'a000','error':'disk full'}]}))
    assert not collector.only_quarantined_exports(tmp_path)
    q=tmp_path/'attempts/s1/a000/export_quality.json'
    q.parent.mkdir(parents=True)
    q.write_text(json.dumps({'status':'rejected','failure_code':'camera_low_texture_needs_review'}))
    assert collector.only_quarantined_exports(tmp_path)
