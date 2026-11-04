from typing import List, Optional

from fastapi import Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from common import config
from common.app import create_app, errores, llamar
from common.auth import requiere
from common.db import get_conn, query, execute
from common.mensajeria import publicar

DB = "db_pedidos"
RESTAURANTES = config.url("restaurantes")
MENU = config.url("menu")
PAGOS = config.url("pagos")
DOMICILIOS = config.url("domicilios")

ESTADOS = ["CREADO", "CONFIRMADO", "EN_COCINA", "LISTO", "EN_CAMINO", "ENTREGADO"]
# Los dos últimos pasos los mueve el repartidor desde el servicio de domicilios
SOLO_SISTEMA = ("EN_CAMINO", "ENTREGADO")
CANCELABLE_CLIENTE = ("CREADO", "CONFIRMADO")
CANCELABLE_ADMIN = ("CREADO", "CONFIRMADO", "EN_COCINA", "LISTO")

app = create_app(
    "pedidos",
    db=DB,
    descripcion=(
        "**Responsabilidad:** ciclo de vida del pedido. Valida restaurante y productos (los **precios los pone el "
        "servidor**), reserva el stock, guarda pedido y detalle, dispara el pago, controla la máquina de estados "
        "`CREADO → CONFIRMADO → EN_COCINA → LISTO → EN_CAMINO → ENTREGADO` (o `CANCELADO`) y publica un evento "
        "`pedido.estado_cambiado` en RabbitMQ por cada cambio.\n\n"
        "**Datos propios:** base `db_pedidos`, tablas `pedidos` y `detalle_pedido`.\n\n"
        "**Se comunica con:** restaurantes, menu y pagos (HTTP síncrono, porque necesita la respuesta al instante) y "
        "con notificaciones (evento asíncrono). Si algo falla a mitad de la creación, deshace el stock y cancela."),
    tags=[
        {"name": "Pedidos", "description": "Crear, consultar y cancelar pedidos."},
        {"name": "Cocina", "description": "Cambio de estado (ADMIN) y resumen para el tablero."},
        {"name": "Monitoreo", "description": "Salud y métricas del servicio."},
    ],
)


class Item(BaseModel):
    producto_id: int
    cantidad: int = Field(gt=0, le=100)


class PedidoIn(BaseModel):
    cliente_id: Optional[int] = Field(default=None, description="Solo lo usa un ADMIN; el cliente siempre es quien tiene la sesión")
    restaurante_id: int
    direccion: str = Field(max_length=255)
    metodo_pago: str = Field(default="EFECTIVO", description="EFECTIVO, TARJETA o NEQUI")
    items: List[Item]
    model_config = ConfigDict(json_schema_extra={"examples": [{
        "restaurante_id": 1, "direccion": "Calle 30 #5-20, Montería", "metodo_pago": "TARJETA",
        "items": [{"producto_id": 1, "cantidad": 2}, {"producto_id": 6, "cantidad": 1}]}]})


class CambioEstado(BaseModel):
    estado: str = Field(description="Estado siguiente en la secuencia")
    model_config = ConfigDict(json_schema_extra={"examples": [{"estado": "CONFIRMADO"}]})


class PedidoCreado(BaseModel):
    id: int
    total: float
    estado: str


class EstadoOut(BaseModel):
    id: int
    estado: str


def evento_estado(cliente_id, pid, estado):
    """Publica el evento de dominio; notificaciones lo convierte en el aviso para el cliente."""
    publicar("pedido.estado_cambiado", {"pedido_id": pid, "cliente_id": cliente_id, "estado": estado})


def reponer(lineas):
    """Devuelve stock al menú. lineas = [(producto_id, cantidad), ...]"""
    for prod_id, cant in lineas:
        llamar("PATCH", f"{MENU}/productos/{prod_id}/reponer", json={"cantidad": cant})


def cargar_pedido(pid):
    ped = query(DB, "SELECT * FROM pedidos WHERE id=%s", (pid,), one=True)
    if not ped:
        raise HTTPException(404, "Pedido no encontrado")
    return ped


def verificar_acceso(ped, u):
    if u["rol"] == "CLIENTE" and ped["cliente_id"] != u["id"]:
        raise HTTPException(403, "Ese pedido no es tuyo")


