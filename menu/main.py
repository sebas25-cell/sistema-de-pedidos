from typing import Optional

from fastapi import Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from common import config
from common.app import create_app, errores, llamar
from common.auth import requiere
from common.db import execute, query

DB = "db_menu"
RESTAURANTES = config.url("restaurantes")
app = create_app(
    "menu",
    db=DB,
    descripcion=(
        "**Responsabilidad:** productos de cada restaurante y su **inventario (stock)**. Expone el menú público, "
        "la gestión del ADMIN y las operaciones atómicas de stock que usa el servicio de pedidos.\n\n"
        "**Datos propios:** base `db_menu`, tabla `productos`. Para validar que un restaurante exista consulta "
        "el servicio **restaurantes** por su API (no comparte tablas)."),
    tags=[
        {"name": "Menú", "description": "Consulta pública de productos."},
        {"name": "Administración", "description": "Gestión de productos y stock (solo ADMIN)."},
        {"name": "Uso interno", "description": "Operaciones de stock que invoca el servicio de pedidos."},
        {"name": "Monitoreo", "description": "Salud y métricas del servicio."},
    ],
)


class ProductoUpd(BaseModel):
    nombre: str = Field(min_length=1, max_length=100)
    categoria: Optional[str] = Field(default=None, max_length=50)
    precio: float = Field(gt=0, lt=100000000)
    stock: int = Field(default=0, ge=0)
    activo: bool = True


class ProductoIn(ProductoUpd):
    restaurante_id: int
    model_config = ConfigDict(json_schema_extra={"examples": [
        {"restaurante_id": 1, "nombre": "Hamburguesa Clásica", "categoria": "Hamburguesas", "precio": 18000,
         "stock": 40, "activo": True}]})


class Cantidad(BaseModel):
    cantidad: int = Field(gt=0)


class ProductoOut(BaseModel):
    id: int
    restaurante_id: int
    nombre: str
    categoria: Optional[str] = None
    precio: float
    stock: int
    activo: int


def _existe(pid):
    p = query(DB, "SELECT * FROM productos WHERE id=%s", (pid,), one=True)
    if not p:
        raise HTTPException(404, "Producto no encontrado")
    return p


@app.get("/productos/restaurante/{rid}", response_model=list[ProductoOut], tags=["Menú"],
         summary="Menú de un restaurante", description="Público. Solo productos activos (los ocultos no se muestran).")
def menu_restaurante(rid: int):
    return query(DB, "SELECT * FROM productos WHERE restaurante_id=%s AND activo=TRUE ORDER BY categoria, nombre", (rid,))


@app.get("/admin/productos/restaurante/{rid}", response_model=list[ProductoOut], tags=["Administración"],
         summary="Menú completo de un restaurante, con productos ocultos (ADMIN)", responses=errores(401, 403))
def menu_completo(rid: int, u=Depends(requiere("ADMIN"))):
    return query(DB, "SELECT * FROM productos WHERE restaurante_id=%s ORDER BY categoria, nombre", (rid,))


@app.get("/productos/{pid}", response_model=ProductoOut, tags=["Menú"], summary="Consultar un producto",
         description="Público. Incluye precio, stock y si está activo.", responses=errores(404))
def producto(pid: int):
    return _existe(pid)


@app.post("/productos", status_code=201, response_model=ProductoOut, tags=["Administración"],
          summary="Crear un producto (ADMIN)",
          description="Valida por API que el restaurante exista.", responses=errores(400, 401, 403, 503))
def crear(d: ProductoIn, u=Depends(requiere("ADMIN"))):
    r = llamar("GET", f"{RESTAURANTES}/restaurantes/{d.restaurante_id}")
    if r is None:
        raise HTTPException(503, "Servicio de restaurantes no disponible")
    if r.status_code != 200:
        raise HTTPException(400, "El restaurante no existe")
    pid, _ = execute(DB, "INSERT INTO productos (restaurante_id, nombre, categoria, precio, stock, activo) "
                         "VALUES (%s,%s,%s,%s,%s,%s)",
                     (d.restaurante_id, d.nombre.strip(), (d.categoria or "").strip() or None, d.precio, d.stock, d.activo))
    app.state.log.info("Producto creado id=%s restaurante=%s stock=%s", pid, d.restaurante_id, d.stock)
    return _existe(pid)


@app.put("/productos/{pid}", response_model=ProductoOut, tags=["Administración"],
         summary="Actualizar un producto (ADMIN)", responses=errores(401, 403, 404))
def actualizar(pid: int, d: ProductoUpd, u=Depends(requiere("ADMIN"))):
    _existe(pid)
    execute(DB, "UPDATE productos SET nombre=%s, categoria=%s, precio=%s, stock=%s, activo=%s WHERE id=%s",
            (d.nombre.strip(), (d.categoria or "").strip() or None, d.precio, d.stock, d.activo, pid))
    return _existe(pid)


@app.delete("/productos/{pid}", tags=["Administración"], summary="Ocultar un producto (ADMIN)",
            description="Baja lógica: deja de mostrarse pero se conserva en los pedidos anteriores.",
            responses=errores(401, 403, 404))
def desactivar(pid: int, u=Depends(requiere("ADMIN"))):
    _existe(pid)
    execute(DB, "UPDATE productos SET activo=FALSE WHERE id=%s", (pid,))
    return {"ok": True}


@app.patch("/productos/{pid}/reponer", tags=["Administración"], summary="Sumar stock",
           description="Reposición manual del ADMIN, o devolución automática que hace el servicio de pedidos "
                       "cuando se cancela un pedido.", responses=errores(401, 403, 404))
def reponer(pid: int, d: Cantidad, u=Depends(requiere("ADMIN"))):
    _existe(pid)
    execute(DB, "UPDATE productos SET stock = stock + %s WHERE id=%s", (d.cantidad, pid))
    return {"ok": True}


@app.patch("/productos/{pid}/descontar", tags=["Uso interno"], summary="Descontar stock (solo servicios internos)",
           description="Atómico: `UPDATE ... WHERE stock >= cantidad`; si no alcanza responde 409 sin tocar nada. "
                       "Solo acepta llamadas firmadas con la clave interna (servicio de pedidos).",
           responses=errores(401, 403, 409))
def descontar(pid: int, d: Cantidad, u=Depends(requiere())):
    _, filas = execute(DB, "UPDATE productos SET stock = stock - %s WHERE id=%s AND stock >= %s AND activo=TRUE",
                       (d.cantidad, pid, d.cantidad))
    if filas == 0:
        app.state.log.warning("Stock insuficiente producto=%s cantidad=%s", pid, d.cantidad)
        raise HTTPException(409, "Stock insuficiente")
    return {"ok": True}
