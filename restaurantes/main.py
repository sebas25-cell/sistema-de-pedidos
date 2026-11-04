from typing import Optional

from fastapi import Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from common.app import create_app, errores
from common.auth import requiere
from common.db import execute, query

DB = "db_restaurantes"
app = create_app(
    "restaurantes",
    db=DB,
    descripcion=(
        "**Responsabilidad:** catálogo de restaurantes. Los clientes consultan los activos; el ADMIN los crea, "
        "edita, activa o desactiva (baja lógica, para conservar el historial de pedidos).\n\n"
        "**Datos propios:** base `db_restaurantes`, tabla `restaurantes`. El menú de cada restaurante vive en el "
        "servicio **menu**, que consulta aquí solo para validar que el restaurante exista."),
    tags=[
        {"name": "Restaurantes", "description": "Consulta pública del catálogo."},
        {"name": "Administración", "description": "Gestión del catálogo (solo ADMIN)."},
        {"name": "Monitoreo", "description": "Salud y métricas del servicio."},
    ],
)


class RestauranteIn(BaseModel):
    nombre: str = Field(min_length=1, max_length=100)
    direccion: str = Field(default="", max_length=200)
    telefono: Optional[str] = Field(default=None, max_length=30)
    activo: bool = True
    model_config = ConfigDict(json_schema_extra={"examples": [
        {"nombre": "Burger del Sinú", "direccion": "Calle 27 #3-45, Montería", "telefono": "3001234567", "activo": True}]})


class RestauranteOut(BaseModel):
    id: int
    nombre: str
    direccion: str
    telefono: Optional[str] = None
    activo: int


def _existe(rid):
    r = query(DB, "SELECT * FROM restaurantes WHERE id=%s", (rid,), one=True)
    if not r:
        raise HTTPException(404, "Restaurante no encontrado")
    return r


@app.get("/restaurantes", response_model=list[RestauranteOut], tags=["Restaurantes"],
         summary="Listar restaurantes activos", description="Público. Solo devuelve los restaurantes activos.")
def listar():
    return query(DB, "SELECT * FROM restaurantes WHERE activo=TRUE ORDER BY nombre")


@app.get("/restaurantes/{rid}", response_model=RestauranteOut, tags=["Restaurantes"],
         summary="Consultar un restaurante",
         description="Público. Devuelve el restaurante aunque esté inactivo (el servicio de pedidos lo usa para "
                     "validar que esté recibiendo pedidos).", responses=errores(404))
def detalle(rid: int):
    return _existe(rid)


@app.get("/admin/restaurantes", response_model=list[RestauranteOut], tags=["Administración"],
         summary="Listar todos los restaurantes, incluidos los inactivos (ADMIN)", responses=errores(401, 403))
def listar_todos(u=Depends(requiere("ADMIN"))):
    return query(DB, "SELECT * FROM restaurantes ORDER BY nombre")


@app.post("/restaurantes", status_code=201, response_model=RestauranteOut, tags=["Administración"],
          summary="Crear un restaurante (ADMIN)", responses=errores(401, 403))
def crear(d: RestauranteIn, u=Depends(requiere("ADMIN"))):
    rid, _ = execute(DB, "INSERT INTO restaurantes (nombre, direccion, telefono, activo) VALUES (%s,%s,%s,%s)",
                     (d.nombre.strip(), d.direccion.strip(), d.telefono, d.activo))
    app.state.log.info("Restaurante creado id=%s nombre=%s", rid, d.nombre)
    return _existe(rid)


@app.put("/restaurantes/{rid}", response_model=RestauranteOut, tags=["Administración"],
         summary="Actualizar un restaurante (ADMIN)", responses=errores(401, 403, 404))
def actualizar(rid: int, d: RestauranteIn, u=Depends(requiere("ADMIN"))):
    _existe(rid)
    execute(DB, "UPDATE restaurantes SET nombre=%s, direccion=%s, telefono=%s, activo=%s WHERE id=%s",
            (d.nombre.strip(), d.direccion.strip(), d.telefono, d.activo, rid))
    app.state.log.info("Restaurante actualizado id=%s activo=%s", rid, d.activo)
    return _existe(rid)


@app.delete("/restaurantes/{rid}", tags=["Administración"], summary="Desactivar un restaurante (ADMIN)",
            description="Baja lógica: deja de mostrarse y de recibir pedidos, pero se conserva su historial.",
            responses=errores(401, 403, 404))
def desactivar(rid: int, u=Depends(requiere("ADMIN"))):
    _existe(rid)
    execute(DB, "UPDATE restaurantes SET activo=FALSE WHERE id=%s", (rid,))
    app.state.log.info("Restaurante desactivado id=%s", rid)
    return {"ok": True}
