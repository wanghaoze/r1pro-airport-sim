"""Shared-clock collection primitives; no simulator imports at module load.

Room coordinates are metadata, never policy observations. Probe replay is
explicitly excluded from training; physical collection still needs its audit.
"""
import json
import math
from pathlib import Path
import queue
import subprocess
import threading

import numpy as np

CAMERAS = {'head_left': (320, 256), 'head_right': (320, 256),
           'left_wrist': (320, 180), 'right_wrist': (320, 180)}


def room_origins(count, spacing=12.):
    if count not in (1, 4, 8, 16, 32) or spacing < 10.:
        raise ValueError('invalid_registered_room_grid')
    columns = math.ceil(math.sqrt(count))
    return np.asarray([(i % columns * spacing, i // columns * spacing, 0.)
                       for i in range(count)], np.float32)


def batched_joint_targets(actions):
    actions = np.asarray(actions)
    if actions.ndim != 2 or actions.shape[1] != 19 or not np.isfinite(actions).all():
        raise ValueError('invalid_batched_mobile19')
    return np.concatenate((actions[:, :7], actions[:, 7:8]/2,
                           actions[:, 7:8]/2, actions[:, 8:15],
                           actions[:, 15:16]/2, actions[:, 15:16]/2), axis=1)


def validate_sources(rows):
    """Keep descendants together even when rooms are shuffled across batches."""
    parents = {}
    for row in rows:
        parent, split = row['parent_scene_id'], row['parent_split']
        if split not in ('train', 'val', 'test'):
            raise ValueError('invalid_parent_split')
        if parents.setdefault(parent, split) != split:
            raise ValueError('parallel_parent_split_leakage')
    return parents


def sample_table_poses(table, tray_size, count, seed):
    """Full footprint stays on the unchanged table at initialization.

    Sample the full 180-degree tray symmetry interval, not a tiny yaw jitter.
    This is geometric support eligibility only, NOT arm reachability. Failed
    direct IK goes to supported preadjustment, never a fake success label.
    """
    rng = np.random.default_rng(seed)
    half = np.asarray(table['dimensions_m'][:2], float)/2
    size = np.asarray(tray_size[:2], float)
    face = float(table['yaw_world'])
    c, s = np.cos(face), np.sin(face)
    rotation = np.array([[c, -s], [s, c]])
    rows = []
    for i in range(count):
        for _ in range(1000):
            yaw = rng.uniform(-np.pi/2, np.pi/2)
            c, s = abs(np.cos(yaw)), abs(np.sin(yaw))
            extent = np.array([c*size[0]+s*size[1], s*size[0]+c*size[1]])/2
            freedom = half-extent
            if np.any(freedom < 0):
                continue
            local = rng.uniform(-freedom, freedom)
            xy = np.asarray(table['center_world'][:2])+rotation@local
            absolute_yaw = yaw+face
            rows.append(dict(sample_id=i, seed=int(seed), table_id=table['table_id'],
                initial_xy_m=xy.tolist(), initial_yaw_rad=float(absolute_yaw),
                quaternion_wxyz=[float(np.cos(absolute_yaw/2)), 0., 0., float(np.sin(absolute_yaw/2))],
                table_local_xy_m=local.tolist(), initial_footprint_supported=True,
                reachability='not_checked', preadjustment='required_if_direct_grasp_unavailable',
                training_eligible=False))
            break
        else:
            raise ValueError('tray_footprint_cannot_fit_registered_table')
    return rows


def write_json(path, value):
    path = Path(path)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value, indent=2), encoding='utf8')
    tmp.replace(path)


class BoundedVideoWriter:
    """Backpressure instead of dropping frames; errors propagate to producer."""
    def __init__(self, path, size, *, codec='libx264', capacity=4):
        self.path = Path(path)
        self.size = tuple(size)
        self.queue = queue.Queue(capacity)
        self.error = None
        self.frames = 0
        self.closed = False
        self.log = self.path.with_suffix('.encoder.log').open('wb')
        argv = ['ffmpeg', '-nostdin', '-v', 'error', '-n', '-f', 'rawvideo',
                '-pix_fmt', 'rgb24', '-s', f'{size[0]}x{size[1]}', '-r', '20',
                '-i', 'pipe:0', '-an', '-c:v', codec]
        argv += (['-preset', 'fast', '-crf', '24', '-threads', '1']
                 if codec == 'libx264' else ['-preset', 'p4', '-cq', '25'])
        self.process = subprocess.Popen(argv + [str(self.path)], stdin=subprocess.PIPE,
                                        stdout=subprocess.DEVNULL, stderr=self.log)
        self.thread = threading.Thread(target=self._consume, daemon=True)
        self.thread.start()

    def _consume(self):
        try:
            while True:
                item = self.queue.get()
                try:
                    if item is None:
                        break
                    self.process.stdin.write(item)
                    self.frames += 1
                finally:
                    self.queue.task_done()
        except BaseException as exc:
            self.error = exc
        finally:
            self.process.stdin.close()

    def put(self, image):
        image = np.asarray(image)
        if image.shape != (self.size[1], self.size[0], 3) or image.dtype != np.uint8:
            raise ValueError('parallel_camera_frame_mismatch')
        data = np.ascontiguousarray(image).tobytes()
        while True:
            if self.error is not None or not self.thread.is_alive():
                raise RuntimeError('parallel_encoder_failed') from self.error
            try:
                self.queue.put(data, timeout=.2)
                return
            except queue.Full:
                pass

    def close(self):
        if not self.closed:
            while self.thread.is_alive():
                try:
                    self.queue.put(None, timeout=.2)
                    break
                except queue.Full:
                    if self.error:
                        break
            self.thread.join()
            self.returncode = self.process.wait()
            self.log.close()
            self.closed = True
        return dict(path=str(self.path), frames=self.frames,
                    returncode=self.returncode, error=repr(self.error) if self.error else None,
                    dropped_frames=0, fps=20)
