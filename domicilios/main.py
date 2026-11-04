from fastapi import Depends, HTTPException
from pydantic import BaseModel, ConfigDict

from common import config
from common.app import create_app, detalle_error, errores, llamar
from common.auth import requiere
from common.db import query, execute
from common.mensajeria import publicar

DB = "db_domicilios"
USUARIOS = config.url("usuarios")
PEDIDOS = config.url("pedidos")

# estado del domicilio -> estado que se refleja en el pedido
SIGUIENTE = {"ASIGNADO": "EN_RUTA", "EN_RUTA": "ENTREGADO"}
A_PEDIDO = {"EN_RUTA": "EN_CAMINO", "ENTREGADO": "ENTREGADO"}

app = create_app(
    "domicilios",
    db=DB,
    descripcion=(
        "**Responsabilidad:** reparto. Cuando la cocina marca un pedido `LISTO` crea el domicilio y lo **asigna "
        "automáticamente** al repartidor *disponible* con menos entregas activas; si no hay ninguno, queda en la "
        "**bolsa** de pedidos por aceptar y se avisa a los repartidores. Mueve el domicilio `ASIGNADO → EN_RUTA → "
        "ENTREGADO` y refleja cada paso en el pedido.\n\n"
        "**Datos propios:** base `db_domicilios`, tabla `domicilios`. Para saber quién es repartidor y si está "
        "disponible consulta el servicio **usuarios** por su API (no lee su base de datos).\n\n"
        "**Eventos que publica:** `domicilio.asignado`, `domicilio.aceptado`, `domicilio.disponible`."),
    tags=[
        {"name": "Domicilios", "description": "Consulta, asignación y avance del reparto."},
        {"name": "Repartidor", "description": "Pedidos por aceptar y aceptación (rol REPARTIDOR)."},
        {"name": "Uso interno", "description": "Operaciones que invoca el servicio de pedidos."},
        {"name": "Monitoreo", "description": "Salud y métricas del servicio."},
    ],
)


class DomicilioIn(BaseModel):
    pedido_id: int
    model_config = ConfigDict(json_schema_extra={"examples": [{"pedido_id": 1}]})


class Asignacion(BaseModel):
    repartidor_id: int


def repartidores():
    r = llamar("GET", f"{USUARIOS}/repartidores")
    if r is None or r.status_code != 200:
        return None
    return r.json()


def elegir_repartidor():
    """Repartidor con menos domicilios activos entre los DISPONIBLES. Devuelve None si no hay ninguno."""
    lista = repartidores()
    if not lista:
        return None
    activos = {}
    for fila in query(DB, "SELECT repartidor_id, COUNT(*) n FROM domicilios "
                          "WHERE estado<>'ENTREGADO' AND repartidor_id IS NOT NULL GROUP BY repartidor_id"):
        activos[fila["repartidor_id"]] = fila["n"]
    disponibles = [r for r in lista if r.get("disponible")]
    if not disponibles:
        return None
    return min(disponibles, key=lambda x: activos.get(x["id"], 0))


def cliente_del_pedido(pedido_id):
    r = llamar("GET", f"{PEDIDOS}/pedidos/{pedido_id}")
    if r is not None and r.status_code == 200:
        return r.json()["cliente_id"]
    return None


@app.post("/domicilios", status_code=201, tags=["Uso interno"], summary="Crear el domicilio de un pedido LISTO",
          description="Idempotente. Elige un repartidor disponible; si no hay, el domicilio queda sin repartidor "
                      "(`repartidor_id = null`) y publica `domicilio.disponible` para avisar a los repartidores.",
          responses=errores(401, 403))
def crear(d: DomicilioIn, u=Depends(requiere("ADMIN"))):
    existente = query(DB, "SELECT * FROM domicilios WHERE pedido_id=%s", (d.pedido_id,), one=True)
    if existente:
        return existente
    rep = elegir_repartidor()
    did, _ = execute(DB, "INSERT INTO domicilios (pedido_id, repartidor_id) VALUES (%s,%s)",
                     (d.pedido_id, rep["id"] if rep else None))
    if rep:
        app.state.log.info("Domicilio %s del pedido %s asignado al repartidor %s", did, d.pedido_id, rep["id"])
        publicar("domicilio.asignado", {"pedido_id": d.pedido_id, "cliente_id": cliente_del_pedido(d.pedido_id),
                                        "repartidor_id": rep["id"], "repartidor_nombre": rep["nombre"]})
    else:
        app.state.log.warning("Domicilio %s del pedido %s sin repartidor disponible: queda en la bolsa", did, d.pedido_id)
        publicar("domicilio.disponible", {"pedido_id": d.pedido_id,
                                          "repartidores": [r["id"] for r in (repartidores() or [])]})
    return {"id": did, "pedido_id": d.pedido_id, "repartidor_id": rep["id"] if rep else None, "estado": "ASIGNADO"}


