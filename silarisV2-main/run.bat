@echo off
echo Starting RFID Linen Pro Backend...
cd /d "%~dp0backend"
if exist "%~dp0.venv\Scripts\activate.bat" (
    call "%~dp0.venv\Scripts\activate.bat"
) else if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
)
echo Starting FastAPI Uvicorn Server (Port 8000)...
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
pause
