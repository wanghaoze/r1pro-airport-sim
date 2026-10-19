import importlib.util,json
from pathlib import Path
import pytest
SCRIPT=Path(__file__).resolve().parents[1]/'scripts/maintain_three_table_server_index.py'
spec=importlib.util.spec_from_file_location('indexer',SCRIPT);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


def test_resolved_video_and_trace_paths_unique_and_empty_index_has_zero_lines(tmp_path,monkeypatch):
    root=tmp_path/'root';root.mkdir();out=root/'index';out.mkdir();(root/'sub').mkdir()
    video=root/'head_left.mp4';video.write_bytes(b'fixture')
    trace=root/'trace.h5';trace.write_bytes(b'fixture')
    original=Path.rglob
    def scan(path,pattern):
        if path==root and pattern=='*.mp4':return iter([video,root/'sub/../head_left.mp4',video])
        if path==root and pattern=='trace.h5':return iter([trace,root/'sub/../trace.h5'])
        return original(path,pattern)
    monkeypatch.setattr(Path,'rglob',scan)
    result=m.snapshot(root,out)
    assert result['video_count']==result['trajectory_count']==1
    assert (out/'SERVER_VIDEO_PATHS.txt').read_text().splitlines()==[str(video.resolve())]
    assert (out/'SERVER_TRAJECTORY_PATHS.txt').read_text().splitlines()==[str(trace.resolve())]
    assert result['current']['registered'] is False
    empty=tmp_path/'empty';empty.mkdir();emptyout=empty/'index';emptyout.mkdir();m.snapshot(empty,emptyout)
    assert (emptyout/'SERVER_VIDEO_PATHS.txt').read_bytes()==b''


def test_explicit_pipeline_is_current_and_external_training_status_falls_back_status(tmp_path):
    root=tmp_path/'root';root.mkdir();new=root/'NEW34';new.mkdir();old=root/'B29';old.mkdir();out=root/'index';out.mkdir()
    (new/'workflow_status.json').write_text(json.dumps(dict(phase='main_pipeline',updated_unix=123)))
    (new/'pipeline_status.json').write_text(json.dumps(dict(stage='evaluating_new_checkpoint',heartbeat_unix=456)))
    (old/'training_status.json').write_text(json.dumps(dict(status='milestone_checkpoint',actual_completed_updates=10)))
    training=new/'training_options.json';training.write_text(json.dumps(dict(run_dir=str(new),external_training_run=str(old))))
    workflow=new/'workflow_options.json';workflow.write_text(json.dumps(dict(workflow_dir=str(new),training_options=str(training))))
    result=m.snapshot(root,out,workflow)
    assert result['current']['stage']=='evaluating_new_checkpoint'
    assert result['current']['actual_completed_updates']==10
    assert result['current']['training']['stage']=='milestone_checkpoint'
    assert result['current']['pipeline']['heartbeat_unix']==456
    assert result['current']['workflow']['heartbeat_unix']==123
    assert result['current']['optimizer_status_is_recorded_state_not_live_process_inference']
    assert any(s['stage']=='milestone_checkpoint' for s in result['states'])
    (new/'pipeline_status.json').unlink()
    result=m.snapshot(root,out,workflow)
    assert result['current']['stage']=='main_pipeline'
    assert 'read_error' in result['current']['pipeline']


def test_unique_atomic_temp_keeps_stale_crash_evidence_and_target_complete(tmp_path):
    target=tmp_path/'status.json';target.write_text('old');stale=tmp_path/'status.json.writing';stale.write_text('partial')
    m.atomic(target,'new complete')
    assert target.read_text()=='new complete' and stale.read_text()=='partial'


def test_missing_registered_workflow_is_not_replaced_with_newest_history(tmp_path):
    root=tmp_path/'root';root.mkdir();out=root/'index';out.mkdir()
    (root/'training_status.json').write_text(json.dumps(dict(status='training',actual_completed_updates=100)))
    result=m.snapshot(root,out,root/'missing_workflow_options.json')
    assert result['current']['stage']=='registered_current_workflow_unavailable'
    assert result['current'].get('actual_completed_updates') is None
