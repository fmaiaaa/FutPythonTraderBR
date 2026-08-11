# Migra FPT para disco D: (projeto + dados)
# Executar: powershell -ExecutionPolicy Bypass -File scripts\migrate_to_d_drive.ps1

$ErrorActionPreference = "Stop"

$SrcProject = "C:\Users\kaleb\FutPythonTraderBR"
$DstRoot = "D:\FutPythonTraderBR"
$DstProject = "$DstRoot\project"
$DstData = "$DstRoot\data"

Write-Host "=== FPT - Migracao para D: ===" -ForegroundColor Cyan

if (-not (Test-Path "D:\")) {
    Write-Error "Disco D: nao encontrado."
}

New-Item -ItemType Directory -Force -Path $DstRoot, $DstProject, $DstData | Out-Null

if (Test-Path $SrcProject) {
    Write-Host "Copiando codigo $SrcProject -> $DstProject ..."
    robocopy $SrcProject $DstProject /MIR /XD data .git __pycache__ .pytest_cache .venv node_modules .cursor /NFL /NDL /NJH /NJS /nc /ns /np
    if ($LASTEXITCODE -ge 8) { Write-Error "robocopy projeto falhou ($LASTEXITCODE)" }
} else {
    Write-Warning "Origem $SrcProject nao existe - pulando copia do codigo."
}

$LegacyData = @(
    "$SrcProject\data",
    "C:\Users\kaleb\FutPythonTraderBR\data"
)
foreach ($ld in $LegacyData) {
    if (Test-Path $ld) {
        Write-Host "Mesclando dados $ld -> $DstData ..."
        robocopy $ld $DstData /E /XO /NFL /NDL /NJH /NJS /nc /ns /np
        if ($LASTEXITCODE -ge 8) { Write-Error "robocopy dados falhou ($LASTEXITCODE)" }
    }
}

@(
    "merged", "models", "live", "live_collection",
    "betfair\ticks", "sofascore\snapshots", "weekend", "daily",
    "calendar", "raw", "leagues"
) | ForEach-Object {
    $p = Join-Path $DstData $_
    if (-not (Test-Path $p)) { New-Item -ItemType Directory -Path $p -Force | Out-Null }
}

$EnvExample = Join-Path $DstProject ".env.example"
if (Test-Path $EnvExample) {
    $ex = Get-Content $EnvExample -Raw
    $ex = $ex -replace "C:/Users/kaleb/FutPythonTraderBR", "D:/FutPythonTraderBR/project"
    Set-Content $EnvExample $ex -Encoding UTF8
}

$EnvFile = Join-Path $DstProject ".env"
if (Test-Path $EnvFile) {
    $content = Get-Content $EnvFile -Raw
    if ($content -notmatch "FPT_DATA_ROOT") {
        Add-Content $EnvFile "`nFPT_DATA_ROOT=$DstData"
    }
    if ($content -notmatch "FPT_PROJECT_ROOT") {
        Add-Content $EnvFile "`nFPT_PROJECT_ROOT=$DstProject"
    }
    $content = Get-Content $EnvFile -Raw
    $content = $content -replace "C:/Users/kaleb/FutPythonTraderBR", "D:/FutPythonTraderBR/project"
    Set-Content $EnvFile $content -Encoding UTF8
}

$DesktopBat = Join-Path ([Environment]::GetFolderPath("Desktop")) "FPT - Operacao Completa.bat"
if (Test-Path $DesktopBat) {
    $bat = @'
@echo off
title FPT - Operacao Completa
set "REPO=D:\FutPythonTraderBR\project"
if not exist "%REPO%\scripts\start_fpt_completo.bat" (
    echo ERRO: projeto nao encontrado em %REPO%
    pause
    exit /b 1
)
call "%REPO%\scripts\start_fpt_completo.bat"
'@
    Set-Content $DesktopBat $bat -Encoding ASCII
    Write-Host "Atalho desktop atualizado: $DesktopBat"
}

Write-Host ""
Write-Host "Concluido." -ForegroundColor Green
Write-Host "  Projeto: $DstProject"
Write-Host "  Dados:   $DstData"
Write-Host "  SofaScore: $DstData\sofascore\snapshots"
Write-Host ""
Write-Host "Abra o projeto em: $DstProject"
Write-Host "Use o atalho FPT - Operacao Completa na Area de Trabalho."