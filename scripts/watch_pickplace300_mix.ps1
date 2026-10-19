param([int]$RefreshSeconds = 5)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$gatewayKey = (Join-Path $projectRoot '.secrets/haoze_ec2.pem').Replace('\', '/')
$gpuKey = Join-Path $projectRoot '.secrets/mobaxterm_gpu_ed25519'
$proxyCommand = 'ssh -o BatchMode=yes -o ConnectTimeout=10 -i "' + $gatewayKey + '" -W %h:%p ec2-user@47.130.167.160'
if ($RefreshSeconds -lt 1) { throw 'RefreshSeconds must be positive.' }
$remote = 'python3 -u /home/michelle/haoze/r1pro-airport-sim/runs/isaacsim_parallel_pickplace300_20261017_v1/watch_progress.py --watch ' + $RefreshSeconds
& ssh -T -o BatchMode=yes -o ConnectTimeout=15 -o HostKeyAlias=r1pro-gpu-via-ec2 -o "ProxyCommand=$proxyCommand" -p 2222 -i $gpuKey michelle@127.0.0.1 $remote
exit $LASTEXITCODE
