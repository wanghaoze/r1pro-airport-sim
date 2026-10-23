import io
import json
import sys
import threading
import time
import urllib.request
from http.server import HTTPServer
from pathlib import Path

import numpy as np
import pytest
from r1pro_teleop.vla.inference_timing import read_events, summarize, video_timing


def test_legacy_layers_are_separate_and_video_does_not_double_count(tmp_path):
    rows=[dict(unix=1,latency_seconds=.4,camera_sha256={},actions_sha256='abc'),
          dict(unix=2,latency_seconds=.6,requestId='one',error=None),
          dict(unix=3,latency_seconds=30,requestId='two',error='timeout'),
          dict(unix=4,latency_seconds=99)]
    (tmp_path/'inference_events.jsonl').write_text('\n'.join(map(json.dumps,rows)))
    events,stage,result=video_timing(tmp_path)
    assert stage=='model_adapter' and len(events)==1
    assert result['stages']['model_adapter']['mean_seconds']==.4
    assert result['stages']['http_roundtrip']['mean_seconds']==.6
    assert result['stages']['http_roundtrip']['error_count']==1
    assert result['unknown_stage_count']==1 and not result['stages_additive']
    assert not result['gpu_kernel_timing']


@pytest.mark.parametrize('value',[None,True,-1,float('nan'),float('inf'),'0.3'])
def test_invalid_latency_not_zero_or_success(value):
    summary=summarize([dict(stage='model_adapter',latency_seconds=value)])
    group=summary['stages']['model_adapter']
    assert group['invalid_latency_count']==1 and group['success_count']==0
    assert group['mean_seconds'] is None and group['p95_seconds'] is None


def test_shared_service_absence_and_partial_log_are_explicit(tmp_path):
    path=tmp_path/'inference_events.jsonl'
    path.write_text(json.dumps(dict(stage='http_roundtrip',unix=1,latency_seconds=.7))+'\n{"stage":\n[]\n')
    events,stage,result=video_timing(tmp_path)
    assert stage=='http_roundtrip' and len(events)==1
    assert result['malformed_line_count']==2
    assert result['stages']['model_adapter']['mean_seconds'] is None
    unknown=summarize([dict(stage='unrecognized',requestId='legacy-looking',latency_seconds=1)])
    assert unknown['unknown_stage_count']==1


def test_explicit_model_and_transport_logs_keep_percentiles_separate(tmp_path):
    for file,stage,values in [('inference_events.jsonl','http_roundtrip',[.6,.8]),
                              ('inference_model_events.jsonl','model_adapter',[.2,.4])]:
        (tmp_path/file).write_text('\n'.join(json.dumps(dict(stage=stage,unix=i,requestId=str(i),latency_seconds=v)) for i,v in enumerate(values)))
    rows,malformed=read_events(tmp_path);result=summarize(rows,malformed)
    assert len(rows)==4
    assert result['stages']['model_adapter']['p50_seconds']==pytest.approx(.3)
    assert result['stages']['http_roundtrip']['p95_seconds']==pytest.approx(.79)
    assert len(video_timing(tmp_path)[0])==2


def test_actual_http_handler_records_model_stage_and_preserves_actions(tmp_path,monkeypatch):
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
    import studio_model_http as server_module
    class FakeAdapter:
        family='pi05'
        def __init__(self,entry):pass
        def infer(self,sample,room):return np.zeros((20,19),np.float32)
    class OneRequestServer(HTTPServer):
        def serve_forever(self):
            self.timeout=3
            try:self.handle_request()
            finally:self.server_close()
    monkeypatch.setattr(server_module,'Adapter',FakeAdapter)
    monkeypatch.setattr(server_module,'HTTPServer',OneRequestServer)
    monkeypatch.setattr(sys,'argv',['studio_model_http','--run',str(tmp_path)])
    (tmp_path/'checkpoints.json').write_text(json.dumps([dict(id='test',family='pi05')]))
    (tmp_path/'request.json').write_text(json.dumps(dict(payload={})))
    errors=[]
    def start():
        try:server_module.main()
        except Exception as exc:errors.append(exc)
    thread=threading.Thread(target=start);thread.start()
    try:
        ready=tmp_path/'model_http.ready.json';deadline=time.monotonic()+2
        while not ready.exists():
            assert not errors and time.monotonic()<deadline
            time.sleep(.01)
        port=json.loads(ready.read_text())['port'];payload=io.BytesIO()
        np.savez(payload,state=np.zeros(19),prompt='Pick up the tray',_room='run:0',
                 **{'image/'+c:np.zeros((4,4,3),np.uint8) for c in ('head_left','left_wrist','right_wrist')})
        request=urllib.request.Request(f'http://127.0.0.1:{port}/infer',data=payload.getvalue(),
            headers={'X-Inference-Request-Id':'run:room000_000000'})
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(request,timeout=2) as response:
            with np.load(io.BytesIO(response.read())) as output:
                np.testing.assert_array_equal(output['raw_actions'],np.zeros((20,19)))
                assert output['actions'].shape==(20,19)
    finally:thread.join(timeout=4)
    assert not thread.is_alive() and not errors
    row=json.loads((tmp_path/'inference_model_events.jsonl').read_text())
    assert row['stage']=='model_adapter' and row['requestId']=='run:room000_000000'
    assert not (tmp_path/'inference_events.jsonl').exists()
    assert video_timing(tmp_path)[2]['stages']['model_adapter']['success_count']==1
