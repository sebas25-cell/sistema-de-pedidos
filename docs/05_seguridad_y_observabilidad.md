# 05 · Seguridad y observabilidad

## Autenticación y autorización
* `POST /usuarios/login` devuelve un **JWT** (HS256, 12 h) con `sub`, `rol`, `nombre`. Se envía como `Authorization: Bearer <token>`.
* Contraseñas con **bcrypt**. Tras 5 intentos fallidos con el mismo correo, el login se bloquea 15 min (429).
* Cada endpoint declara qué roles aceptan (`requiere("ADMIN")`). Servicio-a-servicio se usa `X-Internal-Key` (rol `SISTEMA`) y el gateway nunca la reenvía.

| Operación | Público | CLIENTE | REPARTIDOR | ADMIN | SISTEMA |
|---|:-:|:-:|:-:|:-:|:-:|
| Ver restaurantes y menú | ✔ | ✔ | ✔ | ✔ | ✔ |
| Registro / login | ✔ | | | | |
| Crear pedido, ver *mis* pedidos, cancelar el propio | | ✔ | | ✔ | |
| Avanzar estados de cocina, cancelar cualquiera | | | | ✔ | ✔ |
| Ver domicilios libres, aceptar domicilio, cambiar disponibilidad | | | ✔ | | ✔ |
| Avanzar domicilio (recoger/entregar) | | | ✔ | ✔ | ✔ |
| Asignar repartidor manualmente, ver todos los domicilios | | | | ✔ | ✔ |
| Registrar/cobrar/anular pagos (directo) | | | | ✔ | ✔ |
| Gestionar restaurantes, menú, usuarios | | | | ✔ | |
| `/metrics`, `/monitor` | | | | ✔ | ✔ |
| Descontar stock, crear notificaciones/eventos, `EN_CAMINO`/`ENTREGADO` | | | | | ✔ |

Otras medidas: el monto del pago se lee del pedido (no del cliente); un cliente solo ve sus pedidos y notificaciones; CORS limitado a `localhost`; un error 500 devuelve solo un mensaje genérico y el `request_id` (el detalle queda en el log); 
en Docker, cada servicio usa un usuario de BD con permisos mínimos y el contenedor corre sin privilegios (`USER app`).

## Observabilidad
| Mecanismo | Dónde |
|---|---|
| **Trazabilidad:** `X-Request-ID` generado/propagado en todas las llamadas y presente en cada línea de log | todos los servicios |
| **Logs** a consola y `logs/<servicio>.log` (rotativo 1 MB × 3); `LOG_FORMAT=json` para JSON, `LOG_LEVEL`, `LOG_DIR` | `common/observabilidad.py` |
| **Logs de negocio:** pedido creado, cambios de estado, asignaciones, pagos, bloqueos de login | servicios |
| **`GET /health`** (200/503, comprueba la BD y el broker) | todos |
| **`GET /metrics`** (ADMIN): peticiones, 2xx/4xx/5xx, latencia media y p95, rutas más usadas, errores recientes | todos |
| **`GET /estado`** (público) y **`GET /monitor`** (ADMIN) agregan los 8 servicios | gateway |
| **Panel visual** `frontend/monitor.html` | admin |

Ejemplo de traza: una misma petición aparece con el mismo id en `gateway.log` y en el servicio de destino:
```
INFO gateway       [traza-1793749979] GET /restaurantes/restaurantes -> 200 (22.9 ms)
INFO restaurantes  [traza-1793749979] GET /restaurantes -> 200 (20.1 ms)
```
