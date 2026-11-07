@echo off
setlocal
cd /d "%~dp0"

set "VIEWER_PYTHON=C:\ProgramData\Anaconda3\python.exe"
if not exist "%VIEWER_PYTHON%" (
    echo Python was not found: %VIEWER_PYTHON%
    echo Please update VIEWER_PYTHON in this file to your Python installation.
    pause
    exit /b 1
)
if not exist "%~dp0host\run.py" (
    echo Viewer entry point was not found: %~dp0host\run.py
    pause
    exit /b 1
)

rem Use the normal desktop platform even if a parent test shell used offscreen.
set "QT_QPA_PLATFORM=windows"
"%VIEWER_PYTHON%" "%~dp0host\run.py"
if errorlevel 1 (
    echo.
    echo Viewer exited with an error. See the messages above and host\logs.
    pause
    exit /b 1
)
endlocal
