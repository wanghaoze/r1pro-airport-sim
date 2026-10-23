"""Durable, idempotent post-training evaluation. Called under scheduler.lock."""
from pathlib import Path
import hashlib
import time


def payload(training_run='current'):
    return dict(schema='studio_auto_evaluation/1',trainingRun=training_run,checkpointSelection='latest_final',
                sceneSetId='isaac32_20261017',roomIds=list(range(32)),framesPerAction=200,
                split='test',baseline='real_only_10000',teacherFallback=False)


def training_root(b,request):
    source=request['payload']['trainingRun']
    if source=='current':return b.CURRENT
    parent=b.read(b.JOBS/source/'request.json')
    if parent.get('kind')!='training.create':raise ValueError('automatic_training_run_not_registered')
    return b.JOBS/source/'training'


def final_checkpoint(b,root,entries):
    """Require actual updates, a closed final checkpoint and a successful child wait."""
    t=b.read(root/'training_status.json');inputs=b.read(root/'inputs.json')
    target=inputs.get('training_steps',t.get('target_updates',10000))
    if t.get('actual_completed_updates',0)<target:return None
    candidates=[c for c in entries if Path(c['run'])==root and c['updates']>=target]
    if not candidates:return None
    latest=max(candidates,key=lambda c:c['updates'])
    receipts=list(root.glob(f'train_{target}_attempt_*.exit.json'))
    if root.parent.parent==b.JOBS:receipts.append(root.parent/'train.exit.json')
    if not any(b.read(p).get('actual_child_wait') is True and b.read(p).get('returncode')==0 for p in receipts):return None
    return latest


def reconcile(b):
    # New training jobs opt in explicitly in their immutable submitted recipe.
    for p in sorted(b.JOBS.glob('*/request.json')):
        parent=b.read(p)
        if parent.get('kind')=='training.create' and parent['payload'].get('autoEvaluate') is True:
            identifier='auto_'+hashlib.sha256(parent['id'].encode()).hexdigest()[:24]
            if not (b.JOBS/identifier/'request.json').exists():
                b.enqueue(dict(id=identifier,kind='evaluation.auto',payload=payload(parent['id'])))
    entries=b.checkpoints()
    for p in sorted(b.JOBS.glob('*/request.json')):
        request=b.read(p)
        if request.get('kind')!='evaluation.auto':continue
        run=p.parent;state=b.read(run/'status.json')
        if state.get('status') in ('completed','failed'):continue
        try:
            root=training_root(b,request);binding=b.read(run/'selection.json')
            if not binding:
                checkpoint=final_checkpoint(b,root,entries)
                if not checkpoint:
                    training=b.read(root/'training_status.json');parent=b.read(root.parent/'status.json')
                    failed=training.get('stage')=='failed' or parent.get('status')=='failed'
                    b.write(run/'status.json',dict(state,status='failed' if failed else 'waiting_training',
                        message='Training failed; no partial checkpoint is evaluated.' if failed else 'Waiting for completed training, a closed final checkpoint and its successful exit receipt.',heartbeat_unix=time.time()))
                    continue
                baselines=[c for c in entries if Path(c['run']).name=='real_only_pi05_20261012_v1' and c['updates']==10000]
                if not baselines:raise ValueError('automatic_real_baseline_not_registered')
                key=hashlib.sha256((request['id']+checkpoint['id']).encode()).hexdigest()[:24]
                binding=dict(checkpointId=checkpoint['id'],checkpointLabel=checkpoint['label'],checkpointUpdates=checkpoint['updates'],
                             trainingRun=str(root),baselineId=baselines[0]['id'],vlaJobId='avla_'+key,mseJobId='amse_'+key,selectedAt=time.time())
                b.write(run/'selection.json',binding)
            vla=dict(schema='studio_vla/1',actionSafetyMode='robot_limits',checkpointIds=[binding['checkpointId']],sceneSetId='isaac32_20261017',roomIds=list(range(32)),
                     framesPerAction=200,fps=20,executionHorizon=5,policyHorizon=20,baseActuatorMask='fixed_episode_base',teacherFallback=False,
                     scope='training_scene_native_closed_loop_diagnostic',heldOutGeneralization=False,trainingEligible=False)
            mse=dict(schema='studio_mse/1',checkpointIds=[binding['checkpointId'],binding['baselineId']],split='test',
                     protocol='real_all_frames_h20_noise42000_v1',horizon=20,stride=1,baseChannelsExcluded=True,units={'arms':'rad²','grippers':'mm²'},robotExecution=False)
            for kind,job_id,config in [('evaluation.vla',binding['vlaJobId'],vla),('evaluation.mse',binding['mseJobId'],mse)]:
                if not (b.JOBS/job_id/'request.json').exists():
                    b.enqueue(dict(id=job_id,kind=kind,payload=config,automaticParentId=request['id']))
            children={name:b.read(b.JOBS/binding[name+'JobId']/'status.json') for name in ('vla','mse')}
            finished=all(c.get('status') in ('completed','failed','blocked') for c in children.values())
            failed=any(c.get('status') in ('failed','blocked') for c in children.values())
            report=dict(scope='automatic_evaluation',**binding,**children,trainingRunId=request['payload']['trainingRun'])
            b.write(run/'status.json',dict(state,status=('failed' if failed else 'completed') if finished else 'running',
                message='Automatic evaluations finished. Read the measured results below.' if finished else 'Latest final checkpoint selected. Automatic VLA and paired MSE are queued or running.',
                heartbeat_unix=time.time(),report=report))
        except Exception as exc:
            b.write(run/'status.json',dict(state,status='failed',message=str(exc),error=repr(exc),heartbeat_unix=time.time()))


def summaries(b):
    return [dict(id=p.parent.name,payload=b.read(p)['payload'],**b.read(p.parent/'status.json'))
            for p in sorted(b.JOBS.glob('*/request.json'),key=lambda p:p.stat().st_mtime,reverse=True)
            if b.read(p).get('kind')=='evaluation.auto'][:20]
