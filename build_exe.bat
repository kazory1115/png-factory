@echo off
setlocal

set APP_NAME=PngFactory
set MAIN_FILE=main.py
set ICON_FILE=assets\icon.ico

if exist ".venv\Scripts\python.exe" (
    set PYTHON=.venv\Scripts\python.exe
) else (
    set PYTHON=python
)

if exist "%ICON_FILE%" (
    "%PYTHON%" -m PyInstaller --noconfirm --clean --onefile --windowed --name %APP_NAME% --icon "%ICON_FILE%" --add-data "assets\icon.png;assets" --collect-all customtkinter --copy-metadata pymatting %MAIN_FILE%
) else (
    "%PYTHON%" -m PyInstaller --noconfirm --clean --onefile --windowed --name %APP_NAME% --collect-all customtkinter --copy-metadata pymatting %MAIN_FILE%
)

if errorlevel 1 exit /b %errorlevel%

echo.
echo Build complete. Check the dist folder for %APP_NAME%.exe
if not defined CI pause
