@echo off

setlocal EnableExtensions



title FPT — Iniciar operacao completa



if exist "D:\FutPythonTraderBR\project\fpt" (set "REPO=D:\FutPythonTraderBR\project") else if exist "D:\FutPythonTraderBR\project\scripts" (set "REPO=D:\FutPythonTraderBR\project") else (set "REPO=%~dp0..")

set "FPT_DATA_ROOT=D:\FutPythonTraderBR\data"

set "FPT_PROJECT_ROOT=%REPO%"

set "FPT_PERSIST_LOCAL=1"

set "BETFAIR_ENABLED=true"



if not exist "%REPO%" (

    echo ERRO: repositorio nao encontrado em %REPO%

    pause

    exit /b 1

)



cd /d "%REPO%"

set "PYTHONPATH=%REPO%"



if not exist "D:\FutPythonTraderBR\data" mkdir "D:\FutPythonTraderBR\data"

if not exist "D:\FutPythonTraderBR\data\live" mkdir "D:\FutPythonTraderBR\data\live"

if not exist "D:\FutPythonTraderBR\data\live_collection" mkdir "D:\FutPythonTraderBR\data\live_collection"



call "%REPO%\scripts\choose_fpt_profile.bat"

if errorlevel 1 exit /b 1



echo.

echo Verificando ambiente...

python "%REPO%\scripts\verify_operacao.py"

if errorlevel 1 (

    echo.

    echo Corrija os erros acima antes de continuar.

    pause

    exit /b 1

)



echo.

echo ========================================

echo  FPT — Operacao completa

echo  Perfil salvo em: %FPT_DATA_ROOT%\live\runtime_profile.json

echo  1. Coleta SofaScore + odds

echo  2. Operacao Betfair (PAPER R$ 100)

echo  3. Dashboard (http://127.0.0.1:8501)

echo  Dados: %FPT_DATA_ROOT%

echo ========================================

echo.



echo Iniciando coleta...

start "FPT Coleta" cmd /k "cd /d "%REPO%" && set FPT_DATA_ROOT=%FPT_DATA_ROOT% && set FPT_PERSIST_LOCAL=1 && set BETFAIR_ENABLED=true && set PYTHONPATH=%REPO% && scripts\start_coleta.bat"



timeout /t 2 /nobreak >nul



echo Iniciando operacao...

start "FPT Operacao" cmd /k "cd /d "%REPO%" && set FPT_DATA_ROOT=%FPT_DATA_ROOT% && set FPT_PERSIST_LOCAL=1 && set BETFAIR_ENABLED=true && set PYTHONPATH=%REPO% && scripts\start_operacao.bat"



timeout /t 3 /nobreak >nul



echo Iniciando dashboard...

start "FPT Dashboard" cmd /k "cd /d "%REPO%" && set FPT_DATA_ROOT=%FPT_DATA_ROOT% && set FPT_PERSIST_LOCAL=1 && set PYTHONPATH=%REPO% && scripts\launch_robot.bat"



echo.

echo Tudo iniciado em 3 janelas separadas.

echo Feche cada janela com Ctrl+C para parar o processo.

echo.

timeout /t 5 /nobreak >nul



endlocal

