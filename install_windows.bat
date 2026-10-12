@echo off
chcp 65001 > nul
cd /d "%~dp0"
echo === Creating Python environment ===
py -3.12 -m venv .venv || python -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt
if not exist .env copy .env.example .env
python scripts\init_db.py
echo.
echo === Now create the first staff user ===
python scripts\create_user.py
echo.
echo Done. Open .env in Notepad and fill in GEMINI_API_KEY and ROBOT_COM_PORT.
pause
