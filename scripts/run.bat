@echo off
setlocal enabledelayedexpansion

cd /d "%~dp0"
cd ..

:: Backward compatibility: rename .venv to venv if needed
if exist ".venv" if not exist "venv" (
    echo [compat] Renaming .venv to venv...
    rename .venv venv
)

if not exist "venv" (
    echo [1/3] Creating virtual environment...
    python -m venv venv
    if errorlevel 1 (
        echo Failed to create virtual environment.
        pause
        exit /b 1
    )
) else (
    echo Virtual environment already exists.
)

echo [2/3] Activating virtual environment...
call .\venv\Scripts\activate.bat
if errorlevel 1 (
    echo Failed to activate virtual environment.
    pause
    exit /b 1
)

echo [3/3] Testing pip mirrors...

set "MIRROR="
set "BEST_MS=99999"

:: --- PyPI official ---
set "T="
for /f "delims=" %%A in ('curl -s -o NUL -w "%%{time_connect}" -m 3 -I "https://pypi.org/simple/" 2^>NUL') do set "T=%%A"
if defined T (
    call :parse_ms "!T!" MS
    echo     pypi.org ... !T!s
    if !MS! lss !BEST_MS! (set "BEST_MS=!MS!" & set "MIRROR=-i https://pypi.org/simple/")
) else (
    echo     pypi.org ... timeout
)

:: --- Tsinghua ---
set "T="
for /f "delims=" %%A in ('curl -s -o NUL -w "%%{time_connect}" -m 3 -I "https://pypi.tuna.tsinghua.edu.cn/simple/" 2^>NUL') do set "T=%%A"
if defined T (
    call :parse_ms "!T!" MS
    echo     pypi.tuna.tsinghua.edu.cn ... !T!s
    if !MS! lss !BEST_MS! (set "BEST_MS=!MS!" & set "MIRROR=-i https://pypi.tuna.tsinghua.edu.cn/simple/")
) else (
    echo     pypi.tuna.tsinghua.edu.cn ... timeout
)

:: --- Aliyun ---
set "T="
for /f "delims=" %%A in ('curl -s -o NUL -w "%%{time_connect}" -m 3 -I "https://mirrors.aliyun.com/pypi/simple/" 2^>NUL') do set "T=%%A"
if defined T (
    call :parse_ms "!T!" MS
    echo     mirrors.aliyun.com ... !T!s
    if !MS! lss !BEST_MS! (set "BEST_MS=!MS!" & set "MIRROR=-i https://mirrors.aliyun.com/pypi/simple/")
) else (
    echo     mirrors.aliyun.com ... timeout
)

:: --- Tencent Cloud ---
set "T="
for /f "delims=" %%A in ('curl -s -o NUL -w "%%{time_connect}" -m 3 -I "https://mirrors.cloud.tencent.com/pypi/simple/" 2^>NUL') do set "T=%%A"
if defined T (
    call :parse_ms "!T!" MS
    echo     mirrors.cloud.tencent.com ... !T!s
    if !MS! lss !BEST_MS! (set "BEST_MS=!MS!" & set "MIRROR=-i https://mirrors.cloud.tencent.com/pypi/simple/")
) else (
    echo     mirrors.cloud.tencent.com ... timeout
)

echo.
if defined MIRROR (
    echo   Selected: !MIRROR!
) else (
    echo   All mirrors timed out, using default PyPI.
)

python -m pip install --upgrade pip !MIRROR!
pip install -r requirements.txt !MIRROR!
goto :install_done

:parse_ms
:: Convert curl %{time_connect} (seconds.decimal) to integer milliseconds
set "S=%~1"
for /f "tokens=1,2 delims=." %%X in ("%S%") do (set "SEC=%%X" & set "FRAC=%%Y")
if not defined SEC set "SEC=0"
set "FRAC=%FRAC%000"
set "FRAC=%FRAC:~0,3%"
set /a "MS_VAL=%SEC%*1000+1%FRAC%-1000"
set "%~2=%MS_VAL%"
goto :eof

:install_done

echo ==============================
echo  Launching application...
echo ==============================

python main.py %*
