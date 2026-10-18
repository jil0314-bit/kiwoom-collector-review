$ErrorActionPreference = 'Stop'
$taskName = 'KiwoomTop100Archive_2005'
$launchPath = Join-Path $PSScriptRoot 'start.vbs'
$action = New-ScheduledTaskAction -Execute "$env:SystemRoot\System32\wscript.exe" -Argument ('"' + $launchPath + '" --background') -WorkingDirectory $PSScriptRoot
$triggers = @((New-ScheduledTaskTrigger -Daily -At '09:15'), (New-ScheduledTaskTrigger -Daily -At '20:05'), (New-ScheduledTaskTrigger -AtLogOn -User ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name)))
$principal = New-ScheduledTaskPrincipal -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $triggers -Settings $settings -Principal $principal -Description 'Read-only Kiwoom top-100 daily 1-minute archive. Start at login, 09:15 and 20:05; no orders.' -Force | Select-Object TaskName, State
Get-ScheduledTaskInfo -TaskName $taskName | Select-Object NextRunTime, LastTaskResult
