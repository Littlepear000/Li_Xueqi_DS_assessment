@echo off
setlocal EnableExtensions
cd /d "%~dp0"
echo This removes the private .venv only. Your output\ , config\local.env and data are kept.
echo.
if exist "%~dp0.venv" (
  rmdir /s /q "%~dp0.venv"
  echo Removed .venv.
) else (
  echo No .venv found; nothing to remove.
)
echo.
echo If you previously installed piaa into a global or conda Python, remove it there:
echo     python -m pip uninstall piaa -y
echo     python -m pip check
echo Do NOT mass-uninstall the leftover dependencies.
echo If it was a dedicated conda environment:
echo     conda env remove -n ^<name^>
echo.
pause
