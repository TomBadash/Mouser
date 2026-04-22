@ECHO OFF
TITLE Mouser — MX Master 3S
SETLOCAL
CD /D "%~dp0"
".venv\Scripts\python.exe" main_qml.py
PAUSE
ENDLOCAL
