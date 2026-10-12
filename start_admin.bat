@echo off
chcp 65001 > nul
cd /d "%~dp0"
call .venv\Scripts\activate.bat
echo Admin site: http://localhost:8000
start "" http://localhost:8000
python -m uvicorn admin.main:app --host 127.0.0.1 --port 8000
pause
