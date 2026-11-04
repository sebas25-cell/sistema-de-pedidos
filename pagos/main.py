from typing import Optional

from fastapi import Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from common import config
from common.app import create_app, detalle_error, errores, llamar
from common.auth import requiere
from common.db import query, execute

DB = "db_pagos"
PEDIDOS = config.url("pedidos")
METODOS = ("EFECTIVO", "TARJETA", "NEQUI")

app = create_app(
    "pagos",
    db=DB,
    descripcion=(
        "**Responsabilidad:** registrar y controlar el pago de cada pedido. El **monto lo define el pedido** (se "
        "consulta al servicio de pedidos), nunca quien llama. TARJETA y NEQUI se aprueban de forma simulada y "
        "confirman el pedido; el EFECTIVO queda `PENDIENTE` y se cobra al entregar.\n\n"
        "**Datos propios:** base `db_pagos`, tabla `pagos`. Estados: `PENDIENTE`, `PAGADO`, `FALLIDO`, `REEMBOLSADO`.\n\n"
        "Las operaciones de creación, cobro y anulación son de **uso interno** (las invoca el servicio de pedidos)."),
    tags=[
        {"name": "Pagos", "description": "Consulta y gestión de pagos."},
        {"name": "Uso interno", "description": "Operaciones que invoca el servicio de pedidos."},
        {"name": "Monitoreo", "description": "Salud y métricas del servicio."},
    ],
)


class PagoIn(BaseModel):
    pedido_id: int
    metodo: str = Field(description="EFECTIVO, TARJETA o NEQUI")
    monto: Optional[float] = Field(default=None, description="Opcional: si viene, debe coincidir con el total del pedido")
    model_config = ConfigDict(json_schema_extra={"examples": [{"pedido_id": 1, "metodo": "TARJETA"}]})


class CambioEstado(BaseModel):
    estado: str


class PagoOut(BaseModel):
    id: int
    estado: str


def confirmar_pedido(pedido_id):
    llamar("PATCH", f"{PEDIDOS}/pedidos/{pedido_id}/estado", json={"estado": "CONFIRMADO"})


@app.post("/pagos", status_code=201, response_model=PagoOut, tags=["Uso interno"], summary="Registrar el pago de un pedido",
          description="Consulta el pedido por API, toma su total como monto y registra el pago. Es **idempotente**: "
                      "si ya existe un pago vigente del pedido lo devuelve. Con TARJETA/NEQUI el pago queda `PAGADO` y "
                      "pide al servicio de pedidos pasar a `CONFIRMADO`.",
          responses=errores(400, 401, 403, 404, 409, 502, 503))
def crear_pago(p: PagoIn, u=Depends(requiere("ADMIN"))):
    log = app.state.log
    if p.metodo not in METODOS:
        raise HTTPException(400, "Método inválido")

    # El monto lo define el pedido, nunca quien llama
    r = llamar("GET", f"{PEDIDOS}/pedidos/{p.pedido_id}")
    if r is None:
        raise HTTPException(503, "Servicio de pedidos no disponible")
    if r.status_code != 200:
        raise HTTPException(r.status_code if r.status_code == 404 else 502, detalle_error(r, "Pedido no encontrado"))
    pedido = r.json()
    total = float(pedido["total"])
    if p.monto is not None and abs(p.monto - total) > 0.005:
        log.warning("Pago rechazado: monto %s no coincide con el total %s del pedido %s", p.monto, total, p.pedido_id)
        raise HTTPException(400, "El monto no coincide con el total del pedido")

    existente = query(DB, "SELECT * FROM pagos WHERE pedido_id=%s AND estado<>'FALLIDO'", (p.pedido_id,), one=True)
    if existente:
        return {"id": existente["id"], "estado": existente["estado"]}
    if pedido["estado"] != "CREADO":
        raise HTTPException(409, "Solo se puede pagar un pedido recién creado")

    # TARJETA y NEQUI se aprueban de forma simulada; EFECTIVO queda pendiente (se cobra al entregar)
    estado = "PENDIENTE" if p.metodo == "EFECTIVO" else "PAGADO"
    pid, _ = execute(DB, "INSERT INTO pagos (pedido_id, monto, metodo, estado) VALUES (%s,%s,%s,%s)",
                     (p.pedido_id, total, p.metodo, estado))
    log.info("Pago %s del pedido %s: %s %s por %s", pid, p.pedido_id, p.metodo, estado, total)
    if estado == "PAGADO":
        confirmar_pedido(p.pedido_id)
    return {"id": pid, "estado": estado}


@app.get("/pagos/pedido/{pedido_id}", tags=["Pagos"], summary="Pagos de un pedido (ADMIN)", responses=errores(401, 403))
def pagos_de_pedido(pedido_id: int, u=Depends(requiere("ADMIN"))):
    return query(DB, "SELECT * FROM pagos WHERE pedido_id=%s", (pedido_id,))


@app.patch("/pagos/pedido/{pedido_id}/cobrar", tags=["Uso interno"], summary="Cobrar el efectivo al entregar",
           description="El pago en efectivo `PENDIENTE` pasa a `PAGADO`. Lo invoca pedidos al marcar ENTREGADO.",
           responses=errores(401, 403))
def cobrar(pedido_id: int, u=Depends(requiere("ADMIN"))):
    execute(DB, "UPDATE pagos SET estado='PAGADO' WHERE pedido_id=%s AND estado='PENDIENTE'", (pedido_id,))
    return {"ok": True}


@app.patch("/pagos/pedido/{pedido_id}/anular", tags=["Uso interno"], summary="Anular el pago de un pedido cancelado",
           description="Compensación: lo `PENDIENTE` queda `FALLIDO` y lo `PAGADO` queda `REEMBOLSADO` (simulado).",
           responses=errores(401, 403))
def anular(pedido_id: int, u=Depends(requiere("ADMIN"))):
    execute(DB, "UPDATE pagos SET estado=IF(estado='PAGADO','REEMBOLSADO','FALLIDO') "
                "WHERE pedido_id=%s AND estado IN ('PENDIENTE','PAGADO')", (pedido_id,))
    app.state.log.info("Pagos del pedido %s anulados", pedido_id)
    return {"ok": True}


@app.patch("/pagos/{pago_id}/estado", response_model=PagoOut, tags=["Pagos"], summary="Cambiar el estado de un pago (ADMIN)",
           responses=errores(400, 401, 403, 404))
def cambiar_estado(pago_id: int, d: CambioEstado, u=Depends(requiere("ADMIN"))):
    if d.estado not in ("PENDIENTE", "PAGADO", "FALLIDO", "REEMBOLSADO"):
        raise HTTPException(400, "Estado inválido")
    pago = query(DB, "SELECT * FROM pagos WHERE id=%s", (pago_id,), one=True)
    if not pago:
        raise HTTPException(404, "Pago no encontrado")
    execute(DB, "UPDATE pagos SET estado=%s WHERE id=%s", (d.estado, pago_id))
    return {"id": pago_id, "estado": d.estado}
