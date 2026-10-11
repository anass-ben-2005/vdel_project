<#
.SYNOPSIS
  Remove the hourly VDEL task from Windows Task Scheduler (D-091). Written, NOT run, by the
  overnight batch. Preview with -WhatIf.

.DESCRIPTION
  Stops the task if it is running, then deletes it. The logs (logs\run_hourly-*.log), the database
  and every file of the project are left exactly as they are.

.PARAMETER TaskName  Name in Task Scheduler. Default "VDEL hourly".
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$TaskName = "VDEL hourly"
)

$ErrorActionPreference = "Stop"

$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if (-not $task) {
    Write-Host "No task named '$TaskName'. Nothing to do."
    return
}

if ($PSCmdlet.ShouldProcess($TaskName, "Stop and unregister the hourly VDEL task")) {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Unregistered '$TaskName'. Logs and data were not touched."
}
