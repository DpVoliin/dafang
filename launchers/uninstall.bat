@echo off
rem Dafang Agent - uninstall helper (Windows)
rem ASCII only on purpose: cmd.exe reads .bat in the local codepage.
rem We switch the console to UTF-8 so the Python output shows Chinese properly.
chcp 65001 >nul 2>nul
set PYTHONIOENCODING=utf-8
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
%PY% "%~dp0..\uninstall.py" %*
echo.
pause
exit /b 0

:nopython
echo.
echo   Python not found - cannot run the uninstall helper.
echo   Delete these by hand instead:
echo     1) the app data folder:  Documents (or OneDrive)  ->  the folder named after the app
echo        (it contains your novels and config.json with your API key)
echo     2) the app window cache: %%USERPROFILE%%\.dafang-webview-*  folders
echo     3) the self-test reports: %%USERPROFILE%%\*selftest-report.txt
echo     4) this program folder:  %~dp0..
echo.
pause
exit /b 1
