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
set "BEST_SPEED=0"

for %%M in (
    "pypi.org|https://pypi.org/simple/"
    "pypi.tuna.tsinghua.edu.cn|https://pypi.tuna.tsinghua.edu.cn/simple/"
    "mirrors.aliyun.com|https://mirrors.aliyun.com/pypi/simple/"
    "mirrors.cloud.tencent.com|https://mirrors.cloud.tencent.com/pypi/simple/"
) do (
    for /f "tokens=1,2 delims=|" %%N in ("%%~M") do (
        set "NAME=%%N"
        set "URL=%%O"
        call :test_mirror
    )
)

echo.
if defined MIRROR (
    echo   Selected: !MIRROR!
) else (
    echo   All mirrors unreachable, using default PyPI.
    set "MIRROR=-i https://pypi.org/simple/"
)

python -m pip install --upgrade pip !MIRROR!
if errorlevel 1 (
    echo Failed to upgrade pip.
    pause
    exit /b 1
)
pip install -r requirements.txt !MIRROR!
if errorlevel 1 (
    echo Failed to install dependencies.
    pause
    exit /b 1
)
goto :install_done

:test_mirror
set "T=" & set "SPEED=" & set "HTTP=" & set "OK="
for /f "tokens=1-3" %%A in ('curl -s -o NUL -r 0-32767 -w "%%{http_code} %%{time_connect} %%{speed_download}" -m 5 "!URL!" 2^>NUL') do (set "HTTP=%%A" & set "T=%%B" & set "SPEED=%%C")
if "!HTTP!"=="200" set "OK=1"
if "!HTTP!"=="206" set "OK=1"
if defined OK (
    for /f "tokens=1 delims=." %%S in ("!SPEED!") do set "SPEED_INT=%%S"
    if not defined SPEED_INT set "SPEED_INT=0"
    call :parse_ms "!T!" MS
    call :format_speed !SPEED_INT! FMT
    echo     !NAME! ... !MS!ms, !FMT!
    if !SPEED_INT! gtr !BEST_SPEED! (set "BEST_SPEED=!SPEED_INT!" & set "MIRROR=-i !URL!")
) else (
    echo     !NAME! ... unreachable
)
goto :eof

:parse_ms
set "S=%~1"
for /f "tokens=1,2 delims=." %%X in ("%S%") do (set "SEC=%%X" & set "FRAC=%%Y")
if not defined SEC set "SEC=0"
set "FRAC=%FRAC%000"
set "FRAC=%FRAC:~0,3%"
set /a "MS_VAL=%SEC%*1000+1%FRAC%-1000"
set "%~2=%MS_VAL%"
goto :eof

:format_speed
set /a "VAL=%~1"
if !VAL! geq 1048576 (
    set /a "DISP=!VAL!/1048576"
    set "%~2=!DISP! MB/s"
) else if !VAL! geq 1024 (
    set /a "DISP=!VAL!/1024"
    set "%~2=!DISP! KB/s"
) else (
    set "%~2=!VAL! B/s"
)
goto :eof

:install_done

echo ==============================
echo  Launching application...
echo ==============================

setlocal disabledelayedexpansion
python main.py %*
