@ECHO off

@REM // Using "CALL" to wrap program calls to ensure proper handling.
@REM // Variables are set at the start to ensure proper storage until use.

TITLE Mouser — MX Master 3S
SET /p original_directory=%cd%:"=%
@REM // Set working directory before running anything.
SET /p working_directory=%~dp0:"=%
@REM // Move into directory to contain any built files.
CALL cd /d "%working_directory%"
@REM // Make sure to call correct python executable.
CALL "%working_directory%\.venv\Scripts\python.exe" main_qml.py
@REM // Move into original directory (where you were before executing script).
CALL cd /d "%original_directory%"
@REM // Don't exit until user input.
@REM // DONT REMOVE (lets user see error messages if they exist).
PAUSE
