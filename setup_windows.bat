@echo off
chcp 65001 >nul
rem Cai dat M44 Labeler (1 lan). Can: Python 3.10-3.12 (python.org) va Node.js 20+ (nodejs.org).
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (py -3.11 -m venv .venv 2>nul || py -3 -m venv .venv)
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt || (echo [LOI] pip install that bai & pause & exit /b 1)
pushd frontend && call npm install && call npm run build && popd
echo.
echo Xong. Nap cache YOLO (xem README) roi bam dup run_app.bat
pause
