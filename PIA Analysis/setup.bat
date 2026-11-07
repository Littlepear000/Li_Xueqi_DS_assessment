@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
set "VENV=%~dp0.venv"
set "PYEXE="

echo ==============================================
echo   PIA Analysis - setup (isolated environment)
echo ==============================================
echo.

rem --- find Python 3.10-3.12 via the py launcher (prefer 3.11) ---
for %%V in (3.11 3.12 3.13) do (
  if not defined PYEXE (
    py -%%V -c "import sys" >nul 2>&1 && set "PYEXE=py -%%V"
  )
)
rem --- fallback: python on PATH, only if it is 3.10-3.12 ---
if not defined PYEXE (
  for /f "delims=" %%P in ('python -c "import sys;print('%%d.%%d'%%sys.version_info[:2])" 2^>nul') do set "PYVER=%%P"
  if defined PYVER (
    for %%A in (3.10 3.11 3.12) do if "!PYVER!"=="%%A" set "PYEXE=python"
  )
)
if not defined PYEXE (
  echo ERROR: Python 3.10-3.12 was not found.
  echo Install Python 3.11 from https://www.python.org/downloads/
  echo During install, tick "Add python.exe to PATH" and keep the "py launcher".
  echo Then double-click setup.bat again.
  pause & exit /b 1
)
echo Using Python: !PYEXE!

rem --- create the virtual environment in .venv (re-used if it exists) ---
if not exist "%VENV%\Scripts\python.exe" (
  echo Creating virtual environment in .venv ...
  !PYEXE! -m venv "%VENV%"
  if errorlevel 1 ( echo ERROR: could not create the virtual environment. & pause & exit /b 1 )
) else (
  echo Updating the existing .venv ...
)
set "VPY=%VENV%\Scripts\python.exe"

"%VPY%" -m pip install --upgrade pip
if errorlevel 1 ( echo ERROR: could not upgrade pip. & pause & exit /b 1 )
"%VPY%" -m pip install -r "%~dp0requirements.lock.txt"
if errorlevel 1 ( echo ERROR: installing dependencies failed. & pause & exit /b 1 )
"%VPY%" -m pip install -e "%~dp0."
if errorlevel 1 ( echo ERROR: installing the piaa package failed. & pause & exit /b 1 )

rem --- create config\local.env from the example if missing ---
if not exist "%~dp0config" mkdir "%~dp0config"
if not exist "%~dp0config\local.env" (
  if exist "%~dp0config\local.env.example" (
    copy /y "%~dp0config\local.env.example" "%~dp0config\local.env" >nul
    echo Created config\local.env from the example.
  )
)

set "VER="
"%VPY%" -c "import piaa;print(piaa.__version__)" > "%TEMP%\_piaa_ver.txt" 2>nul
if exist "%TEMP%\_piaa_ver.txt" ( set /p VER=<"%TEMP%\_piaa_ver.txt" & del "%TEMP%\_piaa_ver.txt" >nul 2>&1 )
echo.
echo ==============================================
echo   Setup complete - PIA Analysis !VER!
echo   Next: double-click start.bat
echo ==============================================
pause
