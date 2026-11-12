"""Comunicación asíncrona entre microservicios con RabbitMQ.

Uso en el sistema: los servicios de negocio (pedidos, domicilios) PUBLICAN eventos de dominio y el servicio de
notificaciones los CONSUME. Así un pedido nunca falla ni se demora porque notificaciones esté caído.

Topología (se declara sola, es idempotente):

    eventos (exchange topic, durable)
        ├─ pedido.*     ┐
        └─ domicilio.*  ┴──> cola `notificaciones` (durable, con dead-letter) ──> consumidor
                                      │ mensaje rechazado
                                      ▼
                       eventos.dlx (fanout) ──> cola `notificaciones.dlq`  (para inspección manual)

Respaldo: si RabbitMQ no está configurado (RABBITMQ_URL vacío) o no responde, el evento se envía por HTTP
a `POST /eventos` de notificaciones. El sistema sigue funcionando (modo local con XAMPP, sin Docker).
"""
import contextlib
import json
import logging
import threading
import time
import uuid

try:
    import pika
except ImportError:      # sin la librería, el sistema sigue funcionando con el respaldo HTTP
    pika = None

from common import config, observabilidad
from common.app import llamar

EXCHANGE = "eventos"
DLX = "eventos.dlx"
COLA = "notificaciones"
COLA_DLQ = "notificaciones.dlq"
BINDINGS = ("pedido.*", "domicilio.*")

log = logging.getLogger("app.mensajeria")   # se configura en create_app; así el archivo de log lleva el nombre del servicio
_sin_broker_hasta = 0.0       # interruptor de circuito: tras un fallo no se reintenta AMQP durante unos segundos
_PAUSA_TRAS_FALLO = 15


def _parametros():
    p = pika.URLParameters(config.RABBITMQ_URL)
    p.socket_timeout = 2
    p.connection_attempts = 1
    p.blocked_connection_timeout = 3
    return p


def declarar_topologia(canal):
    canal.exchange_declare(EXCHANGE, exchange_type="topic", durable=True)
    canal.exchange_declare(DLX, exchange_type="fanout", durable=True)
    canal.queue_declare(COLA_DLQ, durable=True)
    canal.queue_bind(COLA_DLQ, DLX)
    canal.queue_declare(COLA, durable=True, arguments={"x-dead-letter-exchange": DLX})
    for clave in BINDINGS:
        canal.queue_bind(COLA, EXCHANGE, clave)


def publicar(tipo, datos):
    """Publica un evento de dominio. Devuelve 'rabbitmq', 'http' o None si no se pudo entregar por ningún medio."""
    global _sin_broker_hasta
    evento = {"id": uuid.uuid4().hex, "tipo": tipo, "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
              "request_id": observabilidad.request_id_var.get(), "datos": datos}
    if pika and config.RABBITMQ_URL and time.time() >= _sin_broker_hasta:
        try:
            with contextlib.closing(pika.BlockingConnection(_parametros())) as conexion:
                canal = conexion.channel()
                declarar_topologia(canal)
                canal.confirm_delivery()
                canal.basic_publish(
                    EXCHANGE, tipo, json.dumps(evento, ensure_ascii=False).encode(),
                    properties=pika.BasicProperties(delivery_mode=2, content_type="application/json",
                                                    message_id=evento["id"]),
                    mandatory=True)
            log.info("Evento %s publicado en RabbitMQ (id=%s)", tipo, evento["id"][:8])
            return "rabbitmq"
        except Exception as e:
            _sin_broker_hasta = time.time() + _PAUSA_TRAS_FALLO
            log.warning("RabbitMQ no disponible (%s); se usa HTTP directo durante %ss", type(e).__name__, _PAUSA_TRAS_FALLO)
    r = llamar("POST", f"{config.url('notificaciones')}/eventos", json=evento)
    if r is not None and r.status_code in (200, 201):
        log.info("Evento %s entregado por HTTP (id=%s)", tipo, evento["id"][:8])
        return "http"
    log.error("No se pudo entregar el evento %s (id=%s): ni RabbitMQ ni HTTP respondieron", tipo, evento["id"][:8])
    return None


def iniciar_consumidor(procesar, estado):
    """Arranca un hilo que consume la cola `notificaciones` y llama a procesar(evento) por cada mensaje.

    procesar lanza excepción  -> el mensaje va a la DLQ (no se pierde ni se reintenta en bucle).
    estado: diccionario que se mantiene actualizado ('broker': conectado|desconectado, 'dlq': n mensajes).
    """
    if not config.RABBITMQ_URL or pika is None:
        estado["broker"] = "sin configurar (HTTP directo)"
        log.info("RABBITMQ_URL vacío: los eventos llegarán por HTTP en POST /eventos")
        return None

    def al_recibir(canal, metodo, _props, cuerpo):
        try:
            evento = json.loads(cuerpo)
            procesar(evento)
            canal.basic_ack(metodo.delivery_tag)
        except Exception:
            log.error("Evento inválido o con error: enviado a la DLQ", exc_info=True)
            canal.basic_nack(metodo.delivery_tag, requeue=False)

    def bucle():
        while True:
            try:
                conexion = pika.BlockingConnection(_parametros())
                canal = conexion.channel()
                declarar_topologia(canal)
                canal.basic_qos(prefetch_count=10)

                def medir_dlq():
                    try:
                        estado["dlq"] = canal.queue_declare(COLA_DLQ, passive=True).method.message_count
                    except Exception:
                        pass
                    conexion.call_later(10, medir_dlq)

                medir_dlq()
                canal.basic_consume(COLA, al_recibir)
                estado["broker"] = "conectado"
                log.info("Consumidor conectado a RabbitMQ, escuchando la cola '%s'", COLA)
                canal.start_consuming()
            except Exception as e:
                estado["broker"] = "desconectado"
                log.warning("Consumidor sin conexión a RabbitMQ (%s); reintento en 5 s", type(e).__name__)
                time.sleep(5)

    estado["broker"] = "conectando"
    hilo = threading.Thread(target=bucle, name="consumidor-rabbitmq", daemon=True)
    hilo.start()
    return hilo
