from contextlib import asynccontextmanager

import pymysql
from fastapi import Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from common.app import create_app, errores
from common.auth import requiere
from common.db import query, execute
from common.mensajeria import iniciar_consumidor

DB = "db_notificaciones"
ESTADO = {"broker": "sin iniciar", "dlq": 0}   # lo actualiza el hilo consumidor; se ve en /health y /metrics

MENSAJES_PEDIDO = {
    "CREADO": "Tu pedido #{id} fue recibido",
    "CONFIRMADO": "Tu pedido #{id} fue confirmado",
    "EN_COCINA": "Tu pedido #{id} está en cocina 🔥",
    "LISTO": "Tu pedido #{id} está listo y esperando repartidor",
    "EN_CAMINO": "Tu pedido #{id} va en camino 🛵",
    "ENTREGADO": "Tu pedido #{id} fue entregado. ¡Buen provecho!",
    "CANCELADO": "Tu pedido #{id} fue cancelado",
}


@asynccontextmanager
async def ciclo_de_vida(_app):
    iniciar_consumidor(procesar, ESTADO)     # conecta a RabbitMQ en segundo plano (si está configurado)
    yield


app = create_app(
    "notificaciones",
    db=DB,
    lifespan=ciclo_de_vida,
    descripcion=(
        "**Responsabilidad:** avisar a clientes y repartidores durante el proceso. Es el **consumidor** de los "
        "eventos de dominio que publican pedidos y domicilios en **RabbitMQ**; los convierte en mensajes legibles y "
        "los guarda por usuario.\n\n"
        "**Eventos que consume:** `pedido.estado_cambiado`, `domicilio.asignado`, `domicilio.aceptado`, "
        "`domicilio.disponible`.\n\n"
        "**Fiabilidad:** cola durable con ack manual; un mensaje que falla va a la cola `notificaciones.dlq` "
        "(dead-letter) en lugar de perderse; el consumo es idempotente (un evento repetido no duplica avisos). "
        "Si RabbitMQ no está disponible, el emisor usa `POST /eventos` por HTTP.\n\n"
        "**Datos propios:** base `db_notificaciones`, tabla `notificaciones`."),
    tags=[
        {"name": "Notificaciones", "description": "Consulta de los avisos de un usuario."},
        {"name": "Eventos", "description": "Entrada HTTP de eventos (respaldo cuando no hay RabbitMQ)."},
        {"name": "Monitoreo", "description": "Salud, métricas y estado del broker."},
    ],
)
app.state.metricas.agregar_proveedor(lambda: dict(ESTADO))


class NotifIn(BaseModel):
    usuario_id: int
    mensaje: str = Field(min_length=1, max_length=255)


class EventoIn(BaseModel):
    id: str = Field(description="Identificador único del evento (permite descartar repetidos)")
    tipo: str = Field(description="pedido.estado_cambiado, domicilio.asignado, domicilio.aceptado o domicilio.disponible")
    datos: dict
    ts: str | None = None
    request_id: str | None = None
    model_config = ConfigDict(json_schema_extra={"examples": [{
        "id": "9f1c2b7a0e4d4b6f8a1d3c5e7f901234", "tipo": "pedido.estado_cambiado",
        "datos": {"pedido_id": 12, "cliente_id": 4, "estado": "EN_COCINA"}}]})


def construir(evento):
    """Traduce un evento de dominio a la lista de (usuario_id, mensaje) que debe notificarse."""
    t, d = evento.get("tipo"), evento.get("datos") or {}
    pid = d.get("pedido_id")
    salida = []
    if t == "pedido.estado_cambiado":
        plantilla = MENSAJES_PEDIDO.get(d.get("estado"))
        if plantilla and d.get("cliente_id"):
            salida.append((d["cliente_id"], plantilla.format(id=pid)))
    elif t == "domicilio.asignado":
        if d.get("cliente_id"):
            salida.append((d["cliente_id"], f"Tu pedido #{pid} fue asignado al repartidor {d.get('repartidor_nombre', '')}".strip()))
        if d.get("repartidor_id"):
            salida.append((d["repartidor_id"], f"Nuevo domicilio: pedido #{pid}. Entra a Mis domicilios para ver los detalles."))
    elif t == "domicilio.aceptado":
        if d.get("cliente_id"):
            salida.append((d["cliente_id"], f"Tu pedido #{pid} fue aceptado por el repartidor {d.get('repartidor_nombre', '')}".strip()))
        if d.get("repartidor_id"):
            salida.append((d["repartidor_id"], f"Aceptaste el domicilio del pedido #{pid}"))
    elif t == "domicilio.disponible":
        for rid in d.get("repartidores") or []:
            salida.append((rid, f"Pedido #{pid} listo para recoger. Entra y activa tu disponibilidad para recibir domicilios."))
    return salida


