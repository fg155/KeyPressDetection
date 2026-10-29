@echo off
setlocal
cd /d "%~dp0"
if exist "runtime\pythonw.exe" (
  start "" "runtime\pythonw.exe" "simulator.py" %*
  exit /b
)
if exist ".venv\Scripts\pythonw.exe" (
  start "" ".venv\Scripts\pythonw.exe" "simulator.py" %*
  exit /b
)
echo Python runtime not found. Run install.cmd first.
pause
