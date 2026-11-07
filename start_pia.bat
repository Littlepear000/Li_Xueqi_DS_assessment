@echo off
rem One-click launcher. First run (or a broken/half-finished install) builds/repairs a private
rem .venv inside "PIA Analysis" and installs everything, then starts. Needs Python 3.11-3.13.
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
set "ROOT=%~dp0"
set "PKG=%~dp0PIA Analysis"
set "VENV=%PKG%\.venv"
set "VPY=%VENV%\Scripts\python.exe"

if not exist "%PKG%\pyproject.toml" (
  echo ERROR: the "PIA Analysis" folder was not found next to this file.
  pause & exit /b 1
)

rem (re)install unless the venv already has piaa importable
if not exist "%VPY%" goto SETUP
"%VPY%" -c "import piaa, fastapi" >nul 2>&1 && goto RUN

:SETUP
echo ============================================================
echo   Preparing the private Python environment (one time).
echo   This can take a few minutes.
echo ============================================================
if exist "%VPY%" goto INSTALL
set "PYEXE="
for %%V in (3.11 3.12 3.13) do if not defined PYEXE ( py -%%V -c "import sys" >nul 2>&1 && set "PYEXE=py -%%V" )
if not defined PYEXE ( python -c "import sys" >nul 2>&1 && set "PYEXE=python" )
if not defined PYEXE (
  echo ERROR: Python 3.11-3.13 not found. Install Python 3.11+ from https://www.python.org/downloads/
  echo During install tick "Add python.exe to PATH" and keep the py launcher, then run this again.
  pause & exit /b 1
)
echo Using Python: !PYEXE!
!PYEXE! -m venv "%VENV%" || ( echo ERROR: could not create .venv & pause & exit /b 1 )

:INSTALL
"%VPY%" -m pip install --upgrade pip
"%VPY%" -m pip install -r "%PKG%\requirements.lock.txt" || ( echo ERROR: installing dependencies failed & pause & exit /b 1 )
"%VPY%" -m pip install -e "%PKG%" || ( echo ERROR: installing the piaa package failed & pause & exit /b 1 )
if not exist "%PKG%\config" mkdir "%PKG%\config"
if not exist "%PKG%\config\local.env" if exist "%PKG%\config\local.env.example" copy /y "%PKG%\config\local.env.example" "%PKG%\config\local.env" >nul
echo Environment ready.

:RUN
rem port: environment variable > config\local.env > default 18765
if not defined PIAA_PORT if exist "%PKG%\config\local.env" (
  for /f "usebackq eol=# tokens=1,* delims==" %%A in ("%PKG%\config\local.env") do (
    set "K=%%A" & set "K=!K: =!"
    if /i "!K!"=="PIAA_PORT" if not defined PIAA_PORT set "PIAA_PORT=%%B"
  )
)
if not defined PIAA_PORT set "PIAA_PORT=18765"
set "PIAA_PORT=%PIAA_PORT: =%"

rem read version via a temp file (avoids FOR /F quoting issues with spaced paths)
set "VER="
"%VPY%" -c "import piaa;print(piaa.__version__)" > "%TEMP%\_piaa_ver.txt" 2>nul
if exist "%TEMP%\_piaa_ver.txt" ( set /p VER=<"%TEMP%\_piaa_ver.txt" & del "%TEMP%\_piaa_ver.txt" >nul 2>&1 )

echo.
echo PIA Analysis !VER!  -  http://127.0.0.1:%PIAA_PORT%   (a free port up to +10 is used if busy)
echo Keep this window open.  R + Enter = restart,  Q + Enter or Ctrl+C = stop.
echo.
"%VPY%" -m piaa.cli serve --raw-dir "%ROOT%raw_data" --out "%ROOT%output" --host 127.0.0.1 --port %PIAA_PORT% --dev
if errorlevel 1 pause
