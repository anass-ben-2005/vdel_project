<#
  The command the hourly task runs (D-095). Dot-sourced by register_task.ps1 and by
  tests/test_task_command.py, so the test runs exactly what the registration script generates.

  Why it looks like this. The first version put the project folder inside a single-quoted
  PowerShell literal: Set-Location -LiteralPath '<folder>'. A folder with an apostrophe
  (stage_a_l'etranger) ended the string early, the command did not parse, the task finished with
  LastTaskResult 1 and nothing was logged. Three layers:

    1. The command is passed as -EncodedCommand (base64 of the UTF-16LE text). The command line
       then holds only [A-Za-z0-9+/=], so quoting, spaces, '&', '%' or '$' in a path cannot
       reach the command-line parser.
    2. Inside the script, every path is a single-quoted literal with each ' doubled to '' (the
       PowerShell rule for that literal) and is used with -LiteralPath.
    3. The task's "Start in" is also the project folder, but it is NOT relied on: tested, Windows
       PowerShell 5.1 started in a folder whose name holds [ or ] silently falls back to its own
       install folder (the brackets are read as a wildcard), so the script's first act is
       Set-Location -LiteralPath '<folder>' (layer 2 makes that safe).
#>

function ConvertTo-PsLiteral {
    # A string as a single-quoted PowerShell literal: ' becomes '', nothing else needs escaping.
    param([Parameter(Mandatory)][string]$Text)
    return "'" + $Text.Replace("'", "''") + "'"
}

function New-HourlyTaskScript {
    # The PowerShell text the task runs. Relative paths = relative to the task's "Start in".
    param(
        [Parameter(Mandatory)][string]$ProjectFolder,
        [Parameter(Mandatory)][string]$PythonExe,
        [switch]$AllowGitHubWrite,
        [switch]$UseDockerGrading,
        [switch]$WithLlm,
        [switch]$WithCodeAgent
    )
    # D-104. -WithLlm adds `--with-llm` (the Feedback Agent) and sets LLM_PROVIDER for THIS TASK ONLY
    # (an environment variable of the task's own process; nothing else on the machine changes).
    # -WithCodeAgent adds `--with-code-agent` and is refused without -WithLlm, as run_hourly itself
    # refuses it. Neither switch changes anything when absent: the no-flag command is the old one.
    if ($WithCodeAgent -and -not $WithLlm) {
        throw "-WithCodeAgent needs -WithLlm: the Code Agent is a second agent of the same hook."
    }
    $py = ConvertTo-PsLiteral $PythonExe
    $folder = ConvertTo-PsLiteral $ProjectFolder
    $flags = ""
    if ($AllowGitHubWrite) { $flags += "`$env:VDEL_ALLOW_GITHUB_WRITE = '1'`n  " }
    if ($UseDockerGrading) { $flags += "`$env:VDEL_GRADING_SANDBOX = 'docker'`n  " }
    if ($WithLlm) { $flags += "`$env:LLM_PROVIDER = 'openai'`n  " }
    $agentArgs = ""
    if ($WithLlm) { $agentArgs += " --with-llm" }
    if ($WithCodeAgent) { $agentArgs += " --with-code-agent" }
    # A startup failure is never silent: whatever python (or this wrapper) writes to stderr, and
    # any error raised before python starts, lands in logs\task_stderr.log.
    return @"
`$ErrorActionPreference = 'Continue'
`$python = $py
`$utf8 = New-Object Text.UTF8Encoding(`$false)
function Write-TaskLog([string]`$Path, [string]`$Text) {
  [IO.File]::AppendAllText(`$Path, `$Text + [Environment]::NewLine, `$utf8)
}
try {
  Set-Location -LiteralPath $folder -ErrorAction Stop
} catch {
  Write-TaskLog (Join-Path `$env:TEMP 'vdel_task_stderr.log') ('{0} PROJECT FOLDER NOT FOUND: {1}' -f (Get-Date -Format s), `$_.Exception.Message)
  exit 1
}
`$logDir = Join-Path (Get-Location).ProviderPath 'logs'
[void][IO.Directory]::CreateDirectory(`$logDir)
`$stderrLog = Join-Path `$logDir 'task_stderr.log'
Write-TaskLog `$stderrLog ('--- {0} task start, folder {1}' -f (Get-Date -Format s), (Get-Location).ProviderPath)
try {
  if (-not (Test-Path -LiteralPath `$python -PathType Leaf)) { throw ('python not found: ' + `$python) }
  try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch { }
  `$env:PYTHONIOENCODING = 'utf-8'
  $flags& `$python -m scripts.run_hourly$agentArgs 2>&1 | ForEach-Object {
    if (`$_ -is [Management.Automation.ErrorRecord]) { Write-TaskLog `$stderrLog `$_.Exception.Message } else { `$_ }
  }
  `$code = `$LASTEXITCODE
  if (`$null -eq `$code) { `$code = 1 }
} catch {
  Write-TaskLog `$stderrLog ('TASK WRAPPER ERROR: ' + `$_.Exception.Message)
  `$code = 1
}
exit `$code
"@
}

function New-HourlyTaskArguments {
    # The argument string for powershell.exe: no character of the script or of any path is visible.
    param([Parameter(Mandatory)][string]$Script)
    $encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($Script))
    return "-NoProfile -ExecutionPolicy Bypass -EncodedCommand $encoded"
}
