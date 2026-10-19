"""Resume unchanged frozen Isaac BC only after an explicit native video review."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback
from isaacsim_stage_runner import atomic, identity, checked


def verified_legacy_gpu_runtime():
    """Same process-local GPU compatibility settings as the working BC pipeline."""
    return dict(NCCL_P2P_DISABLE='1',NCCL_SHM_DISABLE='1',NCCL_IB_DISABLE='1',
        NCCL_NET='Socket',NCCL_CUMEM_HOST_ENABLE='0',
        XLA_FLAGS='--xla_gpu_use_memcpy_local_p2p=false --xla_gpu_enable_nccl_user_buffers=false '
                  '--xla_gpu_enable_command_buffer= --xla_gpu_enable_triton_gemm=false')


def main():
    p=argparse.ArgumentParser();p.add_argument('--config',type=Path,required=True);a=p.parse_args()
    cfg=json.loads(a.config.read_text());run=Path(cfg['run']);training=Path(cfg['training']);run.mkdir(exist_ok=True)
    lock=(run/'bc_resume.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    state=dict(stage='waiting_for_stable_video_review',training_started=False,actual_completed_updates=0)
    def status(**kw):
        state.update(kw,heartbeat_unix=time.time());atomic(run/'pipeline_status.json',state)
    def stage(name,args,required):
        for attempt in range(3):
            stem=run/f'{name}_attempt_{attempt}';receipt=Path(str(stem)+'.exit.json');launch=Path(str(stem)+'.launch.json');job=Path(str(stem)+'.job.json')
            if receipt.exists():
                if json.loads(receipt.read_text())['returncode']==0 and all(Path(p).exists() for p in required):return
                continue
            if not job.exists():
                # A verified prior child is always adopted, never duplicated.
                for d in Path('/proc').iterdir():
                    if not d.name.isdigit():continue
                    try:argv=(d/'cmdline').read_text().split('\0')[:-1]
                    except (FileNotFoundError,PermissionError,ProcessLookupError):continue
                    if '--mode' in argv and 'train' in argv and any(x.endswith('/train_pi05_isaac_three_tray.py') for x in argv):
                        raise RuntimeError('another_native_BC_process_exists_no_duplicate:'+d.name)
                env=dict(AIRPORT_PROJECT=cfg['project'],PATH=cfg['compiler_bin']+':'+str(Path(cfg['vla_python']).parent)+':'+os.environ.get('PATH',''))
                if cfg.get('disable_nccl_p2p',False):
                    # Verified transport workaround only; preserve two GPUs,
                    # optimizer, batch, sample schedule and model math.
                    env.update(NCCL_P2P_DISABLE='1',NCCL_DEBUG='WARN')
                if cfg.get('verified_legacy_gpu_runtime',False):env.update(verified_legacy_gpu_runtime())
                atomic(job,dict(argv=args,cwd=cfg['project'],log=str(stem)+'.log',launch=str(launch),receipt=str(receipt),environment=env))
                subprocess.Popen([sys.executable,str(Path(__file__).with_name('isaacsim_stage_runner.py')),'--job',str(job)],cwd=cfg['project'],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
            while not receipt.exists():
                child=json.loads(launch.read_text()) if launch.exists() else None
                runner=Path(str(stem)+'.job.runner.json');runner_identity=json.loads(runner.read_text()) if runner.exists() else None
                if child and not checked(child) and not (runner_identity and checked(runner_identity)):raise RuntimeError('child_missing_without_wait_receipt')
                if not child and runner_identity and not checked(runner_identity):raise RuntimeError('stage_runner_died_before_launch')
                if not child and not runner_identity and time.time()-job.stat().st_mtime>60:raise RuntimeError('stage_runner_not_started_no_training_timeout_applied')
                t=training/'training_status.json';progress=json.loads(t.read_text()) if t.exists() else {}
                status(stage=name,child=child,training_status=progress.get('stage','not_started'),training_started=progress.get('training_started',False),actual_completed_updates=progress.get('actual_completed_updates',0))
                time.sleep(5)
            result=json.loads(receipt.read_text())
            if result['returncode']==0 and all(Path(p).exists() for p in required):return
            status(last_error=dict(stage=name,attempt=attempt,exit=result,required_artifacts=required))
            if attempt<2:time.sleep((10,30)[attempt])
        raise RuntimeError('stage_failed_after_three_preserved_attempts:'+name)
    try:
        # Independent native probes may still own the GPUs. Receipt closure,
        # including a recorded failed candidate, releases resources only; it
        # does not qualify that candidate as data for this frozen BC.
        pending=list(map(Path,cfg.get('wait_for_native_receipts',[])))
        while pending:
            missing=[str(p) for p in pending if not p.exists()]
            if not missing:
                if any(json.loads(p.read_text()).get('actual_child_wait') is not True for p in pending):
                    raise RuntimeError('resource_release_requires_actual_child_wait')
                break
            status(stage='waiting_for_native_resource_release',pending_actual_exit_receipts=missing)
            time.sleep(5)
        status()
        review=Path(cfg['review'])
        while not review.exists():status();time.sleep(5)
        reviewed=json.loads(review.read_text())
        if reviewed.get('approved_for_original_BC_resume') is not True:raise RuntimeError('video_review_did_not_authorize_resume')
        native=Path(reviewed['recorded_run']);audit=json.loads((native/'audit_summary.json').read_text())
        if not audit.get('all_planned_passed') or audit.get('actual_audited_cases')!=1:raise RuntimeError('recorded_native_audit_incomplete')
        from hashlib import sha256
        for path,digest in reviewed['evidence_sha256'].items():
            if sha256(Path(path).read_bytes()).hexdigest()!=digest:raise RuntimeError('reviewed_evidence_changed:'+path)
        training.mkdir(exist_ok=True)
        original=Path(cfg['original_training']);source=json.loads((original/'inputs.json').read_text())
        inputs=training/'inputs.json'
        if inputs.exists() and json.loads(inputs.read_text())!=source:raise RuntimeError('resume_inputs_changed')
        if not inputs.exists():atomic(inputs,source)
        cmd=[cfg['vla_python'],str(Path(cfg['training_code'])/'scripts/train_pi05_isaac_three_tray.py'),'--run',str(training)]
        stage('prepare',cmd+['--mode','prepare'],[str(training/'preparation_status.json')])
        for name in ('norm.json','sample_indices.npy'):
            if sha256((original/name).read_bytes()).digest()!=sha256((training/name).read_bytes()).digest():raise RuntimeError('original_BC_sampling_or_normalization_changed:'+name)
        for milestone in (10,100,1000,10000,100000):
            stage('train_'+str(milestone),cmd+['--mode','train','--stop',str(milestone)],[str(training/f'checkpoint_{milestone:06d}.json')])
        status(stage='training_complete_model_evaluation_pending',training_started=True,actual_completed_updates=100000)
    except BaseException as exc:
        status(stage='failed',last_error=repr(exc));atomic(run/'failure.json',dict(error=repr(exc),traceback=traceback.format_exc()));raise


if __name__=='__main__':main()
