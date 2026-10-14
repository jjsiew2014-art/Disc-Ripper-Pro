@echo off
title Disc Ripper Pro - Launcher
color 0B

echo.
echo  ╔══════════════════════════════════════╗
echo  ║        Disc Ripper Pro v2.0.0        ║
echo  ║   Powered by Python + FFmpeg         ║
echo  ╚══════════════════════════════════════╝
echo.

:: ── Find Python ────────────────────────────────────────────
set PYTHON_EXE=

:: Try common install locations
for %%P in (
    "C:\Python313\python.exe"
    "C:\Python312\python.exe"
    "C:\Python311\python.exe"
    "C:\Python310\python.exe"
    "C:\Python39\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python39\python.exe"
) do (
    if exist %%P (
        set PYTHON_EXE=%%P
        goto :found_python
    )
)

:: Try PATH (may be Microsoft Store stub, test with -V)
where python.exe >nul 2>&1 && python.exe --version >nul 2>&1
if not errorlevel 1 (
    set PYTHON_EXE=python.exe
    goto :found_python
)

echo  [ERROR] Python 3.10+ is not installed.
echo.
echo  Please install Python from:
echo    https://www.python.org/downloads/
echo.
echo  Make sure to check "Add Python to PATH" during installation.
pause
exit /b 1

:found_python
echo  [OK] Python found: %PYTHON_EXE%

:: ── Check FFmpeg ────────────────────────────────────────────
where ffmpeg >nul 2>&1
if errorlevel 1 (
    :: Also check local ffmpeg/bin
    if exist "%~dp0ffmpeg\bin\ffmpeg.exe" (
        echo  [OK] Local FFmpeg found.
    ) else (
        echo.
        echo  [WARNING] FFmpeg not found.
        echo  Run:  python setup_ffmpeg.py   to auto-download FFmpeg
        echo  Or download manually: https://ffmpeg.org/download.html
        echo  Place ffmpeg.exe + ffprobe.exe in:  %~dp0ffmpeg\bin\
        echo.
    )
)

echo  Launching Disc Ripper Pro...
echo.
%PYTHON_EXE% "%~dp0vcd_ripper.py"

if errorlevel 1 (
    echo.
    echo  [ERROR] Application exited with an error.
    pause
)
