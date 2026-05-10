$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$nodeRoot = Join-Path $repoRoot "tools\node-v24.11.0-win-x64"
$clineRoot = Join-Path $repoRoot "tools\npm-global"
$nodeExe = Join-Path $nodeRoot "node.exe"
$clineCmd = Join-Path $clineRoot "cline.cmd"

if (-not (Test-Path $nodeExe)) {
    Write-Error "Node.js was not found at $nodeExe"
}

if (-not (Test-Path $clineCmd)) {
    Write-Error "cline launcher was not found at $clineCmd"
}

$env:PATH = "$nodeRoot;$clineRoot;$env:PATH"

& $clineCmd @args
