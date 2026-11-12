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

echo == 3/3 Esperando la direccion del tunel ==
powershell -NoProfile -Command "$u=$null; for($i=0;$i -lt 60 -and -not $u;$i++){Start-Sleep 1; if(Test-Path 'cf.log'){$m=Select-String -Path 'cf.log' -Pattern 'https://[a-z0-9-]+\.trycloudflare\.com' | Select-Object -First 1; if($m){$u=$m.Matches[0].Value}}}; if($u){ Start-Sleep 8; $l='https://sistema-de-pedidos-frontend-flame.vercel.app/index.html?api='+$u; Set-Clipboard $l; Write-Host ''; Write-Host 'Tunel:' $u; Write-Host 'Enlace (ya copiado al portapapeles):'; Write-Host $l; Start-Process $l } else { Write-Host 'No se pudo obtener la direccion del tunel. Revisa que cloudflared este instalado.' }"
echo.
echo Deja abiertas las ventanas de los servicios y "Tunel Cloudflare" mientras uses el sistema.
pause
