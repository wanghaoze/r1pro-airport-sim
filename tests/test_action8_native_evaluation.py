import json
from pathlib import Path
from types import SimpleNamespace
import h5py
import numpy as np
import pytest
from scripts.evaluate_action8_checkpoint import evaluation_command,eligible_tail_failure,preserve_strict_partial
from test_render_vla_rollout_videos import fixture,render


def test_four_native_streams_beside_trace_preserve_original_files(tmp_path):
    av=pytest.importorskip('av')
    attempt,collection,base=fixture(tmp_path)
    class FourReplay(base):
        def __init__(self,*args,**kwargs):
            super().__init__(*args,**kwargs)
            for camera in ('left_wrist','right_wrist'):
                self.shapes[camera]=(8,16,3)
                self.camera_checks[camera]=dict(frames=2,shape=[8,16,3],blank_frames=0)
    before={name:(attempt/name).read_bytes() for name in ('result.json','trace.h5')}
    manifest=render.render_attempt(attempt,collection,tmp_path/'unused',replay_factory=FourReplay,
        camera_names=('head_left','head_right','left_wrist','right_wrist'),in_attempt_directory=True)
    assert len(manifest['references'])==4 and manifest['terminal_time_error']==0
    for ref in manifest['references']:
        assert Path(ref['path']).parent==attempt
        with av.open(ref['path']) as container:assert len(list(container.decode(video=0)))==2
    assert before=={name:(attempt/name).read_bytes() for name in before}
    with pytest.raises(FileExistsError):render.render_attempt(attempt,collection,tmp_path/'unused',replay_factory=FourReplay,in_attempt_directory=True)


def test_same_budget_and_profile_for_every_milestone_and_retry():
    args=SimpleNamespace(sim_python='sim',controller_root='frozen',output='step_000010',port=8766,training_status='milestone.json')
    protocol=dict(source_collection='source',scene_ids=['a','b'])
    command=evaluation_command(args,protocol)
    assert command[command.index('--max-skill-steps')+1]=='6000'
    assert '--initializer-base-hold' in command and '--grasp-base-hold' not in command
    assert '--collect-dagger' not in command and '--private-oracle-contact-escape' not in command
    retry=evaluation_command(args,protocol,scene_ids=['b'],output_name='retry')
    assert retry[retry.index('--scene-ids')+1:retry.index('--port')]==['b']
    assert retry[retry.index('--max-skill-steps')+1]=='6000'


@pytest.mark.parametrize('kind,allowed',[('valid',True),('complete',False),('middle',False),('offgrid',False),('prefix',False)])
def test_guarded_tail_fallback_only_after_actual_terminal_mismatch(kind,allowed,tmp_path):
    attempt=tmp_path/'attempt';attempt.mkdir()
    (attempt/'failure.json').write_text(json.dumps(dict(error='Diagnostic terminal state did not replay exactly' if kind!='prefix' else 'ctrl journal divergence')))
    with h5py.File(attempt/'trace.h5','w') as trace:
        trace.attrs['schema']='airport_fsm_raw/1'
        trace.attrs['metadata_json']=json.dumps(dict(physics_timestep_s=.002,fps=20))
        trace.attrs['terminal_snapshot_json']=json.dumps(dict(time=.085 if kind=='offgrid' else .084))
        trace['sim_time']=[0.,.05]
        trace['transition_completed']=[False,False] if kind=='middle' else [True,True] if kind=='complete' else [True,False]
    assert bool(eligible_tail_failure(attempt)) is allowed


def test_partial_preservation_moves_only_owned_native_artifacts(tmp_path):
    (tmp_path/'trace.h5').write_bytes(b'actual original trace')
    (tmp_path/'head_left.mp4').write_bytes(b'partial generated video')
    (tmp_path/'failure.json').write_text('{}')
    destination=preserve_strict_partial(tmp_path)
    assert (destination/'head_left.mp4').read_bytes()==b'partial generated video'
    assert (tmp_path/'trace.h5').read_bytes()==b'actual original trace'
    with pytest.raises(FileExistsError):preserve_strict_partial(tmp_path)