def procesar(evento):
    """Guarda las notificaciones de un evento. Idempotente: (evento_id, usuario_id) es único."""
    if not isinstance(evento, dict) or not evento.get("tipo"):
        raise ValueError("Evento sin tipo")
    destinos = construir(evento)
    if not destinos and evento["tipo"] not in ("pedido.estado_cambiado", "domicilio.asignado", "domicilio.aceptado", "domicilio.disponible"):
        app.state.log.warning("Evento desconocido ignorado: %s", evento["tipo"])
        return 0
    creadas = 0
    for uid, mensaje in destinos:
        try:
            execute(DB, "INSERT INTO notificaciones (usuario_id, mensaje, evento_id) VALUES (%s,%s,%s)",
                    (uid, mensaje, evento.get("id")))
            creadas += 1
        except pymysql.err.IntegrityError:
            app.state.log.info("Evento %s ya procesado para el usuario %s: se ignora", str(evento.get("id"))[:8], uid)
    app.state.log.info("Evento %s procesado: %s notificación(es) creada(s) [rid=%s]", evento["tipo"], creadas, evento.get("request_id"))
    return creadas


@app.post("/eventos", status_code=201, tags=["Eventos"], summary="Recibir un evento por HTTP (uso interno)",
          description="Mismo procesamiento que el consumidor de RabbitMQ. Lo usan los demás servicios como respaldo "
                      "cuando el broker no está disponible.", responses=errores(400, 401, 403))
def recibir_evento(e: EventoIn, u=Depends(requiere())):
    try:
        return {"ok": True, "creadas": procesar(e.model_dump())}
    except ValueError as ex:
        raise HTTPException(400, str(ex))


@app.post("/notificaciones", status_code=201, tags=["Notificaciones"], summary="Crear una notificación directa (uso interno)",
          responses=errores(401, 403))
def crear(n: NotifIn, u=Depends(requiere())):
    nid, _ = execute(DB, "INSERT INTO notificaciones (usuario_id, mensaje) VALUES (%s,%s)", (n.usuario_id, n.mensaje))
    return {"id": nid}


@app.get("/notificaciones/usuario/{uid}", tags=["Notificaciones"], summary="Últimos 20 avisos de un usuario",
         description="Cada usuario solo ve los suyos; el ADMIN puede ver los de cualquiera.", responses=errores(401, 403))
def de_usuario(uid: int, u=Depends(requiere("CLIENTE", "REPARTIDOR", "ADMIN"))):
    if u["rol"] != "ADMIN" and u["id"] != uid:
        raise HTTPException(403, "No tienes permiso para esta acción")
    return query(DB, "SELECT id, usuario_id, mensaje, leido, created_at FROM notificaciones "
                     "WHERE usuario_id=%s ORDER BY id DESC LIMIT 20", (uid,))


@app.patch("/notificaciones/usuario/{uid}/leidas", tags=["Notificaciones"], summary="Marcar todos mis avisos como leídos",
           responses=errores(401, 403))
def marcar_todas(uid: int, u=Depends(requiere("CLIENTE", "REPARTIDOR", "ADMIN"))):
    if u["rol"] != "ADMIN" and u["id"] != uid:
        raise HTTPException(403, "No tienes permiso para esta acción")
    execute(DB, "UPDATE notificaciones SET leido=TRUE WHERE usuario_id=%s AND leido=FALSE", (uid,))
    return {"ok": True}


@app.patch("/notificaciones/{nid}/leido", tags=["Notificaciones"], summary="Marcar un aviso como leído",
           responses=errores(401, 403, 404))
def marcar_leido(nid: int, u=Depends(requiere("CLIENTE", "REPARTIDOR", "ADMIN"))):
    n = query(DB, "SELECT usuario_id FROM notificaciones WHERE id=%s", (nid,), one=True)
    if not n:
        raise HTTPException(404, "Notificación no encontrada")
    if u["rol"] != "ADMIN" and n["usuario_id"] != u["id"]:
        raise HTTPException(403, "No tienes permiso para esta acción")
    execute(DB, "UPDATE notificaciones SET leido=TRUE WHERE id=%s", (nid,))
    return {"ok": True}
