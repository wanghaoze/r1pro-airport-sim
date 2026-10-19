"""Four native cameras beside a fresh VLA attempt's trace; inspection only."""
from pathlib import Path
import argparse,hashlib,json,sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


def current_native_video_metadata(directory,shapes):
    """Inspect only current direct streams; preserved partials are separate evidence."""
    import av
    result=[]
    for camera,(height,width,_) in shapes.items():
        path=Path(directory)/(camera+'.mp4')
        with av.open(str(path)) as container:
            stream=container.streams.video[0]
            fps=float(stream.average_rate) if stream.average_rate else None
            if (stream.width,stream.height)!=(width,height) or fps!=20 or stream.codec_context.name!='h264':
                raise ValueError('Current native video contract mismatch:'+camera)
            frames=sum(1 for _ in container.decode(video=0))
            if frames<=0:raise ValueError('Current native stream has no decoded frames')
            result.append(dict(file=path.name,camera=camera,width=width,height=height,fps=fps,frames=frames,codec='h264'))
    return result


def render_one(attempt,collection,controller_root,*,recover_failed_tail=False):
    from scripts.render_vla_rollout_videos import render_attempt
    from r1pro_teleop.airport_fsm.exporter import Replay
    instances=[]
    factory=Replay
    if recover_failed_tail:
        helper=Path(controller_root)/'runs/vla_deploy_20261001/render_failed_raw1_heads.py'
        import importlib.util
        spec=importlib.util.spec_from_file_location('guarded_raw1_tail',helper)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        class TailReplay(Replay):
            def __init__(self,*args,**kwargs):
                super().__init__(*args,**kwargs);instances.append(self);self.tail_details=None
            def __iter__(self):
                yield from super().__iter__()
                self.tail_details=module.recover_failed_raw1_tail(self)
        factory=TailReplay
    manifest=render_attempt(attempt,collection,Path(attempt).parents[2],controller_root=controller_root,
        replay_factory=factory,video_checker=current_native_video_metadata,
        camera_names=('head_left','head_right','left_wrist','right_wrist'),in_attempt_directory=True)
    if recover_failed_tail:
        manifest['failed_final_interval_replay']=instances[0].tail_details
        manifest['diagnostic_tail_helper_sha256']=hashlib.sha256(helper.read_bytes()).hexdigest()
        manifest['control_journal_semantics']+='; unique incomplete final raw1 interval reconstructed with held frozen-servo controls and strict terminal proof; no terminal ctrl journal'
        (Path(attempt)/'manifest.json').write_text(json.dumps(manifest,indent=2))
    return manifest


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--attempt',required=True);parser.add_argument('--source-collection',required=True)
    parser.add_argument('--controller-root',required=True)
    parser.add_argument('--recover-failed-tail',action='store_true')
    args=parser.parse_args()
    print(json.dumps(render_one(args.attempt,args.source_collection,args.controller_root,
        recover_failed_tail=args.recover_failed_tail)))


if __name__=='__main__':main()
