import re
import time

import bcrypt
import pymysql
from fastapi import Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from common.app import create_app, errores
from common.auth import crear_token, requiere
from common.db import execute, query

DB = "db_usuarios"
ROLES = ("CLIENTE", "ADMIN", "REPARTIDOR")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

app = create_app(
    "usuarios",
    db=DB,
    descripcion=(
        "**Responsabilidad:** identidad y acceso del sistema. Registra clientes, autentica a cualquier usuario y "
        "emite el **token JWT** que usan los demás servicios; administra el personal (admins y repartidores) y la "
        "**disponibilidad** de los repartidores.\n\n"
        "**Datos propios:** base `db_usuarios`, tabla `usuarios`. Ningún otro servicio accede a ella: "
        "los demás consultan este servicio por su API.\n\n"
        "**Roles:** `CLIENTE`, `REPARTIDOR`, `ADMIN`."),
    tags=[
        {"name": "Autenticación", "description": "Registro público y login (devuelve el JWT)."},
        {"name": "Usuarios", "description": "Consulta de un usuario y administración del personal."},
        {"name": "Repartidores", "description": "Listado y disponibilidad de los repartidores."},
        {"name": "Monitoreo", "description": "Salud y métricas del servicio."},
    ],
)

# Freno básico a la fuerza bruta: 5 intentos fallidos por correo bloquean 15 minutos
_fallos = {}


def _bloqueado(email):
    n, desde = _fallos.get(email, (0, 0))
    if n >= 5 and time.time() - desde < 900:
        return True
    if n >= 5:
        _fallos.pop(email, None)
    return False


class Registro(BaseModel):
    nombre: str = Field(min_length=2, max_length=100)
    email: str = Field(max_length=150)
    password: str = Field(max_length=72, description="Mínimo 6 caracteres")
    model_config = ConfigDict(json_schema_extra={"examples": [
        {"nombre": "Ana Pérez", "email": "ana@correo.com", "password": "secreto1"}]})


class Login(BaseModel):
    email: str
    password: str
    model_config = ConfigDict(json_schema_extra={"examples": [
        {"email": "cliente@monteria.com", "password": "cliente123"}]})


class NuevoUsuario(Registro):
    rol: str = Field(description="CLIENTE, ADMIN o REPARTIDOR")
    model_config = ConfigDict(json_schema_extra={"examples": [
        {"nombre": "Pedro Gómez", "email": "pedro@monteria.com", "password": "reparto1", "rol": "REPARTIDOR"}]})


class UsuarioOut(BaseModel):
    id: int
    nombre: str
    email: str
    rol: str


class LoginOut(UsuarioOut):
    token: str = Field(description="JWT; enviarlo como `Authorization: Bearer <token>`")


class Disponibilidad(BaseModel):
    disponible: bool


def _crear(nombre, email, password, rol):
    email = email.strip().lower()
    if not EMAIL_RE.match(email):
        raise HTTPException(400, "Correo electrónico inválido")
    if len(password) < 6:
        raise HTTPException(400, "La contraseña debe tener al menos 6 caracteres")
    hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    try:
        uid, _ = execute(DB, "INSERT INTO usuarios (nombre, email, password, rol) VALUES (%s,%s,%s,%s)",
                         (nombre.strip(), email, hashed, rol))
    except pymysql.err.IntegrityError:
        raise HTTPException(409, "Ese email ya está registrado")
    app.state.log.info("Usuario creado id=%s rol=%s", uid, rol)
    return {"id": uid, "nombre": nombre.strip(), "email": email, "rol": rol}


@app.post("/registro", status_code=201, response_model=UsuarioOut, tags=["Autenticación"],
          summary="Registrar un cliente",
          description="Registro público: siempre crea un usuario con rol `CLIENTE`. "
                      "El personal lo crea un ADMIN con `POST /admin/usuarios`.",
          responses=errores(400, 409, 422))
def registro(d: Registro):
    return _crear(d.nombre, d.email, d.password, "CLIENTE")


@app.post("/login", response_model=LoginOut, tags=["Autenticación"], summary="Iniciar sesión",
          description="Valida correo y contraseña (bcrypt) y devuelve los datos del usuario con su **token JWT** "
                      "(vigencia 12 h). Tras 5 intentos fallidos con el mismo correo se bloquea 15 minutos.",
          responses=errores(401, 422, 429))
