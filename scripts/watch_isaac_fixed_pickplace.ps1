param([switch]$Watch,[int]$IntervalSeconds=15)
$ErrorActionPreference='Stop'
$projectRoot=Split-Path -Parent $PSScriptRoot
$jumpKey=(Join-Path $projectRoot '.secrets/haoze_ec2.pem').Replace('\','/')
$serverKey=Join-Path $projectRoot '.secrets/mobaxterm_gpu_ed25519'
$proxy='ssh -o BatchMode=yes -o ConnectTimeout=8 -i "'+$jumpKey+'" -W %h:%p ec2-user@47.130.167.160'
$query=@'
from pathlib import Path
import json,datetime
b=Path('/home/michelle/haoze/r1pro-airport-sim');pointer=json.loads((b/'runs/ISAAC_FIXED_PICKPLACE_CURRENT.json').read_text());r=Path(pointer['run'])
def read(p):return json.loads(p.read_text()) if p.exists() else None
def alive(j):
 if not j:return False
 try:
  p=Path('/proc')/str(j['pid']);s=(p/'stat').read_text().rsplit(')',1)[1].split()
  return s[0]!='Z' and s[19]==str(j['start_ticks']) and (p/'cmdline').read_text().split('\0')[:-1]==j['argv'] and str((p/'cwd').resolve())==j['cwd']
 except (FileNotFoundError,ProcessLookupError):return False
state=read(r/'collection_status.json') or {};native=read(r/'pipeline_status.json') or {};guard=read(r/'guardian_launch.json');g=read(r/'guardian_status.json') or {};catalog=read(r/'dataset_catalog.json') or {};paths=[]
for batch in catalog.get('frozen_batches',[]):
 for segment in batch['segments']:
  paths.append('# '+segment['prompt']+' '+segment['split']+' EXPERT_CLOSED_TWO_ACTION_SCOPE')
  paths.extend(v['path'] for v in segment['videos'])
print(json.dumps(dict(time=datetime.datetime.now(datetime.timezone.utc).isoformat(),pointer=pointer,status=state,native=native,guardian_alive=alive(guard),supervisor_alive=alive(g.get('producer')),native_alive=alive(native.get('child')),catalog=catalog,video_paths='\n'.join(paths))))
'@
do {
 $raw=$query | ssh -T -o BatchMode=yes -o ConnectTimeout=10 -o HostKeyAlias=r1pro-gpu-via-ec2 -o "ProxyCommand=$proxy" -p 2222 -i $serverKey michelle@127.0.0.1 'python3 -'
 if($LASTEXITCODE -ne 0){throw 'SSH failed; last verified snapshot retained. This does not mean server jobs stopped.'}
 $s=$raw | ConvertFrom-Json
 $reference=Join-Path $projectRoot 'runs/isaacsim_fixed_pickplace_20261016_v1_reference'
 New-Item -ItemType Directory -Force -Path $reference | Out-Null
 $utf8=New-Object System.Text.UTF8Encoding($false)
 [IO.File]::WriteAllText((Join-Path $reference 'monitor_latest.json'),($raw -join "`n"),$utf8)
 $lines=@("Snapshot: $($s.time)",'Scope: fixed-base Pick/Place expert data, not full three-tray task or VLA results.',"Stage: $($s.status.stage)","Closed source pairs: $($s.catalog.complete_source_pairs); Pick: $($s.catalog.pick_segments); Place: $($s.catalog.place_segments)","Guardian: $($s.guardian_alive); supervisor: $($s.supervisor_alive); native: $($s.native_alive)","Current frame: $($s.native.progress.frames); action: $($s.native.progress.action.prompt)","Server root: $($s.pointer.run)","Viewer: $($s.pointer.viewer)",'Media and trajectories remain on server; no new training is implied.')
 [IO.File]::WriteAllText((Join-Path $projectRoot 'ISAAC_FIXED_PICKPLACE_STATUS.txt'),($lines -join "`r`n"),$utf8)
 [IO.File]::WriteAllText((Join-Path $projectRoot 'ISAAC_FIXED_PICKPLACE_VIDEO_PATHS.txt'),('Snapshot: '+$s.time+"`r`n"+$s.video_paths),$utf8)
 $lines | Write-Output
 if($s.status.last_error){Write-Output $s.status.last_error}
 if($Watch){Start-Sleep -Seconds $IntervalSeconds}
} while($Watch)
