$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$gatewayKey = Join-Path $projectRoot '.secrets/haoze_ec2.pem'
$gpuKey = Join-Path $projectRoot '.secrets/mobaxterm_gpu_ed25519'
$gatewayKey = $gatewayKey.Replace('\', '/')
$proxyCommand = 'ssh -o BatchMode=yes -i "' + $gatewayKey + '" -W %h:%p ec2-user@47.130.167.160'
& ssh -tt -o BatchMode=yes -o ConnectTimeout=15 -o HostKeyAlias=r1pro-gpu-via-ec2 -o "ProxyCommand=$proxyCommand" -p 2222 -i $gpuKey michelle@127.0.0.1
exit $LASTEXITCODE
