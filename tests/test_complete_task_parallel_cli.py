"""Reuse checks reject changed source-plan identity and missing RGB verification."""
import importlib.util,json
from pathlib import Path
import pytest
spec=importlib.util.spec_from_file_location('task_parallel_cli',Path(__file__).resolve().parents[1]/'scripts/materialize_complete_task_actions_parallel.py')
cli=importlib.util.module_from_spec(spec);spec.loader.exec_module(cli)
def fixture(tmp_path):
    output=tmp_path/'old';root=output/'cases/s';root.mkdir(parents=True);(output/'plans').mkdir()
    task=dict(scene_id='s',split='train',trace_sha256='trace',result_sha256='result');case=dict(original_inventory=task,plan={'fixture':True})
    plan=output/'plans/s.jsonl';plan.write_text(json.dumps(case)+'\n')
    label=tmp_path/'label.json';label.write_text('{}')
    native=root/'native_action_clips/source.mkv';native.parent.mkdir();native.write_bytes(b'fixture')
    manifest=dict(split='train',label_spec_sha256=cli.digest(label),all_parquet_values_verified={'verified':True},
        actual_training_rgb_derivation={'verified':True},training_video_encoding_verification={'verified':True},
        episodes=[dict(scene_id='s',source_trace_sha256='trace',original_task_result_sha256='result',
                       native_action_clips={'head_left':dict(path=str(native),sha256=cli.digest(native))})],
        input_plan_sha256=cli.digest(plan),repo_id='test',counts={},action_vocabulary=[])
    (root/'airport_training_manifest.json').write_text(json.dumps(manifest))
    return root,case,label,manifest
def test_reuse_binds_plan_case_and_current_native_bytes(tmp_path,monkeypatch):
    root,case,label,m=fixture(tmp_path);monkeypatch.setattr(cli,'action_vocabulary',lambda x:{})
    monkeypatch.setattr(cli,'audit_task_parquet',lambda *a,**k:{'verified':True})
    result=cli.verified_reuse(root,case,label)
    assert result['reuse_verified'] and result['current_resource_inventory']
    (root/'native_action_clips/source.mkv').write_bytes(b'changed')
    with pytest.raises(ValueError,match='native_clip_changed'):cli.verified_reuse(root,case,label)
def test_reuse_cannot_change_split_or_missing_image_audit(tmp_path,monkeypatch):
    root,case,label,m=fixture(tmp_path);m['actual_training_rgb_derivation']['verified']=False
    (root/'airport_training_manifest.json').write_text(json.dumps(m))
    with pytest.raises(ValueError,match='not_verified'):cli.verified_reuse(root,case,label)