# ---------------------------------------------------------------- crear
@app.post("/pedidos", status_code=201, response_model=PedidoCreado, tags=["Pedidos"],
          summary="Crear un pedido",
          description="Flujo: 1) valida restaurante activo, 2) valida productos y calcula el total con los precios del "
                      "servidor, 3) **reserva el stock** (atómico), 4) guarda pedido y detalle en una transacción, "
                      "5) publica el evento `CREADO`, 6) pide el pago al servicio de pagos. Con TARJETA/NEQUI el pago "
                      "se aprueba y el pedido queda `CONFIRMADO`; con EFECTIVO queda `CREADO`.\n\n"
                      "Si el pago no puede procesarse, el pedido se cancela y el stock se devuelve.",
          responses=errores(400, 401, 403, 409, 503))
def crear_pedido(p: PedidoIn, u=Depends(requiere("CLIENTE", "ADMIN"))):
    log = app.state.log
    cliente_id = u["id"] if u["rol"] == "CLIENTE" else p.cliente_id
    if not cliente_id:
        raise HTTPException(400, "Falta el cliente del pedido")
    direccion = p.direccion.strip()
    if len(direccion) < 5:
        raise HTTPException(400, "Escribe una dirección de entrega válida")
    if not p.items:
        raise HTTPException(400, "El pedido no tiene productos")
    if p.metodo_pago not in ("EFECTIVO", "TARJETA", "NEQUI"):
        raise HTTPException(400, "Método de pago inválido")

    # 0. El restaurante debe existir y estar activo
    r = llamar("GET", f"{RESTAURANTES}/restaurantes/{p.restaurante_id}")
    if r is None:
        raise HTTPException(503, "Servicio de restaurantes no disponible")
    if r.status_code != 200:
        raise HTTPException(400, "El restaurante no existe")
    if not r.json().get("activo"):
        raise HTTPException(409, "Ese restaurante no está recibiendo pedidos")

    # 1. Validar productos contra el servicio de menú; el precio lo pone el servidor, no el cliente
    cantidades = {}
    for it in p.items:                     # si repiten un producto se suman
        cantidades[it.producto_id] = cantidades.get(it.producto_id, 0) + it.cantidad
    lineas, total = [], 0.0                # lineas = (producto_id, nombre, cantidad, precio)
    for prod_id, cant in cantidades.items():
        r = llamar("GET", f"{MENU}/productos/{prod_id}")
        if r is None:
            raise HTTPException(503, "Servicio de menú no disponible")
        if r.status_code != 200:
            raise HTTPException(400, f"Producto {prod_id} no existe")
        prod = r.json()
        if prod["restaurante_id"] != p.restaurante_id:
            raise HTTPException(400, f"{prod['nombre']} no pertenece a este restaurante")
        if not prod.get("activo"):
            raise HTTPException(409, f"{prod['nombre']} ya no está disponible")
        precio = float(prod["precio"])
        lineas.append((prod_id, prod["nombre"], cant, precio))
        total += precio * cant
    total = round(total, 2)

    # 2. Reservar el stock (cada descuento es atómico); si algo falla se devuelve lo ya descontado
    descontados = []
    for prod_id, nombre, cant, _ in lineas:
        r = llamar("PATCH", f"{MENU}/productos/{prod_id}/descontar", json={"cantidad": cant})
        if r is None or r.status_code != 200:
            reponer(descontados)
            if r is None:
                raise HTTPException(503, "Servicio de menú no disponible")
            if r.status_code == 409:
                log.warning("Pedido rechazado por stock insuficiente de %s (cliente=%s)", nombre, cliente_id)
                raise HTTPException(409, f"Stock insuficiente de {nombre}")
            raise HTTPException(502, "No se pudo reservar el stock")
        descontados.append((prod_id, cant))

    # 3. Guardar pedido y detalle en una sola transacción
    conn = get_conn(DB)
    try:
        with conn.cursor() as c:
            c.execute("INSERT INTO pedidos (cliente_id, restaurante_id, total, direccion) VALUES (%s,%s,%s,%s)",
                      (cliente_id, p.restaurante_id, total, direccion))
            pid = c.lastrowid
            c.executemany("INSERT INTO detalle_pedido (pedido_id, producto_id, nombre, cantidad, precio) "
                          "VALUES (%s,%s,%s,%s,%s)",
                          [(pid, a, n, b, pr) for a, n, b, pr in lineas])
        conn.commit()
    except Exception:
        conn.rollback()
        reponer(descontados)
        log.error("No se pudo guardar el pedido del cliente %s; stock devuelto", cliente_id, exc_info=True)
        raise HTTPException(500, "No se pudo guardar el pedido")
    finally:
        conn.close()

    log.info("Pedido %s creado cliente=%s restaurante=%s total=%s pago=%s", pid, cliente_id, p.restaurante_id, total, p.metodo_pago)
    evento_estado(cliente_id, pid, "CREADO")

    # 4. Registrar el pago (pagos valida el monto contra este pedido). Si falla, se deshace todo.
    r = llamar("POST", f"{PAGOS}/pagos", json={"pedido_id": pid, "metodo": p.metodo_pago})
    if r is None or r.status_code not in (200, 201):
        execute(DB, "UPDATE pedidos SET estado='CANCELADO' WHERE id=%s", (pid,))
        reponer(descontados)
        evento_estado(cliente_id, pid, "CANCELADO")
        log.error("Pedido %s cancelado: el pago no pudo procesarse", pid)
        raise HTTPException(503, "No se pudo procesar el pago, tu pedido fue cancelado. Intenta de nuevo.")

    estado = query(DB, "SELECT estado FROM pedidos WHERE id=%s", (pid,), one=True)["estado"]
    return {"id": pid, "total": total, "estado": estado}


