# 07 · Manual de instalación y de usuario

## Instalación

### Opción A — Windows con XAMPP
1. Instala **Python 3.10+** (marca *Add Python to PATH*) y **XAMPP**. En el panel de XAMPP pulsa **Start** en **Apache** y **MySQL**.
2. En la carpeta del proyecto, doble clic en **`instalar.bat`** (una sola vez): instala librerías, crea las 7 bases y tablas, carga datos de demostración y copia el frontend a `C:\xampp\htdocs\restaurante`.
3. Doble clic en **`iniciar.bat`**: abre 8 ventanas (una por servicio) y el navegador.
4. Si tu `root` de MySQL tiene contraseña: en la consola `set DB_PASS=tu_clave` antes de los pasos 2 y 3.

*Si PowerShell dice que no reconoce `instalar.bat`, escribe `.\instalar.bat`.*

### Opción B — Docker Compose
1. Instala Docker Desktop.
2. `copy .env.example .env` (o `cp`) y cambia las claves.
3. `docker compose up --build -d` y espera ~1 minuto. Revisa `docker compose ps` (todos *healthy*).
4. Abre <http://localhost:3000>. Para apagar: `docker compose down` (añade `-v` para borrar datos).

### Verificar que todo funciona
* <http://localhost:8000/estado> debe mostrar los 7 servicios en `true`.
* `python probar.py` debe terminar con *0 con falla*.

### Problemas frecuentes
| Síntoma | Causa y solución |
|---|---|
| "No se pudo conectar con MySQL" en `instalar.bat` | MySQL de XAMPP no está iniciado, o `root` tiene contraseña (`set DB_PASS=…`) |
| La tienda muestra "No hay conexión con el servidor" | Falta `iniciar.bat` (gateway en el puerto 8000) |
| Puerto ocupado | Cierra el programa que usa 8000–8007 o ejecuta `iniciar.bat` otra vez tras cerrar las ventanas viejas |
| Avisos no llegan en modo Docker | Revisa <http://localhost:15672> y `docker compose logs notificaciones` |

## Manual de usuario

### Cliente — `index.html`
1. **Ingresar o crear cuenta** (demo: cliente@monteria.com / cliente123).
2. **Elige un restaurante**, filtra por categoría o usa el buscador.
3. Pulsa **+** en los productos; la insignia del carrito muestra cuántos llevas. Las etiquetas indican *¡Quedan pocos!* o *Agotado*.
4. Abre el **carrito** 🛒, escribe la **dirección**, elige el **método de pago** (efectivo, tarjeta o Nequi, simulados) y pulsa **Realizar pedido**.
5. **Sigue tu pedido** en la línea de tiempo (Recibido → Confirmado → En cocina → Listo → En camino → Entregado). Puedes cancelarlo mientras no esté en cocina.
6. La campana 🔔 muestra tus **avisos**; el número rojo son los no leídos y se marcan como leídos al abrirla.
7. Botón ☀️/🌙 cambia el tema.

### Administrador — `admin.html` (admin@monteria.com / admin123)
* **Pedidos:** tablero por estado con tiempo de espera (rojo si pasa de 15 min). Botones para avanzar cada pedido; en *Listos* puedes **asignar o cambiar el repartidor** (se indica si está disponible). Indicadores de pedidos activos, entregados y cancelados.
* **Restaurantes / Menú:** crear, editar, activar/desactivar, reponer stock (+10) y ocultar productos.
* **Equipo:** crear repartidores, administradores o clientes.
* **Monitoreo** (`monitor.html`): estado de los 8 servicios, peticiones, errores, latencia, RabbitMQ/DLQ y los últimos avisos con su id de traza.

### Repartidor — `admin.html` (carlos@monteria.com / reparto123)
1. Activa **tu disponibilidad** para recibir pedidos.
2. Si hay pedidos listos sin repartidor aparecen en **Pedidos listos para aceptar**: pulsa **Aceptar domicilio**.
3. En **Mis domicilios activos**: *Recogido: salir a ruta* y luego *Marcar entregado*.
4. Mira tus **notificaciones recientes** al final de la página.

### Swagger — <http://localhost:8000/docs>
1. Ejecuta `POST /usuarios/login` y copia el `token`.
2. Pulsa **Authorize** y pégalo (sin la palabra *Bearer*).
3. Prueba cualquier operación; las respuestas de error están documentadas por operación.
