import json
from pathlib import Path

import h5py
import numpy as np
from PIL import Image
import pytest

from r1pro_teleop.vla.data import digest, prepare_manifest, read_mobile19_segment
from r1pro_teleop.vla.data_lerobot import materialize_lerobot, project_dataset_class, validate_training_encoding, CameraFrameReader
from test_vla_data import fixture


def prepared(tmp_path):
    root, trace = fixture(tmp_path)
    scene = root / 'scenes/scene1'
    scene.mkdir()
    xml = scene / 'mobile.xml'
    xml.write_text('''<mujoco><worldbody><body><joint name="dummy" type="hinge"/><geom size=".1"/>
      <body pos="8 9 0"><joint name="agent_base_x" type="slide" axis="1 0 0"/>
      <joint name="agent_base_y" type="slide" axis="0 1 0"/>
      <joint name="agent_base_yaw" type="hinge" axis="0 0 1"/><geom size=".1"/>
      </body></body></worldbody></mujoco>''', encoding='utf-8')
    cameras = ('head_left', 'head_right', 'left_wrist', 'right_wrist')
    with h5py.File(trace, 'a') as f:
        metadata = json.loads(f.attrs['metadata_json'])
        metadata['scene_xml_sha256'] = digest(xml)
        metadata['scene']['camera'] = {'streams': {k: {'width': 32, 'height': 24} for k in cameras}}
        f.attrs['metadata_json'] = json.dumps(metadata)
        f['qpos'] = np.tile([99, .1, .2, .3], (6, 1))
        f['base_state'] = np.tile([8.1, 9.2, .3], (6, 1))
    refs = []
    for camera in cameras:
        video = tmp_path / (camera + '.mp4')
        video.write_bytes(b'video fixture')
        refs.append({'trace': str(trace), 'camera': camera, 'path': str(video), 'frames': 6})
    manifest = tmp_path / 'segments.jsonl'
    prepare_manifest([root], manifest, video_references=refs,
        video_probe=lambda _: {'width': 32, 'height': 24, 'fps': 20, 'frames': 6})
    return manifest, xml


def test_state_projection_is_joint_offset_not_world_pose(tmp_path):
    manifest, xml = prepared(tmp_path)
    row = json.loads(manifest.read_text().splitlines()[0])
    state = read_mobile19_segment(row, state_layout='mobile19')['observation.state']
    assert state.shape == (3, 19)
    np.testing.assert_allclose(state[:, 16:], np.tile([.1, .2, .3], (3, 1)))
    xml.write_text(xml.read_text() + ' ', encoding='utf-8')
    with pytest.raises(ValueError, match='scene_xml_hash_mismatch'):
        read_mobile19_segment(row, state_layout='mobile19')


def test_lerobot_segments_do_not_cross_operations(tmp_path, monkeypatch):
    manifest, _ = prepared(tmp_path)
    source_rows = [json.loads(line) for line in manifest.read_text().splitlines()]
    expected_quality = {'source_needs_review': True,
        'verified_lift_takeoff': {'qualification': 'verified_lift_takeoff', 'rule_version': 1},
        'strict_deviations': {'position_error': 2},
        'approximate_deviation_counts': {'lift_intermediate': 1},
        'initial_posture_qualification': {'qualification': 'initial_tuck_after_physical_settle'},
        'local_qualification': None}
    source_rows[0].update(expected_quality)
    manifest.write_text('\n'.join(json.dumps(row) for row in source_rows), encoding='utf-8')
    captured = []
    class Cursor:
        def frame(self, path, index):
            return Image.fromarray(np.full((24, 32, 3), index, dtype=np.uint8))
        def close(self):
            pass
    monkeypatch.setattr('r1pro_teleop.vla.data_lerobot.VideoCursor', Cursor)
    class Dataset:
        def __init__(self, **kwargs):
            self.frames = []
            self.root = Path(kwargs['root'])
            self.root.mkdir()
            assert kwargs['features']['observation.state']['shape'] == (19,)
        @classmethod
        def create(cls, **kwargs):
            return cls(**kwargs)
        def add_frame(self, frame):
            self.frames.append(frame)
        def save_episode(self):
            captured.append(self.frames)
            self.frames = []
        def stop_image_writer(self):
            pass
    destination = tmp_path / 'training'
    result = materialize_lerobot(manifest, destination, 'local/test', dataset_class=Dataset)
    assert result == {'path': str(destination), 'episodes': 2, 'scenes': 1, 'frames': 6}
    assert [len(episode) for episode in captured] == [3, 3]
    assert captured[1][0]['observation.images.head_left'][112, 112, 0] == 3
    assert captured[0][0]['observation.images.head_left'].shape == (224, 224, 3)
    np.testing.assert_allclose(captured[0][0]['observation.state'][16:], [.1, .2, .3])
    assert np.all(captured[0][0]['action'][16:] == 2)
    train = json.loads((destination / 'airport_training_manifest.json').read_text())
    assert train['state_semantics'] == 'measured_joint16_plus_base_origin_offset3'
    assert train['image_derivation']['source_native_preserved']
    assert [e['base_qpos_indices'] for e in train['episodes']] == [[1, 2, 3], [1, 2, 3]]
    assert train['training_video_encoding']['codec'] == 'h264'
    assert train['training_video_encoding']['crf'] == 18
    assert {key: train['episodes'][0][key] for key in expected_quality} == expected_quality


