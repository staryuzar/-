@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  py -3.11 -m venv .venv >nul 2>nul
  if errorlevel 1 py -3.12 -m venv .venv >nul 2>nul
  if errorlevel 1 (
    echo ERROR: Install Python 3.11 or 3.12 and retry.
    pause
    exit /b 1
  )
)
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r "python\requirements-ui.txt"
if errorlevel 1 (
  echo ERROR: Dependency installation failed. Read the message above.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m streamlit run "app.py" --server.address 127.0.0.1
pause
