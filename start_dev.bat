@echo off
echo Starting Xserver App for Local Development...
echo.

REM Check if venv exists
if not exist venv (
    echo Creating virtual environment venv...
    python -m venv venv
    echo Installing dependencies...
    call venv\Scripts\activate
    pip install -r requirements.txt
) else (
    echo Activating virtual environment...
    call venv\Scripts\activate
)

echo.
echo Starting Uvicorn Server (Hot Reload)...
echo Access: http://localhost:8000
echo.

uvicorn main:app --reload

pause