def test_project_codec_wrapper_preserves_official_paths_and_vendor(tmp_path):
    calls = []
    class Base:
        def encode_episode_videos(self, index):
            return 'original-vendor-behavior'
    class Meta:
        video_keys = ['observation.images.head_left', 'observation.images.left_wrist']
        def get_video_file_path(self, index, key):
            return Path('videos') / key / f'episode_{index:06d}.mp4'
    def encoder(directory, path, fps, **kwargs):
        calls.append((directory, path, fps, kwargs))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'encoded')
    ProjectDataset = project_dataset_class(Base, encoder)
    ds = ProjectDataset()
    ds.root, ds.meta, ds.fps = tmp_path, Meta(), 20
    ds._get_image_file_path = lambda episode_index, image_key, frame_index: (
        tmp_path / 'images' / image_key / f'episode_{episode_index:06d}' / 'frame_000000.png')
    paths = ds.encode_episode_videos(3)
    assert set(paths) == set(ds.meta.video_keys)
    assert len(calls) == 2
    for directory, path, fps, kwargs in calls:
        assert fps == 20
        assert directory.name == 'episode_000003'
        assert str(path) in paths.values()
        assert kwargs == {'vcodec': 'h264', 'pix_fmt': 'yuv420p', 'g': 2, 'crf': 18,
                          'fast_decode': 1, 'overwrite': True}
    assert ds.encode_episode_videos(3) == paths
    assert len(calls) == 2  # Existing encoded video is never overwritten.
    assert Base().encode_episode_videos(3) == 'original-vendor-behavior'


def test_encoded_media_and_official_metadata_must_agree(tmp_path):
    expected = {'video.codec': 'h264', 'video.pix_fmt': 'yuv420p',
                'video.fps': 20, 'video.width': 224, 'video.height': 224}
    (tmp_path / 'meta').mkdir()
    info = {'features': {'observation.images.' + camera: {'info': dict(expected)}
                       for camera in ('head_left', 'left_wrist', 'right_wrist')}}
    metadata = tmp_path / 'meta/info.json'
    metadata.write_text(json.dumps(info), encoding='utf-8')
    for camera in ('head_left', 'left_wrist', 'right_wrist'):
        (tmp_path / (camera + '.mp4')).write_bytes(b'video fixture')
    verified = validate_training_encoding(tmp_path, 3, video_info=lambda _: expected)
    assert verified == {'verified': True, 'videos': 3, 'actual_codec': 'h264'}
    with pytest.raises(ValueError, match='encoded_video_contract'):
        validate_training_encoding(tmp_path, 3, video_info=lambda _: {**expected, 'video.codec': 'av1'})
    info['features']['observation.images.head_left']['info']['video.codec'] = 'av1'
    metadata.write_text(json.dumps(info), encoding='utf-8')
    with pytest.raises(ValueError, match='video_metadata'):
        validate_training_encoding(tmp_path, 3, video_info=lambda _: expected)


def test_parallel_camera_pixels_offsets_and_cursor_ownership_match_serial():
    import threading
    import time
    created = []
    class Cursor:
        def __init__(self):
            self.thread_ids, self.frames, self.active, self.closed = set(), [], False, False
            created.append(self)
        def frame(self, path, index):
            assert not self.active
            self.active = True
            self.thread_ids.add(threading.get_ident())
            self.frames.append((path, index))
            camera = int(path)
            time.sleep(.001 * (3-camera))
            array = np.zeros((31 + camera, 47 + camera, 3), dtype=np.uint8)
            array[:, :, 0] = index
            array[:, :, 1] = camera * 50
            array[0, :, 2] = 255
            self.active = False
            return Image.fromarray(array)
        def close(self):
            assert not self.active
            self.closed = True
    cameras = ('head_left', 'left_wrist', 'right_wrist')
    refs = {camera: {'path': str(i), 'start_frame': 4 + i * 10} for i, camera in enumerate(cameras)}
    parallel = CameraFrameReader(cursor_factory=Cursor)
    serial = CameraFrameReader(parallel=False, cursor_factory=Cursor)
    try:
        for offset in (0, 1, 2, 8, 0):
            concurrent = parallel.read(refs, offset)
            expected = serial.read(refs, offset)
            for camera in cameras:
                np.testing.assert_array_equal(concurrent[camera], expected[camera])
        for i, camera in enumerate(cameras):
            cursor = parallel.cursors[camera]
            assert len(cursor.thread_ids) == 1
            assert cursor.frames == [(str(i), 4 + i*10 + offset) for offset in (0, 1, 2, 8, 0)]
        assert len(set().union(*(cursor.thread_ids for cursor in parallel.cursors.values()))) == 3
    finally:
        parallel.close()
        serial.close()
    assert all(cursor.closed for cursor in created)


def test_parallel_decode_error_waits_before_closing_other_cursors():
    import time
    created = []
    class Cursor:
        def __init__(self):
            self.active, self.closed = False, False
            created.append(self)
        def frame(self, path, index):
            self.active = True
            try:
                if path == 'bad':
                    raise ValueError('decode_failure')
                time.sleep(.02)
                return Image.fromarray(np.zeros((16, 32, 3), dtype=np.uint8))
            finally:
                self.active = False
        def close(self):
            assert not self.active
            self.closed = True
    reader = CameraFrameReader(cursor_factory=Cursor)
    refs = {camera: {'path': 'bad' if camera == 'head_left' else 'good', 'start_frame': 0}
            for camera in ('head_left', 'left_wrist', 'right_wrist')}
    try:
        with pytest.raises(ValueError, match='decode_failure'):
            reader.read(refs, 0)
    finally:
        reader.close()
    assert all(cursor.closed for cursor in created)


def test_training_resize_matches_policy_aspect_padding():
    from PIL import Image
    from r1pro_teleop.vla.data_lerobot import model_image
    image = Image.fromarray(np.full((90, 160, 3), 255, dtype=np.uint8))
    result = model_image(image)
    assert result.shape == (224, 224, 3)
    assert not result[:49].any()
    assert np.all(result[49:175] == 255)
    assert not result[175:].any()
