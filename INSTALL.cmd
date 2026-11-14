@echo off
setlocal
cd /d "%~dp0."
if not exist ".venv\Scripts\python.exe" (
  call :create_environment
  if errorlevel 1 goto fail
)
if exist "wheels\django-5.2.19-py3-none-any.whl" (
  ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check --no-index --find-links wheels -r requirements.txt
) else (
  ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.txt
)
if errorlevel 1 goto fail
echo Django dependencies are ready. You can close this window.
pause
exit /b 0
:fail
echo Installation failed. Check Python and internet access.
pause
exit /b 1

:create_environment
py -3 -m venv .venv >nul 2>&1
if exist ".venv\Scripts\python.exe" exit /b 0
for /d %%D in ("%LocalAppData%\Programs\Python\Python3*" "%ProgramFiles%\Python3*" "%SystemDrive%\Python3*") do (
  if exist "%%~fD\python.exe" (
    "%%~fD\python.exe" -c "import sys; raise SystemExit(sys.version_info < (3, 10))" >nul 2>&1
    if not errorlevel 1 "%%~fD\python.exe" -m venv .venv
    if exist ".venv\Scripts\python.exe" exit /b 0
  )
)
exit /b 1
