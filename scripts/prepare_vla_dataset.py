"""Build frame-aligned pi0.5 supervision manifests without modifying collections."""
from pathlib import Path
import argparse
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from r1pro_teleop.vla.data import prepare_manifest, probe_video, read_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--collection', action='append', required=True)
    parser.add_argument('--output', required=True, help='New JSONL outside source collections')
    parser.add_argument('--video-references', help='JSON list: trace/camera/path/source_start_frame/video_start_frame/frames')
    parser.add_argument('--local-qualifications', help='Explicit reviewed failed-prefix labels; excluded by default')
    parser.add_argument('--verify-videos', action='store_true', help='ffprobe native shape/FPS and decoded frame counts')
    args = parser.parse_args()
    result = prepare_manifest(args.collection, args.output,
        video_references=read_json(args.video_references) if args.video_references else (),
        local_qualifications=read_json(args.local_qualifications) if args.local_qualifications else (),
        video_probe=probe_video if args.verify_videos else None)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
