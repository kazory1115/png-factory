@echo off
setlocal

set APP_NAME=PngFactory
set MAIN_FILE=main.py
set ICON_FILE=assets\icon.ico

if exist "%ICON_FILE%" (
    pyinstaller --noconfirm --clean --onefile --windowed --name %APP_NAME% --icon "%ICON_FILE%" --add-data "assets\icon.png;assets" --collect-all customtkinter %MAIN_FILE%
) else (
    pyinstaller --noconfirm --clean --onefile --windowed --name %APP_NAME% --collect-all customtkinter %MAIN_FILE%
)

echo.
echo Build complete. Check the dist folder for %APP_NAME%.exe
if not defined CI pause
