# Toda sabado 07:00 (horario local) — busca jogos do sabado + domingo
$TaskName = "FutPythonTrader-Weekend"
$Bat = "C:\Users\kaleb\FutPythonTraderBR\RODAR-FIM-DE-SEMANA.bat"

Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue

$Action = New-ScheduledTaskAction -Execute $Bat -WorkingDirectory "C:\Users\kaleb\FutPythonTraderBR"
$Trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Saturday -At 07:00
$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopOnIdleEnd -ExecutionTimeLimit (New-TimeSpan -Hours 3)
Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Force
Write-Host "Tarefa $TaskName agendada: TODO SABADO 07:00"
