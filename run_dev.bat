@echo off
chcp 65001 >nul
rem Che do dev: backend --reload (8770) + Vite hot reload (5173).
cd /d "%~dp0"
if not defined NUSC_ROOT if not exist "data\nuscenes" if exist "D:\data\nuscenes" set NUSC_ROOT=D:\data\nuscenes
start "M44 backend" cmd /k "cd backend && ..\.venv\Scripts\python.exe -m uvicorn labeler.main:app --port 8770 --reload"
cd frontend && npm run dev
