# Convenient PowerShell entrypoint for Story Connect Policy Demo Launcher
[CmdletBinding()]
param(
    [switch]$Status,
    [switch]$Health,
    [switch]$Active,
    [switch]$Stop,
    [switch]$Background
)

$hackathonRoot = Split-Path -Parent $PSScriptRoot
$pythonExe = Join-Path $hackathonRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $pythonExe)) {
    $pythonExe = "python.exe"
}
$launcherScript = Join-Path $PSScriptRoot "launch_policy_demo.py"

if ($Active -and -not $Health) {
    Write-Error "-Active is valid only together with -Health."
    exit 2
}

$pythonArgs = @($launcherScript)
if ($Status) { $pythonArgs += "--status" }
if ($Health) { $pythonArgs += "--health" }
if ($Active) { $pythonArgs += "--active" }
if ($Stop) { $pythonArgs += "--stop" }
if ($Background) { $pythonArgs += "--background" }

& $pythonExe @pythonArgs
exit $LASTEXITCODE
