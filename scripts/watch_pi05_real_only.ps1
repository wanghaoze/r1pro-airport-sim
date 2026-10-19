param([int]$RefreshSeconds=10)
$ErrorActionPreference='Stop'
$projectRoot=Split-Path -Parent $PSScriptRoot
$gatewayKey=(Join-Path $projectRoot '.secrets/haoze_ec2.pem').Replace('\','/')
$gpuKey=Join-Path $projectRoot '.secrets/mobaxterm_gpu_ed25519'
$proxyCommand='ssh -o BatchMode=yes -i "'+$gatewayKey+'" -W %h:%p ec2-user@47.130.167.160'
$remoteRoot='/home/michelle/haoze/r1pro-airport-sim'
& ssh -T -o BatchMode=yes -o ConnectTimeout=15 -o HostKeyAlias=r1pro-gpu-via-ec2 -o "ProxyCommand=$proxyCommand" -p 2222 -i $gpuKey michelle@127.0.0.1 "python3 -u $remoteRoot/scripts/watch_pi05_real_only.py --run $remoteRoot/runs/real_only_pi05_20261012_v1 --watch $RefreshSeconds"
exit $LASTEXITCODE
