"""Export an annotated wall-clock diagnostic from native frames; never hide waits."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
from PIL import Image,ImageDraw,ImageFont

def export(run):
    run=Path(run);out=run/'video_export';out.mkdir(exist_ok=False)
    native=run/'native';room=native/'rooms/room_000'
    report=json.loads((run/'report.json').read_text())
    status=json.loads((native/'status.json').read_text())
    wall=[json.loads(s) for s in (native/'wall_clock_frames.jsonl').read_text().splitlines()]
    events=[json.loads(s) for s in (run/'inference_events.jsonl').read_text().splitlines()]
    if not wall:raise ValueError('No executed native frames; cannot export a working-motion video')
    sources=[native/'global_overview.mp4',room/'head_left.mp4',room/'left_wrist.mp4',room/'right_wrist.mp4']
    names=['Simulator overview','Robot head camera','Left wrist camera','Right wrist camera']
    for i,source in enumerate(sources):
        folder=out/str(i);folder.mkdir()
        subprocess.run(['ffmpeg','-v','error','-i',str(source),str(folder/'%06d.png')],check=True)
    font_path='/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
    font=ImageFont.truetype(font_path,22);small=ImageFont.truetype(font_path,18)
    duration=float(status['elapsed_seconds']);concat=[]
    for i,clock in enumerate(wall):
        image=Image.new('RGB',(1280,840),'#101820');draw=ImageDraw.Draw(image)
        draw.text((24,14),f"{report['modelFamily']} | checkpoint server -> ROS 2 -> Isaac PhysX",font=font,fill='white')
        draw.text((24,46),'Native camera observations and model commands. No teacher / IK fallback.',font=small,fill='#c4cdd5')
        for j,name in enumerate(names):
            frame=Image.open(out/str(j)/f'{i+1:06d}.png').convert('RGB');frame.thumbnail((632,316))
            x=8+(j%2)*640;y=85+(j//2)*350
            image.paste(frame,(x+(632-frame.width)//2,y+25));draw.text((x+8,y),name,font=small,fill='#82b1ff')
        query=sum(e['unix']<=clock['unix'] for e in events)
        draw.text((24,790),f"Frame {i+1}/{len(wall)} | sim {clock['simulation_seconds']:.2f}s | model replies {query} | waits retained",font=small,fill='white')
        path=out/f'frame_{i:06d}.png';image.save(path)
        start=0. if i==0 else clock['wall_seconds']
        end=wall[i+1]['wall_seconds'] if i+1<len(wall) else duration
        concat.extend([f"file '{path}'",f'duration {max(.001,end-start):.6f}'])
    final=Image.new('RGB',(1280,840),'#101820');draw=ImageDraw.Draw(final)
    lines=['Measured result',f"Model replies: {len(events)}; executed frames: {len(wall)}",f"Simulation: {len(wall)/20:.2f}s; wall-clock rollout: {duration:.2f}s",'20 Hz wall-clock requirement: '+('met' if duration<=len(wall)/20 else 'NOT MET'),f"Pick / Place passed: {report['passedPairs']} / {report['totalRooms']}"]
    reason=report['rooms'][0].get('reason');reason=reason.get('message') if isinstance(reason,dict) else reason
    lines.extend([str(reason or 'Completed physical task'),report.get('temporalComparison',''),'Recorded diagnostic, not a successful-task claim.'])
    for i,line in enumerate(lines):draw.text((40,100+i*65),line,font=font if i<5 else small,fill='white' if i<3 else '#ffcc80')
    finalpath=out/'result.png';final.save(finalpath);concat.extend([f"file '{finalpath}'",'duration 4',f"file '{finalpath}'"])
    (out/'timeline.txt').write_text('\n'.join(concat)+'\n')
    video=out/'camera_model_simulator_wallclock.mp4'
    subprocess.run(['ffmpeg','-v','error','-f','concat','-safe','0','-i',str(out/'timeline.txt'),'-vf','fps=30','-c:v','libx264','-crf','19','-pix_fmt','yuv420p','-movflags','+faststart',str(video)],check=True)
    receipt=dict(video=str(video),sha256=hashlib.sha256(video.read_bytes()).hexdigest(),executedFrames=len(wall),simulationSeconds=len(wall)/20,rolloutWallSeconds=duration,inferenceLatencies=[e['latency_seconds'] for e in events],speedRatio=(len(wall)/20)/duration,wallclock20HzMet=duration<=len(wall)/20,waitsRetained=True,resultSlateSeconds=4,rawSources=[str(s) for s in sources])
    (out/'receipt.json').write_text(json.dumps(receipt,indent=2));print(json.dumps(receipt))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);export(p.parse_args().run)
