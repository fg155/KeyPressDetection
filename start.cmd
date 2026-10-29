@echo off
chcp 65001 >nul
setlocal
title Key Press Detection
pushd "%~dp0"
set PYTHONHOME=
set PYTHONPATH=
set PYTHONUTF8=1
if exist "runtime\python.exe" (
  set "KPD_PYTHON=%~dp0runtime\python.exe"
) else if exist ".venv\Scripts\python.exe" (
  set "KPD_PYTHON=%~dp0.venv\Scripts\python.exe"
) else (
  echo Missing runtime. Extract the complete portable release, or run install.cmd for the source edition.
  pause
  popd
  exit /b 1
)
"%KPD_PYTHON%" -B -u "%~dp0server.py" %*
if errorlevel 1 (
  echo.
  echo Key Press Detection could not start. See the error above.
  pause
)
popd
endlocal
