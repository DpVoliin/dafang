@echo off
rem Dafang Agent - self test (no model / no internet needed)
rem ASCII only on purpose: cmd.exe reads .bat in the local codepage.
setlocal
cd /d "%~dp0.."
set "PY="
for %%C in (python.exe py.exe python3.exe) do (
  if not defined PY (
    where %%C >nul 2>nul && set "PY=%%C"
  )
)
if not defined PY goto nopython
echo.
%PY% "%~dp0..\dafang.py" --selftest
echo.
echo If the report shows FAIL, send me this file:
echo    %%USERPROFILE%%\dafang-selftest-report.txt
echo.
pause
exit /b 0

:nopython
echo.
echo   Python not found on this computer.
echo   Please install Python 3.9 or newer: https://www.python.org/downloads/
echo   During installation, CHECK the box "Add python.exe to PATH".
echo.
pause
exit /b 1
