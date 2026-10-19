param([int]$RefreshSeconds = 5)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$identityPath = Join-Path $projectRoot '.secrets/experiments_ed25519'
$remoteRun = '/home/michelle/haoze/r1pro-airport-sim/runs/real_sim_pickplace_20261009_v3'
$remoteMonitor = '/home/michelle/haoze/r1pro-airport-sim/scripts/watch_real_sim_transfer.py'
if ($RefreshSeconds -lt 1) { throw 'RefreshSeconds must be positive.' }
& ssh -T -o BatchMode=yes -o ConnectTimeout=10 -i $identityPath michelle@100.104.0.108 "python3 -u $remoteMonitor --run $remoteRun --watch $RefreshSeconds"
exit $LASTEXITCODE
