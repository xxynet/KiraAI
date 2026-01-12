@echo off
setlocal

cd /d "%~dp0"
cd ..

if not exist ".venv" (
    echo [1/3] Creating virtual environment...
    python -m venv .venv
    if errorlevel 1 (
        echo Failed to create virtual environment.
        pause
        exit /b 1
    )
) else (
    echo Virtual environment already exists.
)

echo [2/3] Activating virtual environment...
call .\.venv\Scripts\activate.bat
if errorlevel 1 (
    echo Failed to activate virtual environment.
    pause
    exit /b 1
)

echo [3/3] Installing dependencies...
python -m pip install --upgrade pip
pip install -r requirements.txt

echo ==============================
echo  Launching application...
echo ==============================

python main.py