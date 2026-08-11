@echo off
title FPT - Coleta SofaScore 24h

if exist "D:\FutPythonTraderBR\project\fpt" (cd /d "D:\FutPythonTraderBR\project") else if exist "D:\FutPythonTraderBR\project\scripts" (cd /d "D:\FutPythonTraderBR\project") else (cd /d "%~dp0..")
set FPT_DATA_ROOT=D:\FutPythonTraderBR\data
set FPT_PROJECT_ROOT=%CD%
set FPT_PERSIST_LOCAL=1
set PYTHONPATH=%CD%

if not exist "D:\FutPythonTraderBR\data\live_collection" mkdir "D:\FutPythonTraderBR\data\live_collection"

echo.
echo ========================================
echo  FPT Coleta — SofaScore + odds (24/7)
echo  Dados: %FPT_DATA_ROOT%
echo  Ctrl+C para parar
echo ========================================
echo.

python scripts\run_sofascore_collector.py --interval 60
pause
