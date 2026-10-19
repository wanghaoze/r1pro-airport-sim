"""Read-only run metadata index; never controls jobs or certifies media."""
import argparse
import json
import os
from pathlib import Path
import time
import tempfile


def atomic(path, content):
    descriptor,name=tempfile.mkstemp(prefix=path.name+'.writing.',dir=path.parent)
    temporary=Path(name)
    with os.fdopen(descriptor,'w',encoding='utf-8') as stream:
        stream.write(content);stream.flush();os.fsync(stream.fileno())
    temporary.replace(path)


def stage(value):
    return value.get('stage') or value.get('phase') or value.get('status') or 'unavailable'


def current_state(options_path):
    if options_path is None:return dict(registered=False,stage='current_workflow_not_registered')
    result=dict(registered=True,options_path=str(options_path))
    try:
        path=Path(options_path).resolve();workflow=json.loads(path.read_text())
        settings=json.loads(Path(workflow['training_options']).read_text())
        run=Path(settings['run_dir']);training=Path(settings.get('external_training_run',run))
        result.update(resolved_options_path=str(path),workflow_dir=workflow['workflow_dir'],
                      pipeline_status_path=str(run/'pipeline_status.json'),training_status_path=str(training/'training_status.json'))
        for key,status_path in (('workflow',Path(workflow['workflow_dir'])/'workflow_status.json'),
                               ('pipeline',run/'pipeline_status.json'),('training',training/'training_status.json')):
            try:
                value=json.loads(status_path.read_text())
                result[key]=dict(path=str(status_path),stage=stage(value),
                    heartbeat_unix=value.get('heartbeat_unix',value.get('updated_unix')),
                    modified_unix=status_path.stat().st_mtime,
                    actual_completed_updates=value.get('actual_completed_updates'),
                    error=value.get('last_error',value.get('error')))
            except (OSError,ValueError) as error:result[key]=dict(path=str(status_path),read_error=repr(error))
        result['stage']=result.get('pipeline',{}).get('stage',result.get('workflow',{}).get('stage','unavailable'))
        result['actual_completed_updates']=result.get('training',{}).get('actual_completed_updates')
        result['optimizer_status_is_recorded_state_not_live_process_inference']=True
    except (OSError,ValueError,KeyError) as error:result.update(stage='registered_current_workflow_unavailable',read_error=repr(error))
    return result


def resolved_files(root,pattern):
    return sorted({str(p.resolve()) for p in root.rglob(pattern) if p.is_file()})


def snapshot(root, output, current_workflow=None):
    states = []
    seen=set()
    for name in ('workflow_status.json', 'pipeline_status.json', 'training_status.json',
                 'guardian_status.json', 'evaluation_summary.json'):
        for path in sorted(root.rglob(name)):
            try:
                resolved=str(path.resolve())
                if resolved in seen:continue
                seen.add(resolved)
                value = json.loads(path.read_text())
                states.append(dict(path=resolved, stage=stage(value),
                    pid=value.get('pid', value.get('guardian_pid')),
                    training_started=value.get('training_started'),
                    actual_completed_updates=value.get('actual_completed_updates'),
                    error=value.get('last_error', value.get('error')),
                    modified_unix=path.stat().st_mtime))
            except (OSError, ValueError) as error:
                states.append(dict(path=str(path), read_error=repr(error)))
    videos = resolved_files(root,'*.mp4')
    trajectories = resolved_files(root,'trace.h5')
    current=current_state(current_workflow)
    states.sort(key=lambda row:(-row.get('modified_unix',0),row['path']))
    receipt = dict(schema='airport_three_table_readonly_server_index/1',
        heartbeat_unix=time.time(), pid=os.getpid(), run_root=str(root),
        states=states, video_count=len(videos), trajectory_count=len(trajectories),
        current=current, media_identity='unique_resolved_file_path', historical_states_are_not_current_stage=True,
        metadata_only=True, validity_requires_stage_receipt=True,
        training_status_is_not_inferred_from_waiter_pid=True)
    atomic(output/'SERVER_VIDEO_PATHS.txt', ''.join(p+'\n' for p in videos))
    atomic(output/'SERVER_TRAJECTORY_PATHS.txt', ''.join(p+'\n' for p in trajectories))
    atomic(output/'SERVER_PROGRESS.txt',
        'Read-only server snapshot; artifact existence alone is not success.\n'+
        'CURRENT_REGISTERED_WORKFLOW '+json.dumps(current,ensure_ascii=False)+'\n'+
        'HISTORICAL_AND_CURRENT_METADATA (each resolved file once; no current-stage inference)\n'+
        '\n'.join(json.dumps(row, ensure_ascii=False) for row in states)+'\n')
    atomic(output/'index_status.json', json.dumps(receipt, indent=2))
    return receipt


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--once', action='store_true')
    parser.add_argument('--current-workflow',type=Path,help='Explicit current workflow options; external training run is read from this registration')
    args=parser.parse_args()
    root=args.root.resolve(); output=args.output.resolve()
    if not root.is_dir() or not output.is_relative_to(root):
        raise ValueError('index_output_must_be_inside_existing_run_root')
    if args.current_workflow is not None and not args.current_workflow.resolve().is_relative_to(root):
        raise ValueError('current_workflow_registration_must_be_inside_run_root')
    output.mkdir(parents=True, exist_ok=True)
    import fcntl
    lock=(output/'index.lock').open('a+')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    while True:
        receipt=snapshot(root, output,args.current_workflow)
        if args.once:
            print(json.dumps(receipt)); return
        time.sleep(30)


if __name__=='__main__':
    main()
