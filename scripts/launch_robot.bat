@echo off

title FPT Dashboard

set FPT_DATA_ROOT=D:\FutPythonTraderBR\data
set FPT_PERSIST_LOCAL=1

if exist "D:\FutPythonTraderBR\project\fpt" (
  cd /d "D:\FutPythonTraderBR\project"
) else if exist "D:\FutPythonTraderBR\project\scripts" (
  cd /d "D:\FutPythonTraderBR\project"
) else (
  cd /d "%~dp0.."
)
set PYTHONPATH=%CD%
set FPT_PROJECT_ROOT=%CD%



if exist "data\merged\brazil_male_all.parquet" (

  if not exist "D:\FutPythonTraderBR\data\merged\brazil_male_all.parquet" (

    echo Copiando base merged para D:...

    xcopy /E /I /Y "data\merged" "D:\FutPythonTraderBR\data\merged"

  )

)

if exist "data\models\model_outcome.joblib" (

  if not exist "D:\FutPythonTraderBR\data\models\model_outcome.joblib" (

    echo Copiando modelos para D:...

    xcopy /E /I /Y "data\models" "D:\FutPythonTraderBR\data\models"

  )

)



echo.

echo ========================================

echo  FPT Dashboard (somente leitura)

echo  Dados: %FPT_DATA_ROOT%

echo  URL:   http://127.0.0.1:8501

echo.

echo  Operacao:  scripts\start_operacao.bat

echo  Coleta:    scripts\start_coleta.bat

echo ========================================

echo.



start "" "http://127.0.0.1:8501"

python -m streamlit run dashboard_app.py --server.address 127.0.0.1 --browser.gatherUsageStats false

if errorlevel 1 (

  echo.

  echo ERRO ao iniciar Streamlit. Verifique: pip install -r requirements.txt

  pause

)


