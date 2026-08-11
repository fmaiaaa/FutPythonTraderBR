# Instala atalho "FPT Robo" na Area de Trabalho
$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$BatPath = Join-Path $ProjectRoot "scripts\launch_robot.bat"
$Desktop = [Environment]::GetFolderPath("Desktop")
$ShortcutPath = Join-Path $Desktop "FPT Robo.lnk"

if (-not (Test-Path $BatPath)) {
    Write-Error "Nao encontrado: $BatPath"
}

$WshShell = New-Object -ComObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = $BatPath
$Shortcut.WorkingDirectory = $ProjectRoot
$Shortcut.Description = "FutPythonTrader - Dashboard (somente leitura)"
$Shortcut.WindowStyle = 1
$Shortcut.Save()

Write-Host "Atalho criado: $ShortcutPath"
Write-Host "Dashboard: launch_robot.bat"
Write-Host "Coleta 24h: scripts\start_coleta.bat"
Write-Host "Operacao 24h: scripts\start_operacao.bat"
Write-Host "Dados serao salvos em D:\FutPythonTraderBR\data"

# Criar estrutura D:
$DataRoot = "D:\FutPythonTraderBR\data"
@("merged", "models", "live", "live_collection", "betfair\ticks", "sofascore\snapshots", "weekend") | ForEach-Object {
    $p = Join-Path $DataRoot $_
    if (-not (Test-Path $p)) { New-Item -ItemType Directory -Path $p -Force | Out-Null }
}