# ---------------------------------------------------------------- consultas
@app.get("/pedidos", tags=["Pedidos"], summary="Listar pedidos",
         description="Un CLIENTE solo ve los suyos; un ADMIN puede filtrar por `cliente_id`, `estado` o `activos` "
                     "(los que no están ENTREGADO ni CANCELADO). Cada pedido incluye `unidades`.",
         responses=errores(401, 403))
def listar(cliente_id: Optional[int] = None, estado: Optional[str] = None, activos: bool = False,
           limit: int = Query(200, ge=1, le=500), u=Depends(requiere("CLIENTE", "ADMIN"))):
    if u["rol"] == "CLIENTE":
        cliente_id = u["id"]                       # un cliente solo ve lo suyo
    sql = ("SELECT p.*, (SELECT CAST(COALESCE(SUM(d.cantidad),0) AS SIGNED) FROM detalle_pedido d "
           "WHERE d.pedido_id=p.id) AS unidades FROM pedidos p")
    params, cond = [], []
    if cliente_id is not None:
        cond.append("p.cliente_id=%s"); params.append(cliente_id)
    if estado:
        cond.append("p.estado=%s"); params.append(estado)
    if activos:
        cond.append("p.estado NOT IN ('ENTREGADO','CANCELADO')")
    if cond:
        sql += " WHERE " + " AND ".join(cond)
    return query(DB, sql + " ORDER BY p.id DESC LIMIT %s", tuple(params) + (limit,))


# (declarada antes de /pedidos/{pid} para que "resumen" no se confunda con un id)
@app.get("/pedidos/resumen", tags=["Cocina"], summary="Resumen para el tablero (ADMIN)",
         description="Pedidos activos y entregados/cancelados hoy.", responses=errores(401, 403))
def resumen(u=Depends(requiere("ADMIN"))):
    return query(DB, "SELECT "
                     "CAST(COALESCE(SUM(estado NOT IN ('ENTREGADO','CANCELADO')),0) AS SIGNED) AS activos, "
                     "CAST(COALESCE(SUM(estado='ENTREGADO' AND DATE(created_at)=CURDATE()),0) AS SIGNED) AS entregados_hoy, "
                     "CAST(COALESCE(SUM(estado='CANCELADO' AND DATE(created_at)=CURDATE()),0) AS SIGNED) AS cancelados_hoy "
                     "FROM pedidos", one=True)


@app.get("/pedidos/{pid}", tags=["Pedidos"], summary="Consultar un pedido con su detalle",
         description="Un CLIENTE solo puede ver sus propios pedidos. Incluye la lista `items`.",
         responses=errores(401, 403, 404))
def detalle(pid: int, u=Depends(requiere("CLIENTE", "ADMIN", "REPARTIDOR"))):
    ped = cargar_pedido(pid)
    verificar_acceso(ped, u)
    ped["items"] = query(DB, "SELECT * FROM detalle_pedido WHERE pedido_id=%s", (pid,))
    return ped


