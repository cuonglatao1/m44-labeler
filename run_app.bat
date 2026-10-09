@echo off
rem Called again by itself (minimised) to open the browser once the backend answers.
if "%~1"=="--open-when-ready" goto wait_open
chcp 65001 >nul
rem Chay M44 Labeler: backend (cong 8770) phuc vu ca giao dien da build (frontend\dist).
cd /d "%~dp0"
if not defined NUSC_ROOT if not exist "data\nuscenes" if exist "D:\data\nuscenes" set NUSC_ROOT=D:\data\nuscenes
if not exist "frontend\dist\index.html" (
  echo Build giao dien lan dau...
  pushd frontend && call npm install && call npm run build && popd
)
echo Dang nap du lieu nuScenes (khoang 20 giay), trinh duyet se tu mo khi san sang...
start "" /min "%~f0" --open-when-ready
cd backend && "..\.venv\Scripts\python.exe" -m uvicorn labeler.main:app --port 8770
exit /b

:wait_open
rem loading nuScenes takes ~20 s; opening the page earlier shows "cannot connect"
for /l %%i in (1,1,120) do (
  curl -s -o nul --max-time 2 http://127.0.0.1:8770/api/config && (start "" http://localhost:8770 & exit)
  ping -n 2 127.0.0.1 >nul
)
exit
