@echo off
setlocal EnableExtensions

if exist "D:\FutPythonTraderBR\project\fpt" (set "REPO=D:\FutPythonTraderBR\project") else if exist "D:\FutPythonTraderBR\project\scripts" (set "REPO=D:\FutPythonTraderBR\project") else (set "REPO=%~dp0..")
cd /d "%REPO%"
set "PYTHONPATH=%REPO%"
set "FPT_DATA_ROOT=D:\FutPythonTraderBR\data"

echo.
echo  ========================================
echo   FPT — Perfil de operacao
echo  ========================================
echo.
echo   [1] ROBUSTO — 14 ligas tier 1 (recomendado)
echo       Pre-live: FPT + Betfair ^(exchange^)
echo       Scalping: SofaScore + Betfair
echo       Sem ligas em probation
echo.
echo   [2] Watchlist — 14 ligas + probation tier 3
echo       Pre-live: FPT + Betfair ^(exchange^)
echo       Scalping: SofaScore + Betfair
echo.
echo   [3] TODAS as ligas FPT do dia
echo       Pre-live: FPT + Betfair ^(exchange^)
echo       Scalping: SofaScore + Betfair
echo.

set "SEL=1"
choice /c 123 /n /m "Opcao (1=robusto, 2=watchlist, 3=todas): "
if errorlevel 3 set "SEL=3"
if errorlevel 2 if not errorlevel 3 set "SEL=2"

if "%SEL%"=="3" (
  set "PROFILE=all_leagues"
  echo.
  echo Perfil: TODAS as ligas FPT
) else if "%SEL%"=="2" (
  set "PROFILE=watchlist"
  echo.
  echo Perfil: Watchlist
) else (
  set "PROFILE=robust"
  echo.
  echo Perfil: ROBUSTO (tier 1)
)

python "%REPO%\scripts\set_fpt_profile.py" %PROFILE%
if errorlevel 1 (
  echo ERRO ao salvar perfil.
  pause
  exit /b 1
)

python "%REPO%\scripts\seed_robust_ranking.py" >nul 2>&1

endlocal
exit /b 0
