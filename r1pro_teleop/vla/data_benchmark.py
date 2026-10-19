"""Small isolated stage timings for native-to-training video conversion."""
from pathlib import Path
import argparse
import json
import sys
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release', required=True)
    parser.add_argument('--native', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--frames', type=int, default=200)
    parser.add_argument('--parallel-candidate')
    args = parser.parse_args()
    sys.path.insert(0, args.release)
    from PIL import Image
    from r1pro_teleop.vla.data_lerobot import VideoCursor, model_image, MODEL_CAMERAS
    from lerobot.common.datasets.video_utils import encode_video_frames
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=False)
    if args.parallel_candidate:
        import importlib.util
        import numpy as np
        spec = importlib.util.spec_from_file_location('r1pro_teleop.vla.data_lerobot_parallel_audit', args.parallel_candidate)
        candidate = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(candidate)
        refs = {camera: {'path': str(Path(args.native) / (camera + '.mp4')), 'start_frame': 0}
                for camera in MODEL_CAMERAS}
        serial = candidate.CameraFrameReader(parallel=False)
        started = time.perf_counter()
        expected = []
        try:
            for index in range(args.frames):
                expected.append(serial.read(refs, index))
        finally:
            serial.close()
        serial_seconds = time.perf_counter() - started
        parallel = candidate.CameraFrameReader()
        parallel_seconds = 0.
        try:
            for index in range(args.frames):
                started = time.perf_counter()
                actual = parallel.read(refs, index)
                parallel_seconds += time.perf_counter() - started
                for camera in MODEL_CAMERAS:
                    np.testing.assert_array_equal(actual[camera], expected[index][camera])
        finally:
            parallel.close()
        measured = {'frames': args.frames, 'cameras': len(MODEL_CAMERAS), 'pixel_exact': True,
                    'serial_decode_resize_s': serial_seconds, 'parallel_decode_resize_s': parallel_seconds,
                    'speedup': serial_seconds / parallel_seconds, 'prefetch_frames': 0, 'workers': 3}
        (output / 'timings.json').write_text(json.dumps(measured, indent=2))
        print(json.dumps(measured), flush=True)
        return
    measured = {}
    for camera in MODEL_CAMERAS:
        times = {'decode_rgb_pil_s': 0., 'resize_pad224_s': 0., 'png_stage_s': 0.}
        directory = output / camera
        directory.mkdir()
        cursor = VideoCursor()
        for index in range(args.frames):
            start = time.perf_counter()
            image = cursor.frame(Path(args.native) / (camera + '.mp4'), index)
            after_decode = time.perf_counter()
            training_image = model_image(image)
            after_resize = time.perf_counter()
            Image.fromarray(training_image).save(directory / f'frame_{index:06d}.png')
            after_png = time.perf_counter()
            times['decode_rgb_pil_s'] += after_decode - start
            times['resize_pad224_s'] += after_resize - after_decode
            times['png_stage_s'] += after_png - after_resize
        cursor.close()
        start = time.perf_counter()
        encode_video_frames(directory, output / (camera + '.mp4'), 20,
            vcodec='h264', pix_fmt='yuv420p', g=2, crf=18, fast_decode=1, overwrite=True)
        times['official_h264_encode_s'] = time.perf_counter() - start
        times['frames'] = args.frames
        measured[camera] = times
        print(json.dumps({camera: times}), flush=True)
    (output / 'timings.json').write_text(json.dumps(measured, indent=2))


if __name__ == '__main__':
    main()
