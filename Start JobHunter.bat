@echo off
cd /d "%~dp0"
title JobHunter
echo.
echo  JobHunter
echo  ---------
if exist ".venv\ready.txt" goto start

echo  First-time setup. This takes a few minutes and only happens once.
echo  Please keep this window open.
echo.
python --version >nul 2>nul
if errorlevel 1 goto trypy
set PY=python
goto makeenv

:trypy
py -3 --version >nul 2>nul
if errorlevel 1 goto nopython
set PY=py -3

:makeenv
if exist ".venv" rmdir /s /q ".venv"
%PY% -m venv .venv
if errorlevel 1 goto fail
".venv\Scripts\python.exe" -m pip install --upgrade pip -q
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto fail
".venv\Scripts\python.exe" -m playwright install chromium
if errorlevel 1 echo  Warning: the browser download failed. Searching will work, applying will not.
>".venv\ready.txt" echo ready
echo.
echo  Setup finished.

:start
echo.
echo  Starting JobHunter. Your web browser will open by itself.
echo  Keep this window open while you use it. Close it to stop JobHunter.
echo.
".venv\Scripts\python.exe" run.py dashboard
echo.
echo  JobHunter has stopped.
pause
exit /b 0

:nopython
echo  Python is not installed. Install it from python.org
echo  and tick "Add python.exe to PATH" on the first screen.
echo  Then double-click this file again.
pause
exit /b 1

:fail
echo.
echo  Setup did not finish. Scroll up to read the error, then double-click this file to try again.
pause
exit /b 1
