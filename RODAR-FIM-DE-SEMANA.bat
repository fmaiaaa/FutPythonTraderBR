@echo off
cd /d "%~dp0"
echo === FutPythonTrader — Rotina Semanal Fim de Semana ===
echo %date% %time%

python scripts\weekend_run.py

echo.
echo Concluido. Relatorio em data\weekend\
pause