@app.get("/domicilios", tags=["Domicilios"], summary="Domicilios activos (ADMIN)", responses=errores(401, 403))
def activos(u=Depends(requiere("ADMIN"))):
    return query(DB, "SELECT * FROM domicilios WHERE estado<>'ENTREGADO' ORDER BY id")


@app.get("/domicilios/disponibles", tags=["Repartidor"], summary="Pedidos listos por aceptar (REPARTIDOR)",
         description="La bolsa: domicilios sin repartidor que un repartidor disponible puede aceptar.",
         responses=errores(401, 403))
def domicilios_disponibles(u=Depends(requiere("REPARTIDOR"))):
    return query(DB, "SELECT * FROM domicilios WHERE repartidor_id IS NULL AND estado='ASIGNADO' ORDER BY created_at, id")


@app.patch("/domicilios/{did}/aceptar", tags=["Repartidor"], summary="Aceptar un domicilio de la bolsa (REPARTIDOR)",
           description="Exige estar disponible (se consulta al servicio de usuarios). La asignación es un `UPDATE` "
                       "atómico: si dos repartidores aceptan a la vez, solo uno gana y el otro recibe 409.",
           responses=errores(401, 403, 404, 409, 503))
def aceptar(did: int, u=Depends(requiere("REPARTIDOR"))):
    lista = repartidores()
    if lista is None:
        raise HTTPException(503, "Servicio de usuarios no disponible")
    yo = next((r for r in lista if r["id"] == u["id"]), None)
    if not yo or not yo.get("disponible"):
        raise HTTPException(409, "Activa tu disponibilidad antes de aceptar domicilios")
    d = query(DB, "SELECT * FROM domicilios WHERE id=%s", (did,), one=True)
    if not d:
        raise HTTPException(404, "Domicilio no encontrado")
    if d["estado"] != "ASIGNADO" or d["repartidor_id"] is not None:
        raise HTTPException(409, "Otro repartidor ya tomó este domicilio")
    _, filas = execute(DB, "UPDATE domicilios SET repartidor_id=%s WHERE id=%s AND repartidor_id IS NULL AND estado='ASIGNADO'",
                       (u["id"], did))
    if filas == 0:
        raise HTTPException(409, "Otro repartidor ya tomó este domicilio. Actualiza la lista.")
    app.state.log.info("Domicilio %s aceptado por el repartidor %s", did, u["id"])
    publicar("domicilio.aceptado", {"pedido_id": d["pedido_id"], "cliente_id": cliente_del_pedido(d["pedido_id"]),
                                    "repartidor_id": u["id"], "repartidor_nombre": yo["nombre"]})
    return {"ok": True, "id": did, "pedido_id": d["pedido_id"], "repartidor_id": u["id"]}


@app.get("/domicilios/pedido/{pedido_id}", tags=["Domicilios"], summary="Domicilio de un pedido (ADMIN, REPARTIDOR)",
         description="Un REPARTIDOR solo puede ver los domicilios que le pertenecen.", responses=errores(401, 403, 404))
def por_pedido(pedido_id: int, u=Depends(requiere("ADMIN", "REPARTIDOR"))):
    d = query(DB, "SELECT * FROM domicilios WHERE pedido_id=%s", (pedido_id,), one=True)
    if not d:
        raise HTTPException(404, "Domicilio no encontrado")
    if u["rol"] == "REPARTIDOR" and d["repartidor_id"] != u["id"]:
        raise HTTPException(403, "Ese domicilio no es tuyo")
    return d


@app.get("/domicilios/repartidor/{rid}", tags=["Domicilios"], summary="Domicilios activos de un repartidor",
         description="Un REPARTIDOR solo puede consultar los suyos.", responses=errores(401, 403))
def por_repartidor(rid: int, u=Depends(requiere("ADMIN", "REPARTIDOR"))):
    if u["rol"] == "REPARTIDOR" and u["id"] != rid:
        raise HTTPException(403, "No tienes permiso para esta acción")
    return query(DB, "SELECT * FROM domicilios WHERE repartidor_id=%s AND estado<>'ENTREGADO' ORDER BY id", (rid,))


