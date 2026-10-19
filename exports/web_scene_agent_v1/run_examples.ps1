$ErrorActionPreference = 'Stop'
$agentProject = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$agentPython = Join-Path $agentProject '.conda/experiment/python.exe'
foreach ($agentExample in @('describe', 'edit_room', 'list_datasets', 'plan_training')) {
    & $agentPython (Join-Path $PSScriptRoot 'executor.py') --project $agentProject --command (Join-Path $PSScriptRoot "examples/$agentExample.json")
    if ($LASTEXITCODE -ne 0) { throw "Agent example failed: $agentExample" }
}
