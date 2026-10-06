# AI Investment Committee Daily Email — Mon-Sat 08:00 local
# Replaces single-engine Apex-R daily with M×R committee minutes.

$ErrorActionPreference = "Stop"
$Desktop = Split-Path -Parent $MyInvocation.MyCommand.Path
$PyCmd = Get-Command py -ErrorAction SilentlyContinue
if (-not $PyCmd) { throw "py launcher not found. Install Python first." }
$Py = $PyCmd.Source

$TaskName = "Apex AI Committee Daily"
$WorkDir = $Desktop
$Arg = "-3.13 `"$Desktop\daily_committee_report.py`" --via gmail"

$Action = New-ScheduledTaskAction -Execute $Py -Argument $Arg -WorkingDirectory $WorkDir
$Trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday,Saturday -At 8:00am
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
$Principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

# Remove old single-engine task if present
Unregister-ScheduledTask -TaskName "Apex-R Daily Email" -Confirm:$false -ErrorAction SilentlyContinue
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Principal $Principal -Description "AI investment committee daily: Apex-M + Apex-R minutes via Gmail" | Out-Null

Write-Host "Registered task: $TaskName"
Write-Host "Schedule: Mon-Sat 08:00 (local). Interactive logon for monthly popup."
Write-Host "WorkDir: $WorkDir"
Write-Host "Test: Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "Dry-run: py -3.13 daily_committee_report.py --dry-run --date 2026-09-23"
