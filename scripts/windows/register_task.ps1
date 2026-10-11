<#
.SYNOPSIS
  Register the hourly VDEL task (scripts/run_hourly.py) in Windows Task Scheduler.

.DESCRIPTION
  D-091. Runs `python -m scripts.run_hourly` every hour from the project folder: collect, grade,
  features, profile, then feedback by GitHub issue. Nothing is written to GitHub unless you pass
  -AllowGitHubWrite, which sets VDEL_ALLOW_GITHUB_WRITE=1 in the task's own environment (and in
  nothing else on the machine). Without it the task only observes and logs what it WOULD post.

  The task runs as YOU, only while you are logged on (Docker Desktop and the Postgres container
  need your session anyway), never starts a second copy while one is still running, runs at the
  next opportunity if the PC was off at the scheduled time, and is stopped after 50 minutes.

  This script was written but NOT run by the overnight batch. Preview it first:
      powershell -ExecutionPolicy Bypass -File scripts\windows\register_task.ps1 -WhatIf

.PARAMETER TaskName        Name in Task Scheduler. Default "VDEL hourly".
.PARAMETER PythonExe       Full path of python.exe. Default: the first `python` on PATH.
.PARAMETER AllowGitHubWrite  Let the task post feedback comments (VDEL_ALLOW_GITHUB_WRITE=1).
.PARAMETER UseDockerGrading  Grade in the container (VDEL_GRADING_SANDBOX=docker in the task's environment).
                  The image must exist first: docs/OPERATIONS.md section 11.
.PARAMETER EveryMinutes    Repeat interval. Default 60.
.PARAMETER Force           Replace a task of the same name.
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$TaskName = "VDEL hourly",
    [string]$PythonExe = "",
    [switch]$AllowGitHubWrite,
    [switch]$UseDockerGrading,
    [int]$EveryMinutes = 60,
    [switch]$Force
)

$ErrorActionPreference = "Stop"

$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
if (-not (Test-Path (Join-Path $root "scripts\run_hourly.py"))) {
    throw "scripts\run_hourly.py not found under $root; run this script from the project's scripts\windows folder."
}
if (-not $PythonExe) {
    $PythonExe = (Get-Command python -ErrorAction Stop).Source
}
if (-not (Test-Path $PythonExe)) { throw "python.exe not found at $PythonExe" }

# The command the task runs: set the (optional) write flag for this process only, then run.
$flag = ""
if ($AllowGitHubWrite) { $flag = "`$env:VDEL_ALLOW_GITHUB_WRITE='1'; " }
if ($UseDockerGrading) { $flag += "`$env:VDEL_GRADING_SANDBOX='docker'; " }
$inner = "Set-Location -LiteralPath '$root'; $flag& '$PythonExe' -m scripts.run_hourly; exit `$LASTEXITCODE"
$arguments = "-NoProfile -ExecutionPolicy Bypass -Command `"$inner`""

$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $arguments -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(2) `
    -RepetitionInterval (New-TimeSpan -Minutes $EveryMinutes) -RepetitionDuration (New-TimeSpan -Days 3650)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 50) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -RunOnlyIfNetworkAvailable
$principal = New-ScheduledTaskPrincipal -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) `
    -LogonType Interactive -RunLevel Limited

$writeText = if ($AllowGitHubWrite) { "WRITES TO GITHUB ENABLED" } else { "observe only (no GitHub write)" }
Write-Host "Task      : $TaskName"
Write-Host "Folder    : $root"
Write-Host "Python    : $PythonExe"
Write-Host "Every     : $EveryMinutes minute(s), first run in about 2 minutes"
Write-Host "GitHub    : $writeText"
Write-Host "Grading   : $(if ($UseDockerGrading) { 'in a Docker container' } else { 'in a subprocess on this PC' })"
Write-Host "Command   : powershell.exe $arguments"

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing -and -not $Force) {
    throw "A task named '$TaskName' already exists. Pass -Force to replace it, or run unregister_task.ps1 first."
}

if ($PSCmdlet.ShouldProcess($TaskName, "Register the hourly VDEL task")) {
    if ($existing) { Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false }
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings `
        -Principal $principal -Description "VDEL: run_hourly (collect, grade, features, feedback). See docs/OPERATIONS.md." | Out-Null
    Write-Host "Registered. Check it with: Get-ScheduledTaskInfo -TaskName '$TaskName'"
}
