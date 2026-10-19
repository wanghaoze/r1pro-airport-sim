"""Independently expose action clips as soon as a full native source closes."""
import argparse
import fcntl
import html
import json
from pathlib import Path
import sys
import subprocess
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from isaacsim_stage_runner import atomic
from r1pro_teleop.vla.isaac_dataset import export_episode_preview,validate_episode,sha,resolve_inside,video_probe


def reuse_preview(output,episode,registry):
    source=validate_episode(episode,registry);result=json.loads((output/'manifest.json').read_text())
    if (result.get('schema')!='airport_isaac_episode_action_preview/1' or not result.get('ready') or
            result['source_manifest_sha256']!=sha(episode/'episode.json') or len(result['segments'])!=len(source['actions'])):
        raise ValueError('preview_reuse_source_or_count_mismatch')
    for segment in result['segments']:
        if segment['source_trace_sha256']!=source['trace_sha256']:raise ValueError('preview_reuse_trace_changed')
        for path,expected in ((segment['trajectory'],segment['trajectory_sha256']),(segment['instruction_path'],segment['instruction_sha256'])):
            if sha(resolve_inside(output,Path(path)))!=expected:raise ValueError('preview_reuse_artifact_changed')
        for video in segment['videos'].values():
            path=resolve_inside(output,Path(video['path']))
            if sha(path)!=video['sha256'] or video_probe(path)['frames']!=segment['frames']:raise ValueError('preview_reuse_video_not_closed')
    return result


def main():
    p=argparse.ArgumentParser();p.add_argument('--config',type=Path,required=True);a=p.parse_args()
    cfg=json.loads(a.config.read_text());run=Path(cfg['run']);run.mkdir(exist_ok=True)
    lock=(run/'preview.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    def state(stage,**kw):atomic(run/'preview_status.json',dict(stage=stage,training_started=False,heartbeat_unix=time.time(),**kw))
    try:
        receipt=Path(cfg['demo_exit']);episode=Path(cfg['episode']);output=Path(cfg['output'])
        while not receipt.exists():state('waiting_complete_demo');time.sleep(5)
        if json.loads(receipt.read_text())['returncode']!=0:raise RuntimeError('failed_demo_cannot_export_action_preview')
        while not (episode/'process_exit.json').exists():
            primary=Path(cfg['primary'])/'pipeline_status.json'
            if primary.exists() and json.loads(primary.read_text()).get('stage')=='failed':raise RuntimeError('primary_failed_before_exit_closure')
            state('waiting_independent_exit_copy');time.sleep(5)
        state('validating_and_exporting_qualified_source',output=str(output))
        registry=json.loads(Path(cfg['registry']).read_text());base_output=output;result=None
        for attempt in range(3):
            output=base_output if attempt==0 else base_output.with_name(base_output.name+f'_attempt_{attempt}')
            if (output/'manifest.json').exists():result=reuse_preview(output,episode,registry);break
            if output.exists():continue  # Preserve an unclosed previous process attempt.
            try:result=export_episode_preview(episode,registry,output);break
            except (OSError,subprocess.CalledProcessError) as exc:
                if attempt==2:raise
                state('export_process_backoff',attempt=attempt,error=repr(exc),output=str(output));time.sleep((10,30)[attempt])
        if result is None:raise RuntimeError('preview_export_attempts_exhausted_preserved_partials')
        links={prompt:[] for prompt in ('Pick up the tray','Place the tray','Flush tray to the left')}
        for segment in result['segments']:
            directory=Path(segment['trajectory']).parent
            body='<meta charset="utf-8"><h1>'+html.escape(segment['prompt'])+'</h1><p>合格完整三盘来源的动作片段；不是模型执行。</p>'
            for camera,video in segment['videos'].items():
                body+='<h2>'+html.escape(camera)+'</h2><video controls preload="metadata" width="640" src="'+Path(video['path']).name+'"></video>'
            (directory/'viewer.html').write_text(body)
            links[segment['prompt']].append('<a href="'+str((directory/'viewer.html').relative_to(output)).replace('\\','/')+'">'+html.escape(str(segment.get('tray_id') or segment['episode_id']))+'</a>')
        page=f'<meta charset="utf-8"><h1>三动作片段</h1><p>1 条完整合格来源，{len(result["segments"])} 个动作片段；三split训练批次尚需另行闭合。</p>'
        for prompt,items in links.items():page+='<h2>'+html.escape(prompt)+'</h2>'+' | '.join(items)
        (output/'index.html').write_text(page)
        state('preview_ready',full_sources=1,action_segments=len(result['segments']),training_batch_ready=False,output=str(output))
    except BaseException as exc:state('failed',last_error=repr(exc));raise


if __name__=='__main__':main()
