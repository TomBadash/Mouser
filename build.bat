@echo off
:: ──────────────────────────────────────────────────────────────
:: build.bat — Build a portable Mouser distribution
::
:: Produces:  dist\Mouser\Mouser.exe   (+ supporting files)
:: Zip that folder and distribute — no Python install required.
::
:: Usage:  build.bat           — incremental (fast, reuses cache)
::         build.bat --clean   — full clean rebuild
:: ──────────────────────────────────────────────────────────────
title Mouser — Build
cd /d "%~dp0"
set "START_TIME=%TIME%"

echo.
echo ===  Mouser Portable Build  ===
echo.

:: ── 1. Activate venv if present ──────────────────────────────
if exist ".venv\Scripts\activate.bat" (
    call ".venv\Scripts\activate.bat"
    echo [*] Virtual-env activated
) else (
    echo [!] No .venv found — using system Python
)

:: ── 2. Install and verify build dependencies ─────────────────
echo [*] Installing requirements...
python -m pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Failed to install requirements.
    pause
    exit /b 1
)

echo [*] Verifying hidapi import...
python -c "import hid; print('[*] hidapi:', hid.__file__)"
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] hidapi is not importable. The packaged app would not detect Logitech devices.
    pause
    exit /b 1
)

:: ── 3. Clean previous build ──────────────────────────────────
:: Always clean dist (output); only clean build cache with --clean
if exist "dist\Mouser" (
    echo [*] Removing previous dist\Mouser...
    rmdir /s /q "dist\Mouser"
)
if /i "%~1"=="--clean" (
    if exist "build\Mouser" (
        echo [*] Full clean: removing build cache...
        rmdir /s /q "build\Mouser"
    )
) else (
    if exist "build\Mouser" (
        echo [*] Incremental build — reusing analysis cache
    )
)

:: ── 4. Run PyInstaller ───────────────────────────────────────
echo [*] Building with PyInstaller...
pyinstaller Mouser.spec --noconfirm

if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Build failed — see messages above.
    pause
    exit /b 1
)

:: ── 5. Copy default config if missing ────────────────────────
:: (not needed — config is auto-created at first run in %APPDATA%)

set "END_TIME=%TIME%"
echo.
echo ===  Build complete!  ===
echo Output: dist\Mouser\Mouser.exe
echo Started:  %START_TIME%
echo Finished: %END_TIME%
echo.
echo To distribute: zip the  dist\Mouser  folder.
echo.
pause