def login(d: Login):
    email = d.email.strip().lower()
    if _bloqueado(email):
        app.state.log.warning("Login bloqueado por demasiados intentos email=%s", email)
        raise HTTPException(429, "Demasiados intentos fallidos. Espera 15 minutos.")
    u = query(DB, "SELECT * FROM usuarios WHERE email=%s", (email,), one=True)
    try:
        ok = bool(u) and bcrypt.checkpw(d.password.encode(), u["password"].encode())
    except ValueError:
        ok = False
    if not ok:
        n, _ = _fallos.get(email, (0, 0))
        _fallos[email] = (n + 1, time.time())
        app.state.log.warning("Login fallido email=%s intento=%s", email, n + 1)
        raise HTTPException(401, "Credenciales incorrectas")
    _fallos.pop(email, None)
    app.state.log.info("Login correcto usuario=%s rol=%s", u["id"], u["rol"])
    return {"id": u["id"], "nombre": u["nombre"], "email": u["email"], "rol": u["rol"], "token": crear_token(u)}


@app.get("/usuarios/{uid}", response_model=UsuarioOut, tags=["Usuarios"], summary="Consultar un usuario",
         description="Un CLIENTE o REPARTIDOR solo puede consultarse a sí mismo; un ADMIN, a cualquiera.",
         responses=errores(401, 403, 404))
def get_usuario(uid: int, u=Depends(requiere("CLIENTE", "REPARTIDOR", "ADMIN"))):
    if u["rol"] in ("CLIENTE", "REPARTIDOR") and u["id"] != uid:
        raise HTTPException(403, "No tienes permiso para esta acción")
    r = query(DB, "SELECT id, nombre, email, rol FROM usuarios WHERE id=%s", (uid,), one=True)
    if not r:
        raise HTTPException(404, "Usuario no encontrado")
    return r


@app.get("/repartidores", tags=["Repartidores"], summary="Listar repartidores y su disponibilidad (ADMIN)",
         description="Devuelve `id`, `nombre` y `disponible` de cada repartidor. "
                     "Lo consume el servicio de domicilios para asignar pedidos (llamada interna).",
         responses=errores(401, 403))
def repartidores(u=Depends(requiere("ADMIN"))):
    return query(DB, "SELECT id, nombre, disponible FROM usuarios WHERE rol='REPARTIDOR' ORDER BY nombre")


@app.get("/repartidores/yo", tags=["Repartidores"], summary="Mi disponibilidad (REPARTIDOR)",
         responses=errores(401, 403, 404))
def mi_disponibilidad(u=Depends(requiere("REPARTIDOR"))):
    r = query(DB, "SELECT id, nombre, disponible FROM usuarios WHERE id=%s AND rol='REPARTIDOR'", (u["id"],), one=True)
    if not r:
        raise HTTPException(404, "Repartidor no encontrado")
    return r


@app.patch("/repartidores/disponibilidad", tags=["Repartidores"], summary="Activar o desactivar mi disponibilidad",
           description="Solo los repartidores disponibles reciben asignación automática de pedidos y pueden aceptar "
                       "pedidos de la bolsa.",
           responses=errores(401, 403))
def cambiar_disponibilidad(d: Disponibilidad, u=Depends(requiere("REPARTIDOR"))):
    execute(DB, "UPDATE usuarios SET disponible=%s WHERE id=%s AND rol='REPARTIDOR'",
            (1 if d.disponible else 0, u["id"]))
    app.state.log.info("Repartidor %s disponible=%s", u["id"], d.disponible)
    return {"ok": True, "disponible": d.disponible}


@app.get("/admin/usuarios", response_model=list[UsuarioOut], tags=["Usuarios"], summary="Listar usuarios (ADMIN)",
         responses=errores(401, 403))
def listar_usuarios(u=Depends(requiere("ADMIN"))):
    return query(DB, "SELECT id, nombre, email, rol FROM usuarios ORDER BY rol, nombre")


@app.post("/admin/usuarios", status_code=201, response_model=UsuarioOut, tags=["Usuarios"],
          summary="Crear un usuario de cualquier rol (ADMIN)",
          description="Es la forma de crear repartidores y otros administradores.",
          responses=errores(400, 401, 403, 409, 422))
def crear_usuario(d: NuevoUsuario, u=Depends(requiere("ADMIN"))):
    if d.rol not in ROLES:
        raise HTTPException(400, "Rol inválido")
    return _crear(d.nombre, d.email, d.password, d.rol)
