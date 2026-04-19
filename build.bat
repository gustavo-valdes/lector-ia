@echo off
REM ─────────────────────────────────────────────────────────────────────────────
REM  LectorIA – Script de compilación a .exe distribuible
REM  Requiere: Python 3.11+ en el PATH
REM ─────────────────────────────────────────────────────────────────────────────

echo.
echo [1/4] Instalando dependencias...
pip install -r requirements.txt
pip install pyinstaller
if errorlevel 1 (
    echo ERROR: Fallo al instalar dependencias.
    pause & exit /b 1
)

echo.
echo [2/4] Generando icono...
python generate_icon.py
if errorlevel 1 (
    echo ADVERTENCIA: No se pudo generar el icono. Continuando sin el.
)

echo.
echo [3/4] Compilando LectorIA...
pyinstaller ^
  --onedir ^
  --windowed ^
  --name "LectorIA" ^
  --icon "icon.ico" ^
  --hidden-import "PySide6.QtCore" ^
  --hidden-import "PySide6.QtWidgets" ^
  --hidden-import "PySide6.QtGui" ^
  --hidden-import "PySide6.QtNetwork" ^
  --hidden-import "pygame" ^
  --hidden-import "pygame.mixer" ^
  --hidden-import "gtts" ^
  --hidden-import "gtts.tts" ^
  --hidden-import "gtts.lang" ^
  --hidden-import "fitz" ^
  --hidden-import "PIL" ^
  --hidden-import "PIL.Image" ^
  --hidden-import "PIL.ImageDraw" ^
  --hidden-import "google.genai" ^
  --hidden-import "certifi" ^
  --hidden-import "httpx" ^
  --collect-all "gtts" ^
  --collect-all "certifi" ^
  --noconfirm ^
  --clean ^
  main.py

if errorlevel 1 (
    echo ERROR: Fallo la compilacion.
    pause & exit /b 1
)

echo.
echo [4/4] Preparando distribucion...
REM Crear carpetas que la app necesita al iniciar
if not exist "dist\LectorIA\sessions"    mkdir "dist\LectorIA\sessions"
if not exist "dist\LectorIA\audio_cache" mkdir "dist\LectorIA\audio_cache"

echo.
echo =============================================================================
echo  LISTO.
echo.
echo  Carpeta distribuible:  dist\LectorIA\
echo.
echo  Para compartir la app:
echo    1. Comprime la carpeta  dist\LectorIA\  en un .zip
echo    2. El destinatario descomprime y ejecuta  LectorIA.exe
echo    3. No requiere Python ni ninguna instalacion adicional.
echo =============================================================================
echo.
pause
