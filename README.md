# Sistema de Pedidos para Restaurantes — Montería

Plataforma de pedidos a domicilio construida con **microservicios** (Python · FastAPI), **una base de datos por servicio**
(MySQL/MariaDB), **API Gateway**, **autenticación JWT con roles**, **mensajería asíncrona con RabbitMQ**,
**Swagger unificado**, **logs y monitoreo**, y **Docker Compose**.

![Arquitectura](docs/diagramas/01_arquitectura.png)

## Qué hace

Flujo completo, probado de punta a punta: **restaurante → menú → pedido → pago → asignación de repartidor → cambio de estado → notificación al cliente**.

| Servicio | Puerto | Responsabilidad | Base de datos |
|---|---|---|---|
| gateway | 8000 | Único punto de entrada, Swagger unificado, `/estado`, `/monitor` | — |
| usuarios | 8001 | Registro, login (JWT), roles, disponibilidad de repartidores | `db_usuarios` |
| restaurantes | 8002 | Catálogo de restaurantes | `db_restaurantes` |
| menu | 8003 | Productos, precios, stock (descuento atómico) | `db_menu` |
| pedidos | 8004 | Ciclo de vida del pedido, máquina de estados, compensaciones | `db_pedidos` |
| pagos | 8005 | Cobro (efectivo/tarjeta/Nequi simulados), idempotente | `db_pagos` |
| domicilios | 8006 | Asignación y seguimiento de repartidores, bolsa de pedidos | `db_domicilios` |
| notificaciones | 8007 | Consume eventos y guarda avisos para cliente y repartidor | `db_notificaciones` |

## Formas de ejecutarlo

### A) Windows + XAMPP (la más simple)
1. Inicia **Apache y MySQL** en XAMPP. Requiere Python 3.10+.
2. Doble clic en `instalar.bat` (una vez) y luego en `iniciar.bat`.
3. Cliente: <http://localhost/restaurante/> · Personal: <http://localhost/restaurante/admin.html> · Swagger: <http://localhost:8000/docs>

En este modo no hay RabbitMQ: los eventos viajan por **HTTP de respaldo** (el sistema funciona igual).
Para usar RabbitMQ localmente: `set RABBITMQ_URL=amqp://guest:guest@localhost:5672/%2F` antes de `iniciar.bat`.

### B) Docker Compose (todo el stack)
```bash
cp .env.example .env          # cambia las claves
docker compose up --build -d
```
| Qué | URL |
|---|---|
| Tienda (cliente) | <http://localhost:3000> |
| Panel del personal | <http://localhost:3000/admin.html> |
| Monitoreo | <http://localhost:3000/monitor.html> |
| Swagger unificado | <http://localhost:8000/docs> |
| RabbitMQ (consola) | <http://localhost:15672> (usuario/clave de `.env`) |
| phpMyAdmin (opcional) | `docker compose --profile tools up -d` → <http://localhost:8080> |

### Cuentas de demostración
| Rol | Correo | Contraseña |
|---|---|---|
| ADMIN | admin@monteria.com | admin123 |
| REPARTIDOR | carlos@monteria.com · laura@monteria.com | reparto123 |
| CLIENTE | cliente@monteria.com | cliente123 |

> Cambia estas contraseñas, `JWT_SECRET` e `INTERNAL_KEY` antes de publicar el sistema.

## Pruebas
```bash
python -m pytest tests -q          # 16 pruebas unitarias (no necesitan servicios)
python probar.py                   # 94 verificaciones de integración (servicios en marcha)
python tests/resiliencia_rabbitmq.py   # idempotencia, DLQ, caída de RabbitMQ y del consumidor
python tests/prueba_interfaz.py    # recorrido en navegador (Playwright) con capturas
python exportar_openapi.py         # exporta los contratos a docs/openapi/
```
Resultados y evidencias: [`docs/06_plan_y_evidencias_de_pruebas.md`](docs/06_plan_y_evidencias_de_pruebas.md).

## Documentación

| Documento | Contenido |
|---|---|
| [01 Arquitectura](docs/01_arquitectura.md) | Visión general, servicios, despliegue |
| [02 Comunicación](docs/02_comunicacion.md) | APIs REST, eventos asíncronos, flujo obligatorio, manejo de errores |
| [03 Modelo de datos](docs/03_modelo_de_datos.md) | Esquema de cada servicio y reglas de aislamiento |
| [04 Decisiones técnicas](docs/04_decisiones_tecnicas.md) | Qué se decidió, por qué y con qué compromisos |
| [05 Seguridad y observabilidad](docs/05_seguridad_y_observabilidad.md) | JWT, roles, claves internas, logs, métricas |
| [06 Plan y evidencias de pruebas](docs/06_plan_y_evidencias_de_pruebas.md) | Casos, resultados y capturas |
| [07 Manual de instalación y de usuario](docs/07_manual_instalacion_y_usuario.md) | Paso a paso por rol |
| [08 Guion de demostración y sustentación](docs/08_guion_demostracion.md) | Los 10 momentos de la sustentación |
| `docs/diagramas/` | Fuentes Mermaid (`.mmd`) + PNG/SVG |
| `docs/openapi/` | Contratos OpenAPI de cada servicio y el unificado |

## Estructura
```
common/        código compartido: auth JWT, app base, observabilidad, mensajería, config
<servicio>/    main.py + Dockerfile por microservicio
frontend/      index.html (cliente) · admin.html (admin y repartidor) · monitor.html · css/ · js/
schema.sql · setup_db.py     bases de datos, usuarios de BD por servicio y datos demo
docker-compose.yml · Dockerfile.setup · .env.example
tests/ · probar.py · exportar_openapi.py
```

## Alcance honesto
Los pagos son **simulados** (no hay pasarela real). El broker, las imágenes Docker y el despliegue en la nube dependen de tu entorno: ver
la sección de limitaciones en [`docs/06`](docs/06_plan_y_evidencias_de_pruebas.md).
