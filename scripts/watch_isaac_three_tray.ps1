param([switch]$Watch, [int]$IntervalSeconds = 15)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$jumpKey = (Join-Path $projectRoot '.secrets/haoze_ec2.pem').Replace('\','/')
$serverKey = Join-Path $projectRoot '.secrets/mobaxterm_gpu_ed25519'
$proxy = 'ssh -o BatchMode=yes -o ConnectTimeout=8 -i "' + $jumpKey + '" -W %h:%p ec2-user@47.130.167.160'
$query = @'
import pathlib,json,datetime
w=pathlib.Path('/home/michelle/haoze/r1pro-airport-sim/runs/isaacsim_three_tray_workflow_20261015_v1')
def read(p):
 p=pathlib.Path(p);return json.loads(p.read_text()) if p.exists() else None
p=read(w/'CURRENT_NATIVE_PIPELINE.json');bootstrap=read(w/'CURRENT_NATIVE_BOOTSTRAP.json');bs=None
if bootstrap:
 bs=read(w/bootstrap['pipeline']/'status.json')
 if bs and bs.get('stage')!='recorded_demo_and_background_pipeline_started':p=bootstrap
 else:bs=None
d=w/p['demo'];r=w/p['pipeline'];jobs=[]
pipeline=dict(bs,training_status='waiting_for_data') if bs else read(r/'pipeline_status.json')
identities=[(key,read(w/p[key])) for key in ['demo_identity','pipeline_identity','guardian_identity']]
if pipeline:
 active=read(r/'logs'/(pipeline.get('stage','')+'.launch.json'))
 if active:identities.append(('active_stage_identity',active))
for key,j in identities:
 if not j:jobs.append(dict(role=key,pid=None,identity_alive=False));continue
 proc=pathlib.Path(f"/proc/{j['pid']}");alive=False
 if proc.exists():
  try:
   stat=proc.joinpath('stat').read_text().rsplit(')',1)[1].split();argv=proc.joinpath('cmdline').read_text().split('\0')[:-1]
   alive=stat[0]!='Z' and stat[19]==str(j['start_ticks']) and argv==j.get('argv',j.get('command')) and str(proc.joinpath('cwd').resolve())==j['cwd']
  except FileNotFoundError:pass
 jobs.append(dict(role=key,pid=j['pid'],identity_alive=alive))
index=[]
cases=list(w.glob('demo_candidate_*'))+list(w.glob('pipeline_v*/episodes/case_*'))+list((w/p.get('expansion','expansion_v2')/'episodes').glob('seed_*'))
for case in sorted(set(cases)):
 exit=read(w/(case.name.replace('demo_candidate_','demo')+'_exit.json')) if case.name.startswith('demo_candidate_') else read(case/'process_exit.json');q=read(case/'qualification.json');f=read(case/'failure.json')
 if not exit and case.name.startswith('case_'):exit=read(case.parent.parent/'logs'/('episode_'+case.name[5:]+'.exit.json'))
 label=('VALIDATED_FULL_SOURCE' if (case/'native_data_validation.json').exists() else 'TASK_SUCCESS_MEDIA_PENDING') if exit and exit['returncode']==0 and q and q['complete_task_success'] else 'FAILED_NOT_TRAINING' if exit else 'IN_PROGRESS_NOT_QUALIFIED'
 index.append('# '+str(case.relative_to(w))+' '+label+(' '+f['message'] if f else ''));index.extend(str(v) for v in sorted(case.glob('*.mp4')))
clip_roots=list(w.glob('demo*_action_preview_v*'))+[r/'three_actions_v1',w/p.get('expansion','expansion_v2')/'three_actions_v2']
for clips in clip_roots:
 if clips.is_dir():
  m=read(clips/'manifest.json');index.append('# '+clips.name+(' CLOSED_ACTION_CLIPS_PREVIEW_IS_NOT_A_TRAINING_BATCH' if m and m.get('ready') else 'UNCLOSED_EXPORT_NOT_TRAINING'))
  index.extend(str(v) for v in sorted(clips.rglob('*.mp4')))
active_progress=None;active_output=None
if pipeline:
 active=read(r/'logs'/(pipeline.get('stage','')+'.launch.json'))
 if active and '--output' in active.get('argv',[]):
  argv=active['argv'];active_output=argv[argv.index('--output')+1];active_progress=read(pathlib.Path(active_output)/'progress.json')
preview=read(w/p.get('preview','_no_preview')/'preview_status.json')
clip_progress=read(pathlib.Path(preview['output'])/'export_progress.json') if preview and preview.get('output') else None
resume=read(w/'CURRENT_NATIVE_BC_RESUME.json');resume_state=read(pathlib.Path(resume['root'])/'pipeline_status.json') if resume else None
training=read(pathlib.Path(resume['root'])/'training/training_status.json') if resume else None
if resume and not training:training=dict(stage=(resume_state or {}).get('stage','not_started'),training_started=False,actual_completed_updates=(resume_state or {}).get('actual_completed_updates',0))
print(json.dumps(dict(time=datetime.datetime.now(datetime.timezone.utc).isoformat(),pointer=p,jobs=jobs,demo_validated=(d/'native_data_validation.json').exists(),active_progress=active_progress,active_output=active_output,clip_progress=clip_progress,demo_status=read(d/'status.json'),progress=read(d/'progress.json'),failure=read(d/'failure.json'),pipeline=pipeline,training=training or read(r/'training/training_status.json'),bc_resume=resume,bc_resume_state=resume_state,data=read(r/'dataset_v1/manifest.json'),expansion=read(w/p.get('expansion','expansion_v2')/'pipeline_status.json'),preview=read(w/p.get('preview','_no_preview')/'preview_status.json'),video_index='\n'.join(index))))
'@
do {
    $raw = $query | & ssh -T -o BatchMode=yes -o ConnectTimeout=10 -o HostKeyAlias=r1pro-gpu-via-ec2 -o "ProxyCommand=$proxy" -p 2222 -i $serverKey michelle@127.0.0.1 'python3 -'
    if ($LASTEXITCODE -ne 0) { throw 'SSH failed; this does not mean the server jobs stopped.' }
    $state = $raw | ConvertFrom-Json
    $reference = Join-Path $projectRoot 'runs/isaacsim_three_tray_workflow_20261015_v1_reference'
    New-Item -ItemType Directory -Force -Path $reference | Out-Null
    $snapshotPath = Join-Path $reference 'monitor_latest.json'
    $snapshotTemp = $snapshotPath + '.tmp.' + $PID
    [System.IO.File]::WriteAllText($snapshotTemp, ($raw -join "`n"), (New-Object System.Text.UTF8Encoding($true)))
    Move-Item -LiteralPath $snapshotTemp -Destination $snapshotPath -Force
    $indexPath = Join-Path $projectRoot 'THREE_TRAY_ISAAC_VIDEO_PATHS.txt'
    $indexTemp = $indexPath + '.tmp.' + $PID
    $indexText = @('Snapshot: ' + $state.time, 'Videos remain on server. Success requires native qualification and actual exit.', $state.video_index) -join "`r`n"
    [System.IO.File]::WriteAllText($indexTemp, $indexText, (New-Object System.Text.UTF8Encoding($true)))
    Move-Item -LiteralPath $indexTemp -Destination $indexPath -Force
    $workflowPath = Join-Path $projectRoot 'THREE_TRAY_ISAAC_WORKFLOW_STATUS.txt'
    $workflowTemp = $workflowPath + '.tmp.' + $PID
    $workflowText = @"
Snapshot: $($state.time)
Scope: native three-tray expert/controller validation; not model execution.
Stage: $($state.pipeline.stage)
Training status: $($state.pipeline.training_status)
BC resume stage: $($state.bc_resume_state.stage)
BC resume directory: $($state.bc_resume.root)
Actual verified training updates: $($state.training.actual_completed_updates)
Demo/control case: $($state.pointer.run)/$($state.pointer.demo)
Current coordinator directory: $($state.pointer.run)/$($state.pointer.pipeline)
Pipeline state: $($state.pointer.run)/$($state.pointer.pipeline)/pipeline_status.json
Guardian state: $($state.pointer.run)/$($state.pointer.pipeline)/guardian_status.json
Demo media/trace validation present: $($state.demo_validated)
Active collection output: $($state.active_output)
Active collection frame: $($state.active_progress.frames)
Data manifest present: $([bool]$state.data)
Current process identities: $($state.jobs | ConvertTo-Json -Compress)
Viewer: $($state.pointer.viewer)
Live snapshot: runs/isaacsim_three_tray_workflow_20261015_v1_reference/monitor_latest.json
Actual video paths: THREE_TRAY_ISAAC_VIDEO_PATHS.txt
Missing training status or manifest means not yet verified; never means trained.
"@
    [System.IO.File]::WriteAllText($workflowTemp, $workflowText, (New-Object System.Text.UTF8Encoding($true)))
    Move-Item -LiteralPath $workflowTemp -Destination $workflowPath -Force
    Write-Host ($state.time + '  pipeline=' + $state.pipeline.stage + '  training=' + $state.pipeline.training_status)
    if ($state.bc_resume) { Write-Host ('BC resume: ' + $state.bc_resume_state.stage + '  ' + $state.bc_resume.root) }
    $demoPhase = if ($state.demo_validated) { 'validated_complete' } else { $state.demo_status.stage }
    Write-Host ('Demo: ' + $demoPhase + '  action=' + $state.progress.action.prompt + '  cycle=' + $state.progress.action.cycle_id + '/2  frames=' + $state.progress.frames)
    if ($state.active_progress) { Write-Host ('Active collection: action=' + $state.active_progress.action.prompt + ' cycle=' + $state.active_progress.action.cycle_id + '/2 frames=' + $state.active_progress.frames) }
    if ($state.clip_progress) { Write-Host ('Closed preview segments: ' + $state.clip_progress.completed_segments + '/' + $state.clip_progress.total_segments) }
    if ($state.failure) { Write-Host ('Failure: ' + $state.failure.message) }
    if ($state.preview) { Write-Host ('Action preview: ' + $state.preview.stage) }
    if ($state.training) {
        $updates = [int]$state.training.actual_completed_updates
        Write-Host ('BC: {0}/100000 ({1:F3}%)  active-stage ETA={2}s' -f $updates, ($updates/1000), $state.training.eta_seconds)
    } else { Write-Host 'BC: waiting_for_data; no native training updates verified.' }
    $state.jobs | Format-Table role,pid,identity_alive -AutoSize
    Write-Host ('Viewer: ' + $state.pointer.viewer)
    if ($Watch) { Start-Sleep -Seconds $IntervalSeconds }
} while ($Watch)
