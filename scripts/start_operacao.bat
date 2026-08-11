@echo off

title FPT - Operacao Betfair 24h



if exist "D:\FutPythonTraderBR\project\fpt" (cd /d "D:\FutPythonTraderBR\project") else if exist "D:\FutPythonTraderBR\project\scripts" (cd /d "D:\FutPythonTraderBR\project") else (cd /d "%~dp0..")

set "REPO=%CD%"

set "FPT_DATA_ROOT=D:\FutPythonTraderBR\data"

set "FPT_PROJECT_ROOT=%CD%"

set "FPT_PERSIST_LOCAL=1"

set "BETFAIR_ENABLED=true"

set "PYTHONPATH=%CD%"



if not exist "D:\FutPythonTraderBR\data\live" mkdir "D:\FutPythonTraderBR\data\live"



if not exist "D:\FutPythonTraderBR\data\live\runtime_profile.json" (

  call "%REPO%\scripts\choose_fpt_profile.bat"

)



echo.

echo ========================================

echo  FPT Operacao — Betfair (24/7)

echo  Modo: PAPER (simulacao — banca R$ 100)

echo  Perfil: ver %FPT_DATA_ROOT%\live\runtime_profile.json

echo  Dados: %FPT_DATA_ROOT%

echo  Ctrl+C para parar com seguranca

echo ========================================

echo.



python scripts\run_betfair_operator.py

pause

