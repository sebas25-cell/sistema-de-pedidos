@echo off
REM Modo local (XAMPP): sin RabbitMQ los eventos viajan por HTTP de respaldo. Para usar RabbitMQ: set RABBITMQ_URL=amqp://guest:guest@localhost:5672/%%2F antes de iniciar.
REM Arranca los 8 servicios (cada uno en su ventana). Requiere haber ejecutado instalar.bat y tener Apache y MySQL de XAMPP iniciados.
cd /d "%~dp0"
start "usuarios 8001"       cmd /k python -m uvicorn usuarios.main:app --port 8001 --no-access-log
start "restaurantes 8002"   cmd /k python -m uvicorn restaurantes.main:app --port 8002 --no-access-log
start "menu 8003"           cmd /k python -m uvicorn menu.main:app --port 8003 --no-access-log
start "pedidos 8004"        cmd /k python -m uvicorn pedidos.main:app --port 8004 --no-access-log
start "pagos 8005"          cmd /k python -m uvicorn pagos.main:app --port 8005 --no-access-log
start "domicilios 8006"     cmd /k python -m uvicorn domicilios.main:app --port 8006 --no-access-log
start "notificaciones 8007" cmd /k python -m uvicorn notificaciones.main:app --port 8007 --no-access-log
start "gateway 8000"        cmd /k python -m uvicorn gateway.main:app --port 8000 --no-access-log
echo Esperando a que arranquen los servicios...
timeout /t 5 /nobreak >nul
start "" "http://localhost/restaurante/"
start "" "http://localhost/restaurante/admin.html"
start "" "http://localhost:8000/docs"
