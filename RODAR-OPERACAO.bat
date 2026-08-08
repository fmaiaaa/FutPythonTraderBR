@echo off
cd /d "%~dp0"
python main.py download-all
python main.py operacao
pause
