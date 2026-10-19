"""Independent camera concurrency keeps every source interval and RGB value."""
from pathlib import Path
import threading
import numpy as np
import pytest
from r1pro_teleop.vla.data_task_lerobot import NATIVE_CAMERAS,cut_case_native_windows,cut_native_windows
from r1pro_teleop.vla.data import digest

def test_parallel_camera_contexts_overlap_without_shared_cursor(tmp_path):
    barrier=threading.Barrier(4);calls=[];lock=threading.Lock()
    views={c:dict(camera=c) for c in NATIVE_CAMERAS}
    windows={c:[dict(path=tmp_path/c)] for c in NATIVE_CAMERAS}
    def cut(ref,items,expected_source_frames):
        with lock:calls.append(ref['camera'])
        barrier.wait(timeout=3)
        return dict(camera=ref['camera'],frames=expected_source_frames)
    result=cut_case_native_windows(views,windows,expected_source_frames=6,cutter=cut)
    assert list(result)==list(NATIVE_CAMERAS) and set(calls)==set(NATIVE_CAMERAS)
    assert all(result[c]['camera']==c for c in NATIVE_CAMERAS)

def test_parallel_and_sequential_overlapping_window_rgb_exact(tmp_path):
    views={};images={};saved={};counter={};lock=threading.Lock()
    for index,camera in enumerate(NATIVE_CAMERAS):
        path=tmp_path/camera;path.write_bytes(camera.encode());views[camera]=dict(path=str(path),sha256=digest(path))
        images[str(path)]=[np.full((3,5,3),index*20+n,np.uint8) for n in range(8)]
    class Writer:
        def __init__(self,path,fps):self.path=Path(path);self.path.write_bytes(b'fixture');saved[str(path)]=[]
        def write(self,image):saved[str(self.path)].append(image.copy())
        def finish(self):return len(saved[str(self.path)])
        def abort(self):pass
    def decode(path):
        with lock:counter[str(path)]=counter.get(str(path),0)+1
        return iter(images[str(path)] if str(path) in images else saved[str(path)])
    def cut(ref,windows,expected_source_frames):
        return cut_native_windows(ref,windows,expected_source_frames=expected_source_frames,decoder=decode,writer_factory=Writer)
    reports=[]
    for workers in (1,4):
        windows={c:[dict(segment_id='place',start_frame=2,end_frame=7,path=tmp_path/f'{workers}_{c}_place'),
                    dict(segment_id='push',start_frame=4,end_frame=7,path=tmp_path/f'{workers}_{c}_push')] for c in NATIVE_CAMERAS}
        reports.append(cut_case_native_windows(views,windows,expected_source_frames=8,workers=workers,cutter=cut))
    for c in NATIVE_CAMERAS:
        assert counter[views[c]['path']]==2
        for skill in ('place','push'):
            a,b=reports[0][c][skill],reports[1][c][skill]
            assert a['decoded_rgb_sha256']==b['decoded_rgb_sha256'] and a['frames']==b['frames']
            np.testing.assert_array_equal(saved[a['path']],saved[b['path']])

def test_parallel_camera_failure_propagates_without_complete_return(tmp_path):
    views={c:dict(camera=c) for c in NATIVE_CAMERAS};windows={c:[dict(path=tmp_path/c)] for c in NATIVE_CAMERAS}
    def cut(ref,*args,**kwargs):
        if ref['camera']=='left_wrist':raise ValueError('source_truncated')
        return {'fixture':'completed'}
    with pytest.raises(ValueError,match='source_truncated'):cut_case_native_windows(views,windows,expected_source_frames=3,cutter=cut)

def test_parallel_camera_rejects_colliding_outputs_and_unbounded_workers(tmp_path):
    views={c:{} for c in NATIVE_CAMERAS};windows={c:[dict(path=tmp_path/'same')] for c in NATIVE_CAMERAS}
    with pytest.raises(ValueError,match='overlap'):cut_case_native_windows(views,windows,expected_source_frames=2)
    with pytest.raises(ValueError,match='workers'):cut_case_native_windows(views,windows,expected_source_frames=2,workers=8)
