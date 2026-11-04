@echo off
setlocal enabledelayedexpansion
title Disc Ripper Pro - Build Setup Installer
color 0A

echo.
echo ========================================================
echo   Building Disc Ripper Pro Setup v2.0.4
echo ========================================================
echo.

set SCRIPT_DIR=%~dp0
cd /d "%SCRIPT_DIR%"

set SOURCE_DIR=Release\Disc_Ripper_Pro_Portable_v2.0.4
set OUTPUT_DIR=Release
set SETUP_EXE_NAME=Disc Ripper Pro Setup v2.0.4.exe
set FINAL_SETUP_PATH=%OUTPUT_DIR%\%SETUP_EXE_NAME%
set DIST_INSTALLER_DIR=dist\installer

:: 1. Check required release files and binaries
echo [1/4] Verifying portable release dependencies...
if not exist "%SOURCE_DIR%\Disc Ripper Pro.exe" (
    echo [ERROR] Main executable not found: %SOURCE_DIR%\Disc Ripper Pro.exe
    echo Please run build.bat first to build the portable release.
    exit /b 1
)

if not exist "%SOURCE_DIR%\_internal" (
    echo [ERROR] Runtime dependencies directory not found: %SOURCE_DIR%\_internal
    exit /b 1
)

if not exist "%SOURCE_DIR%\ffmpeg\bin\ffmpeg.exe" (
    echo [ERROR] FFmpeg binary not found: %SOURCE_DIR%\ffmpeg\bin\ffmpeg.exe
    exit /b 1
)

if not exist "%SOURCE_DIR%\ffmpeg\bin\ffprobe.exe" (
    echo [ERROR] FFprobe binary not found: %SOURCE_DIR%\ffmpeg\bin\ffprobe.exe
    exit /b 1
)

if not exist "%SOURCE_DIR%\ffmpeg\bin\HandBrakeCLI.exe" (
    echo [ERROR] HandBrakeCLI binary not found: %SOURCE_DIR%\ffmpeg\bin\HandBrakeCLI.exe
    exit /b 1
)

if not exist "%SOURCE_DIR%\CompactDisc.ico" (
    echo [ERROR] Icon not found: %SOURCE_DIR%\CompactDisc.ico
    exit /b 1
)

if not exist "%SOURCE_DIR%\LICENSE" (
    echo [ERROR] License file not found: %SOURCE_DIR%\LICENSE
    exit /b 1
)

echo [OK] All required application files and tools verified.
echo.

:: 2. Locate Inno Setup compiler
echo [2/4] Locating Inno Setup 6 compiler (ISCC.exe)...
set ISCC_CMD=

where ISCC.exe >nul 2>&1
if not errorlevel 1 (
    for /f "tokens=*" %%i in ('where ISCC.exe') do (
        if not defined ISCC_CMD set ISCC_CMD="%%i"
    )
)

if not defined ISCC_CMD (
    if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" set ISCC_CMD="%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
)
if not defined ISCC_CMD (
    if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set ISCC_CMD="%ProgramFiles%\Inno Setup 6\ISCC.exe"
)
if not defined ISCC_CMD (
    if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set ISCC_CMD="%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
)
if not defined ISCC_CMD (
    if exist "C:\Users\Admin\AppData\Local\Programs\Inno Setup 6\ISCC.exe" set ISCC_CMD="C:\Users\Admin\AppData\Local\Programs\Inno Setup 6\ISCC.exe"
)

if not defined ISCC_CMD (
    echo [ERROR] Inno Setup 6 compiler ISCC.exe was not found!
    echo Please install Inno Setup 6 from https://jrsoftware.org/isdl.php
    exit /b 1
)

echo [OK] Found Inno Setup Compiler: !ISCC_CMD!
echo.

:: 3. Compile the Inno Setup installer script
echo [3/4] Compiling installer script: installer\DiscRipperPro.iss...
!ISCC_CMD! /Qp "installer\DiscRipperPro.iss"

if errorlevel 1 (
    echo.
    echo [ERROR] Inno Setup compilation failed!
    exit /b 1
)

echo [OK] Installer compilation completed.
echo.

:: 4. Verify generated installer and organize output
echo [4/4] Verifying generated installer package...
if not exist "%FINAL_SETUP_PATH%" (
    echo [ERROR] Expected installer binary was not found at: %FINAL_SETUP_PATH%
    exit /b 1
)

:: Also mirror to dist\installer for consistent build output
if not exist "%DIST_INSTALLER_DIR%" mkdir "%DIST_INSTALLER_DIR%"
copy /y "%FINAL_SETUP_PATH%" "%DIST_INSTALLER_DIR%\%SETUP_EXE_NAME%" >nul

for %%F in ("%FINAL_SETUP_PATH%") do set FILE_SIZE=%%~zF

echo.
echo ========================================================
echo   [SUCCESS] Disc Ripper Pro Setup v2.0.4 Created!
echo ========================================================
echo   Path: %FINAL_SETUP_PATH%
echo   Size: !FILE_SIZE! bytes
echo   Mirror: %DIST_INSTALLER_DIR%\%SETUP_EXE_NAME%
echo ========================================================
echo.
exit /b 0
