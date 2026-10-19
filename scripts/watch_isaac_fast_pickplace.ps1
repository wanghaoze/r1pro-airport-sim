param([switch]$Watch, [int]$IntervalSeconds = 15)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$jumpKey = (Join-Path $projectRoot '.secrets/haoze_ec2.pem').Replace('\','/')
$serverKey = Join-Path $projectRoot '.secrets/mobaxterm_gpu_ed25519'
$proxy = 'ssh -o BatchMode=yes -o ConnectTimeout=8 -i "' + $jumpKey + '" -W %h:%p ec2-user@47.130.167.160'
$query = @'
import pathlib,json,datetime
b=pathlib.Path('/home/michelle/haoze/r1pro-airport-sim')
pointer=b/'runs/ISAAC_FAST_PICKPLACE_CURRENT.json'
r=pathlib.Path(json.loads(pointer.read_text())['run']) if pointer.exists() else b/'runs/isaacsim_fast_pickplace_20261016_v3'
def read(p):
 return json.loads(p.read_text()) if p.exists() else None
def alive(j):
 if not j:return False
 p=pathlib.Path('/proc')/str(j['pid'])
 try:
  s=(p/'stat').read_text().rsplit(')',1)[1].split()
  return s[0]!='Z' and s[19]==str(j['start_ticks']) and (p/'cmdline').read_text().split('\0')[:-1]==j.get('argv',j.get('command')) and str((p/'cwd').resolve())==j['cwd']
 except (FileNotFoundError,ProcessLookupError):return False
s=read(r/'pipeline_status.json') or {};g=read(r/'guardian_status.json') or {};a=read(r/'guardian_launch.json');rows=read(r/'results.json') or []
index=[]
for case in sorted(r.glob('case_[0-9][0-9][0-9]')):
 audit=read(case/'independent_audit_v2.json') or read(case/'independent_audit_v1.json');result=read(case/'result.json')
 label='ENDPOINT_AUDITED_PATH_STABILITY_SEPARATE_NOT_TRAINING' if audit and audit['passed'] else 'RAW_BENCHMARK_RESULT_NOT_STABILITY_APPROVAL' if result else 'IN_PROGRESS'
 index.append('# '+case.name+' '+label)
 index.extend(str(p) for p in sorted(case.rglob('*.mp4')))
index.extend(str(p) for p in sorted(r.glob('multi_pose*.mp4')))
f=read(r/'finalizer_identity.json')
cases={c.name:dict(stability=read(c/'path_stability.json'),rubber=read(c/'rubber_pad_contact_translation.json')) for c in r.glob('case_[0-9][0-9][0-9]')}
config=read(r/'config.json') or {}
viewer=json.loads(pointer.read_text()).get('viewer') if pointer.exists() else 'http://100.104.0.108:8776/fast_pickplace_20261016_v3/index.html'
pointer_data=read(pointer) or {};probe_root=pointer_data.get('active_probe');probe=None
if probe_root:
 pr=pathlib.Path(probe_root);launch=read(pr/'case_000.launch.json');progress=pr/'case_000/native_steps.jsonl'
 probe=dict(root=str(pr),status=read(pr/'case_000/status.json'),result=read(pr/'case_000/result.json'),stability=read(pr/'case_000/path_stability.json'),exit=read(pr/'case_000.exit.json'),identity=launch,alive=alive(launch),recorded_frames=sum(1 for _ in progress.open()) if progress.exists() else 0,video_demo=False)
print(json.dumps(dict(time=datetime.datetime.now(datetime.timezone.utc).isoformat(),root=str(r),planned_cases=len(config.get('cases',[])),viewer=viewer,status=s,guardian=g,guardian_identity=a,guardian_alive=alive(a),producer_alive=alive(g.get('producer')),child_alive=alive(s.get('child')),finalizer_identity=f,finalizer_alive=alive(f),results=rows,cases=cases,audit=read(r/'audit_summary.json'),active_probe=probe,training_deferred_until_stable_video=pointer_data.get('training_deferred_until_stable_video',False),video_index='\n'.join(index))))
'@
do {
    $raw = $query | & ssh -T -o BatchMode=yes -o ConnectTimeout=10 -o HostKeyAlias=r1pro-gpu-via-ec2 -o "ProxyCommand=$proxy" -p 2222 -i $serverKey michelle@127.0.0.1 'python3 -'
    if ($LASTEXITCODE -ne 0) { throw 'SSH failed; the last verified snapshot is retained. Server jobs may still be running.' }
    $s = $raw | ConvertFrom-Json
    $runName = ($s.root -split '/')[-1]
    $reference = Join-Path $projectRoot ('runs/'+$runName+'_reference')
    New-Item -ItemType Directory -Force -Path $reference | Out-Null
    $utf8 = New-Object System.Text.UTF8Encoding($true)
    [System.IO.File]::WriteAllText((Join-Path $reference 'monitor_latest.json'), ($raw -join "`n"), $utf8)
    $lines = @("Snapshot: $($s.time)", 'Scope: native expert fast benchmark, not VLA, not full three-tray task, not training data. Endpoint success does not prove path stability.', "Run: $($s.root)", "Stage: $($s.status.stage)", "Completed: $($s.status.completed_cases)/$($s.planned_cases); endpoint passed: $($s.status.successful_cases); independently audited endpoints: $($s.audit.independently_passed)", "Guardian: $($s.guardian_alive); producer: $($s.producer_alive); active native: $($s.child_alive); finalizer: $($s.finalizer_alive)", "Viewer: $($s.viewer)")
    if ($s.active_probe) { $lines += @("Active physics probe (not video): $($s.active_probe.root)", "Probe: $($s.active_probe.status.stage); alive=$($s.active_probe.alive); frames=$($s.active_probe.recorded_frames); exit=$($s.active_probe.exit.returncode)") }
    if ($s.training_deferred_until_stable_video) { $lines += 'BC initialization deferred by user; 0 completed updates. Resume after stable recorded demo.' }
    [System.IO.File]::WriteAllText((Join-Path $projectRoot 'ISAAC_FAST_PICKPLACE_STATUS.txt'), ($lines -join "`r`n"), $utf8)
    [System.IO.File]::WriteAllText((Join-Path $projectRoot 'ISAAC_FAST_PICKPLACE_VIDEO_PATHS.txt'), ('Snapshot: '+$s.time+"`r`n"+$s.video_index), $utf8)
    $lines | Write-Output
    if ($s.status.last_error) { Write-Output $s.status.last_error }
    if ($Watch) { Start-Sleep -Seconds $IntervalSeconds }
} while ($Watch)
