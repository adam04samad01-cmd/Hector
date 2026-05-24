@echo off
cd /d "%~dp0"

set PYTHON_EXE=C:\Users\Adam Samad\AppData\Roaming\uv\python\cpython-3.11-windows-x86_64-none\python.exe
set VENV_PYTHON=%~dp0.hector_venv\Scripts\python.exe
set TEMP=%~dp0pip-temp
set TMP=%~dp0pip-temp

if not exist "%TEMP%" mkdir "%TEMP%"

if not exist "%PYTHON_EXE%" (
  echo Could not find Python at:
  echo %PYTHON_EXE%
  echo.
  echo Please install Python, then run:
  echo pip install streamlit pandas
  echo streamlit run app.py
  pause
  exit /b 1
)

if not exist "%VENV_PYTHON%" (
  echo Creating Hector private Python environment...
  "%PYTHON_EXE%" -m venv "%~dp0.hector_venv"
)

if exist "%VENV_PYTHON%" (
  set RUN_PYTHON=%VENV_PYTHON%
) else (
  echo Private environment could not be created. Using managed Python fallback...
  set RUN_PYTHON=%PYTHON_EXE%
)

"%RUN_PYTHON%" -m streamlit --version >nul 2>&1
if errorlevel 1 (
  echo Installing Hector requirements...
  "%RUN_PYTHON%" -m pip install --upgrade pip --break-system-packages
  "%RUN_PYTHON%" -m pip install -r requirements.txt --break-system-packages
)

echo Starting Hector 1.5...
"%RUN_PYTHON%" -m streamlit run app.py
pause
