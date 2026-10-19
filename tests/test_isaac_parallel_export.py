import importlib.util
import json
from pathlib import Path
import sys

import numpy as np
import pytest

SCRIPTS=Path(__file__).resolve().parents[1]/'scripts'
sys.path.insert(0,str(SCRIPTS))
spec=importlib.util.spec_from_file_location('parallel_export',SCRIPTS/'export_isaac_parallel_pickplace.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


def fixture():
    n=120
    z=dict(raw_action=np.zeros((n,19)),state=np.zeros((n+1,19)),
           submitted_control=np.zeros((n,25,18)),time=np.arange(n+1)/20)
    result=dict(actions=[dict(prompt='Pick up the tray',start=0,end=60),
                         dict(prompt='Place the tray',start=60,end=120)],
                case=dict(initial_base_world=[.3,0,0],fixed_base_world=[.3,0,0]))
    initial=dict(frame=60,reset_between_pick_and_place=False,state=z['state'][60].tolist())
    station=dict(fixed_command=[0,0,0],requested_world=[.3,0,0],initialization_only_before_first_step=True)
    return result,z,initial,station


def test_pair_preserves_real_place_start_and_all_preparation_base():
    result,z,initial,station=fixture()
    assert module.validate_alignment(result,z,initial,station)==0
    z['raw_action'][0,16]=.001
    with pytest.raises(ValueError,match='base_command_changed'):
        module.validate_alignment(result,z,initial,station)


def test_rejects_canonical_place_reset_even_with_valid_frames():
    result,z,initial,station=fixture();initial['reset_between_pick_and_place']=True
    with pytest.raises(ValueError,match='continuation'):
        module.validate_alignment(result,z,initial,station)


def test_rejects_unexecuted_substep_and_timestamp_gap():
    result,z,initial,station=fixture();z['submitted_control']=np.zeros((120,24,18))
    with pytest.raises(ValueError,match='control_alignment'):
        module.validate_alignment(result,z,initial,station)
    result,z,initial,station=fixture();z['time'][35]+=.05
    with pytest.raises(ValueError,match='clock_time'):
        module.validate_alignment(result,z,initial,station)


def test_rejects_parent_split_leak_before_media_export(tmp_path):
    room=tmp_path/'room_000';room.mkdir()
    (room/'result.json').write_text(json.dumps(dict(case=dict(parent_scene_id='parent',parent_split='test'))))
    with pytest.raises(ValueError,match='parent_split'):
        module.export_room(tmp_path,room,tmp_path/'actual.exit.json',{'parent':'train'})
    assert not (tmp_path/'dataset').exists()


def test_global_overview_requires_actual_encoder_exit_not_room_trimming(tmp_path,monkeypatch):
    movie=tmp_path/'global_overview.mp4';movie.write_bytes(b'fixture')
    record=dict(path=str(movie),returncode=0,shared_world_render=True,global_start_frame=0,frames=400,fps=20)
    (tmp_path/'global_overview.json').write_text(json.dumps(record))
    monkeypatch.setattr(module,'video_probe',lambda p:dict(frames=400,fps=20))
    row=module.overview(tmp_path,[])
    assert row['time_shift_or_speed_change'] is False
    record['returncode']=1;(tmp_path/'global_overview.json').write_text(json.dumps(record))
    with pytest.raises(ValueError,match='encoder_closure'):
        module.overview(tmp_path,[])


def test_mismatched_overview_frames_are_not_presented_as_closed(tmp_path,monkeypatch):
    movie=tmp_path/'global_overview.mp4';movie.write_bytes(b'fixture')
    (tmp_path/'global_overview.json').write_text(json.dumps(dict(path=str(movie),returncode=0,
        shared_world_render=True,global_start_frame=0,frames=400,fps=20)))
    monkeypatch.setattr(module,'video_probe',lambda p:dict(frames=399,fps=20))
    with pytest.raises(ValueError,match='frame_alignment'):
        module.overview(tmp_path,[])


def test_frozen_manifest_cannot_be_replaced(tmp_path):
    path=tmp_path/'manifest.json';module.immutable(path,dict(seed=1))
    with pytest.raises(ValueError,match='immutable_manifest_changed'):
        module.immutable(path,dict(seed=2))
    assert json.loads(path.read_text())==dict(seed=1)
