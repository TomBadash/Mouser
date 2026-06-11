@echo off
setlocal
cd /d "%~dp0\.."
python "%~dp0build_and_install.py"
if errorlevel 1 exit /b 1
