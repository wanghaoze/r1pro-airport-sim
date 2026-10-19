import numpy as np
import pytest
from r1pro_teleop.vla.data_task_lerobot import action_vocabulary,interval_statistics,cut_native_action,cut_native_windows
from r1pro_teleop.vla.data import digest

def test_overlap_counts_are_explicit():
 assert interval_statistics([(10,30),(20,40)])==dict(supervised_frames=40,unique_source_action_frames=30,duplicate_source_action_frames=10)

def test_vocabulary_rejects_duplicate_prompt_and_unknown_skill():
 r=dict(action_label='a',base_skill='carry_tray',language_prompt='Carry to position 1.')
 assert action_vocabulary([r])['a']['task_index']==0
 with pytest.raises(ValueError):action_vocabulary([r,dict(r,action_label='b')])
 with pytest.raises(ValueError):action_vocabulary([dict(r,base_skill='unknown')])

def test_native_clip_full_absolute_window_rgb(tmp_path):
 src=tmp_path/'source';src.write_bytes(b'source');output=tmp_path/'clip'
 images=[np.full((2,3,3),n,np.uint8) for n in range(8)];written=[]
 def decode(path):return iter(written if path==output else images)
 def encode(frames,path,fps):
  written.extend(image.copy() for image in frames);path.write_bytes(b'clip');assert fps==20;return len(written)
 receipt=cut_native_action(dict(path=str(src),sha256=digest(src)),output,3,7,decoder=decode,encoder=encode)
 assert [int(image[0,0,0]) for image in written]==[3,4,5,6]
 assert receipt['all_decoded_rgb_frames_equal_source'] and receipt['frames']==4

def test_batched_overlapping_windows_decode_source_once(tmp_path):
 src=tmp_path/'source';src.write_bytes(b'source');images=[np.full((2,3,3),n,np.uint8) for n in range(8)]
 saved={};calls=[]
 class Writer:
  def __init__(self,path,shape):self.path=path;saved[path]=[];path.write_bytes(b'clip')
  def write(self,image):saved[self.path].append(image.copy())
  def finish(self):return len(saved[self.path])
  def abort(self):pass
 def decode(path):
  calls.append(path);return iter(images if str(path)==str(src) else saved[path])
 windows=[dict(segment_id='place',start_frame=2,end_frame=7,path=tmp_path/'place'),dict(segment_id='push',start_frame=4,end_frame=7,path=tmp_path/'push')]
 receipt=cut_native_windows(dict(path=str(src),sha256=digest(src)),windows,expected_source_frames=8,decoder=decode,writer_factory=Writer)
 assert sum(str(x)==str(src) for x in calls)==1
 assert [int(x[0,0,0]) for x in saved[tmp_path/'push']]==[4,5,6]
 assert receipt['place']['maximum_active_window_encoders']==2
 assert receipt['push']['source_decode_passes']==1

def test_truncated_source_refuses_complete_window(tmp_path):
 src=tmp_path/'source';src.write_bytes(b'source')
 class Writer:
  def __init__(self,path,shape):pass
  def write(self,image):pass
  def finish(self):pass
  def abort(self):pass
 with pytest.raises(ValueError):
  cut_native_windows(dict(path=str(src),sha256=digest(src)),[dict(segment_id='a',start_frame=0,end_frame=3,path=tmp_path/'a')],expected_source_frames=4,decoder=lambda path:iter([np.zeros((2,3,3),np.uint8)]),writer_factory=Writer)


def test_state_uses_original_xml_qpos_origin_not_segment_rebase(tmp_path,monkeypatch):
 import h5py
 import r1pro_teleop.vla.data_task_lerobot as module
 path=tmp_path/'trace.h5'
 with h5py.File(path,'w') as f:
  f['state']=np.zeros((5,16));f['action']=np.ones((5,16));f['qpos']=np.arange(30).reshape(5,6);f['base_action']=np.arange(15).reshape(5,3)
 monkeypatch.setattr(module,'base_qpos_projection',lambda task,cache=None:[2,3,4])
 state,action,columns=module.read_action_arrays(dict(trace=str(path),trace_sha256=digest(path),frames=5),dict(start_frame=2,end_frame=4))
 assert columns==[2,3,4]
 np.testing.assert_array_equal(state[:,16:],[[14,15,16],[20,21,22]])
 np.testing.assert_array_equal(action[:,16:],[[6,7,8],[9,10,11]])

def test_actual_source_changed_is_rejected_before_read(tmp_path):
 from r1pro_teleop.vla.data_task_lerobot import read_action_arrays
 path=tmp_path/'trace';path.write_bytes(b'changed')
 with pytest.raises(ValueError,match='trace_changed'):
  read_action_arrays(dict(trace=str(path),trace_sha256='0'*64,frames=2),dict(start_frame=0,end_frame=1))
