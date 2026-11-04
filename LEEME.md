# Sistema de pedidos - Montería (v4.0)

La guía completa está en **[README.md](README.md)**; la documentación técnica, en la carpeta **[docs/](docs/)**.

## Inicio rápido (Windows + XAMPP)
1. Inicia **Apache y MySQL** en XAMPP.
2. Doble clic en `instalar.bat` (una vez) y luego en `iniciar.bat`.
3. Cliente: http://localhost/restaurante/ · Personal: http://localhost/restaurante/admin.html ·
   Monitoreo: http://localhost/restaurante/monitor.html · Swagger: http://localhost:8000/docs

Con Docker: `copy .env.example .env` y `docker compose up --build -d` (tienda en http://localhost:3000).

| Rol | Correo | Contraseña |
|---|---|---|
| ADMIN | admin@monteria.com | admin123 |
| REPARTIDOR | carlos@monteria.com / laura@monteria.com | reparto123 |
| CLIENTE | cliente@monteria.com | cliente123 |

Cambia estas contraseñas antes de usar el sistema de verdad.