@app.patch("/domicilios/{did}/asignar", tags=["Domicilios"], summary="Asignar o reasignar repartidor (ADMIN)",
           description="Solo antes de que el domicilio salga a ruta.", responses=errores(400, 401, 403, 404, 409))
def asignar(did: int, a: Asignacion, u=Depends(requiere("ADMIN"))):
    d = query(DB, "SELECT * FROM domicilios WHERE id=%s", (did,), one=True)
    if not d:
        raise HTTPException(404, "Domicilio no encontrado")
    if d["estado"] != "ASIGNADO":
        raise HTTPException(409, "Solo se puede reasignar antes de que salga a ruta")
    rep = next((x for x in (repartidores() or []) if x["id"] == a.repartidor_id), None)
    if not rep:
        raise HTTPException(400, "Ese repartidor no existe")
    execute(DB, "UPDATE domicilios SET repartidor_id=%s WHERE id=%s", (a.repartidor_id, did))
    app.state.log.info("Domicilio %s reasignado al repartidor %s", did, a.repartidor_id)
    publicar("domicilio.asignado", {"pedido_id": d["pedido_id"], "cliente_id": cliente_del_pedido(d["pedido_id"]),
                                    "repartidor_id": rep["id"], "repartidor_nombre": rep["nombre"]})
    return {"id": did, "repartidor_id": a.repartidor_id}


@app.patch("/domicilios/{did}/avanzar", tags=["Domicilios"], summary="Avanzar el domicilio (REPARTIDOR dueño o ADMIN)",
           description="`ASIGNADO → EN_RUTA` (el pedido pasa a `EN_CAMINO`) y `EN_RUTA → ENTREGADO` (el pedido pasa a "
                       "`ENTREGADO`). Si el servicio de pedidos rechaza el cambio, se **deshace** el del domicilio para "
                       "que ambos servicios sigan coherentes.", responses=errores(401, 403, 404, 409, 502, 503))
def avanzar(did: int, u=Depends(requiere("ADMIN", "REPARTIDOR"))):
    d = query(DB, "SELECT * FROM domicilios WHERE id=%s", (did,), one=True)
    if not d:
        raise HTTPException(404, "Domicilio no encontrado")
    if u["rol"] == "REPARTIDOR" and d["repartidor_id"] != u["id"]:
        raise HTTPException(403, "Ese domicilio no es tuyo")
    nuevo = SIGUIENTE.get(d["estado"])
    if not nuevo:
        raise HTTPException(409, "El domicilio ya fue entregado")

    _, filas = execute(DB, "UPDATE domicilios SET estado=%s WHERE id=%s AND estado=%s", (nuevo, did, d["estado"]))
    if filas == 0:
        raise HTTPException(409, "El domicilio ya cambió de estado, actualiza e intenta de nuevo")
    r = llamar("PATCH", f"{PEDIDOS}/pedidos/{d['pedido_id']}/estado", json={"estado": A_PEDIDO[nuevo]})
    if r is None or r.status_code != 200:
        # El pedido no aceptó el cambio: se deshace para que ambos servicios sigan coherentes
        execute(DB, "UPDATE domicilios SET estado=%s WHERE id=%s", (d["estado"], did))
        app.state.log.error("Domicilio %s: el pedido %s rechazó pasar a %s; cambio revertido", did, d["pedido_id"], A_PEDIDO[nuevo])
        if r is None:
            raise HTTPException(503, "Servicio de pedidos no disponible")
        raise HTTPException(409 if r.status_code == 409 else 502, detalle_error(r, "El pedido no pudo avanzar"))
    app.state.log.info("Domicilio %s: %s -> %s", did, d["estado"], nuevo)
    return {"id": did, "estado": nuevo}


@app.delete("/domicilios/pedido/{pedido_id}", tags=["Uso interno"], summary="Liberar el domicilio de un pedido cancelado",
            description="Solo lo usa el servicio de pedidos cuando se cancela un pedido ya asignado.",
            responses=errores(401, 403))
def eliminar(pedido_id: int, u=Depends(requiere())):
    execute(DB, "DELETE FROM domicilios WHERE pedido_id=%s AND estado<>'ENTREGADO'", (pedido_id,))
    return {"ok": True}
