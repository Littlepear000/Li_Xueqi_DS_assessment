@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
set "VPY=%~dp0.venv\Scripts\python.exe"

if not exist "%VPY%" (
  echo .venv was not found in this folder.
  echo Please run setup.bat first ^(double-click it^), then start.bat.
  pause & exit /b 1
)

rem --- resolve settings: environment variable > config\local.env > default ---
if exist "%~dp0config\local.env" (
  for /f "usebackq eol=# tokens=1,* delims==" %%A in ("%~dp0config\local.env") do (
    set "K=%%A" & set "V=%%B"
    set "K=!K: =!"
    if /i "!K!"=="PIAA_PORT" if not defined PIAA_PORT set "PIAA_PORT=!V!"
    if /i "!K!"=="PIAA_RAW"  if not defined PIAA_RAW  set "PIAA_RAW=!V!"
    if /i "!K!"=="PIAA_OUT"  if not defined PIAA_OUT  set "PIAA_OUT=!V!"
  )
)
if not defined PIAA_PORT set "PIAA_PORT=18765"
if not defined PIAA_RAW set "PIAA_RAW=..\raw_data"
if not defined PIAA_OUT set "PIAA_OUT=..\output"
set "PIAA_PORT=%PIAA_PORT: =%"

echo Starting PIA Analysis on http://127.0.0.1:%PIAA_PORT%  (a free port up to +10 is used if this one is busy)
echo Keep this window open.  R + Enter = restart,  Q + Enter or Ctrl+C = stop.
echo.
"%VPY%" -m piaa.cli serve --raw-dir "%PIAA_RAW%" --out "%PIAA_OUT%" --host 127.0.0.1 --port %PIAA_PORT% --dev
if errorlevel 1 pause
