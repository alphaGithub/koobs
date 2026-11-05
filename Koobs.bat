@echo off
rem Koobs launcher for Windows. Double-click this file.
cd /d "%~dp0"

where pyw >nul 2>nul
if %errorlevel%==0 (
    start "" pyw "%~dp0app\koobs.py"
    exit /b
)

where pythonw >nul 2>nul
if %errorlevel%==0 (
    start "" pythonw "%~dp0app\koobs.py"
    exit /b
)

echo.
echo  Koobs needs Python 3.10 or newer.
echo.
echo  1. Download it from https://www.python.org/downloads/
echo  2. In the installer, tick "Add python.exe to PATH"
echo  3. Double-click Koobs.bat again
echo.
pause
