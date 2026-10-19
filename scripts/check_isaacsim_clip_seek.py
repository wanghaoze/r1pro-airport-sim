"""Compare accurate input seeks with decoded frame indices; no task labels."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess


def hashes(args):
    result=subprocess.run(['ffmpeg','-nostdin','-v','error','-threads','2',*args,
        '-an','-fps_mode','passthrough','-f','framemd5','-'],capture_output=True,text=True,check=True)
    return [line.split(',')[-1].strip() for line in result.stdout.splitlines() if line and not line.startswith('#')]


def main():
    p=argparse.ArgumentParser();p.add_argument('--case',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    a.output.mkdir(parents=True,exist_ok=False);rows=[]
    try:
        for camera in ('head_left','left_wrist'):
            video=a.case/(camera+'.mp4')
            info=json.loads(subprocess.run(['ffprobe','-v','error','-select_streams','v:0',
                '-show_entries','stream=nb_frames,r_frame_rate','-of','json',str(video)],capture_output=True,text=True,check=True).stdout)['streams'][0]
            n=int(info['nb_frames']);assert info['r_frame_rate']=='20/1'
            frames=sorted({0,1,20,min(661,n-1),min(1001,n-1),n-2,n-1})
            expression='+'.join(f'eq(n\\,{f})' for f in frames)
            reference=hashes(['-i',str(video),'-vf',f'select={expression},format=rgb24'])
            assert len(reference)==len(frames)
            for frame,expected in zip(frames,reference):
                actual=hashes(['-ss',f'{frame/20:.6f}','-i',str(video),'-frames:v','1','-vf','format=rgb24'])
                assert actual==[expected],(camera,frame,actual,expected)
            rows.append(dict(camera=camera,frames=frames,decoded_rgb_md5_exact_match=True))
        result=dict(passed=True,scope='read_only_video_timing_regression_not_task_qualification',
            source_case=str(a.case),task_labels_unchanged=True,results=rows)
        (a.output/'report.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
    except BaseException as exc:
        (a.output/'failure.json').write_text(json.dumps(dict(passed=False,error=repr(exc))));raise


if __name__=='__main__':main()
