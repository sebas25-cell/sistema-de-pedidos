# 04 · Decisiones técnicas

| # | Decisión | Alternativas | Por qué | Compromiso aceptado |
|---|---|---|---|---|
| 1 | **Python + FastAPI** | Node/Express, Spring | Documentación OpenAPI automática, validación con Pydantic, curva corta para el equipo | Menor rendimiento bruto que Go/Java; suficiente para la carga del proyecto |
| 2 | **Una BD por servicio** (MySQL/MariaDB) | BD única con tablas por servicio | Independencia y aislamiento exigidos; permite cambiar o escalar una BD sin tocar las demás | Sin JOIN entre servicios; hay que componer datos por API |
| 3 | **API Gateway propio** (FastAPI) | Kong, Traefik, Nginx | Un punto de entrada, Swagger unificado y monitor sin infraestructura adicional | No hace balanceo avanzado ni limitación de tasa global |
| 4 | **JWT HS256, 12 h** + roles | Sesiones en servidor, OAuth2 | Sin estado: cualquier servicio valida el token con el secreto compartido | Un token robado vale hasta vencer; no hay *refresh token* |
| 5 | **Clave interna `X-Internal-Key`** entre servicios | mTLS, JWT de servicio | Simple y suficiente en red privada | Hay que rotarla a mano; el gateway jamás la reenvía |
| 6 | **RabbitMQ** para notificaciones | Kafka; solo HTTP | Se justifica porque notificar no debe bloquear ni romper el pedido. RabbitMQ (colas, ack, DLQ) encaja mejor que Kafka para pocos mensajes y semántica de cola de trabajo | Un componente más que operar; por eso hay **respaldo HTTP** |
| 7 | **Pago y cambio de estado por HTTP, no por eventos** | Orquestación 100 % por eventos | El pedido necesita la respuesta del pago y del stock en el momento | Acoplamiento temporal; se mitiga con *timeouts* y compensación |
| 8 | **Compensación en lugar de transacciones distribuidas (saga simple)** | 2PC | Los servicios tienen BD distintas; 2PC es frágil y lento | Hay una ventana breve de inconsistencia que se corrige restaurando stock |
| 9 | **UPDATEs atómicos condicionados** (estado, stock, repartidor) | Bloqueos explícitos, colas por pedido | Resuelven carreras (dos repartidores aceptando, doble descuento de stock) con una sola sentencia | Requiere diseñar cada operación así |
| 10 | **Idempotencia por `(evento_id, usuario_id)`** | Deduplicar en memoria | RabbitMQ garantiza *al menos una vez*; el índice único evita avisos duplicados incluso tras reinicios | Columna extra en `notificaciones` |
| 11 | **Respaldo HTTP + circuit breaker de 15 s** | Fallar si no hay broker | El sistema sigue funcionando sin Docker (XAMPP) o con el broker caído | Dos caminos de entrega que probar (ambos probados) |
| 12 | **Logs con `X-Request-ID`, métricas en memoria, `/health` con BD** | Prometheus + Grafana + ELK | Cumple "logs y monitoreo básico" sin sumar infraestructura; el id permite seguir una petición por los 8 servicios | Las métricas se reinician con el servicio y no tienen histórico |
| 13 | **Docker Compose** (no Kubernetes) | K8s | Alcance del proyecto; un comando levanta todo | Sin autoescalado |
| 14 | **Frontend estático sin framework** | React/Vue | Cero compilación, se sirve desde XAMPP o nginx | Menos estructura para crecer |
| 15 | **Pagos simulados** | Pasarela real | El alcance es arquitectónico | No hay conciliación ni cobro real |
| 16 | **Frontend en Vercel + backend local con Cloudflare Tunnel** (opcional) | Servidor en la nube | Permite demostrar el sistema desde cualquier dispositivo sin pagar infraestructura; CORS restringido por `CORS_ORIGINS` | El túnel gratuito cambia de dirección y no tiene garantía de disponibilidad; el computador debe quedar encendido |

## Mejoras futuras
Refresh tokens y rotación de secretos, limitación de tasa en el gateway, Prometheus/Grafana, migraciones versionadas (Alembic), *outbox pattern* para publicar eventos dentro de la misma transacción del pedido, y CI con GitHub Actions.
