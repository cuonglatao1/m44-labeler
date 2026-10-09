@echo off
chcp 65001 >nul
rem Cai dat M44 Labeler (1 lan, chay lai sau moi lan git pull). Can: Python 3.10-3.12 va Node.js 20+.
rem Huong dan day du: docs\HUONG_DAN_CAI_DAT.md
cd /d "%~dp0"
where py >nul 2>nul || where python >nul 2>nul || (echo [LOI] Chua cai Python 3.11 - xem docs\HUONG_DAN_CAI_DAT.md & pause & exit /b 1)
where npm >nul 2>nul || (echo [LOI] Chua cai Node.js 20+ - xem docs\HUONG_DAN_CAI_DAT.md & pause & exit /b 1)
if not exist ".venv\Scripts\python.exe" (py -3.11 -m venv .venv 2>nul || py -3 -m venv .venv 2>nul || python -m venv .venv)
if not exist ".venv\Scripts\python.exe" (echo [LOI] Khong tao duoc moi truong Python .venv & pause & exit /b 1)
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt || (echo [LOI] pip install that bai & pause & exit /b 1)
echo.
echo Nap ket qua YOLO co san cho nuScenes-mini...
pushd backend && "..\.venv\Scripts\python.exe" -m labeler.precompute --bundled & popd
echo.
echo Build giao dien...
pushd frontend && call npm install && call npm run build && popd
echo.
if exist "data\nuscenes\v1.0-mini" (echo Da thay du lieu: data\nuscenes) else if exist "D:\data\nuscenes\v1.0-mini" (echo Da thay du lieu: D:\data\nuscenes) else (
  echo [CHU Y] Chua thay nuScenes-mini. Tai v1.0-mini.tgz va giai nen vao thu muc data\nuscenes cua repo ^(xem huong dan^).
)
echo.
echo Xong. Bam dup run_app.bat de chay.
pause
