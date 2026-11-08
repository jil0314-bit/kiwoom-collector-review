$ErrorActionPreference = 'Stop'
$taskName = 'KiwoomTop100Archive_2005'
$collectorPython = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\pythonw.exe'
if (-not (Test-Path -LiteralPath $collectorPython)) { $collectorPython = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python313\pythonw.exe' }
if (Test-Path -LiteralPath (Join-Path $PSScriptRoot '.venv\Scripts\pythonw.exe')) { $collectorPython = Join-Path $PSScriptRoot '.venv\Scripts\pythonw.exe' }
if (Test-Path -LiteralPath (Join-Path $PSScriptRoot '.runtime\pythonw.exe')) { $collectorPython = Join-Path $PSScriptRoot '.runtime\pythonw.exe' }
if (-not (Test-Path -LiteralPath $collectorPython)) { throw 'Python runtime not found' }
$collectorEntry = Join-Path $PSScriptRoot 'app.py'
$action = New-ScheduledTaskAction -Execute $collectorPython -Argument ('-B "' + $collectorEntry + '"') -WorkingDirectory $PSScriptRoot
$triggers = @((New-ScheduledTaskTrigger -Daily -At '09:15'), (New-ScheduledTaskTrigger -Daily -At '17:15'), (New-ScheduledTaskTrigger -Daily -At '20:05'), (New-ScheduledTaskTrigger -AtLogOn -User ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name)))
$principal = New-ScheduledTaskPrincipal -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero)
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $triggers -Settings $settings -Principal $principal -Description 'Read-only Kiwoom top-100 daily 1-minute archive. Start at login, 09:15, 17:15 and 20:05; no orders.' -Force | Select-Object TaskName, State
Get-ScheduledTaskInfo -TaskName $taskName | Select-Object NextRunTime, LastTaskResult
