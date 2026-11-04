# 08 · Guion de demostración y sustentación (≈ 15 min)

Preparación: sistema en marcha, `monitor.html` abierto en una pestaña, Swagger en otra, `index.html` (cliente) y `admin.html` (admin) en ventanas distintas, y un repartidor (`carlos@…`) con la disponibilidad **activada**.

| # | Etapa | Qué decir | Qué mostrar | Min |
|---|---|---|---|---|
| 1 | **Problema** | Un monolito se cae completo; notificar o cobrar no debe frenar la toma de pedidos | Diapositiva | 1 |
| 2 | **Objetivo** | Gestionar restaurantes, menús, pedidos, pagos y domicilios en servicios independientes | Diapositiva | 1 |
| 3 | **Arquitectura** | Gateway + 7 servicios + RabbitMQ + una BD por servicio | `docs/diagramas/01_arquitectura.png` | 2 |
| 4 | **Microservicios** | Responsabilidad de cada uno y qué *no* hace | Tabla del README; `/docs` unificado | 1 |
| 5 | **Comunicación** | HTTP donde se necesita respuesta; eventos donde no se debe esperar | Diagrama de secuencia; consola de RabbitMQ | 2 |
| 6 | **Persistencia** | 7 bases, sin tablas compartidas, usuarios de BD con permisos mínimos | phpMyAdmin o `docs/03`; el *access denied* de `svc_menu` | 1 |
| 7 | **Seguridad** | JWT, roles, clave interna, el cliente no puede falsificar precios | Swagger *Authorize*; 403 al intentar una acción de admin | 1 |
| 8 | **Contenedores** | Compose con healthchecks y dependencias | `docker-compose.yml`, `docker compose ps` | 1 |
| 9 | **Pruebas** | 16 unitarias, 94 de integración, resiliencia, UI | `docs/06`, salida de `probar.py` | 1 |
| 10 | **Demo en vivo** | Flujo completo (abajo) | Navegador | 4 |

## Demo en vivo (flujo obligatorio)
1. **Restaurante → menú:** cliente entra, elige *Burger del Sinú*, ve el menú con stock.
2. **Pedido:** agrega 2-3 productos, dirección, pago **Nequi**, *Realizar pedido*. El stock baja en el menú.
3. **Pago:** el pedido pasa a *Confirmado* solo (lo hace `pagos`). Mostrar en `monitor.html` los servicios implicados.
4. **Notificación #1:** la campana del cliente suma un aviso ("recibido", "confirmado").
5. **Cocina:** en `admin.html` → *Pasar a cocina* → *Marcar listo*.
6. **Asignación de repartidor:** el pedido aparece con **Carlos** (el disponible con menos carga). Mostrar en la vista de Carlos el aviso de nuevo domicilio.
7. **Actualización de estado:** Carlos pulsa *Salir a ruta* y luego *Marcar entregado*; el cliente ve la línea de tiempo avanzar.
8. **Notificación final:** "Tu pedido fue entregado".

## Demostraciones opcionales (según el tiempo)
* **Bolsa de pedidos:** apaga la disponibilidad de todos, marca un pedido listo → queda sin repartidor; el repartidor activa su disponibilidad y lo acepta.
* **Resiliencia:** `python tests/resiliencia_rabbitmq.py` (detiene RabbitMQ, el pedido sigue funcionando y el aviso llega por HTTP).
* **Trazabilidad:** copiar un `request_id` del monitor y buscarlo en `logs/gateway.log` y `logs/pedidos.log`.

## Preguntas probables
* *¿Por qué RabbitMQ y no Kafka?* Pocos mensajes, semántica de cola de trabajo, ack y DLQ simples. Ver decisión 6.
* *¿Qué pasa si notificaciones se cae?* Los eventos esperan en la cola durable; el pedido nunca falla por eso.
* *¿Cómo evitan vender stock que no hay?* `UPDATE … WHERE stock >= cantidad` atómico y compensación si algo falla.
* *¿Y si dos repartidores aceptan a la vez?* `UPDATE … WHERE repartidor_id IS NULL`: uno recibe 409.
* *¿Qué falta para producción?* Refresh tokens, rotación de secretos, limitación de tasa, Prometheus/Grafana, outbox pattern, CI/CD.
