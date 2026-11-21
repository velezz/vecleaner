@echo off
REM ============================================================
REM build.bat — Empaqueta VeClean como .exe portable
REM
REM Requisitos previos:
REM   pip install customtkinter psutil pyinstaller pillow
REM
REM Genera: dist\VeClean.exe (un solo archivo, sin instalador)
REM ============================================================

echo [*] Verificando dependencias...
pip install customtkinter psutil pyinstaller pillow --quiet

echo [*] Buscando ruta de CustomTkinter...
for /f "delims=" %%i in ('python -c "import customtkinter; import os; print(os.path.dirname(customtkinter.__file__))"') do set CTK_PATH=%%i

echo    CustomTkinter en: %CTK_PATH%

echo [*] Empaquetando VeClean...
python -m PyInstaller ^
    --noconfirm ^
    --onefile ^
    --windowed ^
    --name "VeClean" ^
    --add-data "%CTK_PATH%;customtkinter/" ^
    --add-data "logo.ico;." ^
    --icon "logo.ico" ^
    --clean ^
    gui.py

echo.
if exist dist\VeClean.exe (
    echo [OK] VeClean.exe creado en dist\VeClean.exe
    echo     Tamano:
    for %%A in (dist\VeClean.exe) do echo     %%~zA bytes
) else (
    echo [ERROR] Algo fallo. Revisa la salida de PyInstaller arriba.
)

echo.
pause
