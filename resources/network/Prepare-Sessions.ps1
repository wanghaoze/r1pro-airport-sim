$ErrorActionPreference = 'Stop'
$packageRoot = $PSScriptRoot
if ($packageRoot -match '[^\x00-\x7F]') { throw 'Extract this package to an ASCII path, for example C:\ssh-access' }
$keyRoot = Join-Path $packageRoot 'keys'
$ec2Key = Join-Path $keyRoot 'haoze_ec2.pem'
$gpuKey = Join-Path $keyRoot 'mobaxterm_gpu_ed25519'
$sid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
foreach ($keyFile in @($ec2Key, $gpuKey)) {
    if (-not (Test-Path -LiteralPath $keyFile)) { throw "Missing key: $keyFile" }
    & icacls $keyFile /inheritance:r /grant:r "*${sid}:(R)" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Unable to restrict private key permissions' }
}
$template = [System.IO.File]::ReadAllText((Join-Path $packageRoot 'sessions.template'), [System.Text.Encoding]::ASCII)
$sessions = $template.Replace('__EC2_KEY__', $ec2Key).Replace('__GPU_KEY__', $gpuKey)
$output = Join-Path $packageRoot 'EC2-and-GPU.mxtsessions'
[System.IO.File]::WriteAllText($output, $sessions, [System.Text.Encoding]::GetEncoding(1252))
Write-Host "Import this file into MobaXterm: $output"
Write-Host 'Sessions: EC2-public and GPU-public-via-EC2'