# ---------------------------------------------------------------- estados
@app.patch("/pedidos/{pid}/estado", response_model=EstadoOut, tags=["Cocina"], summary="Avanzar el estado (ADMIN)",
           description="Solo permite pasar al estado **siguiente**. `EN_CAMINO` y `ENTREGADO` los mueve el servicio de "
                       "domicilios cuando el repartidor avanza (403 si otro intenta). Al pasar a `LISTO` se crea el "
                       "domicilio; al `ENTREGADO` se cobra el efectivo. Publica el evento `pedido.estado_cambiado`.",
           responses=errores(400, 401, 403, 404, 409))
def cambiar_estado(pid: int, d: CambioEstado, u=Depends(requiere("ADMIN"))):
    ped = cargar_pedido(pid)
    if d.estado not in ESTADOS:
        raise HTTPException(400, "Estado inválido")
    if ped["estado"] not in ESTADOS:
        raise HTTPException(409, f"El pedido está {ped['estado'].lower()} y ya no puede cambiar")
    if d.estado in SOLO_SISTEMA and u["rol"] != "SISTEMA":
        raise HTTPException(403, "Ese paso lo gestiona el repartidor desde domicilios")
    # Solo se permite avanzar al estado siguiente
    if ESTADOS.index(d.estado) != ESTADOS.index(ped["estado"]) + 1:
        raise HTTPException(409, f"No se puede pasar de {ped['estado']} a {d.estado}")

    # Cambio atómico: solo se aplica si nadie más movió el pedido entre la lectura y la escritura
    _, filas = execute(DB, "UPDATE pedidos SET estado=%s WHERE id=%s AND estado=%s", (d.estado, pid, ped["estado"]))
    if filas == 0:
        raise HTTPException(409, "El pedido cambió de estado, actualiza e intenta de nuevo")
    app.state.log.info("Pedido %s: %s -> %s", pid, ped["estado"], d.estado)
    evento_estado(ped["cliente_id"], pid, d.estado)

    if d.estado == "LISTO":          # se crea el domicilio y se asigna repartidor
        llamar("POST", f"{DOMICILIOS}/domicilios", json={"pedido_id": pid})
    elif d.estado == "ENTREGADO":    # el efectivo se cobra al entregar
        llamar("PATCH", f"{PAGOS}/pagos/pedido/{pid}/cobrar")
    return {"id": pid, "estado": d.estado}


@app.post("/pedidos/{pid}/cancelar", response_model=EstadoOut, tags=["Pedidos"], summary="Cancelar un pedido",
          description="El CLIENTE puede cancelar mientras esté `CREADO` o `CONFIRMADO`; el ADMIN hasta `LISTO`. "
                      "Compensa: devuelve el stock, anula el pago y libera el domicilio, y avisa al cliente.",
          responses=errores(401, 403, 404, 409))
def cancelar(pid: int, u=Depends(requiere("CLIENTE", "ADMIN"))):
    ped = cargar_pedido(pid)
    verificar_acceso(ped, u)
    permitidos = CANCELABLE_CLIENTE if u["rol"] == "CLIENTE" else CANCELABLE_ADMIN
    if ped["estado"] not in permitidos:
        raise HTTPException(409, f"Un pedido {ped['estado'].lower().replace('_', ' ')} ya no se puede cancelar")
    _, filas = execute(DB, "UPDATE pedidos SET estado='CANCELADO' WHERE id=%s AND estado=%s", (pid, ped["estado"]))
    if filas == 0:
        raise HTTPException(409, "El pedido cambió de estado, actualiza e intenta de nuevo")
    items = query(DB, "SELECT producto_id, cantidad FROM detalle_pedido WHERE pedido_id=%s", (pid,))
    reponer([(i["producto_id"], i["cantidad"]) for i in items])
    llamar("PATCH", f"{PAGOS}/pagos/pedido/{pid}/anular")
    llamar("DELETE", f"{DOMICILIOS}/domicilios/pedido/{pid}")
    app.state.log.info("Pedido %s cancelado por %s (%s)", pid, u["rol"], ped["estado"])
    evento_estado(ped["cliente_id"], pid, "CANCELADO")
    return {"id": pid, "estado": "CANCELADO"}
