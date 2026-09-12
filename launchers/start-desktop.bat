@echo off
rem Dafang Agent - desktop launcher (Windows)
rem ASCII only on purpose: cmd.exe reads .bat in the local codepage,
rem so non-ASCII text here would break on Chinese/Japanese Windows.
setlocal
cd /d "%~dp0.."

set "PY="
for %%C in (pythonw.exe pyw.exe python.exe py.exe) do (
  if not defined PY (
    where %%C >nul 2>nul && set "PY=%%C"
  )
)

if not defined PY goto nopython

start "" %PY% "%~dp0..\dafang.py" --desktop
exit /b 0

:nopython
echo.
echo   Python not found on this computer.
echo.
echo   Please install Python 3.9 or newer:
echo       https://www.python.org/downloads/
echo.
echo   During installation, CHECK the box "Add python.exe to PATH".
echo   Then double-click this file again.
echo.
pause
exit /b 1
