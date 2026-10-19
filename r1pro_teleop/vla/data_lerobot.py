"""Training-only LeRobot v2 materialization from verified immutable VLA spans.

Original native videos remain unchanged. The new 224x224 streams explicitly
contain resized training derivatives. Each skill/operation span is an episode,
so future-action chunk padding never crosses a DAG operation boundary.
"""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import json

import h5py
import numpy as np

from .data import digest, iter_training_records, base_qpos_projection
from r1pro_teleop.airport_fsm.contracts import NAMES, BASE_NAMES

MODEL_CAMERAS = ('head_left', 'left_wrist', 'right_wrist')


def model_image(image, size=224):
    """Match pinned openpi-client resize_with_pad; retain native aspect ratio."""
    from PIL import Image
    width, height = image.size
    ratio = max(width / size, height / size)
    resized = image.resize((int(width / ratio), int(height / ratio)), Image.Resampling.BILINEAR)
    padded = Image.new('RGB', (size, size), 0)
    padded.paste(resized, ((size - resized.width) // 2, (size - resized.height) // 2))
    return np.asarray(padded, dtype=np.uint8)
STATE_SEMANTICS = 'measured_joint16_plus_base_origin_offset3'

TRAINING_VIDEO_ENCODING = {'codec': 'h264', 'encoder': 'libx264', 'crf': 18,
                           'gop_frames': 2, 'fast_decode': 1, 'pixel_format': 'yuv420p'}

EPISODE_QUALITY_FIELDS = ('source_needs_review', 'verified_lift_takeoff',
                          'strict_deviations', 'approximate_deviation_counts',
                          'initial_posture_qualification', 'local_qualification')


def project_dataset_class(base_class=None, encoder=None):
    """Project-owned codec override; the pinned vendor module remains unchanged."""
    if base_class is None:
        from lerobot.common.datasets.lerobot_dataset import LeRobotDataset
        base_class = LeRobotDataset
    if encoder is None:
        from lerobot.common.datasets.video_utils import encode_video_frames
        encoder = encode_video_frames

    class AirportTrainingDataset(base_class):
        def encode_episode_videos(self, episode_index):
            video_paths = {}
            for key in self.meta.video_keys:
                path = self.root / self.meta.get_video_file_path(episode_index, key)
                video_paths[key] = str(path)
                if path.is_file():
                    continue
                directory = self._get_image_file_path(
                    episode_index=episode_index, image_key=key, frame_index=0).parent
                encoder(directory, path, self.fps, vcodec='h264', pix_fmt='yuv420p',
                        g=2, crf=18, fast_decode=1, overwrite=True)
            return video_paths

    return AirportTrainingDataset


def validate_training_encoding(destination, expected_videos, *, video_info=None):
    """Verify actual media codec and official feature metadata agree."""
    if video_info is None:
        from lerobot.common.datasets.video_utils import get_video_info
        video_info = get_video_info
    destination = Path(destination)
    videos = sorted(destination.rglob('*.mp4'))
    if len(videos) != expected_videos:
        raise ValueError('training_encoded_video_count_mismatch')
    expected = {'video.codec': 'h264', 'video.pix_fmt': 'yuv420p',
                'video.fps': 20, 'video.width': 224, 'video.height': 224}
    for path in videos:
        actual = video_info(path)
        if any(actual.get(key) != value for key, value in expected.items()):
            raise ValueError('training_encoded_video_contract_mismatch')
    info = json.loads((destination / 'meta/info.json').read_text(encoding='utf-8'))
    for camera in MODEL_CAMERAS:
        actual = info['features']['observation.images.' + camera].get('info', {})
        if any(actual.get(key) != value for key, value in expected.items()):
            raise ValueError('training_video_metadata_mismatch')
    return {'verified': True, 'videos': len(videos), 'actual_codec': 'h264'}


class VideoCursor:
    """Sequential exact decoded-frame indexing; reopen only on backward ranges."""
    def __init__(self):
        self.path = None
        self.container = None
        self.next_frame = 0

    def frame(self, path, index):
        import av
        path = str(path)
        if path != self.path or index < self.next_frame:
            self.close()
            self.path = path
            self.container = av.open(path)
            self.decoder = iter(self.container.decode(video=0))
            self.next_frame = 0
        while self.next_frame <= index:
            try:
                frame = next(self.decoder)
            except StopIteration as exc:
                raise ValueError('video_decode_frame_missing') from exc
            current = self.next_frame
            self.next_frame += 1
        if current != index:
            raise ValueError('video_cursor_alignment_error')
        return frame.to_image().convert('RGB')

    def close(self):
        if self.container is not None:
            self.container.close()
        self.container = None
        self.path = None
        self.next_frame = 0


class CameraFrameReader:
    """Three serial camera workers, joined at every source observation frame.

    Each decoder belongs to one single-worker executor. No next-frame work is
    queued until all views finish, so timestamps cannot drift or cross spans.
    """
    def __init__(self, *, parallel=True, cursor_factory=None):
        factory = VideoCursor if cursor_factory is None else cursor_factory
        self.cursors = {camera: factory() for camera in MODEL_CAMERAS}
        self.parallel = parallel
        self.workers = ({camera: ThreadPoolExecutor(max_workers=1, thread_name_prefix='vla_' + camera)
                         for camera in MODEL_CAMERAS} if parallel else {})

    def _read(self, camera, reference, offset):
        image = self.cursors[camera].frame(reference['path'], reference['start_frame'] + offset)
        return model_image(image)

    def read(self, references, offset):
        if not self.parallel:
            return {camera: self._read(camera, references[camera], offset) for camera in MODEL_CAMERAS}
        futures = {camera: self.workers[camera].submit(self._read, camera, references[camera], offset)
                   for camera in MODEL_CAMERAS}
        return {camera: futures[camera].result() for camera in MODEL_CAMERAS}

    def close(self):
        # Pending work must finish before closing a decoder, including errors.
        for worker in self.workers.values():
            worker.shutdown(wait=True)
        for cursor in self.cursors.values():
            cursor.close()


def materialize_lerobot(manifest, destination, repo_id, *, max_scenes=None,
                       include_reviewed_local=False, dataset_class=None):
    """Use the installed pinned official LeRobot create/add_frame/save_episode API."""
    from PIL import Image
    official_loader = dataset_class is None
    if dataset_class is None:
        from importlib.metadata import version
        if version('lerobot') != '0.1.0':
            raise ValueError('lerobot_version_mismatch_requires_pinned_0_1_0')
        dataset_class = project_dataset_class()
    destination = Path(destination).resolve()
    if destination.exists():
        raise ValueError('refuse_existing_training_dataset')
    if max_scenes is not None and (isinstance(max_scenes, bool) or max_scenes < 1):
        raise ValueError('invalid_max_scenes')
    rows = list(iter_training_records(manifest, include_reviewed_local=include_reviewed_local))
    selected_scenes = sorted({row['scene_id'] for row in rows})
    if max_scenes is not None:
        selected_scenes = selected_scenes[:max_scenes]
    selected_scenes = set(selected_scenes)
    rows = [row for row in rows if row['scene_id'] in selected_scenes]
    if not rows:
        raise ValueError('no_verified_train_segments')
    features = {
        'observation.state': {'dtype': 'float32', 'shape': (19,), 'names': NAMES + BASE_NAMES},
        'action': {'dtype': 'float32', 'shape': (19,), 'names': NAMES + BASE_NAMES}}
    for camera in MODEL_CAMERAS:
        features['observation.images.' + camera] = {
            'dtype': 'video', 'shape': (3, 224, 224), 'names': ['channels', 'height', 'width']}
    camera_reader = CameraFrameReader()
    checked_traces, checked_videos, projections = set(), set(), {}
    episodes = []
    ds = None
    try:
        ds = dataset_class.create(repo_id=repo_id, fps=20, root=destination,
            robot_type='r1pro_mujoco_sim_mobile19', features=features,
            use_videos=True, image_writer_threads=4, video_backend='pyav')
        for row in rows:
            if row['fps'] != 20 or row['action_layout'] != 'mobile19':
                raise ValueError('training_contract_mismatch')
            if row['trace'] not in checked_traces:
                if digest(row['trace']) != row['trace_sha256']:
                    raise ValueError('trace_hash_changed')
                checked_traces.add(row['trace'])
            a, b = row['start_frame'], row['end_frame']
            columns = base_qpos_projection(row, cache=projections)
            with h5py.File(row['trace'], 'r') as f:
                if 'qpos' not in f or max(columns) >= f['qpos'].shape[1]:
                    raise ValueError('measured_base_qpos_required')
                states = np.concatenate((f['state'][a:b], f['qpos'][a:b][:, columns]), axis=-1).astype(np.float32)
                actions = np.concatenate((f['action'][a:b], f['base_action'][a:b]), axis=-1).astype(np.float32)
            if states.shape != (b-a, 19) or actions.shape != (b-a, 19) or not np.isfinite(states).all() or not np.isfinite(actions).all():
                raise ValueError('training_nonfinite_or_shape_mismatch')
            for camera in MODEL_CAMERAS:
                ref = row['videos'].get(camera)
                if not ref or ref.get('verified') is not True:
                    raise ValueError('verified_model_camera_required:' + camera)
                if ref['path'] not in checked_videos:
                    if digest(ref['path']) != ref['sha256']:
                        raise ValueError('video_hash_changed')
                    checked_videos.add(ref['path'])
            for i in range(b-a):
                frame = {'observation.state': states[i], 'action': actions[i], 'task': row['language_prompt']}
                images = camera_reader.read(row['videos'], i)
                frame.update({'observation.images.' + camera: images[camera] for camera in MODEL_CAMERAS})
                ds.add_frame(frame)
            ds.save_episode()
            episodes.append({'episode_index': len(episodes), 'scene_id': row['scene_id'], 'split': 'train',
                'segment_id': row['segment_id'], 'source_trace': row['trace'], 'source_trace_sha256': row['trace_sha256'],
                'source_start_frame': a, 'source_end_frame': b, 'frames': b-a,
                'fps': 20, 'action_semantics': 'absolute_mobile19', 'state_semantics': STATE_SEMANTICS,
                'base_qpos_indices': columns,
                'skill': row['skill'], 'phase': row['phase'], 'operation_index': row['operation_index'],
                'language_prompt': row['language_prompt'], 'quality_class': row['quality_class'],
                'episode_strict_success': row['episode_strict_success'], 'acceptance_profile': row['acceptance_profile'],
                'native_source_videos': row['videos']})
            episodes[-1].update({key: row[key] for key in EPISODE_QUALITY_FIELDS if key in row})
        if hasattr(ds, 'stop_image_writer'):
            ds.stop_image_writer()
        encoding_check = {'verified': False, 'reason': 'injected_test_dataset'}
        if official_loader:
            loaded = dataset_class(repo_id=repo_id, root=destination, video_backend='pyav')
            if len(loaded) != sum(e['frames'] for e in episodes):
                raise ValueError('official_loader_frame_count_mismatch')
            offset = 0
            for episode in episodes:
                for index in (offset, offset + episode['frames'] - 1):
                    sample = loaded[index]
                    if tuple(sample['observation.state'].shape) != (19,) or tuple(sample['action'].shape) != (19,):
                        raise ValueError('official_loader_mobile19_shape_mismatch')
                    for camera in MODEL_CAMERAS:
                        if tuple(sample['observation.images.' + camera].shape) != (3, 224, 224):
                            raise ValueError('official_loader_training_image_mismatch')
                offset += episode['frames']
            encoding_check = validate_training_encoding(destination, len(episodes) * len(MODEL_CAMERAS))
        training_manifest = {'schema': 'airport_pi05_training/1', 'repo_id': repo_id,
            'split': 'train', 'fps': 20, 'action_semantics': 'absolute_mobile19',
            'state_semantics': STATE_SEMANTICS, 'environment_source': 'simulation',
            'controller_source': 'program_generated', 'human_demonstration': False,
            'episodes': episodes, 'source_manifest': str(Path(manifest).resolve()),
            'source_manifest_sha256': digest(manifest), 'normalization_split': 'train_only',
            'official_loader_every_episode_first_last': official_loader,
            'base_state_projection': 'qpos_xml_joint_addresses', 'lerobot_version': '0.1.0',
            'training_video_encoding': dict(TRAINING_VIDEO_ENCODING),
            'training_video_encoding_verification': encoding_check,
            'camera_processing': {'workers': 3, 'workers_per_cursor': 1, 'prefetch_frames': 0,
                                  'join_each_source_frame': True},
            'image_derivation': {'size': [224, 224], 'resample': 'bilinear', 'resize': 'aspect_preserving_with_zero_padding', 'crop': False,
                'source_native_preserved': True, 'native_video_export_claim': False},
            'action_chunk_boundary': 'one_skill_operation_phase_span_per_episode'}
        (destination / 'airport_training_manifest.json').write_text(
            json.dumps(training_manifest, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
        return {'path': str(destination), 'episodes': len(episodes), 'scenes': len(selected_scenes),
                'frames': sum(e['frames'] for e in episodes)}
    finally:
        camera_reader.close()
        if ds is not None and hasattr(ds, 'stop_image_writer'):
            ds.stop_image_writer()
