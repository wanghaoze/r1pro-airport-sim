$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$gatewayKey = (Join-Path $projectRoot '.secrets/haoze_ec2.pem').Replace('\', '/')
$gpuKey = Join-Path $projectRoot '.secrets/mobaxterm_gpu_ed25519'
$proxyCommand = 'ssh -o BatchMode=yes -i "' + $gatewayKey + '" -W %h:%p ec2-user@47.130.167.160'
$remoteCommand = '/home/michelle/miniconda3/envs/r1pro-vla/bin/python /home/michelle/haoze/r1pro-airport-sim/releases/galaxea_keyboard_control_20261013_v3/control_galaxea_servers.py --control-file /home/michelle/haoze/r1pro-airport-sim/runs/galaxea_robot_deploy_20261013_v2/operator_control.json'
& ssh -tt -o BatchMode=yes -o ConnectTimeout=15 -o HostKeyAlias=r1pro-gpu-via-ec2 -o "ProxyCommand=$proxyCommand" -p 2222 -i $gpuKey michelle@127.0.0.1 $remoteCommand
exit $LASTEXITCODE
