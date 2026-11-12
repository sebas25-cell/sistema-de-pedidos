@echo off
REM Inicia el sistema + un tunel NUEVO de Cloudflare y abre la tienda de Vercel ya conectada.
REM Requisitos: instalar.bat ejecutado una vez y cloudflared instalado.
cd /d "%~dp0"
if "%CORS_ORIGINS%"=="" set CORS_ORIGINS=https://sistema-de-pedidos-frontend-flame.vercel.app

echo == 1/3 Iniciando servicios ==
call iniciar.bat

echo == 2/3 Abriendo el tunel (se cierra con la ventana "Tunel Cloudflare") ==
if exist cf.log del cf.log
start "Tunel Cloudflare" /min cmd /c "cloudflared tunnel --url http://localhost:8000 > cf.log 2>&1"

echo == 3/3 Esperando la direccion del tunel y publicandola en GitHub ==
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0publicar_tunel.ps1"
echo.
echo Deja abiertas las ventanas de los servicios y "Tunel Cloudflare" mientras uses el sistema.
pause
