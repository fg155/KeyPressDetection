@echo off
setlocal
pushd "%~dp0"
set "KPD_EDITION=%~1"
if "%KPD_EDITION%"=="" set "KPD_EDITION=directml"
if /i "%KPD_EDITION%"=="directml" goto valid_edition
if /i "%KPD_EDITION%"=="cuda" goto valid_edition
echo Usage: install.cmd [directml^|cuda]
popd
exit /b 1
:valid_edition
if exist "runtime\python.exe" (
  echo Portable runtime is already included. Run start.cmd.
  popd
  exit /b 0
)
if exist ".venv\Scripts\python.exe" goto install_packages
if exist "%LocalAppData%\Programs\Python\Python312\python.exe" (
  "%LocalAppData%\Programs\Python\Python312\python.exe" -m venv .venv
  if errorlevel 1 goto failed
  goto install_packages
)
py -3.12 -c "import sys; assert sys.maxsize.bit_length() == 63" >nul 2>&1
if errorlevel 1 (
  echo Python 3.12 x64 is required for the source edition.
  echo Download Python from https://www.python.org/downloads/windows/
  echo Or use the portable release, which includes Python and dependencies.
  popd
  exit /b 1
)
if not exist ".venv\Scripts\python.exe" py -3.12 -m venv .venv
if errorlevel 1 goto failed
:install_packages
".venv\Scripts\python.exe" -c "import sys; assert sys.version_info[:2] == (3,12) and sys.maxsize.bit_length() == 63"
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m pip install -r "requirements-%KPD_EDITION%.txt"
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -c "import json,sys; from pathlib import Path; Path('edition.json').write_text(json.dumps({'edition':sys.argv[1].lower()},indent=2)+'\n',encoding='utf-8')" "%KPD_EDITION%"
if errorlevel 1 goto failed
echo Dependencies installed. Extract the matching model assets from Releases, then run start.cmd.
popd
exit /b 0
:failed
echo Installation failed. Check the error above, network access, and available disk space.
popd
exit /b 1
