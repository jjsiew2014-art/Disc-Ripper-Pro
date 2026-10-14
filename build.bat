@echo off
title Disc Ripper Pro - Build Executable
color 0A

echo.
echo  ============================================
echo   Building Disc Ripper Pro v2.0.0
echo  ============================================
echo.

where pyinstaller >nul 2>&1
if errorlevel 1 (
    echo [ERROR] PyInstaller not found in PATH.
    echo Please install: pip install pyinstaller
    pause
    exit /b 1
)

pyinstaller --noconfirm "Disc Ripper Pro.spec"

if errorlevel 1 (
    echo.
    echo [ERROR] Build failed!
    pause
    exit /b 1
)

if exist "ffmpeg" (
    echo Copying ffmpeg dependencies into dist...
    xcopy /E /I /Y "ffmpeg" "dist\Disc Ripper Pro\ffmpeg" >nul
)

echo.
echo Packaging into Release folder...
python -c "import os, sys, shutil, zipfile; from pathlib import Path; root = Path('.'); dist_app = root / 'dist' / 'Disc Ripper Pro'; release_dir = root / 'Release'; portable_dir = release_dir / 'Disc_Ripper_Pro_Portable_v2.0.0'; zip_path = release_dir / 'Disc_Ripper_Pro_Portable_v2.0.0.zip'; release_dir.mkdir(parents=True, exist_ok=True); shutil.rmtree(portable_dir, ignore_errors=True); portable_dir.mkdir(parents=True, exist_ok=True); shutil.copy2(dist_app / 'Disc Ripper Pro.exe', portable_dir / 'Disc Ripper Pro.exe'); shutil.copytree(dist_app / '_internal', portable_dir / '_internal'); (shutil.copytree(root / 'ffmpeg', portable_dir / 'ffmpeg') if (root / 'ffmpeg').exists() else None); [shutil.copy2(root / f, portable_dir / f) for f in ['CompactDisc.ico', 'CompactDisc.png', 'en.json', 'zh-CN.json', 'LICENSE', 'README.md'] if (root / f).exists()]; zip_path.unlink(missing_ok=True); zf = zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED, compresslevel=6); [zf.write(Path(r) / file, (Path(r) / file).relative_to(portable_dir)) for r, dirs, files in os.walk(portable_dir) for file in files]; zf.close(); shutil.copy2(zip_path, release_dir / 'Disc_Ripper_Pro_Portable.zip'); print('[OK] Release package created successfully!')"

echo.
echo [OK] Build completed successfully!
echo Executable located in: dist\Disc Ripper Pro\Disc Ripper Pro.exe
echo Release package: Release\Disc_Ripper_Pro_Portable_v2.0.0.zip
echo.
pause
