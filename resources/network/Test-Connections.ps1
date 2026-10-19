$ErrorActionPreference = 'Stop'
$ec2Key = Join-Path $PSScriptRoot 'keys/haoze_ec2.pem'
$gpuKey = Join-Path $PSScriptRoot 'keys/mobaxterm_gpu_ed25519'
$knownHosts = Join-Path $PSScriptRoot 'known_hosts'
& ssh -o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=yes -o "UserKnownHostsFile=$knownHosts" -i $ec2Key ec2-user@47.130.167.160 hostname
if ($LASTEXITCODE -ne 0) { throw 'EC2 SSH check failed' }
$proxy = 'ssh -o BatchMode=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile="' + $knownHosts.Replace('\', '/') + '" -i "' + $ec2Key.Replace('\', '/') + '" -W %h:%p ec2-user@47.130.167.160'
& ssh -o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=yes -o "UserKnownHostsFile=$knownHosts" -o HostKeyAlias=r1pro-gpu-via-ec2 -o "ProxyCommand=$proxy" -p 2222 -i $gpuKey michelle@127.0.0.1 hostname
if ($LASTEXITCODE -ne 0) { throw 'GPU SSH through EC2 check failed' }
Write-Host 'EC2 and GPU command-line SSH checks passed. MobaXterm GUI still needs a separate login check.'
