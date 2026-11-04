@echo off
REM Ejecutar UNA sola vez (con MySQL de XAMPP iniciado). Doble clic o desde la carpeta sistema.
cd /d "%~dp0"
echo === 1/3 Instalando dependencias de Python ===
python -m pip install -r requirements.txt
if errorlevel 1 goto error
echo.
echo === 2/3 Preparando las bases de datos - MySQL de XAMPP debe estar iniciado ===
python setup_db.py
if errorlevel 1 goto error
echo.
echo === 3/3 Copiando el frontend a XAMPP ===
if exist "C:\xampp\htdocs" (
  xcopy /E /I /Y "frontend" "C:\xampp\htdocs\restaurante" >nul
  echo Frontend copiado a C:\xampp\htdocs\restaurante
) else (
  echo No encontre C:\xampp\htdocs. Copia la carpeta frontend dentro de htdocs de tu XAMPP y llamala restaurante.
)
echo.
echo Listo. Ahora ejecuta iniciar.bat
pause
exit /b 0
:error
echo.
echo Algo fallo, revisa el mensaje de arriba.
pause
exit /b 1
