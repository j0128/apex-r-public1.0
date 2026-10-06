# Apex-R Daily Email - Mon-Sat 08:00 local time (Interactive for monthly popup)
# Uses Gmail API OAuth token at %USERPROFILE%\.config\apex-gmail\token.json

$ErrorActionPreference = "Stop"
$Desktop = Split-Path -Parent $MyInvocation.MyCommand.Path
$PyCmd = Get-Command py -ErrorAction SilentlyContinue
if (-not $PyCmd) { throw "py launcher not found. Install Python first." }
$Py = $PyCmd.Source

$TaskName = "Apex-R Daily Email"
$WorkDir = $Desktop
$Arg = "-3.13 `"$Desktop\daily_email_report.py`" --via gmail"

$Action = New-ScheduledTaskAction -Execute $Py -Argument $Arg -WorkingDirectory $WorkDir
$Trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday,Saturday -At 8:00am
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
$Principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Principal $Principal -Description "Apex-R daily report via Gmail API; monthly first day asks capital + continue" | Out-Null

Write-Host "Registered task: $TaskName"
Write-Host "Schedule: Mon-Sat 08:00 (local). Interactive logon required for popup."
Write-Host "WorkDir: $WorkDir"
Write-Host "Test now: Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "Force popup: py -3.13 daily_email_report.py --force-ask --dry-run"
