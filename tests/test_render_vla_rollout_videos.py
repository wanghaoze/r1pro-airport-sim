import json
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import pytest
_script=Path(__file__).resolve().parents[1]/'scripts/render_vla_rollout_videos.py'
if not _script.is_file():_script=Path(__file__).with_name('render_vla_rollout_videos.py')
_spec=importlib.util.spec_from_file_location('vla_render_under_test',_script)
render=importlib.util.module_from_spec(_spec);_spec.loader.exec_module(render)


def save(path,value):
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value))


def fixture(tmp_path,terminal_bad=False,journal_bad=False):
    collection=tmp_path/'source';scene={'scene_id':'scene_1','split':'test','difficulty':'ordinary','front_count':2}
    save(collection/'scenes/scene_1/scene.json',scene)
    (collection/'scenes/scene_1/mobile.xml').write_text('<mujoco/>')
    run=tmp_path/'actual_learner';attempt=run/'attempts/scene_1/a000'
    result=dict(scene_id='scene_1',split='test',attempt=0,motion_backend='pi05',controller_source='vla_generated',
                checkpoint_id='sha256:'+'a'*64,task_completed=False,failure_code='vla_action_outside_joint_limits')
    save(attempt/'result.json',result);(attempt/'trace.h5').write_bytes(b'unit-test trace source')
    save(run/'rollout_report.json',dict(schema='airport_vla_rollout/1',source_collection=str(collection),
                                      checkpoint_metadata={'checkpoint_id':result['checkpoint_id']}))
    meta=dict(scene_id='scene_1',split='test',scene=scene,checkpoint_id=result['checkpoint_id'])
    class FakeReplay:
        def __init__(self,root,source,diagnostic):
            assert diagnostic is True and source['trace']==str(attempt/'trace.h5')
            self.n=2;self.maximum_error=0.;self.cfg=SimpleNamespace(replay_tolerance=1e-6)
            self.schema='airport_fsm_raw/1';self.shapes={k:(8,16,3) for k in ('head_left','head_right')}
            self.camera_checks={k:{'frames':2,'shape':list(s),'blank_frames':0} for k,s in self.shapes.items()}
            self.f={'qvel':np.zeros((2,3)),'sim_time':np.array([0.,.05]),
                    'ctrl':np.array([[0.,0.],[.5 if journal_bad else .1,.1]])}
            self.f=DictAttrs(self.f)
            self.f.attrs={'metadata_json':json.dumps(meta),'terminal_snapshot_json':json.dumps(
                {'qpos':[0,0,0],'qvel':[1 if terminal_bad else 0,0,0],'time':.1})}
            d=SimpleNamespace(qpos=np.zeros(3),qvel=np.zeros(3),ctrl=np.zeros(2),time=0.)
            sim=SimpleNamespace(target=np.zeros(16),base_target=np.zeros(3))
            sim.apply_target=lambda:d.ctrl.__setitem__(slice(None),sim.target[:2])
            self.runtime=SimpleNamespace(d=d,sim=sim)
        def __iter__(self):
            for i in range(2):
                yield i,{k:np.arange(8*16*3,dtype=np.uint8).reshape(8,16,3) for k in self.shapes}
                self.runtime.sim.target[:]=.1
                self.runtime.sim.apply_target();self.runtime.d.time+=.05
        def __enter__(self):return self
        def __exit__(self,*_):pass
    return attempt,collection,FakeReplay


class DictAttrs(dict):pass


def test_diagnostic_heads_have_real_encoding_provenance_and_no_source_mutation(tmp_path):
    av=pytest.importorskip('av')
    attempt,collection,factory=fixture(tmp_path)
    before=(attempt/'result.json').read_bytes()
    manifest=render.render_attempt(attempt,collection,tmp_path/'videos',replay_factory=factory)
    assert manifest['task_completed'] is False and manifest['training_candidate'] is False
    assert manifest['purpose']=='inspection_not_training_export' and manifest['expert_label'] is False
    assert manifest['terminal_qpos_error']==0 and manifest['terminal_qvel_error']==0
    assert manifest['source_result_sha256']==render.digest(attempt/'result.json')
    assert len(manifest['references'])==2
    for ref in manifest['references']:
        assert ref['sha256']==render.digest(ref['path']) and ref['frames']==2
        with av.open(ref['path']) as container:
            assert container.streams.video[0].codec_context.name=='h264'
            assert len(list(container.decode(video=0)))==2
    assert (attempt/'result.json').read_bytes()==before
    with pytest.raises(FileExistsError):
        render.render_attempt(attempt,collection,tmp_path/'videos',replay_factory=factory)


@pytest.mark.parametrize('kind',['terminal','journal'])
def test_divergence_keeps_failure_evidence_without_complete_manifest(tmp_path,kind):
    pytest.importorskip('av')
    attempt,collection,factory=fixture(tmp_path,terminal_bad=kind=='terminal',journal_bad=kind=='journal')
    with pytest.raises(ValueError,match='terminal|ctrl journal'):
        render.render_attempt(attempt,collection,tmp_path/'videos',replay_factory=factory)
    directory=tmp_path/'videos/actual_learner/scene_1/a000'
    assert (directory/'failure.json').is_file() and not (directory/'manifest.json').exists()
