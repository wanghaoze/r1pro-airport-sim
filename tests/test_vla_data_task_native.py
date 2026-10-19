"""CPU tests verify native wrapper rejects omissions and divergence; no real render."""
import json
from pathlib import Path
from types import SimpleNamespace
import h5py,numpy as np,pytest,importlib.util
module_spec=importlib.util.spec_from_file_location('task_native_tested',Path(__file__).resolve().parents[1]/'r1pro_teleop/vla/data_task_native.py')
native=importlib.util.module_from_spec(module_spec);module_spec.loader.exec_module(native)

@pytest.fixture
def source(tmp_path):
    controller=tmp_path/'r1pro_teleop/airport_fsm';controller.mkdir(parents=True)
    for name in ('exporter.py','runtime.py','../core.py','../airport_recording.py'):
        (controller/name).write_text('synthetic fixture controller; no physics claims')
    directory=tmp_path/'source';directory.mkdir();row=dict(scene_id='s',split='train',frames=2,attempt=str(directory),collection=str(directory))
    result=dict(scene_id='s',split='train',frames=2,task_completed=True,physics_success=True,failure_code=None,
                controller_source='program_generated',environment_source='simulation',strict_success=False,effective_acceptance_profile='approximate_completion')
    files={'result':result,'scene_json':{'scene_id':'s'},'segments':[],'events':[],'physical_events':[],'scene_xml':{}}
    for name,value in files.items():
        path=directory/(name+'.json');path.write_text(json.dumps(value));row[name]=str(path)
        row[{'scene_xml':'scene_xml_sha256'}.get(name,name+'_sha256')]=native.digest(path)
    path=directory/'trace.h5'
    with h5py.File(path,'w') as f:
        f.attrs['schema']='airport_fsm_raw/1';f.attrs['terminal_snapshot_json']=json.dumps(dict(qpos=[0,0],qvel=[0,0],time=.1))
        f['qpos']=np.zeros((2,2));f['qvel']=np.zeros((2,2));f['sim_time']=[0.,.05];f['transition_completed']=[True,True]
    row.update(trace=str(path),trace_sha256=native.digest(path));return row

class Replay:
    velocity_error=0.;drop_frame=False;texture_blank=0;mask=True
    def __init__(self,root,source,diagnostic=False):
        self.f=h5py.File(source['trace'],'r');self.n=2;self.schema=self.f.attrs['schema']
        self.cfg=SimpleNamespace(fps=20,replay_tolerance=1e-5)
        self.shapes={c:(4,6,3) for c in native.CAMERAS}
        self.camera_checks={c:dict(frames=2,blank_frames=self.texture_blank) for c in native.CAMERAS}
        self.runtime=SimpleNamespace(d=SimpleNamespace(qpos=np.zeros(2),qvel=np.zeros(2),time=0.),base_qids=np.array([0,1,2]))
    def __enter__(self):return self
    def __exit__(self,*args):self.f.close()
    def __iter__(self):
        for i in range(2):
            self.runtime.d.time=i*.05
            yield i+(1 if self.drop_frame else 0),{c:np.zeros((4,6,3),np.uint8) for c in native.CAMERAS}
        self.runtime.d.time=.1;self.runtime.d.qvel[:]=self.velocity_error

class Writer:
    def __init__(self,path,shape):self.path=path;self.path.write_bytes(b'fixture');self.frames=[]
    def add(self,index,image):self.frames.append(index)
    def close(self):pass

def render(row,tmp_path,cls=Replay,**kwargs):
    return native.render_source(row,tmp_path/'output',tmp_path,replay_factory=cls,writer_factory=Writer,
        video_checker=lambda *a:dict(codec_name='h264',frames=2),gpu_checker=lambda index:[dict(physical_index=index,pid=-1)],**kwargs)

def test_complete_native_wrapper_binds_all_four_sources_and_no_training_claim(source,tmp_path):
    result=render(source,tmp_path)
    assert len(result['references'])==4 and result['frames']==2
    assert result['initial_restore_count']==1 and result['per_frame_state_reset'] is False
    assert result['training_ready'] is False and result['camera_texture_quality_passed'] is True
    assert result['terminal_errors']==dict(qpos=0.,qvel=0.,time=0.)

def test_complete_wrapper_rejects_terminal_velocity_even_diagnostic_mode(source,tmp_path):
    class Bad(Replay):velocity_error=.001
    with pytest.raises(ValueError,match='terminal'):render(source,tmp_path,Bad,allow_low_texture=True)
    assert list((tmp_path/'output').glob('*/source/failure.json'))

def test_native_wrapper_rejects_dropped_source_frame(source,tmp_path):
    class Bad(Replay):drop_frame=True
    with pytest.raises(ValueError,match='source_frame'):render(source,tmp_path,Bad)

def test_low_texture_flag_preserved_without_training_qualification(source,tmp_path):
    class Low(Replay):texture_blank=1
    result=render(source,tmp_path,Low,allow_low_texture=True)
    assert result['camera_texture_quality_passed'] is False and result['training_ready'] is False

def test_source_mutation_rejected_before_output_creation(source,tmp_path):
    Path(source['scene_xml']).write_text('changed')
    with pytest.raises(ValueError,match='source_changed'):render(source,tmp_path)
    assert not (tmp_path/'output').exists()

def test_failed_original_case_rejected(source,tmp_path):
    path=Path(source['result']);result=json.loads(path.read_text());result['task_completed']=False;path.write_text(json.dumps(result))
    source['result_sha256']=native.digest(path)
    with pytest.raises(ValueError,match='complete_original'):render(source,tmp_path)

def test_incomplete_mask_rejected_despite_success_result(source,tmp_path):
    with h5py.File(source['trace'],'r+') as f:f['transition_completed'][1]=False
    source['trace_sha256']=native.digest(source['trace'])
    with pytest.raises(ValueError,match='control_interval'):render(source,tmp_path)

def test_existing_output_is_never_overwritten(source,tmp_path):
    render(source,tmp_path)
    with pytest.raises(FileExistsError):render(source,tmp_path)

def test_native_decoder_checks_complete_count_dimensions_and_single_thread(monkeypatch):
    header=dict(codec_name='h264',height=4,width=6,avg_frame_rate='20/1',nb_read_frames='2');calls=[]
    def probe(command,**kwargs):calls.append(command);return json.dumps({'streams':[dict(header)]})
    monkeypatch.setattr(native.subprocess,'check_output',probe)
    assert native.native_video_metadata('video.mp4',(4,6,3),2)['nb_read_frames']=='2'
    assert calls[0][calls[0].index('-threads')+1]=='1'
    header['nb_read_frames']='1'
    with pytest.raises(ValueError,match='framecount'):native.native_video_metadata('video.mp4',(4,6,3),2)

def test_controller_change_during_replay_is_rejected(source,tmp_path):
    class Changed(Replay):
        def __iter__(self):
            yield from super().__iter__()
            (tmp_path/'r1pro_teleop/core.py').write_text('unexpected controller mutation')
    with pytest.raises(ValueError,match='controller_changed'):render(source,tmp_path,Changed)
